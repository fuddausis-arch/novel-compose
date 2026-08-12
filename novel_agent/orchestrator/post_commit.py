"""P1-6 提交后闭环：伏笔自动埋设 / 红线检测 / 命名归一化 / 审校回写 / 圆桌落库。

统一在 summarize_chapter 之后接入（失败不阻塞主流程）。每个函数：
- 规则层部分：确定性、可单测（命名归一化）
- LLM 部分：prompt 驱动，llm_client 为 None 或调用失败时安全降级
- 落库逻辑：mock llm_client 返回结构化 JSON 即可单测
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 子项3：命名归一化（规则层，提交后把别名映射回正名）
# ════════════════════════════════════════════════════════════════════

def normalize_names(text: str, repo, entity_type: str | None = None) -> tuple[str, int]:
    """把正文中的 EntityNameOverride 别名替换为规范名。

    规则：
    - 别名按长度降序替换（长别名优先，避免子串误伤）
    - 若别名是规范名的一部分（如 alias="张", canonical="张伟"），跳过——替换会破坏正名
    - 替换数统计返回

    Returns:
        (替换后的文本, 替换次数)
    """
    try:
        overrides = repo.list_name_overrides(entity_type=entity_type)
    except Exception as e:
        logger.debug("normalize_names 读取别名表失败: %s", e)
        return text, 0
    if not text or not overrides:
        return text, 0
    ordered = sorted(overrides, key=lambda o: len(o.alias or ""), reverse=True)
    count = 0
    for o in ordered:
        alias = (o.alias or "").strip()
        canonical = (o.canonical_name or "").strip()
        if not alias or not canonical or alias == canonical:
            continue
        if alias in canonical:  # 别名是正名一部分，替换会破坏正名
            continue
        before = text
        text = text.replace(alias, canonical)
        count += before.count(alias)
    if count:
        logger.info("命名归一化：替换 %d 处别名 → 正名", count)
    return text, count


# ════════════════════════════════════════════════════════════════════
# 子项2：红线检测（提交后 LLM 对照红线清单检查正文是否违反）
# ════════════════════════════════════════════════════════════════════

_REDLINE_CHECK_PROMPT = """你是红线核查员。以下是第 {chapter} 章的正文与本项目的写作红线。

【红线（绝对不可违反）】
{redlines}

【正文】
{text}

任务：逐条核对红线，判断正文是否违反。正文完全遵守时输出空清单。
输出纯 JSON（禁止 markdown 围栏）：
{{"violations": [{{"redline": "违反的红线内容", "evidence": "正文中的证据片段", "severity": "hard|soft"}}]}}
无违反时输出 {{"violations": []}}。"""


async def check_redline_violations(
    content: str,
    repo,
    chapter: int,
    llm_client: Any,
) -> list[dict]:
    """提交后红线自动检查：LLM 对照项目红线清单核查正文。失败返回空清单（不阻塞）。"""
    try:
        from novel_agent.bible.models import RedLine
        red_lines = repo.db.query(RedLine).filter(
            RedLine.project_id == repo.project_id,
            RedLine.enabled == True,  # noqa: E712
            (RedLine.scope == "project") |
            ((RedLine.scope == "chapter") & (RedLine.chapter_num == chapter)),
        ).all()
        if not red_lines:
            return []
        red_text = "\n".join(
            f"[{r.severity}] {r.content}" for r in red_lines)
        prompt = _REDLINE_CHECK_PROMPT.format(
            chapter=chapter, redlines=red_text, text=content[:6000])
        raw = await llm_client.generate(prompt, system="你是严谨的红线核查员，只输出 JSON。")
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(data, dict):
            violations = data.get("violations") or []
            result = [v for v in violations if isinstance(v, dict)]
            if result:
                logger.warning("ch%d 红线检测：%d 处违反", chapter, len(result))
            return result
        return []
    except Exception as e:
        logger.warning("check_redline_violations 失败（跳过）: %s", e)
        return []


# ════════════════════════════════════════════════════════════════════
# 子项1：伏笔自动埋设（提交后 LLM 提取本章可埋设伏笔 → 落库 pending）
# ════════════════════════════════════════════════════════════════════

_FORESHADOW_SUGGEST_PROMPT = """你是伏笔规划师。以下是第 {chapter} 章正文与本项目已存在的伏笔（避免重复埋设）。

【已有伏笔】
{existing}

【正文】
{text}

