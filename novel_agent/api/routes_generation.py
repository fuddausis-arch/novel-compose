"""生成 API：世界观 / 角色 / 大纲一键生成。"""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Faction, Monster, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.memory.memory_pack import MemoryBudget, MemoryPackBuilder
from novel_agent.memory.recall import RecallMemory
from novel_agent.references.search import ReferenceSearch, canonical_genre
from novel_agent.templates.loader import GenreLoader, PromptLoader

router = APIRouter()


class GenerateWorldRequest(BaseModel):
    project_id: int
    requirements: str = "设计多层世界观"
    style: str = "热血"


class GenerateWorldResponse(BaseModel):
    created: int
    items: list[dict] = []
    warning: str = ""


class GenerateCharactersRequest(BaseModel):
    project_id: int
    protagonist_count: int = 1
    supporting_count: int = 3
    antagonist_count: int = 2
    style: str = "热血"


class GenerateCharactersResponse(BaseModel):
    created: int
    items: list[dict] = []
    warning: str = ""


class GenerateVolumesRequest(BaseModel):
    project_id: int
    count: int = 3
    custom_prompt: str = ""


class GenerateArcsRequest(BaseModel):
    project_id: int
    parent_id: int
    count: int = 5
    custom_prompt: str = ""


class GenerateChaptersRequest(BaseModel):
    project_id: int
    parent_id: int
    count: int = 10
    custom_prompt: str = ""


class GenerateOutlinesResponse(BaseModel):
    created: int
    items: list[dict] = []
    warning: str = ""


class SuggestRequest(BaseModel):
    project_id: int
    context_type: str          # outline / chapter / monster / faction / relationship
    context_id: str | int = ""
    suggest_type: str          # plot / monster / faction / relationship
    count: int = 3
    custom_prompt: str = ""


class SuggestItem(BaseModel):
    type: str
    title: str
    summary: str
    payload: dict = {}


class SuggestResponse(BaseModel):
    suggestions: list[SuggestItem] = []


class AdoptSuggestionInput(BaseModel):
    type: str
    title: str
    summary: str
    payload: dict = {}


class AdoptRequest(BaseModel):
    project_id: int
    context_type: str = ""
    context_id: str = ""
    suggest_type: str = ""
    prompt: str = ""
    raw_response: str = ""
    suggestions: list[AdoptSuggestionInput]
    status: str = "adopted"    # adopted / partial / rejected


class AdoptResponse(BaseModel):
    created: dict = {"outlines": [], "monsters": [], "factions": [], "relationships": [], "world_settings": [], "characters": []}


def _get_repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        db.close()
        raise HTTPException(404, "项目不存在")
    return db, BibleRepository(db, project_id=project_id), project, cfg


def _clean_text(text: str | None) -> str:
    return (text or "").strip()


def _unique_name(repo, entity: str, name: str) -> str:
    """为 monster/faction/character 生成项目内唯一的名称，避免唯一约束冲突。"""
    if entity == "monster":
        existing = repo.get_monster_by_name(name)
    elif entity == "faction":
        existing = repo.get_faction_by_name(name)
    elif entity == "character":
        existing = repo.get_character(name)
    else:
        return name
    if not existing:
        return name
    base = name
    # 如果名称已经带 `-AIx` 后缀，先去掉
    m = re.search(r"-AI(\d+)$", base)
    if m:
        base = base[: m.start()]
    idx = 2
    while True:
        candidate = f"{base}-AI{idx}"
        if entity == "monster":
            existing = repo.get_monster_by_name(candidate)
        elif entity == "faction":
            existing = repo.get_faction_by_name(candidate)
        else:
            existing = repo.get_character(candidate)
        if not existing:
            return candidate
        idx += 1


def _extract_json(text: str) -> dict:
    """从 LLM 返回中提取 JSON 对象。

    用平衡括号匹配代替 rfind("}")，避免长文本中多个 } 导致截取错误。
    """
    import re
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # 平衡括号匹配：找到第一个 { 后，逐字符计数直到括号平衡
        start = candidate.find("{")
        if start < 0:
            return {}
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start:i + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}


