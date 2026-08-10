"""ChatAgent 的工具集：bible 查询 + 写库 + 动作执行 + 子 agent 委托。

- 查询类：AI 自己调，拿到结果继续推理（不推 action SSE）
- 写库类：直接调 repo 创建/更新设定，推 action 事件让前端刷新
- 动作类：交给 ActionExecutor 执行
- 委托类：启动子 agent 做深度研究，上下文隔离
"""
from __future__ import annotations

import json
import logging
from typing import Any

from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.executor import ActionExecutor

# 编码工具集（文件读写/搜索/命令执行，已实现但此前未接进聊天主 Agent）
from novel_agent.tools.coding_tools import (
    CODING_TOOLS_SCHEMA,
    CODING_TOOLS_IMPL,
    CODING_TOOL_NAMES as _CODING_TOOL_NAMES,
)

logger = logging.getLogger(__name__)


def _char_to_dict(c) -> dict:
    return {
        "name": c.name,
        "role": getattr(c, "role", ""),
        "personality": getattr(c, "personality", ""),
        "motivation": getattr(c, "motivation", ""),
        "background": getattr(c, "background", ""),
        "current_location": getattr(c, "current_location", ""),
        "current_emotion": getattr(c, "current_emotion", ""),
        "absolute_taboos": getattr(c, "absolute_taboos", "") or "",
    }


def _summary_to_dict(s) -> dict:
    return {"chapter": s.chapter, "title": s.title, "core_events": getattr(s, "core_events", "")}


def _foreshadow_to_dict(f) -> dict:
    return {
        "id": f.foreshadow_id, "tier": f.tier, "description": f.description,
        "status": f.status, "plant_chapter": f.plant_chapter,
        "planned_resolve_chapter": f.planned_resolve_chapter, "depends_on": f.depends_on,
    }


def _outline_to_dict(o) -> dict:
    return {
        "chapter": getattr(o, "order", None), "title": o.title,
        "summary": getattr(o, "summary", ""), "required_beats": getattr(o, "required_beats", ""),
    }


def _faction_to_dict(f) -> dict:
    return {
        "name": f.name, "alias": getattr(f, "alias", ""), "type": getattr(f, "type", ""),
        "tier": getattr(f, "tier", ""), "alignment": getattr(f, "alignment", ""),
    }


# ---------- 查询类工具（只读，返回 JSON 字符串喂给 LLM） ----------

def _tool_get_character(repo: BibleRepository, name: str) -> str:
    c = repo.get_character(name)
    if not c:
        return f"角色「{name}」不存在"
    return json.dumps(_char_to_dict(c), ensure_ascii=False)


def _tool_list_characters(repo: BibleRepository, limit: int = 50, offset: int = 0) -> str:
    # 缺陷18：分页，防大量角色撑爆上下文
    chars = repo.list_characters()
    if not chars:
        return "本项目暂无角色"
    total = len(chars)
    chars = chars[offset:offset + limit]
    return json.dumps({"total": total, "returned": len(chars), "offset": offset,
                       "characters": [_char_to_dict(c) for c in chars]}, ensure_ascii=False)


def _tool_get_outline(repo: BibleRepository, chapter: int) -> str:
    o = repo.get_outline_by_chapter(chapter)
    if not o:
        return f"第{chapter}章没有章纲"
    return json.dumps(_outline_to_dict(o), ensure_ascii=False)


def _tool_list_chapter_summaries(repo: BibleRepository, limit: int = 10, offset: int = 0) -> str:
    # 缺陷18：分页，直接用 repo 的 limit/offset 查询，避免全量加载
    ss = repo.list_chapter_summaries(limit=limit, offset=offset)
    if not ss:
        return "暂无已生成章节"
    return json.dumps({"returned": len(ss), "offset": offset,
                       "summaries": [_summary_to_dict(s) for s in ss]}, ensure_ascii=False)


def _tool_list_foreshadows(repo: BibleRepository) -> str:
    fs = repo.list_foreshadows()
    if not fs:
        return "暂无伏笔"
    return json.dumps([_foreshadow_to_dict(f) for f in fs], ensure_ascii=False)


def _tool_query_status(repo: BibleRepository) -> str:
    from novel_agent.bible.models import ChapterSummary
    generated_count = repo.db.query(ChapterSummary).filter(
        ChapterSummary.project_id == repo.project_id).count()
    outlines = repo.list_outlines(level="chapter")
    fores = repo.list_foreshadows()
    unresolved = [f for f in fores if f.status not in ("resolved", "abandoned")]
    result = {
        "ok": True, "outline_count": len(outlines),
        "generated_count": generated_count, "unresolved_foreshadows": len(unresolved),
    }
    return json.dumps(result, ensure_ascii=False, default=str)


def _tool_list_factions(repo: BibleRepository) -> str:
    fs = repo.list_factions()
    if not fs:
        return "暂无势力/组织"
    return json.dumps([_faction_to_dict(f) for f in fs], ensure_ascii=False)


def _tool_search(repo: BibleRepository, keyword: str) -> str:
    """缺陷17：跨对象全文检索（角色/伏笔/章纲/世界观/势力）。"""
    kw = keyword.strip()
    if not kw:
        return "关键词不能为空"
    hits: list[dict] = []
    MAX_HITS = 20

    def _add(hit: dict) -> None:
        if len(hits) < MAX_HITS:
            hits.append(hit)

    for c in repo.list_characters():
        if len(hits) >= MAX_HITS:
            break
        text = f"{c.name} {getattr(c, 'role', '')} {getattr(c, 'personality', '')} {getattr(c, 'background', '')} {getattr(c, 'motivation', '')}"
        if kw in text:
            _add({"type": "character", "name": c.name, "snippet": text[:100]})
    for f in repo.list_foreshadows():
        if len(hits) >= MAX_HITS:
            break
        text = f"{f.foreshadow_id} {f.description}"
        if kw in text:
            _add({"type": "foreshadow", "id": f.foreshadow_id, "snippet": f.description[:100]})
    # 章纲太多，只搜 volume 和 arc 层级，不搜 chapter
    for o in [*repo.list_outlines(level="volume"), *repo.list_outlines(level="arc")]:
        if len(hits) >= MAX_HITS:
            break
        text = f"{o.title} {getattr(o, 'summary', '')}"
        if kw in text:
            _add({"type": "outline", "title": o.title, "snippet": getattr(o, 'summary', '')[:100]})
    for w in repo.list_world_settings():
        if len(hits) >= MAX_HITS:
            break
        text = f"{w.title} {w.content}"
        if kw in text:
            _add({"type": "world_setting", "title": w.title, "snippet": w.content[:100]})
    for f in repo.list_factions():
        if len(hits) >= MAX_HITS:
            break
        text = f"{f.name} {getattr(f, 'alias', '')}"
        if kw in text:
            _add({"type": "faction", "name": f.name, "snippet": text[:100]})
    if not hits:
        return f"未找到包含「{kw}」的设定"
    return json.dumps({"keyword": kw, "hit_count": len(hits), "hits": hits}, ensure_ascii=False)


