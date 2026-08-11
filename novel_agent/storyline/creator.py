"""叙事线识别创建：LLM 从大纲/摘要中识别故事线并建线（P1-1 实现）。

对应原 generate-plan / import-from-outlines 占位。流程：
1. 收集项目卷纲/弧段/章纲 + 章节摘要 → 压缩文本
2. LLM 识别故事线（主线/支线/明线/暗线）+ 关键节点（章节事件）
3. 应用：同名线跳过，新线创建 + 节点落库
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CREATOR_SYSTEM = """你是资深网文编辑，擅长从大纲中识别叙事线（故事线）。
根据给定的卷纲、弧段大纲、章纲和章节摘要，识别出这本书的主线、支线、明线、暗线。
只输出 JSON，不要其他文字：
{
  "storylines": [
    {
      "name": "线名（简短，如：复仇线）",
      "line_type": "主线|支线|暗线|明线",
      "tags": ["主线", "明线"],
      "summary": "这条线的一句话概括",
      "planned_resolve_chapter": 0,
      "volume": "第一卷",
      "nodes": [
        {"node_type": "milestone|event", "chapter": 3,
         "title": "关键事件标题", "description": "该线在此章的关键进展"}
      ]
    }
  ]
}
规则：
1. 只识别有大纲/摘要佐证的线，宁缺毋滥，一般 3-8 条
2. 主线 1-2 条（tags 含"主线"），其余为支线/暗线
3. 节点 chapter 必须填真实章号，没有对应章节就不填节点
4. planned_resolve_chapter 0 表示未定；volume 填所属卷，跨卷填"全书"
5. 不要编造大纲里不存在的线"""


def build_outline_text(repo) -> str:
    """收集大纲+摘要，压缩成给 LLM 的输入文本（按卷→弧→章→摘要组织）。"""
    parts: list[str] = []
    try:
        project = repo.get_project()
        if project:
            parts.append(f"【书名】{project.title}\n【类型】{project.genre or ''}\n【简介】{project.summary or ''}")
    except Exception:
        pass

    # 卷纲
    volumes = repo.list_outlines(level="volume")
    for v in volumes:
        v_text = f"【卷纲】卷{v.order}《{v.title or ''}》：{(v.summary or v.description or '')[:200]}"
        parts.append(v_text)
        # 该卷下的弧段
        arcs = repo.list_outlines(level="arc", parent_id=v.id)
        for a in arcs:
            parts.append(f"  【弧段】第{a.order}弧《{a.title or ''}》：{(a.summary or a.description or '')[:150]}")
            # 该弧下的章纲
            chs = repo.list_outlines(level="chapter", parent_id=a.id)
            for c in chs:
                if c.summary:
                    parts.append(f"    第{c.order}章《{c.title or ''}》：{c.summary[:100]}")

    # 章节摘要（补充证据）
    try:
        summaries = repo.list_chapter_summaries(limit=200)
        for s in summaries:
            if s.core_events:
                parts.append(f"第{s.chapter}章摘要：{s.core_events[:120]}")
    except Exception:
        pass

    # 总量保护：按条目完整追加，超限时停止追加（整块跳过，不做硬切——
    # 12000 字硬切会把后面的卷/弧"半截"丢掉，故事线识别就看不到后段剧情）
    text_parts: list[str] = []
    total = 0
    _MAX = 12000
    for p in parts:
        if total + len(p) + 1 > _MAX:
            break
        text_parts.append(p)
        total += len(p) + 1
    text = "\n".join(text_parts)
    return text or "（项目暂无大纲数据）"


async def suggest_storylines(client: Any, outline_text: str,
                             existing_names: list[str]) -> dict:
    """调用 LLM 识别故事线，返回 {"storylines": [...]}。"""
    existing = "、".join(existing_names) if existing_names else "（无）"
    prompt = (
        f"{outline_text}\n\n"
        f"【已存在的线（不要重复创建，可跳过）】{existing}\n\n"
        f"请识别本项目的故事线。"
    )
    raw = await client.generate(prompt, system=_CREATOR_SYSTEM, temperature=0.3)
    from novel_agent.utils.json_parser import parse_json_strict
    parsed = parse_json_strict(raw) or {}
    if isinstance(parsed, dict) and "storylines" in parsed:
        return parsed
    if isinstance(parsed, list):
        return {"storylines": parsed}
    return {}


def apply_storylines(db, project_id: int, suggestions: dict,
                     existing_lines: list | None = None) -> dict:
    """建线 + 建节点。同名线跳过（保留已有），返回创建统计。

    Returns:
        {"created_lines": n, "skipped_lines": n, "created_nodes": n, "lines": [...]}
    """
    from novel_agent.bible.models import Storyline, StorylineNode

    lines = suggestions.get("storylines", []) or []
    if not isinstance(lines, list):
        lines = []
    existing = existing_lines or db.query(Storyline).filter_by(
        project_id=project_id).all()
    existing_names = {l.name for l in existing}
    # 本次会话去重
    seen: set[str] = set()

    created_lines = skipped_lines = created_nodes = 0
    created: list[dict] = []

    for line in lines:
        if not isinstance(line, dict):
            continue
        name = str(line.get("name", "")).strip()
        if not name or name in existing_names or name in seen:
            skipped_lines += 1
            continue
        seen.add(name)
        sl = Storyline(
            project_id=project_id,
            name=name,
            line_type=str(line.get("line_type", "")),
            tags=[str(t) for t in (line.get("tags") or []) if t],
            status="active",
            summary=str(line.get("summary", ""))[:500],
            planned_resolve_chapter=int(line.get("planned_resolve_chapter") or 0),
            volume=str(line.get("volume", "")),
        )
        db.add(sl)
        db.flush()  # 拿到 id
        created_lines += 1

        # 节点
        for n in line.get("nodes") or []:
            if not isinstance(n, dict):
                continue
            try:
                ch = int(n.get("chapter") or 0)
            except (TypeError, ValueError):
                ch = 0
            if ch <= 0:
                continue
            db.add(StorylineNode(
                storyline_id=sl.id,
                node_type=str(n.get("node_type") or "event"),
                chapter=ch,
                title=str(n.get("title") or "")[:200],
                description=str(n.get("description") or "")[:500],
            ))
            created_nodes += 1

        created.append({
            "id": sl.id, "name": name, "line_type": sl.line_type,
            "tags": sl.tags, "summary": sl.summary,
            "nodes": sum(1 for n in (line.get("nodes") or [])
                         if isinstance(n, dict) and int(n.get("chapter") or 0) > 0),
        })

    db.commit()
    logger.info("叙事线创建完成: 新建%d线 跳过%d 节点%d",
                created_lines, skipped_lines, created_nodes)
    return {
        "created_lines": created_lines,
        "skipped_lines": skipped_lines,
        "created_nodes": created_nodes,
        "lines": created,
    }