@router.post("/world/generate", response_model=GenerateWorldResponse)
async def generate_world(req: GenerateWorldRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        client = LLMClient(cfg.llm)
        prompt = PromptLoader().render(
            "world",
            title=project.title,
            genre=project.genre,
            summary=project.summary,
            style=project.style,
            requirements=req.requirements,
            style_hint=req.style,
        )

        try:
            raw = await client.generate(prompt, system="你是网文设定师，擅长设计多层世界观。只输出 JSON。")
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        result = _extract_json(raw)
        if not result:
            raise HTTPException(422, f"LLM 返回内容无法解析为 JSON。原始返回前200字: {raw[:200]}")
        settings = result.get("world_settings") or result.get("worlds") or result.get("settings") or []
        if not settings:
            raise HTTPException(422, f"LLM 未返回有效设定项。原始返回前200字: {raw[:200]}")
        items = []
        for i, s in enumerate(settings):
            data = {
                "category": _clean_text(s.get("category", "其他")),
                "title": _clean_text(s.get("title", "未命名")),
                "content": _clean_text(s.get("content", "")),
                "order": i,
            }
            created = repo.create_world_setting(**data)
            items.append({
                "id": created.id,
                "category": created.category,
                "title": created.title,
                "content": created.content,
                "order": created.order,
            })
        return GenerateWorldResponse(created=len(items), items=items)
    finally:
        db.close()


@router.post("/characters/generate", response_model=GenerateCharactersResponse)
async def generate_characters(req: GenerateCharactersRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        client = LLMClient(cfg.llm)
        prompt = PromptLoader().render(
            "characters",
            title=project.title,
            genre=project.genre,
            summary=project.summary,
            style=project.style,
            protagonist_count=req.protagonist_count,
            supporting_count=req.supporting_count,
            antagonist_count=req.antagonist_count,
            style_hint=req.style,
        )

        try:
            raw = await client.generate(prompt, system="你是网文角色设计师，擅长设计立体角色。只输出 JSON。")
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        result = _extract_json(raw)
        if not result:
            raise HTTPException(422, f"LLM 返回内容无法解析为 JSON。原始返回前200字: {raw[:200]}")
        characters = result.get("characters") or result.get("chars") or result.get("roles") or []
        if not characters:
            raise HTTPException(422, f"LLM 未返回有效角色项。原始返回前200字: {raw[:200]}")
        items = []
        for c in characters:
            data = {
                "name": _clean_text(c.get("name", "未命名")),
                "role": _clean_text(c.get("role", "配角")),
                "age": _clean_text(c.get("age", "")),
                "gender": _clean_text(c.get("gender", "")),
                "appearance": _clean_text(c.get("appearance", "")),
                "background": _clean_text(c.get("background", "")),
                "personality": _clean_text(c.get("personality", "")),
                "motivation": _clean_text(c.get("motivation", "")),
                "arc": _clean_text(c.get("arc", "")),
                "secrets": _clean_text(c.get("secrets", "")),
            }
            created = repo.create_character(**data)
            items.append({
                "id": created.id,
                "name": created.name,
                "role": created.role,
                "age": created.age,
                "gender": created.gender,
                "appearance": created.appearance,
                "background": created.background,
                "personality": created.personality,
                "motivation": created.motivation,
                "arc": created.arc,
                "secrets": created.secrets,
            })
        return GenerateCharactersResponse(created=len(items), items=items)
    finally:
        db.close()


def _outline_context(repo, project) -> tuple[str, str, str, str]:
    """读取项目已有设定，返回 (world_text, char_text, fore_text, existing_outlines_text)。"""
    world = repo.list_world_settings()
    characters = repo.list_characters()
    foreshadows = repo.list_foreshadows()
    outlines = repo.list_outlines()

    world_text = "\n".join([f"【{w.category}】{w.title}：{w.content}" for w in world])
    char_text = "\n".join([f"{c.name}（{c.role}）：{c.personality}；{c.motivation}" for c in characters])
    fore_text = "\n".join([f"{f.foreshadow_id}：{f.description}" for f in foreshadows])
    outline_text = "\n".join([
        f"[{o.level}] {o.title}：{o.summary}" for o in outlines
    ])
    return world_text or "暂无", char_text or "暂无", fore_text or "暂无", outline_text or "暂无"


def _build_context_text(repo, project, cfg, context_type: str, context_id):
    if context_type == "outline":
        o = repo.get_outline(int(context_id)) if context_id else None
        return f"[{o.level}] {o.title}：{o.summary}" if o else "暂无"
    if context_type == "chapter":
        recall = RecallMemory(cfg, project_id=repo.project_id)
        text = recall.read_chapter_text(int(context_id)) if context_id else ""
        return text or "当前章节暂无正文"
    return "基于项目全局上下文"


def _list_asset_text(repo, suggest_type: str) -> str:
    if suggest_type == "monster":
        return "\n".join([f"{m.name}（{m.species}/{m.rank}）：{m.behavior}" for m in repo.list_monsters()]) or "暂无"
    if suggest_type == "faction":
        return "\n".join([f"{f.name}（{f.type}/{f.alignment}）：{f.description}" for f in repo.list_factions()]) or "暂无"
    if suggest_type == "relationship":
        rels = repo.list_character_relationships()
        return "\n".join([f"{r.source_character} → {r.target_character}：{r.relation_type}" for r in rels]) or "暂无"
    if suggest_type == "world":
        items = repo.list_world_settings()
        return "\n".join(f"- {s.category}/{s.title}: {s.content[:80]}" for s in items) if items else ""
    if suggest_type == "character":
        items = repo.list_characters()
        return "\n".join(f"- {c.name}({c.role}): {c.personality or c.background or ''}"[:100] for c in items) if items else ""
    return ""


@router.post("/volumes/generate", response_model=GenerateOutlinesResponse)
async def generate_volumes(req: GenerateVolumesRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        client = LLMClient(cfg.llm)
        world_text, char_text, fore_text, outline_text = _outline_context(repo, project)

        system = "你是资深网文架构师，擅长设计长篇小说的卷级大纲。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》生成 {req.count} 个卷级大纲。
题材：{project.genre}
简介：{project.summary}
风格/要求：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

已有世界观：{world_text}
已有角色：{char_text}
已有伏笔：{fore_text}

每个卷包含：order（从1开始）、title（卷标题）、summary（卷概要，100-200字）、act（开端/发展/小高潮/转折/大高潮/结局）。
请输出 JSON：{{"volumes": [{{"order": 1, "title": "", "summary": "", "act": ""}}]}}"""

        try:
            raw = await client.generate(prompt, system=system)
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        result = _extract_json(raw)
        if not result:
            raise HTTPException(422, f"LLM 返回内容无法解析为 JSON。原始返回前200字: {raw[:200]}")
        volumes = result.get("volumes") or result.get("outlines") or []
        if not volumes:
            raise HTTPException(422, f"LLM 未返回有效卷级大纲。原始返回前200字: {raw[:200]}")
        items = []
        for idx, o in enumerate(volumes):
            order = int(o.get("order", idx + 1))
            created = repo.create_outline(
                level="volume",
                order=order,
                title=_clean_text(o.get("title", f"第{order}卷")),
                summary=_clean_text(o.get("summary", "")),
                act=_clean_text(o.get("act", "")),
                strand="",
            )
            items.append({
                "id": created.id, "level": "volume", "parent_id": None,
                "order": created.order, "title": created.title,
                "summary": created.summary, "act": created.act, "strand": created.strand,
            })
        return GenerateOutlinesResponse(created=len(items), items=items)
    finally:
        db.close()


@router.post("/arcs/generate", response_model=GenerateOutlinesResponse)
async def generate_arcs(req: GenerateArcsRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        volume = repo.get_outline(req.parent_id)
        if not volume or volume.level != "volume":
            raise HTTPException(404, "卷级大纲不存在")

        client = LLMClient(cfg.llm)
        world_text, char_text, fore_text, outline_text = _outline_context(repo, project)

        system = "你是资深网文大纲师，擅长把一卷拆成多个小节（arc）。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》的以下卷生成 {req.count} 个细纲小节：
卷标题：{volume.title}
卷概要：{volume.summary}

题材：{project.genre}
风格/要求：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

已有世界观：{world_text}
已有角色：{char_text}
已有伏笔：{fore_text}
已有大纲：{outline_text}

每个小节包含：order（在该卷内从1开始）、title（小节标题）、summary（小节概要，50-150字）、act（开端/发展/小高潮/转折/大高潮/结局）、strand（主线quest/感情fire/世界观constellation）。
请输出 JSON：{{"arcs": [{{"order": 1, "title": "", "summary": "", "act": "", "strand": "quest"}}]}}"""

        try:
            raw = await client.generate(prompt, system=system)
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        result = _extract_json(raw)
        if not result:
            raise HTTPException(422, f"LLM 返回内容无法解析为 JSON。原始返回前200字: {raw[:200]}")
        arcs = result.get("arcs") or result.get("sections") or []
        if not arcs:
            raise HTTPException(422, f"LLM 未返回有效细纲小节。原始返回前200字: {raw[:200]}")
        items = []
        for idx, o in enumerate(arcs):
            order = int(o.get("order", idx + 1))
            created = repo.create_outline(
                level="arc",
                parent_id=req.parent_id,
                order=order,
                title=_clean_text(o.get("title", f"小节{order}")),
                summary=_clean_text(o.get("summary", "")),
                act=_clean_text(o.get("act", "")),
                strand=_clean_text(o.get("strand", "quest")),
            )
            items.append({
                "id": created.id, "level": "arc", "parent_id": created.parent_id,
                "order": created.order, "title": created.title,
                "summary": created.summary, "act": created.act, "strand": created.strand,
            })
        return GenerateOutlinesResponse(created=len(items), items=items)
    finally:
        db.close()


@router.post("/chapters/generate", response_model=GenerateOutlinesResponse)
async def generate_chapters(req: GenerateChaptersRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        arc = repo.get_outline(req.parent_id)
        if not arc or arc.level != "arc":
            raise HTTPException(404, "细纲小节不存在")

        client = LLMClient(cfg.llm)
        world_text, char_text, fore_text, outline_text = _outline_context(repo, project)

        # 确定全局章节号起始值
        existing_chapters = repo.list_outlines(level="chapter")
        max_chapter = max((c.order for c in existing_chapters), default=0)

        system = "你是资深网文大纲师，擅长把细纲小节拆成具体章节。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》的以下细纲小节生成 {req.count} 个章纲：
小节标题：{arc.title}
小节概要：{arc.summary}

题材：{project.genre}
风格/要求：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

已有世界观：{world_text}
已有角色：{char_text}
已有伏笔：{fore_text}
已有大纲：{outline_text}

每个章纲包含：order（全局章节号，从{max_chapter + 1}开始递增）、title（章标题）、summary（章概要，30-100字）、act（开端/发展/小高潮/转折/大高潮/结局）、strand（主线quest/感情fire/世界观constellation）。
请输出 JSON：{{"chapters": [{{"order": {max_chapter + 1}, "title": "", "summary": "", "act": "", "strand": "quest"}}]}}"""

        try:
            raw = await client.generate(prompt, system=system)
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        result = _extract_json(raw)
        if not result:
            raise HTTPException(422, f"LLM 返回内容无法解析为 JSON。原始返回前200字: {raw[:200]}")
        chapters = result.get("chapters") or result.get("chapter_outlines") or []
        if not chapters:
            raise HTTPException(422, f"LLM 未返回有效章纲。原始返回前200字: {raw[:200]}")
        items = []
        for idx, o in enumerate(chapters):
            order = int(o.get("order", max_chapter + 1 + idx))
            created = repo.create_outline(
                level="chapter",
                parent_id=req.parent_id,
                order=order,
                title=_clean_text(o.get("title", f"第{order}章")),
                summary=_clean_text(o.get("summary", "")),
                act=_clean_text(o.get("act", "")),
                strand=_clean_text(o.get("strand", "quest")),
            )
            items.append({
                "id": created.id, "level": "chapter", "parent_id": created.parent_id,
                "order": created.order, "title": created.title,
                "summary": created.summary, "act": created.act, "strand": created.strand,
            })
        return GenerateOutlinesResponse(created=len(items), items=items)
    finally:
        db.close()


# ---- 章节写作一致性系统（学习 webnovel-writer 架构，自主实现） ----

class ChapterBriefRequest(BaseModel):
    project_id: int
    chapter: int
    title: str = ""


class ChapterReviewRequest(BaseModel):
    project_id: int
    chapter: int


class ChapterCommitRequest(BaseModel):
    project_id: int
    chapter: int


class GenreContextRequest(BaseModel):
    project_id: int


class GenreContextResponse(BaseModel):
    genre: str
    canonical_genre: str
    template_text: str
    references: list[dict[str, str]]


class ChapterBriefResponse(BaseModel):
    chapter: int
    title: str
    brief: dict
    brief_text: str
    context_stats: dict


def _genre_context(project: Project) -> tuple[str, str, str]:
    """返回 (canonical_genre, 题材模板文本, 参考资料文本)。"""
    cg = canonical_genre(project.genre)
    template_text = GenreLoader().load(cg)
    ref_search = ReferenceSearch()
    refs = ref_search.for_skill("webnovel-write", canonical_genre=cg, limit=6)
    ref_text = "\n".join([
        f"- {r.get('关键词', '')}: {r.get('核心摘要', '')}（{r.get('详细展开', '')}）"
        for r in refs
    ])
    return cg, template_text, ref_text


def _build_memory_pack(repo, project, chapter: int, cfg) -> dict[str, str]:
    """使用 MemoryPack 组装带预算的上下文（working/episodic/semantic）。"""
    recall = RecallMemory(cfg, project_id=repo.project_id)
    builder = MemoryPackBuilder(repo, chapter=chapter, recall=recall)
    return builder.build(MemoryBudget())


def _strand_balance_advice(outlines: list, current_chapter: int) -> str:
    """基于最近20章的strand分布给出节奏建议。"""
    recent = [o for o in outlines if abs(o.order - current_chapter) <= 20]
    counts = {"quest": 0, "fire": 0, "constellation": 0, "": 0}
    for o in recent:
        counts[o.strand or ""] = counts.get(o.strand or "", 0) + 1
    total = sum(counts.values()) or 1
    lines = [f"最近20章Strand分布：quest={counts['quest']} fire={counts['fire']} constellation={counts['constellation']} 未标注={counts['']}"]
    if counts["quest"] < total * 0.4:
        lines.append("建议：主线(quest)占比偏低，本章优先推进主线目标。")
    if counts["fire"] < total * 0.2 and total > 5:
        lines.append("建议：感情线(fire)长期断档，可插入人物关系互动。")
    if counts["constellation"] > total * 0.4:
        lines.append("建议：世界观线(constellation)过密，避免本章再大量抛设定。")
    return "\n".join(lines)


@router.post("/chapter/brief", response_model=ChapterBriefResponse)
async def generate_chapter_brief(req: ChapterBriefRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        cg = canonical_genre(project.genre)
        outlines = repo.list_outlines()
        outline = next((o for o in outlines if o.order == req.chapter), None)
        if not outline:
            raise HTTPException(404, f"第{req.chapter}章的章纲不存在，请先生成大纲")

        pack = _build_memory_pack(repo, project, req.chapter, cfg)
        strand_advice = _strand_balance_advice(outlines, req.chapter)

        prompt = PromptLoader().render(
            "brief",
            title=project.title,
            genre=project.genre,
            canonical_genre=cg,
            chapter=req.chapter,
            working_memory=pack["working"],
            episodic_memory=pack["episodic"],
            semantic_memory=pack["semantic"],
            strand_advice=strand_advice,
        )

        raw = await LLMClient(cfg.llm).generate(
            prompt, system="你是网文Context Agent，擅长加载上下文并输出结构化五段写作任务书。只输出JSON。"
        )
        brief_dict = _extract_json(raw)
        if not brief_dict or "opening" not in brief_dict:
            brief_dict = {
                "opening": "LLM未返回标准格式，请手动填写",
                "story": "",
                "characters": "",
                "craft": "",
                "ending": "",
            }

        brief_text = "\n\n".join([
            f"【开篇委托】{brief_dict.get('opening', '')}",
            f"【这章的故事】{brief_dict.get('story', '')}",
            f"【这章的人物】{brief_dict.get('characters', '')}",
            f"【怎么写更顺】{brief_dict.get('craft', '')}",
            f"【收在哪里】{brief_dict.get('ending', '')}",
        ])

        return ChapterBriefResponse(
            chapter=req.chapter,
            title=outline.title,
            brief=brief_dict,
            brief_text=brief_text,
            context_stats={
                "working_chars": len(pack["working"]),
                "episodic_chars": len(pack["episodic"]),
                "semantic_chars": len(pack["semantic"]),
                "total_chars": len(pack["working"]) + len(pack["episodic"]) + len(pack["semantic"]),
                "canonical_genre": cg,
            },
        )
    finally:
        db.close()


@router.post("/chapter/review")
async def review_chapter(req: ChapterReviewRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        recall = RecallMemory(cfg, project_id=req.project_id)
        text = recall.read_chapter_text(req.chapter)
        if not text:
            raise HTTPException(404, "章节正文不存在")

        outlines = repo.list_outlines()
        outline = next((o for o in outlines if o.order == req.chapter), None)
        if not outline:
            raise HTTPException(404, f"第{req.chapter}章的章纲不存在")
        cg = canonical_genre(project.genre)
        pack = _build_memory_pack(repo, project, req.chapter, cfg)

        # 构造五维审查上下文
        dimension_rules = {
            "setting": "检查世界观设定、力量体系、势力规则是否被违反；新设定是否与旧设定冲突；数值是否前后一致。",
            "timeline": "检查时间顺序、事件先后、章节时间戳、伏笔回收时机是否正确。",
            "continuity": "检查物品/功法/势力状态是否承接前文；角色位置/伤势/关系是否连续；未回收伏笔是否被遗忘。",
            "character": "检查角色行为是否符合人设、动机、情绪、信息边界；是否有 OOC；对话风格是否一致。",
            "logic": "检查剧情因果、爽点逻辑、决策合理性、是否机械降神、是否有未解释的便利。",
        }
        dimension_text = "\n".join([f"{k}: {v}" for k, v in dimension_rules.items()])

        # 裁决规则
        adjudication = ReferenceSearch().adjudication_rules(cg)
        adjudication_text = "\n".join([f"- {r.get('关键词', '')}: {r.get('核心摘要', '')}" for r in adjudication[:5]])

        prompt = PromptLoader().render(
            "review",
            title=project.title,
            canonical_genre=cg,
            chapter=req.chapter,
            outline_order=outline.order,
            outline_title=outline.title,
            outline_summary=outline.summary,
            outline_strand=outline.strand,
            working_memory=pack["working"],
            episodic_memory=pack["episodic"],
            semantic_memory=pack["semantic"],
            chapter_text=text,
            dimension_text=dimension_text,
            adjudication_text=adjudication_text,
        )

        raw = await LLMClient(cfg.llm).generate(prompt, system="你是网文Reviewer Agent，只做事实一致性审查，只输出JSON。")
        result = _extract_json(raw)
        result.setdefault("issues", [])
        result.setdefault("dimension_results", [])
        result.setdefault("summary", "")
        result["issues_count"] = len(result.get("issues", []))
        result["blocking_count"] = sum(1 for i in result.get("issues", []) if i.get("blocking"))
        result["has_blocking"] = result["blocking_count"] > 0
        result["chapter"] = req.chapter
        return result
    finally:
        db.close()


@router.post("/chapter/commit")
async def commit_chapter(req: ChapterCommitRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        recall = RecallMemory(cfg, project_id=req.project_id)
        text = recall.read_chapter_text(req.chapter)
        if not text:
            raise HTTPException(404, "章节正文不存在")

        outlines = repo.list_outlines()
        outline = next((o for o in outlines if o.order == req.chapter), None)
        if not outline:
            raise HTTPException(404, f"第{req.chapter}章的章纲不存在")
        cg = canonical_genre(project.genre)
        pack = _build_memory_pack(repo, project, req.chapter, cfg)

        prompt = PromptLoader().render(
            "commit",
            title=project.title,
            genre=project.genre,
            canonical_genre=cg,
            chapter=req.chapter,
            outline_order=outline.order,
            outline_title=outline.title,
            outline_summary=outline.summary,
            working_memory=pack["working"],
            episodic_memory=pack["episodic"],
            semantic_memory=pack["semantic"],
            chapter_text=text,
        )

        raw = await LLMClient(cfg.llm).generate(prompt, system="你是小说事实提取器（Data Agent），只输出结构化的状态增量、关系、事件和伏笔更新。")
        result = _extract_json(raw)
        summary = _clean_text(result.get("summary", ""))
        deltas = result.get("state_deltas", [])
        relationships = result.get("relationships", [])
        events = result.get("events", [])
        fore_updates = result.get("foreshadow_updates", [])

        # 用事务保证 commit 原子性
        with repo.unit_of_work():
            # 应用状态增量
            for d in deltas:
                repo.create_state_change(
                    chapter=req.chapter,
                    entity_type=d.get("entity_type", "角色"),
                    entity_id=d.get("entity_id", ""),
                    field=d.get("field", ""),
                    old_value=str(d.get("old", "")),
                    new_value=str(d.get("new", "")),
                )
                # 同步角色卡上的常见动态字段
                if d.get("entity_type", "角色") == "角色":
                    char = repo.get_character(d.get("entity_id", ""))
                    if char and d.get("field", "") in {"current_location", "current_emotion", "known_info"}:
                        setattr(char, d["field"], str(d.get("new", "")))
                        db.add(char)

            # 记录人物关系变更
            for rel in relationships:
                repo.append_event(
                    chapter=req.chapter,
                    type="relationship_change",
                    entity_id=f"{rel.get('character_a', '')}-{rel.get('character_b', '')}",
                    payload=rel,
                )

            # 追加事件
            for e in events:
                repo.append_event(
                    chapter=req.chapter,
                    type=e.get("event_type", "timeline_event"),
                    entity_id=e.get("subject", ""),
                    payload=e.get("payload", {}),
                )

            # 更新伏笔状态
            for fu in fore_updates:
                repo.update_foreshadow_status(fu.get("foreshadow_id", ""), fu.get("status", "planted"))

            # 生成/更新章节摘要
            repo.create_or_update_chapter_summary(
                chapter=req.chapter,
                title=outline.title,
                core_events=summary,
                characters_present=", ".join({d.get("entity_id", "") for d in deltas if d.get("entity_type") == "角色"}),
                foreshadow_dynamics=", ".join([f"{fu['foreshadow_id']}->{fu['status']}" for fu in fore_updates]),
                word_count=len(text),
            )

            # 写入提交记录
            repo.create_or_update_chapter_commit(
                chapter=req.chapter,
                status="committed",
                summary=summary,
                word_count=len(text),
                committed_at=datetime.utcnow(),
            )

        # 提交成功后索引到 ArchivalMemory，供后续语义检索
        try:
            archival = ArchivalMemory(cfg)
            archival.index_chapter(req.chapter, outline.title, text)
            archived = True
        except Exception:
            archived = False

        return {
            "chapter": req.chapter,
            "committed": True,
            "summary": summary,
            "deltas": len(deltas),
            "relationships": len(relationships),
            "events": len(events),
            "foreshadow_updates": len(fore_updates),
            "archived": archived,
        }
    finally:
        db.close()


@router.post("/genre-context", response_model=GenreContextResponse)
def get_genre_context(req: GenreContextRequest):
    """查看当前项目的题材模板和参考资料（调试用）。"""
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        cg, template_text, _ = _genre_context(project)
        refs = ReferenceSearch().for_skill("webnovel-write", canonical_genre=cg, limit=10)
        return GenreContextResponse(
            genre=project.genre,
            canonical_genre=cg,
            template_text=template_text,
            references=refs,
        )
    finally:
        db.close()


@router.post("/suggest", response_model=SuggestResponse)
async def suggest(req: SuggestRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        client = LLMClient(cfg.llm)
        world_text, char_text, fore_text, outline_text = _outline_context(repo, project)
        context_text = _build_context_text(repo, project, cfg, req.context_type, req.context_id)
        asset_text = _list_asset_text(repo, req.suggest_type)

        template_name = f"suggest_{req.suggest_type}"
        prompt = PromptLoader().render(
            template_name,
            title=project.title,
            genre=project.genre,
            style=project.style,
            context_type=req.context_type,
            context_text=context_text,
            world_text=asset_text if req.suggest_type == "world" else world_text,
            char_text=asset_text if req.suggest_type == "character" else char_text,
            fore_text=fore_text,
            outline_text=outline_text,
            monster_text=asset_text if req.suggest_type == "monster" else "",
            faction_text=asset_text if req.suggest_type in ("faction", "character") else "",
            relationship_text=asset_text if req.suggest_type == "relationship" else "",
            count=req.count,
            custom_prompt=req.custom_prompt,
        )

        system = "你是网文创作助手，擅长基于已有设定生成一致且高质量的后续内容。只输出 JSON。"
        raw = await client.generate(prompt, system=system)
        result = _extract_json(raw)
        suggestions = result.get("suggestions", [])
        items = []
        for s in suggestions:
            items.append(SuggestItem(
                type=req.suggest_type,
                title=_clean_text(s.get("title", "")),
                summary=_clean_text(s.get("summary", "")),
                payload=s.get("payload", {}),
            ))
        return SuggestResponse(suggestions=items)
    finally:
        db.close()


@router.post("/suggest/adopt", response_model=AdoptResponse)
async def adopt_suggestions(req: AdoptRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        created = {"outlines": [], "monsters": [], "factions": [], "relationships": [], "world_settings": [], "characters": []}

        if req.status != "rejected":
            for s in req.suggestions:
                p = s.payload
                if s.type == "plot":
                    parent_id = p.get("parent_id")
                    if parent_id is not None:
                        parent_id = int(parent_id)
                    created_obj = repo.create_outline(
                        level=p.get("level", "chapter"),
                        order=int(p.get("order", 0)),
                        title=s.title,
                        summary=s.summary,
                        act=p.get("act", ""),
                        strand=p.get("strand", ""),
                        parent_id=parent_id,
                    )
                    created["outlines"].append({"id": created_obj.id, "title": created_obj.title})
                elif s.type == "monster":
                    data = {
                        "name": _unique_name(repo, "monster", s.title),
                        "alias": p.get("alias", ""),
                        "species": p.get("species", "未知"),
                        "rank": p.get("rank", "普通"),
                        "tier": p.get("tier", ""),
                        "behavior": s.summary,
                        "habitats": p.get("habitats", ""),
                    }
                    for k, v in p.items():
                        if k not in data and hasattr(Monster, k):
                            data[k] = v
                    created_obj = repo.create_monster(**data)
                    created["monsters"].append({"id": created_obj.id, "name": created_obj.name})
                elif s.type == "faction":
                    data = {
                        "name": _unique_name(repo, "faction", s.title),
                        "alias": p.get("alias", ""),
                        "type": p.get("type", "其他"),
                        "alignment": p.get("alignment", "中立"),
                        "description": s.summary,
                    }
                    for k, v in p.items():
                        if k not in data and hasattr(Faction, k):
                            data[k] = v
                    created_obj = repo.create_faction(**data)
                    created["factions"].append({"id": created_obj.id, "name": created_obj.name})
                elif s.type == "relationship":
                    if p.get("source_faction_id"):
                        created_obj = repo.create_faction_relationship(
                            source_faction_id=int(p["source_faction_id"]),
                            target_faction_id=int(p["target_faction_id"]),
                            relation_type=p.get("relation_type", "neutral"),
                            strength=int(p.get("strength", 0)),
                            description=s.summary,
                        )
                        created["relationships"].append({"id": created_obj.id})
                    else:
                        created_obj = repo.create_character_relationship(
                            source_character=p.get("source_character", ""),
                            target_character=p.get("target_character", ""),
                            relation_type=p.get("relation_type", "其他"),
                            relation_subtype=p.get("relation_subtype", ""),
                            strength=int(p.get("strength", 0)),
                            description=s.summary,
                        )
                        created["relationships"].append({"id": created_obj.id})
                elif s.type == "world":
                    created_obj = repo.create_world_setting(
                        category=p.get("category", "其他"),
                        title=s.title,
                        content=p.get("content", s.summary),
                    )
                    created["world_settings"].append({"id": created_obj.id, "title": created_obj.title})
                elif s.type == "character":
                    created_obj = repo.create_character(
                        name=_unique_name(repo, "character", s.title),
                        role=p.get("role", "配角"),
                        age=p.get("age", ""),
                        gender=p.get("gender", ""),
                        appearance=p.get("appearance", ""),
                        personality=p.get("personality", ""),
                        motivation=p.get("motivation", ""),
                        background=p.get("background", ""),
                        arc=p.get("arc", ""),
                        secrets=p.get("secrets", ""),
                    )
                    created["characters"].append({"id": created_obj.id, "name": created_obj.name})

        # 记录采纳历史
        repo.create_ai_suggestion(
            context_type=req.context_type,
            context_id=str(req.context_id),
            suggest_type=req.suggest_type,
            prompt=req.prompt,
            raw_response=req.raw_response,
            adopted_items=[{"type": s.type, "title": s.title, "summary": s.summary, "payload": s.payload} for s in req.suggestions],
            status=req.status,
        )

        return AdoptResponse(created=created)
    finally:
        db.close()