def _tool_get_character_appearances(repo: BibleRepository, name: str) -> str:
    """缺陷4：关联查询--角色在哪些章节出场。"""
    apps = repo.list_entity_appearances(entity_type="character", entity_id=name)
    if not apps:
        return f"未找到角色「{name}」的出场记录（可能该角色尚未标记出场章节）"
    return json.dumps([
        {"chapter": getattr(a, "chapter", None), "role": getattr(a, "role", ""),
         "note": getattr(a, "note", "")} for a in apps
    ], ensure_ascii=False)


def _tool_read_reference_files(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    """读取项目参考文件内容（设定总纲、参考资料等）。"""
    from novel_agent.config import load_config
    cfg = load_config()
    ref_dir = cfg.project_dir(repo.project_id) / "references"
    if not ref_dir.exists():
        return _ok("read_reference_files", {"files": [], "message": "项目没有参考文件目录"})
    keyword = (arguments.get("keyword") or "").strip()
    files = []
    for f in sorted(ref_dir.iterdir()):
        if not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                continue
            # 有关键词时只返回包含关键词的文件
            if keyword and keyword not in content:
                continue
            # 不截断，返回完整内容
            files.append({"name": f.name, "content": content})
        except Exception:
            continue
    if not files:
        return _ok("read_reference_files", {"files": [], "message": f"未找到{'包含「'+keyword+'」的' if keyword else ''}参考文件"})
    return _ok("read_reference_files", {"files": files, "count": len(files)})


# ---------- Skill 管理类工具（读写 project_data/skills/） ----------

def _tool_list_skills(repo: BibleRepository) -> str:
    """列出所有 Skill（含内置/用户自建）。"""
    from novel_agent.api.routes_skills import _skills_dir
    try:
        d = _skills_dir()
        skills = []
        for p in sorted(d.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                skills.append({
                    "name": data.get("name"),
                    "description": (data.get("description") or "")[:120],
                    "enabled": data.get("enabled", True),
                    "source": data.get("source", "builtin" if data.get("is_builtin") else "user"),
                    "sections_count": len(data.get("sections") or []),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return json.dumps({"total": len(skills), "skills": skills}, ensure_ascii=False)
    except Exception as e:
        return f"列出 Skill 失败: {e}"


def _tool_get_skill(repo: BibleRepository, name: str) -> str:
    """获取单个 Skill 完整内容。"""
    from novel_agent.api.routes_skills import _skill_path
    name = (name or "").strip()
    path = _skill_path(name)
    if not path.exists():
        return f"Skill「{name}」不存在"
    try:
        with open(path, encoding="utf-8") as f:
            return json.dumps(json.load(f), ensure_ascii=False)
    except (json.JSONDecodeError, OSError) as e:
        return f"读取 Skill 失败: {e}"


def _tool_create_skill(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    """创建新 Skill。"""
    name = (arguments.get("name") or "").strip()
    if not name:
        return _fail("create_skill", "name 不能为空")
    desc = (arguments.get("description") or "").strip()
    content = (arguments.get("content") or "").strip()
    if not content:
        return _fail("create_skill", "content（技能正文）不能为空")
    from novel_agent.api.routes_skills import _skill_path
    path = _skill_path(name)
    if path.exists():
        return _fail("create_skill", f"Skill「{name}」已存在，如需修改请用 update_skill")
    data = {
        "name": name,
        "description": desc,
        "enabled": arguments.get("enabled", True),
        "sections": [{"name": "body", "content": content}],
        "tools": arguments.get("tools", []) or [],
        "references": arguments.get("references", []) or [],
        "is_builtin": False,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        from novel_agent.api.routes_skills import rebuild_skill_index
        rebuild_skill_index()
        return _ok("create_skill", {"name": name, "created": True})
    except OSError as e:
        return _fail("create_skill", str(e))


def _tool_update_skill(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    """更新已有 Skill（改 description/content/enabled 等）。"""
    name = (arguments.get("name") or "").strip()
    if not name:
        return _fail("update_skill", "name 不能为空")
    from novel_agent.api.routes_skills import _skill_path
    path = _skill_path(name)
    if not path.exists():
        return _fail("update_skill", f"Skill「{name}」不存在")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return _fail("update_skill", f"读取失败: {e}")
    if data.get("is_builtin"):
        return _fail("update_skill", f"内置 Skill「{name}」不可修改，只可禁用")
    changed = []
    if "description" in arguments:
        data["description"] = arguments["description"]
        changed.append("description")
    if "content" in arguments and arguments["content"]:
        data["sections"] = [{"name": "body", "content": arguments["content"]}]
        changed.append("content")
    if "enabled" in arguments:
        data["enabled"] = bool(arguments["enabled"])
        changed.append("enabled")
    if "tools" in arguments:
        data["tools"] = arguments["tools"] or []
        changed.append("tools")
    if "references" in arguments:
        data["references"] = arguments["references"] or []
        changed.append("references")
    if not changed:
        return _fail("update_skill", "没有要更新的字段")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        from novel_agent.api.routes_skills import rebuild_skill_index
        rebuild_skill_index()
        return _ok("update_skill", {"name": name, "updated": changed})
    except OSError as e:
        return _fail("update_skill", str(e))


def _tool_delete_skill(repo: BibleRepository, name: str) -> dict[str, Any]:
    """删除 Skill（内置不可删）。"""
    from novel_agent.api.routes_skills import _skill_path
    name = (name or "").strip()
    path = _skill_path(name)
    if not path.exists():
        return _fail("delete_skill", f"Skill「{name}」不存在")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("is_builtin"):
            return _fail("delete_skill", f"内置 Skill「{name}」不可删除，只可禁用")
    except (json.JSONDecodeError, OSError):
        pass
    try:
        path.unlink()
        from novel_agent.api.routes_skills import rebuild_skill_index
        rebuild_skill_index()
        return _ok("delete_skill", {"name": name, "deleted": True})
    except OSError as e:
        return _fail("delete_skill", str(e))


def _tool_search_skills(repo: BibleRepository, query: str) -> str:
    """跨 Skill 搜索（复用统一索引：关键词 + 向量语义补漏）。

    与 REST /api/skills/search 共用同一索引，避免 Agent 视角与 API 视角结果不一致。
    """
    from novel_agent.api.routes_skills import _skill_index
    query = (query or "").strip()
    try:
        if not query:
            return "搜索 Skill 失败: query 不能为空"
        results = _skill_index.search(query, limit=10)
        hits = [{"name": r["skill_name"], "description": (r.get("description") or "")[:120],
                 "enabled": r.get("enabled", True)} for r in results]
        if not hits:
            return f"未找到包含「{query}」的 Skill"
        return json.dumps({"query": query, "hit_count": len(hits), "hits": hits}, ensure_ascii=False)
    except Exception as e:
        return f"搜索 Skill 失败: {e}"


# ---------- 记忆类工具（读章节文件 + 向量语义检索） ----------

def _tool_read_chapter_file(repo: BibleRepository, chapter: int) -> str:
    """读取已写章节的正文文件。"""
    try:
        from novel_agent.memory.recall import RecallMemory
        cfg = repo.config if hasattr(repo, "config") else None
        if cfg is None:
            from novel_agent.config import load_config
            cfg = load_config()
        project_id = getattr(repo, "project_id", None)
        rm = RecallMemory(cfg, project_id=project_id)
        text = rm.read_chapter_text(int(chapter))
        if not text:
            return f"第{chapter}章还没有正文（尚未生成或未保存）"
        return f"【第{chapter}章正文】\n{text}"
    except Exception as e:
        return f"读取章节文件失败: {e}"


def _tool_list_chapter_files(repo: BibleRepository) -> str:
    """列出所有已写章节。"""
    try:
        from novel_agent.memory.recall import RecallMemory
        cfg = repo.config if hasattr(repo, "config") else None
        if cfg is None:
            from novel_agent.config import load_config
            cfg = load_config()
        project_id = getattr(repo, "project_id", None)
        rm = RecallMemory(cfg, project_id=project_id)
        items = rm.list_chapters_with_titles()
        if not items:
            return "当前还没有已写章节"
        return json.dumps({"chapters": items}, ensure_ascii=False)
    except Exception as e:
        return f"列出章节失败: {e}"


def _tool_memory_search(repo: BibleRepository, query: str, top_k: int = 4) -> str:
    """向量语义检索已写章节/设定，找回相关内容。"""
    try:
        from novel_agent.memory.archival import ArchivalMemory
        cfg = repo.config if hasattr(repo, "config") else None
        if cfg is None:
            from novel_agent.config import load_config
            cfg = load_config()
        project_id = getattr(repo, "project_id", None)
        am = ArchivalMemory(cfg, project_id=project_id)
        if not am.is_available():
            return "向量记忆不可用（初始化失败），可改用 read_chapter_file 读具体章节"
        res = am.retrieve(query, top_k=int(top_k))
        docs = res.get("documents", [[]])[0]
        if not docs:
            return f"未检索到与「{query}」相关的内容"
        lines = [f"【检索：{query}】"]
        for d in docs:
            lines.append(f"- {d}")
        return "\n".join(lines)
    except Exception as e:
        return f"记忆检索失败: {e}"


# ---------- 网络类工具（抓取网页正文） ----------

async def _tool_web_fetch(url: str) -> str:
    """抓取指定 URL 的正文内容（去 HTML 标签，最多 30000 字）。"""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return "无效 URL，必须以 http:// 或 https:// 开头"
    try:
        import re
        import urllib.request

        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (NovelCompose)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read(200000).decode("utf-8", errors="replace")
        # 去 script/style/注释
        html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
        html = re.sub(r"(?s)<!--.*?-->", " ", html)
        # 去标签
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 30000:
            text = text[:30000] + "\n... (内容已截断)"
        if not text:
            return f"URL {url} 未提取到文本内容（可能是 JS 渲染页面）"
        return f"【{url} 抓取内容】\n{text}"
    except Exception as e:
        return f"抓取网页失败: {e}"


def _extract_options_from_text(text: str) -> list[dict]:
    """从文本里提取'选项A：...'格式的选项（兜底：AI 没调 present_options 时自动提取）。"""
    import re
    # 匹配 "选项 A：描述" / "**选项 A**：描述" / "- 选项A：描述" / "方向A：描述"
    pattern = r'[-*\s]*\**(?:选项|方向)\s*([A-Z])\**\s*[:：]\s*(.+?)(?=\n[-*\s]*\**(?:选项|方向)|\n\n|\n#|\Z)'
    matches = re.findall(pattern, text, re.DOTALL)
    if len(matches) < 2:
        return []
    return [{"label": f"选项{m[0]}：{m[1].strip()[:120]}", "value": f"选项{m[0]}"} for m in matches]


# ---------- 写库类工具实现（有副作用，返回 {"result", "action"}） ----------

def _ok(action_type: str, result: dict) -> dict[str, Any]:
    return {"result": json.dumps(result, ensure_ascii=False),
            "action": {"type": action_type, "status": "done", "result": result}}


def _fail(action_type: str, err: str) -> dict[str, Any]:
    return {"result": f"操作失败: {err}",
            "action": {"type": action_type, "status": "failed", "error": err}}


def _tool_create_character(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    name = (arguments.get("name") or "").strip()
    if not name:
        return _fail("create_character", "name 为空")
    kwargs = {k: v for k, v in arguments.items() if v is not None}
    try:
        c = repo.create_character(**kwargs)
        return _ok("create_character", {"name": c.name, "id": getattr(c, "id", None)})
    except Exception as e:
        return _fail("create_character", str(e))


def _tool_update_character(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    name = (arguments.get("name") or "").strip()
    if not name:
        return _fail("update_character", "name 为空")
    updates = {k: v for k, v in arguments.items() if k != "name" and v is not None}
    if not updates:
        return _fail("update_character", "没有要更新的字段")
    try:
        c = repo.update_character(name, **updates)
        if not c:
            return _fail("update_character", f"角色「{name}」不存在")
        return _ok("update_character", {"name": c.name})
    except Exception as e:
        return _fail("update_character", str(e))


def _tool_create_outline(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    title = (arguments.get("title") or "").strip()
    if not title:
        return _fail("create_outline", "title 为空")
    kwargs = {k: v for k, v in arguments.items() if v is not None}
    kwargs.setdefault("level", "chapter")
    requested_order = kwargs.get("order")
    try:
        o = repo.create_outline(**kwargs)
        actual_order = getattr(o, "order", None)
        result = {"title": o.title, "order": actual_order}
        # Bug 修复：repo 在 order 冲突时会自动重编号，告知 AI 实际 order
        if requested_order is not None and actual_order != requested_order:
            result["warning"] = f"order 被调整为 {actual_order}（{requested_order} 已存在或冲突）"
        return _ok("create_outline", result)
    except Exception as e:
        return _fail("create_outline", str(e))


def _tool_update_outline(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    chapter = arguments.get("chapter")
    if chapter is None:
        return _fail("update_outline", "需要 chapter（章节号）定位要改的章纲")
    o = repo.get_outline_by_chapter(int(chapter))
    if not o:
        return _fail("update_outline", f"第{chapter}章没有章纲")
    updates = {k: v for k, v in arguments.items() if k != "chapter" and v is not None}
    if not updates:
        return _fail("update_outline", "没有要更新的字段")
    try:
        o = repo.update_outline(o.id, **updates)
        return _ok("update_outline", {"title": o.title} if o else {})
    except Exception as e:
        return _fail("update_outline", str(e))


def _tool_create_foreshadow(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    fid = (arguments.get("foreshadow_id") or "").strip()
    desc = (arguments.get("description") or "").strip()
    if not fid or not desc:
        return _fail("create_foreshadow", "foreshadow_id 和 description 不能为空")
    kwargs = {k: v for k, v in arguments.items() if v is not None}
    kwargs.setdefault("status", "pending")
    try:
        f = repo.create_foreshadow(**kwargs)
        return _ok("create_foreshadow", {"foreshadow_id": f.foreshadow_id})
    except Exception as e:
        return _fail("create_foreshadow", str(e))


def _tool_update_foreshadow(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    fid = (arguments.get("foreshadow_id") or "").strip()
    if not fid:
        return _fail("update_foreshadow", "foreshadow_id 不能为空")
    updates = {k: v for k, v in arguments.items() if k != "foreshadow_id" and v is not None}
    # 状态变更必须走 update_foreshadow_status（有状态机校验），防止绕过
    if "status" in updates:
        return _fail("update_foreshadow",
                     "状态变更请用 update_foreshadow_status 工具（有状态机校验），update_foreshadow 不允许直接改 status")
    if not updates:
        return _fail("update_foreshadow", "没有要更新的字段")
    try:
        f = repo.update_foreshadow(fid, **updates)
        if not f:
            return _fail("update_foreshadow", f"伏笔「{fid}」不存在")
        return _ok("update_foreshadow", {"foreshadow_id": f.foreshadow_id})
    except Exception as e:
        return _fail("update_foreshadow", str(e))


def _tool_update_foreshadow_status(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    """改伏笔状态。合法转换：pending->planted/abandoned, planted->developing/resolved/abandoned, developing->resolved/abandoned。"""
    fid = (arguments.get("foreshadow_id") or "").strip()
    status = (arguments.get("status") or "").strip()
    if not fid or not status:
        return _fail("update_foreshadow_status", "foreshadow_id 和 status 不能为空")
    try:
        f = repo.update_foreshadow_status(fid, status)
        if not f:
            return _fail("update_foreshadow_status", f"伏笔「{fid}」不存在")
        # Bug 修复：repo 静默拒绝非法跳转，返回原对象。检查状态是否真变了
        if f.status != status:
            return _fail("update_foreshadow_status",
                         f"状态跳转被拒：{f.status} -> {status} 不合法。"
                         f"合法转换：pending->planted/abandoned, planted->developing/resolved/abandoned, developing->resolved/abandoned")
        return _ok("update_foreshadow_status", {"foreshadow_id": f.foreshadow_id, "status": f.status})
    except Exception as e:
        return _fail("update_foreshadow_status", str(e))


def _tool_create_world_setting(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    title = (arguments.get("title") or "").strip()
    content = (arguments.get("content") or "").strip()
    if not title or not content:
        return _fail("create_world_setting", "title 和 content 不能为空")
    kwargs = {k: v for k, v in arguments.items() if v is not None}
    try:
        w = repo.create_world_setting(**kwargs)
        return _ok("create_world_setting", {"title": w.title})
    except Exception as e:
        return _fail("create_world_setting", str(e))


def _tool_create_faction(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    name = (arguments.get("name") or "").strip()
    if not name:
        return _fail("create_faction", "name 为空")
    kwargs = {k: v for k, v in arguments.items() if v is not None}
    try:
        f = repo.create_faction(**kwargs)
        return _ok("create_faction", {"name": f.name})
    except Exception as e:
        return _fail("create_faction", str(e))


def _tool_update_faction(repo: BibleRepository, arguments: dict[str, Any]) -> dict[str, Any]:
    faction_id = arguments.get("faction_id")
    name = arguments.get("name")
    # 优先用 faction_id 定位，其次用 name 查找
    if faction_id:
        f = repo.get_faction(faction_id)
    elif name:
        f = repo.get_faction_by_name(name)
    else:
        return _fail("update_faction", "需要 faction_id 或 name 定位势力")
    if not f:
        return _fail("update_faction", f"势力「{name or faction_id}」不存在")
    updates = {k: v for k, v in arguments.items()
               if k not in ("faction_id",) and v is not None}
    if not updates:
        return _fail("update_faction", "没有要更新的字段")
    try:
        f = repo.update_faction(f.id, **updates)
        return _ok("update_faction", {"name": f.name} if f else {})
    except Exception as e:
        return _fail("update_faction", str(e))


# ---------- 质量检查类工具（只读，不改数据） ----------

# 默认禁止术语（项目级红线，可通过 RedLine 表扩展）
_DEFAULT_FORBIDDEN_TERMS = ["神明牧场", "四大神明", "神明收割"]


async def _tool_check_red_line(repo: BibleRepository, text: str) -> str:
    """检查文本是否包含禁止术语。"""
    if not text or not text.strip():
        return json.dumps({"passed": False, "error": "文本不能为空"}, ensure_ascii=False)

    # 从项目 RedLine 表提取额外禁止术语（severity=hard 且内容含"禁止"关键词的）
    forbidden = list(_DEFAULT_FORBIDDEN_TERMS)
    try:
        from novel_agent.bible.models import RedLine
        redlines = repo.db.query(RedLine).filter(
            RedLine.project_id == repo.project_id,
            RedLine.severity == "hard",
            RedLine.enabled == True,
        ).all()
        for rl in redlines:
            # 从红线内容中提取引号内的术语
            import re as _re
            quoted = _re.findall(r'[「"\']([^」"\']+)[」"\']', rl.content or "")
            for q in quoted:
                if 2 <= len(q) <= 10 and q not in forbidden:
                    forbidden.append(q)
    except Exception:
        pass  # RedLine 表不存在时用默认列表

    violations = []
    for term in forbidden:
        count = text.count(term)
        if count > 0:
            positions = []
            start = 0
            while True:
                idx = text.find(term, start)
                if idx == -1:
                    break
                positions.append(idx)
                start = idx + len(term)
            violations.append({"term": term, "count": count, "positions": positions[:10]})

    if violations:
        return json.dumps({"passed": False, "violations": violations,
                           "summary": f"发现 {len(violations)} 个违规术语"}, ensure_ascii=False)
    return json.dumps({"passed": True, "message": "文本未违反写作红线"}, ensure_ascii=False)


_AI_STYLE_PROMPT = """分析以下章节正文的AI味浓度，按六维度评分（1-10分，越高越AI味浓）：

1. 句式工整度：句式是否过于整齐划一（长短句交替是否自然）
2. 修辞均匀度：修辞手法是否分布过于均匀（比喻/拟人等是否集中堆砌）
3. 情感正确度：情感表达是否"正确"但缺乏真实感（是否像AI模拟而非人类感受）
4. 过渡平滑度：段落过渡是否过于平滑（缺乏突兀感和真实节奏）
5. 描写全面度：描写是否面面俱到（视觉/听觉/嗅觉/触觉是否每次都全写）
6. 对话功能化度：对话是否过于功能性（每句对话都在推进剧情，缺乏闲聊/废话）

文本：
{text}

输出 JSON 格式：
{{"dimensions": [{{"name": "维度名", "score": 评分, "issues": "问题段落引用", "suggestion": "修改建议"}}], "overall": "总体评价"}}"""


async def _tool_check_ai_style(repo: BibleRepository, text: str, llm_client=None) -> str:
    """检测AI味浓度，六维度评分。"""
    if not text or not text.strip():
        return json.dumps({"error": "文本不能为空"}, ensure_ascii=False)
    if llm_client is None:
        return json.dumps({"error": "LLM 客户端不可用"}, ensure_ascii=False)

    prompt = _AI_STYLE_PROMPT.format(text=text[:8000])
    messages = [{"role": "user", "content": prompt}]

    result = ""
    async for event in llm_client.chat_stream(messages, max_tokens=2000):
        if event["type"] == "text_delta":
            result += event["content"]

    return result or json.dumps({"error": "AI 分析返回空"}, ensure_ascii=False)


_EXCITEMENT_PROMPT = """分析以下章节正文的爽点密度和类型分布。

爽点类型参考：打脸、装逼、获得（物品/能力/认可）、反杀、突破升级、认主、揭穿真相、虐菜碾压、智斗获胜、救场、情感共鸣、悬念制造

文本：
{text}

输出 JSON 格式：
{{"excitements": [{{"type": "爽点类型", "description": "具体描述", "intensity": "强/中/弱"}}], "density": "密度评价（充足/适中/不足）", "missing_types": ["建议补充的爽点类型"], "suggestion": "节奏建议"}}"""


async def _tool_check_excitement(repo: BibleRepository, text: str, llm_client=None) -> str:
    """检测爽点密度和类型分布。"""
    if not text or not text.strip():
        return json.dumps({"error": "文本不能为空"}, ensure_ascii=False)
    if llm_client is None:
        return json.dumps({"error": "LLM 客户端不可用"}, ensure_ascii=False)

    prompt = _EXCITEMENT_PROMPT.format(text=text[:8000])
    messages = [{"role": "user", "content": prompt}]

    result = ""
    async for event in llm_client.chat_stream(messages, max_tokens=2000):
        if event["type"] == "text_delta":
            result += event["content"]

    return result or json.dumps({"error": "AI 分析返回空"}, ensure_ascii=False)


# ---------- OpenAI function calling schema ----------

TOOLS_SCHEMA: list[dict[str, Any]] = [
    # ── 查询类（只读，不推 action） ──
    {"type": "function", "function": {
        "name": "get_character",
        "description": "查询某个角色的详细设定。",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string", "description": "角色名"}},
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "list_characters",
        "description": "列出所有角色（分页）。默认返回前50个。",
        "parameters": {"type": "object",
                       "properties": {
                           "limit": {"type": "integer", "default": 50},
                           "offset": {"type": "integer", "default": 0, "description": "跳过前N条"},
                       }},
    }},
    {"type": "function", "function": {
        "name": "get_outline",
        "description": "查询指定章节的章纲。",
        "parameters": {"type": "object",
                       "properties": {"chapter": {"type": "integer", "description": "章节号"}},
                       "required": ["chapter"]},
    }},
    {"type": "function", "function": {
        "name": "list_chapter_summaries",
        "description": "列出章节摘要（分页）。默认最近10章。",
        "parameters": {"type": "object",
                       "properties": {
                           "limit": {"type": "integer", "default": 10},
                           "offset": {"type": "integer", "default": 0},
                       }},
    }},
    {"type": "function", "function": {
        "name": "list_foreshadows",
        "description": "列出所有伏笔及其状态。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "query_status",
        "description": "查询项目整体状态（大纲数、已生成章节数、未回收伏笔数）。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_factions",
        "description": "列出所有势力/组织。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "search",
        "description": "跨对象全文检索：搜角色/伏笔/章纲/世界观/势力中包含关键词的条目。当用户问“搜一下XX”“哪些设定提到XX”时调用。",
        "parameters": {"type": "object",
                       "properties": {"keyword": {"type": "string", "description": "搜索关键词"}},
                       "required": ["keyword"]},
    }},
    {"type": "function", "function": {
        "name": "get_character_appearances",
        "description": "查角色在哪些章节出场（关联查询）。当用户问“XX在哪几章出场”“涉及XX的章节”时调用。",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string", "description": "角色名"}},
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "check_red_line",
        "description": "检查文本是否违反写作红线（禁止术语）。检查章节正文/细纲/对话是否包含不该出现的术语。每次写章节后应调用。",
        "parameters": {"type": "object",
                       "properties": {
                           "text": {"type": "string", "description": "要检查的文本内容"},
                       },
                       "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "check_ai_style",
        "description": "检测章节正文的AI味浓度，六维度评分（句式工整度/修辞均匀度/情感正确度/过渡平滑度/描写全面度/对话功能化度），给出去AI味建议。",
        "parameters": {"type": "object",
                       "properties": {
                           "text": {"type": "string", "description": "要检测的章节正文内容"},
                       },
                       "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "check_excitement",
        "description": "检测章节的爽点密度和类型分布，评价节奏是否合理。每章至少1个爽点，高潮章2-3个。",
        "parameters": {"type": "object",
                       "properties": {
                           "text": {"type": "string", "description": "要检测的章节正文内容"},
                       },
                       "required": ["text"]},
    }},
    # ── 写库类（推 action 让前端刷新） ──
    {"type": "function", "function": {
        "name": "create_character",
        "description": "创建新角色并写库。用户要求“创建/新增角色叫XX”时必须调用。",
        "parameters": {"type": "object",
                       "properties": {
                           "name": {"type": "string", "description": "角色名（必填）"},
                           "role": {"type": "string"}, "personality": {"type": "string"},
                           "motivation": {"type": "string"}, "background": {"type": "string"},
                           "current_location": {"type": "string"}, "current_emotion": {"type": "string"},
                           "absolute_taboos": {"type": "string"},
                       },
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "update_character",
        "description": "修改已有角色。name 必填，其余只传要改的字段。",
        "parameters": {"type": "object",
                       "properties": {
                           "name": {"type": "string", "description": "要修改的角色名（必填）"},
                           "role": {"type": "string"}, "personality": {"type": "string"},
                           "motivation": {"type": "string"}, "background": {"type": "string"},
                           "current_location": {"type": "string"}, "current_emotion": {"type": "string"},
                           "absolute_taboos": {"type": "string"},
                       },
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "create_outline",
        "description": "创建章纲并写库。order 是章节号。",
        "parameters": {"type": "object",
                       "properties": {
                           "order": {"type": "integer", "description": "章节号"},
                           "title": {"type": "string", "description": "章节标题（必填）"},
                           "summary": {"type": "string"}, "act": {"type": "string"}, "strand": {"type": "string"},
                       },
                       "required": ["title"]},
    }},
    {"type": "function", "function": {
        "name": "update_outline",
        "description": "修改已有章纲。用 chapter 章节号定位。",
        "parameters": {"type": "object",
                       "properties": {
                           "chapter": {"type": "integer", "description": "章节号（必填，定位用）"},
                           "title": {"type": "string"}, "summary": {"type": "string"},
                           "act": {"type": "string"}, "strand": {"type": "string"},
                       },
                       "required": ["chapter"]},
    }},
    {"type": "function", "function": {
        "name": "create_foreshadow",
        "description": "埋新伏笔并写库。",
        "parameters": {"type": "object",
                       "properties": {
                           "foreshadow_id": {"type": "string", "description": "伏笔唯一ID，如 fs_m001（必填）"},
                           "tier": {"type": "string"}, "description": {"type": "string", "description": "伏笔描述（必填）"},
                           "plant_chapter": {"type": "integer"}, "planned_resolve_chapter": {"type": "integer"},
                           "status": {"type": "string", "default": "pending"},
                       },
                       "required": ["foreshadow_id", "description"]},
    }},
    {"type": "function", "function": {
        "name": "update_foreshadow",
        "description": "修改已有伏笔。用 foreshadow_id 定位。",
        "parameters": {"type": "object",
                       "properties": {
                           "foreshadow_id": {"type": "string", "description": "伏笔ID（必填）"},
                           "description": {"type": "string"}, "tier": {"type": "string"},
                           "plant_chapter": {"type": "integer"}, "planned_resolve_chapter": {"type": "integer"},
                           "status": {"type": "string"},
                       },
                       "required": ["foreshadow_id"]},
    }},
    {"type": "function", "function": {
        "name": "update_foreshadow_status",
        "description": "单独改伏笔状态。合法值：pending（待埋）/ planted（已埋）/ developing（发展中）/ resolved（已回收）/ abandoned（已废弃）。转换规则：pending->planted/abandoned, planted->developing/resolved/abandoned, developing->resolved/abandoned。",
        "parameters": {"type": "object",
                       "properties": {
                           "foreshadow_id": {"type": "string", "description": "伏笔ID（必填）"},
                           "status": {"type": "string", "description": "新状态（必填）"},
                       },
                       "required": ["foreshadow_id", "status"]},
    }},
    {"type": "function", "function": {
        "name": "create_world_setting",
        "description": "新增世界观设定并写库。如新增势力规则、地理、力量体系等。",
        "parameters": {"type": "object",
                       "properties": {
                           "category": {"type": "string"}, "title": {"type": "string", "description": "标题（必填）"},
                           "content": {"type": "string", "description": "内容（必填）"}, "order": {"type": "integer", "default": 0},
                       },
                       "required": ["title", "content"]},
    }},
    {"type": "function", "function": {
        "name": "create_faction",
        "description": "创建势力/组织并写库。如治安队、神殿、黑市等。",
        "parameters": {"type": "object",
                       "properties": {
                           "name": {"type": "string", "description": "势力名（必填）"},
                           "alias": {"type": "string"}, "type": {"type": "string"},
                           "tier": {"type": "string"}, "alignment": {"type": "string"},
                       },
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "update_faction",
        "description": "修改已有势力。用 faction_id 或 name 定位。可改 alignment/tier/description/goals 等字段。",
        "parameters": {"type": "object",
                       "properties": {
                           "faction_id": {"type": "integer", "description": "势力ID（优先用此字段定位）"},
                           "name": {"type": "string", "description": "势力名（无 faction_id 时用此字段查找）"},
                           "alias": {"type": "string"}, "type": {"type": "string"},
                           "tier": {"type": "string"}, "alignment": {"type": "string"},
                           "description": {"type": "string"}, "goals": {"type": "string"},
                           "hierarchy": {"type": "string"}, "territories": {"type": "string"},
                           "resources": {"type": "string"}, "history": {"type": "string"},
                       },
                       "required": []},
    }},
    # ── 交互类（推 action 让前端渲染选项按钮） ──
    {"type": "function", "function": {
        "name": "present_options",
        "description": "【必须用此工具提问】向用户展示可点击的选项按钮。当你想问用户问题、给方向让用户选时，必须调用此工具弹出按钮。【绝对禁止】在文本里直接提问，必须用此工具。调用后不要继续生成文本，等用户选择。",
        "parameters": {"type": "object",
                       "properties": {
                           "options": {
                               "type": "array",
                               "items": {
                                   "type": "object",
                                   "properties": {
                                       "label": {"type": "string", "description": "选项显示文本"},
                                       "value": {"type": "string", "description": "选项值（用户点击后发送这个）"},
                                   },
                                   "required": ["label", "value"],
                               },
                               "description": "选项列表（2-4个）",
                           },
                       },
                       "required": ["options"]},
    }},
    # ── 动作类（交给 executor） ──
    {"type": "function", "function": {
        "name": "rewrite_chapter",
        "description": "启动章节重写流程。用户明确要求重写/改写某章时调用。",
        "parameters": {"type": "object",
                       "properties": {"chapter": {"type": "integer"}, "feedback": {"type": "string"}},
                       "required": ["chapter"]},
    }},
    {"type": "function", "function": {
        "name": "add_chapter_feedback",
        "description": "给某章追加修改意见（不立即重写）。",
        "parameters": {"type": "object",
                       "properties": {"chapter": {"type": "integer"}, "feedback": {"type": "string"}},
                       "required": ["chapter", "feedback"]},
    }},
    # ── 委托类 ──
    {"type": "function", "function": {
        "name": "delegate_research",
        "description": "委托子 agent 做深度研究：查多个设定并综合成摘要返回。只读不改。",
        "parameters": {"type": "object",
                       "properties": {"task": {"type": "string", "description": "研究任务"}},
                       "required": ["task"]},
    }},
    # ── 参考文件类 ──
    {"type": "function", "function": {
        "name": "read_reference_files",
        "description": "读取项目参考文件内容（设定总纲、参考资料等）。可传 keyword 过滤只返回包含关键词的文件。单文件最大30000字符。",
        "parameters": {"type": "object",
                       "properties": {
                           "keyword": {"type": "string", "description": "可选关键词，只返回包含该词的文件"},
                       },
                       "required": []},
    }},
    # ── Skill 管理类（读写 project_data/skills/） ──
    {"type": "function", "function": {
        "name": "list_skills",
        "description": "列出所有 Skill（写作技能），含内置和用户自建，返回名称/描述/启用状态。当用户问“有哪些技能/skill”时调用。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "get_skill",
        "description": "获取指定 Skill 的完整内容（正文）。用户要看某个技能详情时调用。",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string", "description": "Skill 名称（必填）"}},
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "create_skill",
        "description": "创建新的 Skill（写作技能）并落盘。用户要求“做一个/创建一个/写个 skill 帮助我写XXX文”时调用。name 用 kebab-case 小写短横线（如 urban-writing）。content 是技能正文，需完整描述该题材的写作方法/风格/技巧。创建成功会写库，前端管理页可见。",
        "parameters": {"type": "object",
                       "properties": {
                           "name": {"type": "string", "description": "技能名，kebab-case（必填）"},
                           "description": {"type": "string", "description": "技能描述（触发条件+解决什么）"},
                           "content": {"type": "string", "description": "技能正文，完整写作方法（必填）"},
                           "enabled": {"type": "boolean", "default": True},
                           "tools": {"type": "array", "items": {"type": "string"}},
                           "references": {"type": "array", "items": {"type": "string"}},
                       },
                       "required": ["name", "content"]},
    }},
    {"type": "function", "function": {
        "name": "update_skill",
        "description": "更新已有 Skill（改描述/正文/启用状态）。内置 Skill 不可改内容。",
        "parameters": {"type": "object",
                       "properties": {
                           "name": {"type": "string", "description": "Skill 名称（必填）"},
                           "description": {"type": "string"},
                           "content": {"type": "string", "description": "替换技能正文"},
                           "enabled": {"type": "boolean", "description": "启用/禁用"},
                           "tools": {"type": "array", "items": {"type": "string"}},
                           "references": {"type": "array", "items": {"type": "string"}},
                       },
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "delete_skill",
        "description": "删除用户自建的 Skill。内置 Skill 不可删除。",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string", "description": "Skill 名称（必填）"}},
                       "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "search_skills",
        "description": "跨 Skill 关键词搜索，找包含某主题/题材的写作技能。",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string", "description": "搜索关键词（必填）"}},
                       "required": ["query"]},
    }},
    # ── 记忆类（读章节正文 + 向量语义检索） ──
    {"type": "function", "function": {
        "name": "read_chapter_file",
        "description": "读取指定章节的正文文件内容。用户问“某章写了什么/看下第X章”时调用。",
        "parameters": {"type": "object",
                       "properties": {"chapter": {"type": "integer", "description": "章节号（必填）"}},
                       "required": ["chapter"]},
    }},
    {"type": "function", "function": {
        "name": "list_chapter_files",
        "description": "列出所有已写章节（含章号和标题）。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "memory_search",
        "description": "向量语义检索已写章节和设定，按主题找回相关内容。用于回答“之前有没有写过XX/关于XX的设定是什么”。",
        "parameters": {"type": "object",
                       "properties": {
                           "query": {"type": "string", "description": "检索主题（必填）"},
                           "top_k": {"type": "integer", "description": "返回条数", "default": 4},
                       },
                       "required": ["query"]},
    }},
    # ── 网络类（抓取网页正文） ──
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "抓取指定 URL 的网页正文内容（去 HTML 标签）。用于获取参考资料、网页文章内容。",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string", "description": "以 http:// 或 https:// 开头的完整 URL（必填）"}},
                       "required": ["url"]},
    }},
    # ── 文件/命令类（coding_tools 集，读项目文件、搜代码、执行命令） ──
    *CODING_TOOLS_SCHEMA,
]


# 只读工具子集（子 agent 用，不含写库/动作/委托，防递归）
READONLY_TOOL_NAMES = {
    "get_character", "list_characters", "get_outline", "list_chapter_summaries",
    "list_foreshadows", "query_status", "list_factions", "search",
    "get_character_appearances",
    "read_reference_files",
    "check_red_line", "check_ai_style", "check_excitement",
    "list_skills", "get_skill", "search_skills",
    # 记忆类（只读）
    "read_chapter_file", "list_chapter_files", "memory_search",
    # 网络类（只读）
    "web_fetch",
    # coding_tools 只读子集（读文件/搜索/列目录，不含写文件/执行命令）
    "read_file", "search_files", "search_file", "list_files", "list_code_definitions",
}
READONLY_TOOLS_SCHEMA = [t for t in TOOLS_SCHEMA if t["function"]["name"] in READONLY_TOOL_NAMES]


async def dispatch_tool(name: str, arguments: dict[str, Any], repo: BibleRepository,
                        executor: ActionExecutor, llm_client=None) -> dict[str, Any]:
    """执行工具，返回 {"result": str, "action": dict | None}。"""
    # ── 查询类（只读，不推 action） ──
    if name == "get_character":
        return {"result": _tool_get_character(repo, arguments.get("name", "")), "action": None}
    if name == "list_characters":
        try:
            limit = int(arguments.get("limit", 50) or 50)
            offset = int(arguments.get("offset", 0) or 0)
        except (TypeError, ValueError):
            return {"result": "参数 limit/offset 必须是整数，请重试", "action": None}
        return {"result": _tool_list_characters(repo, limit, offset), "action": None}
    if name == "get_outline":
        try:
            chapter = int(arguments.get("chapter", 0) or 0)
        except (TypeError, ValueError):
            return {"result": "参数 chapter 必须是整数，请重试", "action": None}
        return {"result": _tool_get_outline(repo, chapter), "action": None}
    if name == "list_chapter_summaries":
        try:
            limit = int(arguments.get("limit", 10) or 10)
            offset = int(arguments.get("offset", 0) or 0)
        except (TypeError, ValueError):
            return {"result": "参数 limit/offset 必须是整数，请重试", "action": None}
        return {"result": _tool_list_chapter_summaries(repo, limit, offset), "action": None}
    if name == "list_foreshadows":
        return {"result": _tool_list_foreshadows(repo), "action": None}
    if name == "query_status":
        return {"result": _tool_query_status(repo), "action": None}
    if name == "list_factions":
        return {"result": _tool_list_factions(repo), "action": None}
    if name == "search":
        return {"result": _tool_search(repo, arguments.get("keyword", "")), "action": None}
    if name == "get_character_appearances":
        return {"result": _tool_get_character_appearances(repo, arguments.get("name", "")), "action": None}

    # ── 写库类（推 action 让前端刷新） ──
    if name == "create_character":
        return _tool_create_character(repo, arguments)
    if name == "update_character":
        return _tool_update_character(repo, arguments)
    if name == "create_outline":
        return _tool_create_outline(repo, arguments)
    if name == "update_outline":
        return _tool_update_outline(repo, arguments)
    if name == "create_foreshadow":
        return _tool_create_foreshadow(repo, arguments)
    if name == "update_foreshadow":
        return _tool_update_foreshadow(repo, arguments)
    if name == "update_foreshadow_status":
        return _tool_update_foreshadow_status(repo, arguments)
    if name == "create_world_setting":
        return _tool_create_world_setting(repo, arguments)
    if name == "create_faction":
        return _tool_create_faction(repo, arguments)
    if name == "update_faction":
        return _tool_update_faction(repo, arguments)
    if name == "read_reference_files":
        return _tool_read_reference_files(repo, arguments)

    # ── Skill 管理类 ──
    if name == "list_skills":
        return {"result": _tool_list_skills(repo), "action": None}
    if name == "get_skill":
        return {"result": _tool_get_skill(repo, arguments.get("name", "")), "action": None}
    if name == "create_skill":
        return _tool_create_skill(repo, arguments)
    if name == "update_skill":
        return _tool_update_skill(repo, arguments)
    if name == "delete_skill":
        return _tool_delete_skill(repo, arguments.get("name", ""))
    if name == "search_skills":
        return {"result": _tool_search_skills(repo, arguments.get("query", "")), "action": None}

    # ── 记忆类 ──
    if name == "read_chapter_file":
        return {"result": _tool_read_chapter_file(repo, arguments.get("chapter", 0)), "action": None}
    if name == "list_chapter_files":
        return {"result": _tool_list_chapter_files(repo), "action": None}
    if name == "memory_search":
        return {"result": _tool_memory_search(repo, arguments.get("query", ""), arguments.get("top_k", 4)), "action": None}

    # ── 网络类 ──
    if name == "web_fetch":
        return {"result": await _tool_web_fetch(arguments.get("url", "")), "action": None}

    # ── 文件/命令类（coding_tools：读文件/写文件/搜索/执行命令） ──
    if name in _CODING_TOOL_NAMES:
        impl = CODING_TOOLS_IMPL[name]
        try:
            kwargs = {k: v for k, v in arguments.items() if v is not None}
            raw = await impl(**kwargs) if name != "ask_user" else await impl(**kwargs)
            # coding_tools 返回 JSON 字符串，作为 result 喂回 LLM
            return {"result": raw, "action": None}
        except Exception as e:
            logger.warning("工具 %s 执行失败: %s", name, e)
            return {"result": f"工具执行失败: {e}", "action": None}

    # ── 交互类：present_options 推 action 让前端渲染选项按钮 ──
    if name == "present_options":
        options = arguments.get("options", [])
        if not options:
            return {"result": "选项列表为空", "action": None}
        return {"result": "选项已展示给用户，等待用户选择。不要继续生成文本。",
                "action": {"type": "present_options", "status": "done", "options": options}}

    # ── 质量检查类（只读，不推 action） ──
    if name == "check_red_line":
        return {"result": await _tool_check_red_line(repo, arguments.get("text", "")), "action": None}
    if name == "check_ai_style":
        return {"result": await _tool_check_ai_style(repo, arguments.get("text", ""), llm_client=llm_client), "action": None}
    if name == "check_excitement":
        return {"result": await _tool_check_excitement(repo, arguments.get("text", ""), llm_client=llm_client), "action": None}

    # ── 委托类 ──
    if name == "delegate_research":
        task = arguments.get("task", "")
        if not task:
            return {"result": "未提供研究任务", "action": None}
        if llm_client is None:
            return {"result": "子 agent 不可用（未注入 LLM 客户端）", "action": None}
        from novel_agent.chat.sub_agent import ResearchSubAgent
        sub = ResearchSubAgent(repo, llm_client, executor)
        summary = await sub.run(task)
        return {"result": summary, "action": None}

    # ── 动作类（交给 executor） ──
    # 已知动作类工具只有 rewrite_chapter 和 add_chapter_feedback；
    # 其余未知工具名不推 action，直接返回错误，避免把无效 action 推给前端
    if name not in ("rewrite_chapter", "add_chapter_feedback"):
        return {"result": f"未知工具：{name}", "action": None}
    action = {"type": name, **{k: v for k, v in arguments.items()}}
    try:
        result = await executor.execute(action)
        return {"result": json.dumps(result, ensure_ascii=False, default=str),
                "action": {**action, "status": "done", "result": result}}
    except Exception as e:
        logger.warning("工具 %s 执行失败: %s", name, e)
        return {"result": f"执行失败: {e}",
                "action": {**action, "status": "failed", "error": str(e)}}
