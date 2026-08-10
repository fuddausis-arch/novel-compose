"""资产桥接：bishu-novel 文件资产 ↔ NovelAgent 数据库 双向同步。

这是融合的核心手艺——让 bishu-novel 的 agent（写文件）和 NovelAgent 的设定库
（SQLite 数据库）互相认识。

方向1（DB→文件）：用户在前端建的角色卡/世界观/大纲 → 导出成 mvp 需要的
    meta/*.md 和 cache/character/*.json，供 agent 消费。
方向2（文件→DB）：agent 产出的 character_state_long.md / world_state.md →
    解析 upsert 回数据库，前端页面立刻能看到更新。

支持作为工作流 script 节点调用（run() 入口），也支持命令行独立运行。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


# ============================================================
# 格式校验告警收集器
# ============================================================
# 收集解析过程中的格式漂移告警（如角色未识别到字段、伏笔缺 expected_payoff 等）。
# 把"静默失效"变成"有日志可查"，便于排查 agent prompt 漂移问题。
# 每次 sync_all_to_db 调用开始时会清空，结束时汇总打印。
_parse_warnings: list[str] = []


def _warn(msg: str) -> None:
    """记录一条格式校验告警并打印到 stderr（stderr 不影响脚本 stdout 变量回写协议）。"""
    _parse_warnings.append(msg)
    print(f"  ⚠ {msg}", file=sys.stderr)


def get_and_clear_warnings() -> list[str]:
    """取出并清空告警列表（供 sync_all_to_db 结束时汇总）。"""
    ws = list(_parse_warnings)
    _parse_warnings.clear()
    return ws


# ============================================================
# 数据库辅助
# ============================================================

_DB_PATH = None  # 模块级缓存，首次从 config 读取


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        from novel_agent.config import load_config
        cfg = load_config()
        _DB_PATH = cfg.project_data_dir / "bible.db"
    return _DB_PATH


def _project_id_from_workspace(workspace: Path) -> int | None:
    """从工作区路径反推 project_id。

    workspace = project_data_dir/projects/{id}/，故 workspace.name 即 id。
    找不到则返回 None（调用方需显式传 --project）。
    """
    ws = workspace.resolve()
    if ws.parent.name == "projects" and ws.name.isdigit():
        return int(ws.name)
    # 兜底：往上找 projects/{id}
    for parent in ws.parents:
        if parent.name == "projects" and ws.name.isdigit():
            return int(ws.name)
        if parent.parent.name == "projects" and parent.name.isdigit():
            return int(parent.name)
    return None


def _resolve_chapter_dir(workspace: Path, chapter: str | int) -> Path:
    """解析章节目录路径，兼容 "0001" / "1" 两种形式。

    工作流用 story/{{chapter_number}}/ 写文件，chapter_number 默认 "0001"，
    但 DB chapter 列存 int。这里按实际存在的目录匹配。
    """
    chapter_str = str(chapter)
    candidates = [
        workspace / "story" / chapter_str,
        workspace / "story" / str(int(chapter_str)),
        workspace / "story" / chapter_str.zfill(4),
    ]
    for c in candidates:
        if c.exists():
            return c
    # 都不存在，返回首选项（后续 exists() 检查会跳过）
    return candidates[0]


def _connect(project_id: int, workspace: Path | None = None) -> sqlite3.Connection:
    """连接数据库。工作区与数据库强绑定，避免写错全局库。

    workspace = <project_data>/projects/{id}/ 时，一律使用 <project_data>/bible.db
    （不存在则就地创建），绝不回退到全局 config 库。否则全局 config 的 project_data_dir
    可能指向 Roaming 主库，导致把项目本地产出的 sync 写进真实主库、污染真实项目。
    仅在 workspace 无法反推出 project_data（如 CLI 裸跑 --workspace .）时才回退 config。
    """
    db_path = None
    if workspace is not None:
        pdd = _project_data_dir_from_workspace(workspace)
        if pdd is not None:
            db_path = pdd / "bible.db"
            print(f"  ℹ 工作区绑定数据库: {db_path}", file=sys.stderr)
    if db_path is None:
        db_path = _db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _project_data_dir_from_workspace(workspace: Path) -> Path | None:
    """从工作区反推所在 project_data 目录（工作区与数据库强绑定的依据）。

    workspace 通常是 <project_data>/projects/{id}/，故 project_data = workspace.parent.parent。
    若 workspace 不处于 projects/{id} 结构下，返回 None（调用方回退到 config 默认）。
    """
    ws = workspace.resolve()
    if ws.parent.name == "projects":
        return ws.parent.parent
    for parent in ws.parents:
        if parent.name == "projects":
            return parent.parent
    return None


def _upsert_character_state(conn: sqlite3.Connection, project_id: int, name: str, fields: dict) -> None:
    """更新 characters 表的角色状态字段（current_location/current_emotion 等）。

    只更新非空字段，不动其他字段。角色不存在则尝试模糊匹配（如"周德"→"周德（老瘸子）"），
    仍找不到则跳过（不自动创建，防止脏数据）。
    """
    # 精确匹配
    row = conn.execute(
        "SELECT id, name FROM characters WHERE project_id=? AND name=?", (project_id, name)
    ).fetchone()
    # 模糊匹配（md 里的"周德"→db 里的"周德（老瘸子）"）
    if not row:
        row = conn.execute(
            "SELECT id, name FROM characters WHERE project_id=? AND name LIKE ?",
            (project_id, f"%{name}%"),
        ).fetchone()
    if not row:
        print(f"  ⚠ 角色不存在，跳过: {name}", file=sys.stderr)
        return
    actual_name = row["name"]

    # 构造 SET 子句
    set_clauses = []
    values = []
    field_map = {
        "current_location": "current_location",
        "current_emotion": "current_emotion",
        "motivation": "motivation",
        "secrets": "secrets",
        "role": "role",
        "personality": "personality",
    }
    for md_key, db_col in field_map.items():
        val = fields.get(md_key)
        if val:  # 非空才更新
            set_clauses.append(f"{db_col}=?")
            values.append(val[:500])  # 截断防超长

    if not set_clauses:
        return  # 没有要更新的

    set_clauses.append("updated_at=datetime('now')")
    values.extend([project_id, actual_name])
    sql = f"UPDATE characters SET {', '.join(set_clauses)} WHERE project_id=? AND name=?"
    conn.execute(sql, values)
    print(f"  ✓ 已同步角色状态: {actual_name} (更新{len(set_clauses)-1}个字段)")


# ============================================================
# 方向1：DB → 文件（让工作流能消费数据库资产）
# ============================================================

def _safe(row: sqlite3.Row | None, key: str) -> str:
    if row is None:
        return ""
    try:
        v = row[key]
        return v if v is not None else ""
    except (KeyError, IndexError):
        return ""


def export_characters(project_id: int, workspace: Path) -> None:
    """从 characters 表导出到 bishu-novel 期望的文件格式。

    产出：
    - meta/character_profiles.md（角色档案，供 agent 消费）
    - meta/character_voice.md（声线锚）
    - cache/character/skeleton.json（骨架，供 mvp sync_down 用）
    - cache/character/beliefs.json（信念）
    - cache/character/voice.json（声线）
    - cache/character/{name}_deep.json（深层维度，每个角色一个）
    """
    conn = _connect(project_id, workspace)
    rows = conn.execute(
        "SELECT * FROM characters WHERE project_id=? ORDER BY importance DESC, id",
        (project_id,),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"  ⚠ 项目{project_id}无角色，跳过导出")
        return

    meta = workspace / "meta"
    cache_char = workspace / "cache" / "character"
    meta.mkdir(parents=True, exist_ok=True)
    cache_char.mkdir(parents=True, exist_ok=True)

    # character_profiles.md
    lines = ["# 角色档案", ""]
    for r in rows:
        lines.append(f"## {r['name']}")
        lines.append("")
        lines.append(f"- 重要性: {_safe(r,'importance')}")
        if _safe(r, "role"):
            lines.append(f"- 定位: {_safe(r,'role')}")
        if _safe(r, "appearance"):
            lines.append(f"- 外貌: {_safe(r,'appearance')}")
        if _safe(r, "personality"):
            lines.append(f"- 性格: {_safe(r,'personality')}")
        if _safe(r, "background"):
            lines.append(f"- 背景: {_safe(r,'background')}")
        if _safe(r, "ability") or _safe(r, "combat_style"):
            lines.append(f"- 能力: {_safe(r,'ability') or _safe(r,'combat_style')}")
        if _safe(r, "current_location"):
            lines.append(f"- 当前位置: {_safe(r,'current_location')}")
        if _safe(r, "current_emotion"):
            lines.append(f"- 当前情绪: {_safe(r,'current_emotion')}")
        lines.append("")
    (meta / "character_profiles.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ character_profiles.md ({len(rows)}个角色)")

    # character_voice.md + voice.json
    voice_lines = ["# 角色声线锚", ""]
    voice_json = {"characters": []}
    for r in rows:
        v = _safe(r, "language_style") or _safe(r, "emotional_anchor")
        voice_lines.append(f"## {r['name']}")
        voice_lines.append(f"- {v if v else '自然口语，暂无声线设定'}")
        voice_lines.append("")
        voice_json["characters"].append({
            "name": r["name"],
            "voice": v if v else "自然口语",
            "speech_style": v if v else "自然口语",
        })
    (meta / "character_voice.md").write_text("\n".join(voice_lines), encoding="utf-8")
    (cache_char / "voice.json").write_text(json.dumps(voice_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ character_voice.md + voice.json")

    # skeleton.json
    skeleton = {"characters": []}
    for r in rows:
        skeleton["characters"].append({
            "name": r["name"],
            "importance": _safe(r, "importance") or "次要",
            "role": _safe(r, "role"),
            "appearance": _safe(r, "appearance"),
            "personality": _safe(r, "personality"),
            "background": _safe(r, "background"),
            "ability": _safe(r, "ability") or _safe(r, "combat_style"),
            "current_location": _safe(r, "current_location"),
            "current_emotion": _safe(r, "current_emotion"),
        })
    (cache_char / "skeleton.json").write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ skeleton.json")

    # beliefs.json
    beliefs = {"beliefs": []}
    for r in rows:
        beliefs["beliefs"].append({
            "name": r["name"],
            "core_belief": _safe(r, "motivation") or "（待补充）",
            "values": _safe(r, "absolute_taboos"),
            "fears": "",
            "desire": _safe(r, "motivation"),
        })
    (cache_char / "beliefs.json").write_text(json.dumps(beliefs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ beliefs.json")

    # 每角色 deep.json
    for r in rows:
        name = r["name"]
        deep = {
            "name": name,
            "inner_world": _safe(r, "emotional_anchor"),
            "secret": _safe(r, "secrets"),
            "growth_arc": _safe(r, "growth_curve"),
            "core_contradiction": _safe(r, "core_contradiction"),
        }
        # 角色名可能含 Windows 非法字符（/ \ : * ? " < > |），sanitize 后再拼文件名
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)[:80] or "unnamed"
        (cache_char / f"{safe_name}_deep.json").write_text(
            json.dumps(deep, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"  ✓ {len(rows)}个 *_deep.json")

    print(f"角色导出完成: {len(rows)}个角色 → {workspace}/meta + cache/character")


def export_world_foundation(project_id: int, workspace: Path) -> None:
    """从 world_settings 表导出到 meta/world_foundation.md。"""
    conn = _connect(project_id, workspace)
    rows = conn.execute(
        "SELECT * FROM world_settings WHERE project_id=? ORDER BY dimension, id",
        (project_id,),
    ).fetchall()
    conn.close()

    meta = workspace / "meta"
    meta.mkdir(parents=True, exist_ok=True)

    lines = ["# 世界观总纲", ""]
    for r in rows:
        dim = r["dimension"] if "dimension" in r.keys() else "未分类"
        lines.append(f"## {dim}")
        lines.append("")
        content = _safe(r, "content") or _safe(r, "value") or _safe(r, "summary")
        if content:
            lines.append(content)
        else:
            lines.append(f"- {_safe(r,'name')}: {_safe(r,'summary')}")
        lines.append("")
    (meta / "world_foundation.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"世界观导出完成: {len(rows)}条 → meta/world_foundation.md")


def export_outlines(project_id: int, workspace: Path) -> None:
    """从 outlines 表导出到 outline/volume_outline.md + near_term_outline.md。"""
    conn = _connect(project_id, workspace)
    vol_rows = conn.execute(
        'SELECT * FROM outlines WHERE project_id=? AND level="volume" ORDER BY "order"',
        (project_id,),
    ).fetchall()
    ch_rows = conn.execute(
        'SELECT * FROM outlines WHERE project_id=? AND level IN ("chapter","arc") ORDER BY "order" LIMIT 10',
        (project_id,),
    ).fetchall()
    conn.close()

    outline_dir = workspace / "outline"
    outline_dir.mkdir(parents=True, exist_ok=True)

    # volume_outline.md（取第一卷）
    if vol_rows:
        vol = vol_rows[0]
        vol_lines = [f"# {vol['title']}", ""]
        if _safe(vol, "summary"):
            vol_lines.append(_safe(vol, "summary"))
        if _safe(vol, "content"):
            vol_lines.append("")
            vol_lines.append(_safe(vol, "content"))
        (outline_dir / "volume_outline.md").write_text("\n".join(vol_lines), encoding="utf-8")
        print(f"  ✓ volume_outline.md ({vol['title']})")

    # near_term_outline.md
    nt_lines = ["# 近期大纲", ""]
    for r in ch_rows:
        nt_lines.append(f"## {r['title']}")
        if _safe(r, "summary"):
            nt_lines.append(_safe(r, "summary"))
        nt_lines.append("")
    (outline_dir / "near_term_outline.md").write_text("\n".join(nt_lines), encoding="utf-8")
    print(f"  ✓ near_term_outline.md ({len(ch_rows)}章/弧)")

    print(f"大纲导出完成 → outline/")


def export_all(project_id: int, workspace: Path) -> None:
    """一键导出全部数据库资产到工作区文件（DB→文件方向）。"""
    print(f"=== 资产桥接：DB → 文件（项目{project_id}）===")
    export_world_foundation(project_id, workspace)
    export_characters(project_id, workspace)
    export_outlines(project_id, workspace)


# ============================================================
# 方向2：文件 → DB（让 agent 产出回流数据库）
# ============================================================

def _parse_character_state_md(md_text: str) -> dict[str, dict]:
    """解析 character_state_long.md，返回 {角色名: {字段}}。

    格式：
    ## {角色名}
    ### snapshot
    - location：xxx
    - emotional baseline：xxx
    ### drives
    - core desire：xxx
    - secret：xxx
    ### identity
    - core tags：xxx
    - contrast detail：xxx

    格式校验：解析后统计每个角色识别到的字段数，字段数为0的角色
    会被记入 _parse_warnings（说明 agent 输出格式偏离了约定）。
    这样把"静默失效"变成"有日志可查"，便于排查 agent prompt 漂移问题。
    """
    characters = {}
    current_name = None
    current_section = None

    for line in md_text.split("\n"):
        line = line.rstrip()
        if line.startswith("## ") and not line.startswith("### "):
            current_name = line[3:].strip()
            characters[current_name] = {}
            current_section = None
        elif line.startswith("### "):
            current_section = line[4:].strip().lower()
        elif line.startswith("- ") and current_name and current_section:
            # 解析 "- key：value" 或 "- key: value"
            content = line[2:].strip()
            # 匹配中文冒号或英文冒号
            m = re.match(r"^([^：:]+)[：:]\s*(.+)$", content)
            if m:
                key = m.group(1).strip().lower()
                val = m.group(2).strip()
                # 映射到数据库字段
                if current_section == "snapshot":
                    if "location" in key:
                        characters[current_name]["current_location"] = val
                    elif "emotional" in key or "emotion" in key:
                        characters[current_name]["current_emotion"] = val
                elif current_section == "drives":
                    if "desire" in key or "motivation" in key:
                        characters[current_name]["motivation"] = val
                    elif "secret" in key:
                        characters[current_name]["secrets"] = val
                elif current_section == "identity":
                    if "core tag" in key:
                        characters[current_name]["role"] = val
                    elif "contrast" in key or "personality" in key:
                        characters[current_name]["personality"] = val

    # 格式校验告警：字段数为0的角色说明格式漂移
    for name, fields in characters.items():
        if not fields:
            _warn(f"角色「{name}」未识别到任何字段，可能 agent 输出格式偏离约定（应为 ### snapshot/drives/identity + - key：value）")

    return characters


def sync_character_state_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """读 story/{N}/character_state_long.md → 解析 → upsert 到 characters 表。"""
    chapter_dir = _resolve_chapter_dir(workspace, chapter_num)
    md_path = chapter_dir / "character_state_long.md"
    if not md_path.exists():
        print(f"  ⚠ 文件不存在: {md_path}")
        return

    md_text = md_path.read_text(encoding="utf-8")
    characters = _parse_character_state_md(md_text)
    if not characters:
        # 这说明整份 md 一个 ## 角色块都没识别到——格式严重漂移
        _warn("character_state_long.md 未解析出任何角色，agent 输出可能整体格式异常（应有 ## 角色名 段落）")
        return

    print(f"  解析出 {len(characters)} 个角色: {list(characters.keys())}")

    conn = _connect(project_id, workspace)
    try:
        for name, fields in characters.items():
            _upsert_character_state(conn, project_id, name, fields)
        conn.commit()
        print(f"角色状态已同步到数据库（第{chapter_num}章）")
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 同步失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def sync_chapter_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """读 story/{N}/chapter.md → 写入 chapter_commits 表。

    chapter_commits 表结构：project_id / chapter / status / summary / word_count / committed_at
    （无 title/content 列，summary 存摘要，正文存文件由前端按章号读取）
    """
    from datetime import datetime, timezone

    chapter_dir = _resolve_chapter_dir(workspace, chapter_num)
    md_path = chapter_dir / "chapter.md"
    if not md_path.exists():
        print(f"  ⚠ 文件不存在: {md_path}")
        return

    content = md_path.read_text(encoding="utf-8")
    word_count = len(content)
    # 取前200字作摘要
    summary = content[:200].replace("\n", " ").strip()
    now = datetime.now(timezone.utc).isoformat()
    chapter_db = int(chapter_num)  # DB chapter 列存 int

    conn = _connect(project_id, workspace)
    try:
        # 检查是否已存在该章
        existing = conn.execute(
            "SELECT id FROM chapter_commits WHERE project_id=? AND chapter=?",
            (project_id, chapter_db),
        ).fetchone()
        if existing:
            # 更新
            conn.execute(
                "UPDATE chapter_commits SET summary=?, word_count=?, status='committed', updated_at=? WHERE project_id=? AND chapter=?",
                (summary, word_count, now, project_id, chapter_db),
            )
            print(f"  ✓ 章节已更新: 第{chapter_db}章 ({word_count}字)")
        else:
            # 插入
            conn.execute(
                """INSERT INTO chapter_commits (project_id, chapter, status, summary, word_count, committed_at, created_at, updated_at)
                   VALUES (?, ?, 'committed', ?, ?, ?, ?, ?)""",
                (project_id, chapter_db, summary, word_count, now, now, now),
            )
            print(f"  ✓ 章节已写入: 第{chapter_db}章 ({word_count}字)")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 章节同步失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def sync_hooks_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """读 cache/od/hooks.json（或 meta/hooks.md 兜底）→ upsert foreshadows 表。

    优先读 JSON 缓存（od_post 直接产出，结构最准）；不存在则解析 md。
    状态映射：open→pending、resolved→resolved、abandoned→abandoned。
    foreshadow_id 用 hooks 的 id（如 h001）；tier 从 expected_payoff 推断
    （≤3章=short、≤10章=medium、其余=long）。
    """
    import json as _json

    # 优先 JSON 缓存
    json_path = workspace / "cache" / "od" / "hooks.json"
    hooks: list[dict] = []
    if json_path.exists():
        try:
            hooks = _json.loads(json_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError as e:
            print(f"  ⚠ hooks.json 解析失败: {e}", file=sys.stderr)
    if not hooks:
        # md 兜底
        md_path = workspace / "meta" / "hooks.md"
        if md_path.exists():
            hooks = _parse_hooks_md(md_path.read_text(encoding="utf-8"))
    if not hooks:
        print("  ⚠ 无伏笔数据可同步")
        return

    print(f"  解析出 {len(hooks)} 条伏笔")

    # tier 推断：解析 expected_payoff 里的章数
    def _infer_tier(payoff: str) -> str:
        import re as _re
        nums = _re.findall(r"\d+", payoff or "")
        if not nums:
            return "medium"
        n = max(int(x) for x in nums)
        if n <= 3:
            return "short"
        if n <= 10:
            return "medium"
        return "long"

    # 解析 planned_resolve_chapter：取 expected_payoff 的最大章数
    def _parse_resolve_chapter(payoff: str) -> int:
        import re as _re
        nums = _re.findall(r"\d+", payoff or "")
        return max(int(x) for x in nums) if nums else 0

    conn = _connect(project_id, workspace)
    try:
        for h in hooks:
            fid = h.get("id", "")
            if not fid:
                continue
            # 兼容 "h001" / "S-001" / "H001" 等，统一存原样
            desc = h.get("description", "")
            status_raw = h.get("status", "open")
            # 状态映射
            status_map = {"open": "pending", "planted": "planted",
                          "developing": "developing", "resolved": "resolved",
                          "abandoned": "abandoned"}
            status = status_map.get(status_raw, "pending")
            plant_ch = h.get("chapter_created") or h.get("plant_chapter") or 0
            payoff = h.get("expected_payoff") or ""
            tier = _infer_tier(payoff)
            resolve_ch = _parse_resolve_chapter(payoff)

            existing = conn.execute(
                "SELECT id FROM foreshadows WHERE project_id=? AND foreshadow_id=?",
                (project_id, fid),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE foreshadows SET description=?, status=?, tier=?,
                       plant_chapter=?, planned_resolve_chapter=?, updated_at=datetime('now')
                       WHERE project_id=? AND foreshadow_id=?""",
                    (desc, status, tier, int(plant_ch), resolve_ch, project_id, fid),
                )
            else:
                conn.execute(
                    """INSERT INTO foreshadows
                       (project_id, foreshadow_id, tier, plant_chapter, description,
                        depends_on, status, planned_resolve_chapter, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, '', ?, ?, datetime('now'), datetime('now'))""",
                    (project_id, fid, tier, int(plant_ch), desc, status, resolve_ch),
                )
        conn.commit()
        print(f"  ✓ 伏笔已同步: {len(hooks)} 条 → foreshadows 表")
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 伏笔同步失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def _parse_hooks_md(md_text: str) -> list[dict]:
    """解析 meta/hooks.md，返回 [{id, description, status, chapter_created, ...}]。"""
    hooks = []
    current = None
    for line in md_text.split("\n"):
        line = line.rstrip()
        if line.startswith("## ") and not line.startswith("### "):
            if current:
                hooks.append(current)
            current = {"id": line[3:].strip()}
        elif line.startswith("- ") and current:
            content = line[2:].strip()
            m = re.match(r"^([^：:]+)[：:]\s*(.*)$", content)
            if m:
                key = m.group(1).strip().lower().replace(" ", "_")
                val = m.group(2).strip()
                key_map = {"chapter_created": "chapter_created", "chapter_resolved": "chapter_resolved",
                           "expected_payoff": "expected_payoff", "last_advanced": "last_advanced",
                           "source": "source", "description": "description", "status": "status"}
                if key in key_map:
                    current[key_map[key]] = val if val != "（空）" else None
    if current:
        hooks.append(current)
    return hooks