任务：提取本章适合埋设的新伏笔（未来才兑现的悬念/线索/矛盾）。
要求：
- 必须能从本章正文中自然产生（是正文里埋下的种子，不是凭空加设定）
- 与已有伏笔不重复
- 符合本书世界观设定

输出纯 JSON（禁止 markdown 围栏）：
{{"foreshadows": [{{"foreshadow_id": "S-001", "tier": "short|medium|long", "description": "伏笔内容", "planned_resolve_chapter": 计划回收章}}]}}
没有合适的新伏笔时输出 {{"foreshadows": []}}。"""


async def suggest_foreshadow_plants(
    content: str,
    repo,
    chapter: int,
    llm_client: Any,
) -> list[dict]:
    """提交后伏笔自动埋设：LLM 提取本章新伏笔 → 落库 status=pending（待正式埋设）。"""
    try:
        from novel_agent.bible.models import Foreshadow
        existing = repo.db.query(Foreshadow).filter(
            Foreshadow.project_id == repo.project_id,
        ).all()
        existing_text = "\n".join(
            f"- {f.foreshadow_id}: {f.description}" for f in existing[:20]) or "（无）"
        prompt = _FORESHADOW_SUGGEST_PROMPT.format(
            chapter=chapter, existing=existing_text, text=content[:6000])
        raw = await llm_client.generate(prompt, system="你是严谨的伏笔规划师，只输出 JSON。")
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        suggestions = []
        if isinstance(data, dict):
            for f in (data.get("foreshadows") or []):
                if not isinstance(f, dict) or not f.get("foreshadow_id"):
                    continue
                fid = str(f["foreshadow_id"])
                if repo.get_foreshadow(fid):
                    continue  # 已存在，跳过
                repo.create_foreshadow(
                    foreshadow_id=fid,
                    tier=f.get("tier", "short"),
                    description=str(f.get("description", ""))[:500],
                    plant_chapter=chapter,
                    planned_resolve_chapter=int(f.get("planned_resolve_chapter") or chapter + 5),
                    status="pending",
                )
                suggestions.append({"foreshadow_id": fid, "tier": f.get("tier", "short")})
            if suggestions:
                logger.info("ch%d 伏笔自动埋设建议：%d 条落库 pending", chapter, len(suggestions))
        return suggestions
    except Exception as e:
        logger.warning("suggest_foreshadow_plants 失败（跳过）: %s", e)
        return []


# ════════════════════════════════════════════════════════════════════
# 子项4：审校回写设定库（审校报告 → LLM 提取设定修正 → 应用）
# ════════════════════════════════════════════════════════════════════

_WRITEBACK_PROMPT = """你是设定管理员。以下是第 {chapter} 章审校报告发现的问题与当前角色卡。

【审校报告摘要】
{report}

【当前角色卡（name: 角色名，其余为字段）】
{characters}

任务：从审校报告中提取"需要修正的角色卡字段"（如外貌、性格、身份、关系等被正文推翻或需要补全的）。
只输出明确、可执行的字段修正，不确定的不要提。
输出纯 JSON（禁止 markdown 围栏）：
{{"fixes": [{{"name": "角色名", "field": "appearance|personality|motivation|background|secrets|relationships", "value": "修正后的内容"}}]}}
无修正时输出 {{"fixes": []}}。"""


async def writeback_audit_fixes(
    audit_report: Any,
    repo,
    chapter: int,
    llm_client: Any,
) -> list[dict]:
    """审校结论结构化 → 自动更新角色卡（只改审校明确指出的字段）。"""
    try:
        if not audit_report:
            return []
        if isinstance(audit_report, dict):
            report_text = str(audit_report.get("summary", ""))[:1500]
        else:
            report_text = str(audit_report)[:1500]
        chars = repo.list_characters()
        chars_text = "\n".join(
            f"- {c.name}: 外貌={c.appearance or ''} 性格={c.personality or ''} "
            f"动机={c.motivation or ''} 身份={c.role or ''}"
            for c in chars[:10]) or "（无角色卡）"
        prompt = _WRITEBACK_PROMPT.format(
            chapter=chapter, report=report_text, characters=chars_text)
        raw = await llm_client.generate(prompt, system="你是严谨的设定管理员，只输出 JSON。")
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        applied = []
        if isinstance(data, dict):
            allowed_fields = {
                "appearance", "personality", "motivation", "background",
                "secrets", "relationships", "role", "arc",
            }
            for fix in (data.get("fixes") or []):
                if not isinstance(fix, dict):
                    continue
                name = str(fix.get("name", "")).strip()
                field = str(fix.get("field", "")).strip()
                value = str(fix.get("value", "")).strip()
                if not name or field not in allowed_fields or not value:
                    continue
                if repo.get_character(name):
                    repo.update_character(name, **{field: value})
                    applied.append({"name": name, "field": field})
            if applied:
                logger.info("ch%d 审校回写设定库：%d 处角色卡字段已更新", chapter, len(applied))
        return applied
    except Exception as e:
        logger.warning("writeback_audit_fixes 失败（跳过）: %s", e)
        return []


# ════════════════════════════════════════════════════════════════════
# 子项5：圆桌落库（圆桌最终结论 → 写设定库）
# ════════════════════════════════════════════════════════════════════

def persist_roundtable_conclusions(
    repo,
    conclusions: dict[str, Any],
    source: str = "圆桌会议",
) -> int:
    """把圆桌结构化结论写进 Bible 设定库（角色卡 / 世界观设定）。

    conclusions 建议结构：
    {
        "characters": [{"name": "...", "field": "...", "value": "..."}],
        "world_settings": [{"category": "规则", "title": "...", "content": "..."}],
    }
    仅更新已存在的角色卡字段 / 新增世界观设定条目。返回落库条数。
    """
    if not isinstance(conclusions, dict):
        return 0
    count = 0
    # 角色卡
    for fix in (conclusions.get("characters") or []):
        try:
            if not isinstance(fix, dict):
                continue
            name = str(fix.get("name", "")).strip()
            field = str(fix.get("field", "")).strip()
            value = str(fix.get("value", "")).strip()
            if not name or not field or not value:
                continue
            if repo.get_character(name):
                repo.update_character(name, **{field: value})
                count += 1
        except Exception as e:
            logger.warning("圆桌落库：角色更新失败: %s", e)
    # 世界观设定
    for ws in (conclusions.get("world_settings") or []):
        try:
            if not isinstance(ws, dict):
                continue
            title = str(ws.get("title", "")).strip()
            content = str(ws.get("content", "")).strip()
            if not title or not content:
                continue
            repo.create_world_setting(
                category=str(ws.get("category", "规则"))[:50],
                title=title[:200],
                content=content,
            )
            count += 1
        except Exception as e:
            logger.warning("圆桌落库：世界观写入失败: %s", e)
    if count:
        logger.info("%s 结论落库设定库：%d 条", source, count)
    return count


# ════════════════════════════════════════════════════════════════════
# 统一入口：提交后闭环（接入 summarize_chapter 之后）
# ════════════════════════════════════════════════════════════════════

async def run_post_commit_closures(
    content: str,
    repo,
    chapter: int,
    llm_client: Any,
    state: dict | None = None,
) -> dict:
    """运行全部提交后闭环子项（各自容错，不阻塞主流程）。

    Returns:
        {"normalized_names": n, "redline_violations": [...],
         "foreshadows_suggested": [...], "audit_fixes": [...], "roundtable_landed": n}
    """
    result: dict[str, Any] = {
        "normalized_names": 0,
        "redline_violations": [],
        "foreshadows_suggested": [],
        "audit_fixes": [],
        "roundtable_landed": 0,
    }
    if not repo:
        return result

    # 3. 命名归一化：正文别名 → 正名（替换后回写正文文件，失败不阻塞）
    try:
        if content:
            normalized, cnt = normalize_names(content, repo)
            result["normalized_names"] = cnt
            if cnt and state and state.get("polished"):
                state["polished"] = normalized
    except Exception as e:
        logger.warning("ch%d 命名归一化失败: %s", chapter, e)

    # 2. 红线检测（LLM）
    if llm_client:
        result["redline_violations"] = await check_redline_violations(
            content, repo, chapter, llm_client)

    # 1. 伏笔自动埋设（LLM）
    if llm_client:
        result["foreshadows_suggested"] = await suggest_foreshadow_plants(
            content, repo, chapter, llm_client)

    # 4. 审校回写设定库（LLM）
    if llm_client:
        audit_report = (state or {}).get("audit_report")
        result["audit_fixes"] = await writeback_audit_fixes(
            audit_report, repo, chapter, llm_client)

    # 5. 圆桌落库：由圆桌引擎在会议结束后调用 persist_roundtable_conclusions，
    #    本入口不主动触发（需要圆桌结论作为输入）。
    return result