def sync_debts_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """读 cache/od/debts.json（或 meta/debts.md 兜底）→ upsert plot_debts 表。

    plot_debts 无 debt_id 字段，用 (project_id, description) 做唯一判断。
    debt_type 从 from/to 推断（有"复仇/弃/害"→复仇，否则→因果）。
    term 从 expected_payoff 推断（≤5章=short，其余=long）。
    """
    import json as _json

    json_path = workspace / "cache" / "od" / "debts.json"
    debts: list[dict] = []
    if json_path.exists():
        try:
            debts = _json.loads(json_path.read_text(encoding="utf-8"))
        except _json.JSONDecodeError as e:
            print(f"  ⚠ debts.json 解析失败: {e}", file=sys.stderr)
    if not debts:
        md_path = workspace / "meta" / "debts.md"
        if md_path.exists():
            debts = _parse_debts_md(md_path.read_text(encoding="utf-8"))
    if not debts:
        print("  ⚠ 无剧情债数据可同步")
        return

    print(f"  解析出 {len(debts)} 条剧情债")

    def _infer_debt_type(d: dict) -> str:
        from_to = (d.get("from", "") + d.get("to", "") + d.get("description", ""))
        if any(kw in from_to for kw in ("弃", "害", "杀", "仇", "背叛")):
            return "复仇"
        if any(kw in from_to for kw in ("承诺", "答应", "许")):
            return "承诺"
        if any(kw in from_to for kw in ("秘密", "隐瞒")):
            return "秘密"
        return "因果"

    def _infer_term(payoff: str) -> str:
        import re as _re
        nums = _re.findall(r"\d+", payoff or "")
        if nums and max(int(x) for x in nums) <= 5:
            return "short"
        return "long"

    conn = _connect(project_id, workspace)
    try:
        for d in debts:
            desc = d.get("description", "")
            if not desc:
                continue
            status_raw = d.get("status", "open")
            status_map = {"open": "open", "resolved": "resolved", "abandoned": "abandoned"}
            status = status_map.get(status_raw, "open")
            created_ch = d.get("chapter_created") or 0
            resolved_ch = d.get("chapter_resolved") or 0
            payoff = d.get("expected_payoff") or ""
            debt_type = _infer_debt_type(d)
            term = _infer_term(payoff)

            existing = conn.execute(
                "SELECT id FROM plot_debts WHERE project_id=? AND description=?",
                (project_id, desc),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE plot_debts SET debt_type=?, status=?, term=?,
                       created_chapter=?, resolved_chapter=?, updated_at=datetime('now')
                       WHERE project_id=? AND description=?""",
                    (debt_type, status, term, int(created_ch),
                     int(resolved_ch) if resolved_ch else 0, project_id, desc),
                )
            else:
                conn.execute(
                    """INSERT INTO plot_debts
                       (project_id, debt_type, description, pressure, term, status,
                        created_chapter, resolved_chapter, created_at, updated_at)
                       VALUES (?, ?, ?, 3, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                    (project_id, debt_type, desc, term, status,
                     int(created_ch), int(resolved_ch) if resolved_ch else 0),
                )
        conn.commit()
        print(f"  ✓ 剧情债已同步: {len(debts)} 条 → plot_debts 表")
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 剧情债同步失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def _parse_debts_md(md_text: str) -> list[dict]:
    """解析 meta/debts.md，返回 [{id, description, from, to, status, ...}]。"""
    debts = []
    current = None
    for line in md_text.split("\n"):
        line = line.rstrip()
        if line.startswith("## ") and not line.startswith("### "):
            if current:
                debts.append(current)
            current = {"id": line[3:].strip()}
        elif line.startswith("- ") and current:
            content = line[2:].strip()
            m = re.match(r"^([^：:]+)[：:]\s*(.*)$", content)
            if m:
                key = m.group(1).strip().lower().replace(" ", "_")
                val = m.group(2).strip()
                current[key] = val if val != "（空）" else None
    if current:
        debts.append(current)
    return debts


def sync_world_state_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """读 cache/we/world_state.json → upsert world_states 表。

    world_states 有 unique(project_id, chapter)，按章节号 upsert。
    forces/undercurrents 直接存 JSON。
    """
    import json as _json

    json_path = workspace / "cache" / "we" / "world_state.json"
    if not json_path.exists():
        print(f"  ⚠ 文件不存在: {json_path}")
        return
    try:
        data = _json.loads(json_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        print(f"  ❌ world_state.json 解析失败: {e}", file=sys.stderr)
        return

    chapter_db = int(chapter_num)
    world_time = data.get("world_time", "")
    time_adv = data.get("time_advanced_days", 0) or 0
    forces = data.get("forces", [])
    undercurrents = data.get("undercurrents", [])

    conn = _connect(project_id, workspace)
    try:
        existing = conn.execute(
            "SELECT id FROM world_states WHERE project_id=? AND chapter=?",
            (project_id, chapter_db),
        ).fetchone()
        forces_json = _json.dumps(forces, ensure_ascii=False)
        under_json = _json.dumps(undercurrents, ensure_ascii=False)
        if existing:
            conn.execute(
                """UPDATE world_states SET world_time=?, time_advanced_days=?,
                   forces=?, undercurrents=? WHERE project_id=? AND chapter=?""",
                (world_time, time_adv, forces_json, under_json, project_id, chapter_db),
            )
            print(f"  ✓ 世界状态已更新: 第{chapter_db}章")
        else:
            conn.execute(
                """INSERT INTO world_states
                   (project_id, chapter, world_time, time_advanced_days,
                    forces, undercurrents, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (project_id, chapter_db, world_time, time_adv, forces_json, under_json),
            )
            print(f"  ✓ 世界状态已写入: 第{chapter_db}章 ({len(forces)}势力/{len(undercurrents)}暗线)")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 世界状态同步失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def sync_world_events_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """读 cache/we/world_events.json → upsert world_events 表。

    world_events 有 unique(project_id, chapter)。power_shift 可能是空字符串
    或数组，统一转 JSON 存。
    """
    import json as _json

    json_path = workspace / "cache" / "we" / "world_events.json"
    if not json_path.exists():
        print(f"  ⚠ 文件不存在: {json_path}")
        return
    try:
        data = _json.loads(json_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        print(f"  ❌ world_events.json 解析失败: {e}", file=sys.stderr)
        return

    chapter_db = int(chapter_num)
    on_camera = data.get("on_camera_events", [])
    off_camera = data.get("off_camera_events", [])
    under_progress = data.get("undercurrent_progress", [])
    power_shift = data.get("power_shift", "")
    # power_shift 可能是字符串或数组，统一转 JSON
    if isinstance(power_shift, str) and power_shift:
        power_shift_json = _json.dumps([{"description": power_shift}], ensure_ascii=False)
    elif isinstance(power_shift, list):
        power_shift_json = _json.dumps(power_shift, ensure_ascii=False)
    else:
        power_shift_json = "[]"

    conn = _connect(project_id, workspace)
    try:
        existing = conn.execute(
            "SELECT id FROM world_events WHERE project_id=? AND chapter=?",
            (project_id, chapter_db),
        ).fetchone()
        on_json = _json.dumps(on_camera, ensure_ascii=False)
        off_json = _json.dumps(off_camera, ensure_ascii=False)
        prog_json = _json.dumps(under_progress, ensure_ascii=False)
        if existing:
            conn.execute(
                """UPDATE world_events SET on_camera_events=?, off_camera_events=?,
                   undercurrent_progress=?, power_shift=? WHERE project_id=? AND chapter=?""",
                (on_json, off_json, prog_json, power_shift_json, project_id, chapter_db),
            )
            print(f"  ✓ 世界事件已更新: 第{chapter_db}章")
        else:
            conn.execute(
                """INSERT INTO world_events
                   (project_id, chapter, on_camera_events, off_camera_events,
                    undercurrent_progress, power_shift, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (project_id, chapter_db, on_json, off_json, prog_json, power_shift_json),
            )
            print(f"  ✓ 世界事件已写入: 第{chapter_db}章 ({len(on_camera)}台上/{len(off_camera)}台下)")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 世界事件同步失败: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def sync_all_to_db(project_id: int, chapter_num: str | int, workspace: Path) -> None:
    """一键把工作流产出同步回数据库（文件→DB方向）。

    同步 6 类资产：角色状态、章节正文、伏笔、剧情债、世界状态、世界事件。

    容错策略：每类资产独立 try/except，任一类失败不中断后续同步
    （比如角色同步挂了，伏笔/世界状态仍能正常回流）。
    最后汇总打印成功/失败清单 + 格式校验告警。
    """
    print(f"=== 资产桥接：文件 → DB（项目{project_id}，第{chapter_num}章）===")
    # 清空上次遗留的告警
    _parse_warnings.clear()

    sync_targets = [
        ("角色状态", sync_character_state_to_db),
        ("章节正文", sync_chapter_to_db),
        ("伏笔", sync_hooks_to_db),
        ("剧情债", sync_debts_to_db),
        ("世界状态", sync_world_state_to_db),
        ("世界事件", sync_world_events_to_db),
    ]

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []
    for label, fn in sync_targets:
        try:
            fn(project_id, chapter_num, workspace)
            succeeded.append(label)
        except Exception as e:
            failed.append((label, str(e)))
            # 单类失败不影响其他类同步
            print(f"  ❌ {label}同步失败（其他类继续）: {e}", file=sys.stderr)

    # 汇总报告
    print(f"--- 同步汇总：成功 {len(succeeded)}/{len(sync_targets)}，失败 {len(failed)} ---")
    if failed:
        print(f"  失败类: {[label for label, _ in failed]}")
    warnings = get_and_clear_warnings()
    if warnings:
        print(f"  ⚠ 格式校验告警 {len(warnings)} 条（agent 输出可能有格式漂移）:")
        for w in warnings:
            print(f"    - {w}")


# ============================================================
# 命令行入口 & 工作流 script 节点入口
# ============================================================

def run(args: list[str], workspace: Path | None = None) -> str:
    """工作流 script 节点入口（被 nvl/__init__.py 的 run_script 调用）。

    签名兼容 nvl 框架：run(args, workspace)。
    bridge 不需要 chdir（用绝对路径），但接受 workspace 参数。

    project_id 优先级：--project 参数 > 从 workspace 路径反推。
    chapter 保留字符串原样（兼容 "0001" / "1"）。

    用法（script_args 格式）：
      export-all                       # DB→文件（mvp跑前，project_id 从 workspace 反推）
      export-all --project 3           # 显式指定 project_id
      sync-all --chapter {{chapter_number}}   # 文件→DB（mvp跑后回流）
    """
    import argparse

    parser = argparse.ArgumentParser(description="资产桥接：DB ↔ 文件 双向同步")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export_all = sub.add_parser("export-all", help="一键导出全部DB资产")
    p_export_all.add_argument("--project", type=int, default=None,
                              help="项目ID，省略则从 workspace 路径反推")

    p_sync_all = sub.add_parser("sync-all", help="一键同步全部产出到DB")
    p_sync_all.add_argument("--project", type=int, default=None,
                            help="项目ID，省略则从 workspace 路径反推")
    p_sync_all.add_argument("--chapter", type=str, required=True,
                            help="章节号（兼容 0001 / 1）")

    # 兼容命令行直接调用（带 --workspace）
    p_export = sub.add_parser("export", help="DB → 文件（带workspace）")
    p_export.add_argument("--project", type=int, default=None)
    p_export.add_argument("--workspace", default=".")

    p_sync = sub.add_parser("sync", help="文件 → DB（带workspace）")
    p_sync.add_argument("--project", type=int, default=None)
    p_sync.add_argument("--chapter", type=str, required=True)
    p_sync.add_argument("--workspace", default=".")

    parsed = parser.parse_args(args)

    # workspace 优先级：调用方传入 > 命令行 --workspace
    ws_path = workspace
    if ws_path is None:
        ws_str = getattr(parsed, "workspace", ".")
        ws_path = Path(ws_str).resolve()
    elif not isinstance(ws_path, Path):
        ws_path = Path(ws_path)

    # project_id 优先级：--project 参数 > workspace 路径反推
    project_id = parsed.project
    if project_id is None:
        project_id = _project_id_from_workspace(ws_path)
        if project_id is None:
            raise RuntimeError(
                f"无法从 workspace 反推 project_id（{ws_path}），请显式传 --project"
            )
        print(f"  ℹ 从 workspace 反推 project_id={project_id}")

    if parsed.command in ("export", "export-all"):
        export_all(project_id, ws_path)
    elif parsed.command in ("sync", "sync-all"):
        sync_all_to_db(project_id, parsed.chapter, ws_path)

    return json.dumps({"status": "ok"}, ensure_ascii=False)


if __name__ == "__main__":
    # 命令行直接运行
    result = run(sys.argv[1:])
    print(result)
