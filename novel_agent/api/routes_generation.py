"""生成 API：世界观 / 角色 / 大纲一键生成。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from novel_agent.api.app import limiter
from novel_agent.audit.validator import count_chinese_chars, run_deterministic_checks
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Faction, Monster, Outline, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.chat.session_store import get_session_store
from novel_agent.config import load_config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.archival import ArchivalMemory
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.nodes import polish_chapter
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.references.corpus_hooks import load_corpus_hook_examples
from novel_agent.references.search import ReferenceSearch, canonical_genre
from novel_agent.api.routes_references import get_all_reference_text
from novel_agent.templates.loader import GenreLoader, PromptLoader

logger = logging.getLogger(__name__)
router = APIRouter()

# 交互式创作会话状态已迁移到 SQLite（SessionStore.interactive_sessions 表），
# 替代原内存字典 _INTERACTIVE_SESSIONS，支持断线重连。

# 用户通过指令主动加载的参考文件缓存：project_id -> 参考文本
# 仅当用户明确说「阅读参考文件」等指令时加载，不自动注入；按项目隔离
_PROJECT_REFERENCE_TEXT: dict[int, str] = {}


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


class GenerateChaptersByVolumeRequest(BaseModel):
    """按卷纲生成章纲：拉取该卷下所有细纲，参考全部设定一次性生成。"""
    project_id: int
    volume_id: int           # 卷级大纲 id
    count: int = 0            # 0=自动决定章数
    custom_prompt: str = ""


class GenerateOutlinesRequest(BaseModel):
    project_id: int
    level: str = "chapter"  # volume / arc / chapter
    parent_id: int | None = None
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
    context_id: str | int = ""
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
    """清理 LLM 返回文本：剥离 HTML 标签 + strip。

    LLM 偶尔在 content 字段塞 <br>/<b>/<p> 等 HTML 标签，前端渲染会显示原始标签。
    非字符串（如 LLM 把 age 返回成数字）也需兜底，避免 AttributeError。
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    cleaned = text.strip()
    # 剥离 HTML 标签（<br>、<b>、</b>、<p> 等）
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return cleaned


def _save_foreshadow_plans(repo, plans: list, default_chapter: int = 0) -> int:
    """P0#7：卷纲 foreshadow_plan / 章纲 new_foreshadows 落库到 ForeshadowImplant。

    条目格式兼容：
      - {action/status, foreshadow_id, tier, description, chapter}
      - {foreshadow_id, description, ...}
    返回写入数量。幂等：同 foreshadow_id + chapter 重复跳过（含同批次内重复）。
    """
    from novel_agent.bible.models import ForeshadowImplant

    count = 0
    seen: set[tuple[str, int]] = set()
    for p in (plans or []):
        if not isinstance(p, dict):
            continue
        fid = str(p.get("foreshadow_id") or "").strip()
        if not fid:
            continue
        ch = int(p.get("chapter") or default_chapter or 0)
        method = str(p.get("action") or p.get("implant_method") or "").strip()
        desc = str(p.get("description") or "").strip()
        if method and desc:
            method = f"{method}: {desc}"
        elif desc:
            method = desc
        key = (fid, ch)
        if key in seen:
            continue  # 同批次内重复（add 未 flush 查不到库，用内存 set 兜底）
        seen.add(key)
        dup = repo.db.query(ForeshadowImplant).filter(
            ForeshadowImplant.project_id == repo.project_id,
            ForeshadowImplant.foreshadow_id == fid,
            ForeshadowImplant.chapter == ch,
        ).first()
        if dup:
            continue
        # 统一走 repository 入口（消除双轨写入）
        repo.create_foreshadow_implant(foreshadow_id=fid, chapter=ch, implant_method=method)
        count += 1
    try:
        repo.db.commit()
    except Exception:
        repo.db.rollback()
    return count


def _build_create_delta(entry: dict, chapter: int | None, delta_type: str,
                        rename_type: str | None = None) -> dict:
    """构造 create 类 delta，防止 LLM 条目里的 type 字段覆盖 delta 动作类型。

    Data Agent 提取的势力条目带业务 type（如"宗门/世家"），与 delta 的
    type（动作类型）同名冲突，直接 **entry 展开会把 delta.type 覆盖掉，
    导致 applier 报「不支持的 delta 类型」。此处剔除 type，并把有业务含义的
    type（势力类型）改名保留（rename_type）。
    """
    item = {k: v for k, v in (entry or {}).items() if k != "type"}
    if rename_type and entry.get("type"):
        item[rename_type] = entry.get("type")
    delta = {"type": delta_type, **item}
    if chapter is not None:
        delta["chapter"] = chapter
    return delta


# 多层世界观题材：需要现实层/异能层/神明层
_MULTI_LAYER_GENRES = {"都市异能", "规则怪谈", "悬疑脑洞", "无限流", "科幻未来"}


def _get_categories_for_genre(genre: str) -> str:
    """根据题材返回 category 列表字符串，注入 prompt 的 ${categories} 占位符。

    多层世界观题材（都市异能等）加现实层/异能层/神明层；
    其他题材（修真/仙侠/末日等）只用通用 category，避免"异能层"串味。
    """
    base = ["世界观", "力量体系", "势力", "地点", "规则", "历史", "其他"]
    try:
        cg = canonical_genre(genre) if genre else ""
    except Exception:
        cg = ""
    if cg in _MULTI_LAYER_GENRES:
        return "、".join(["世界观", "现实层", "力量体系", "异能层", "势力", "地点", "规则", "历史", "神明层", "其他"])
    return "、".join(base)


def _check_title_content_consistency(items: list[dict]) -> str:
    """检查力量体系类条目的 title 数字与 content 条目数是否一致，返回 warning 文本。

    防止 LLM 在 title 写"九品登仙梯"但 content 实际只列了 4 个境界。
    """
    cn_num_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    warnings = []
    for item in items:
        category = item.get("category", "")
        title = item.get("title", "")
        content = item.get("content", "")
        # 只检查力量体系/境界体系/异能体系类
        if not any(k in category for k in ("力量", "境界", "体系", "异能")):
            continue
        # 提取 title 中的中文数字和阿拉伯数字
        title_nums = []
        for m in re.finditer(r"[一二三四五六七八九十]+|\d+", title):
            s = m.group()
            if s.isdigit():
                title_nums.append(int(s))
            else:
                if s == "十":
                    title_nums.append(10)
                elif len(s) == 1:
                    title_nums.append(cn_num_map.get(s, 0))
                elif len(s) == 2 and s[0] == "十":
                    title_nums.append(10 + cn_num_map.get(s[1], 0))
                elif len(s) == 2 and s[1] == "十":
                    title_nums.append(cn_num_map.get(s[0], 0) * 10)
        if not title_nums:
            continue
        # 统计 content 中的条目数（按列表标记切分，否则按非空行计数）
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        list_items = [l for l in lines if re.match(r"^[\·•\-—\d一二三四五六七八九十]+[\.、\)）]", l)]
        content_count = len(list_items) if list_items else len(lines)
        # 检查 title 数字是否与 content 条目数匹配
        for n in title_nums:
            if n > 0 and n != content_count:
                warnings.append(
                    f"条目《{title}》的 title 出现数字 {n}，但 content 实际列出 {content_count} 项，可能不一致"
                )
                break
    return "；".join(warnings)


def _safe_int(val, default=0) -> int:
    """安全转int，LLM常返回 '中等'/'高' 等非数字字符串。"""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


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
    """从 LLM 返回中提取 JSON 对象（统一使用 parse_json_strict）。"""
    from novel_agent.utils.json_parser import parse_json_strict
    return parse_json_strict(text)


async def _generate_json_with_repair(
    client,
    prompt: str,
    system: str,
    max_tokens: int = 128000,
    *,
    root_key: str | None = None,
) -> dict | None:
    """调 LLM 生成 JSON，解析失败时走 LLM 自修复。返回 dict 或 None。

    统一所有生成接口的 LLM 调用 + 解析 + 自修复兜底，避免单点缺失自修复导致 422。

    Args:
        root_key: 期望的顶层数组字段名（如 arcs / chapters / world_settings），
                  自修复时会额外提示 LLM 保持该结构。
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        raw = await client.generate(prompt, system=system, max_tokens=max_tokens, max_retries=1)
    except Exception as e:
        raise HTTPException(502, f"LLM 调用失败: {e}")
    result = _extract_json(raw)
    if result:
        return result
    # 首次解析失败，记录原始内容便于诊断，再走 LLM 自修复
    logger.warning("generate_json 首次解析失败，raw 前 300 字: %s", (raw or "")[:300])
    try:
        structure_hint = (
            f"顶层必须包含一个名为 '{root_key}' 的数组。"
            if root_key
            else "保持原始数据的顶层结构不变。"
        )
        repair_prompt = (
            "下面这段内容本应是 JSON，但解析时报错。请只输出修复后的合法 JSON 对象，"
            "不要 markdown 代码块、不要任何解释文字。\n"
            f"{structure_hint}\n\n"
            f"{raw}"
        )
        fixed = await client.generate(
            repair_prompt,
            system="你是 JSON 修复助手，只输出合法 JSON 对象。",
            max_tokens=max_tokens,
        )
        result = _extract_json(fixed)
        if not result:
            logger.warning("generate_json 自修复仍失败，fixed 前 300 字: %s", (fixed or "")[:300])
    except Exception as e:
        logger.warning("generate_json 自修复调用异常: %s", e)
    return result



@router.post("/world/generate", response_model=GenerateWorldResponse)
@limiter.limit("10/minute")
async def generate_world(request: Request, req: GenerateWorldRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        client = LLMClient(cfg.get_agent_llm("architect"))
        # 注入已有设定约束 + 世界观设计指南
        from novel_agent.templates.style_guide_loader import get_task_guide
        consistency = _build_consistency_constraint(repo, project)
        worldview_guide = get_task_guide("worldview")
        prompt = PromptLoader().render(
            "world",
            title=project.title,
            genre=project.genre,
            summary=project.summary,
            style=project.style,
            requirements=(req.requirements or "") + "\n\n" + worldview_guide,
            style_hint=req.style,
            existing_world=consistency,
            categories=_get_categories_for_genre(project.genre),
        )

        result = await _generate_json_with_repair(
            client, prompt, system="你是网文设定师，擅长设计多层世界观。只输出 JSON。", root_key="world_settings")
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
        settings = result.get("world_settings") or result.get("worlds") or result.get("settings") or []
        if not settings:
            raise HTTPException(422, "LLM 未返回有效设定项，请检查模型配置或重试")
        # 预览模式：不写库，只返回带临时 ID 的 items，用户确认后再调 /world/import
        items = []
        for i, s in enumerate(settings):
            items.append({
                "id": i,
                "category": _clean_text(s.get("category", "其他")),
                "title": _clean_text(s.get("title", "未命名")),
                "content": _clean_text(s.get("content", "")),
                "order": i,
            })
        # 标题/内容数字一致性校验（防止 title 写"九品"但 content 只列 4 个境界）
        warning = _check_title_content_consistency(items)
        return GenerateWorldResponse(created=len(items), items=items, warning=warning)
    finally:
        if client is not None:
            await client.close()
        db.close()


@router.post("/characters/generate", response_model=GenerateCharactersResponse)
@limiter.limit("10/minute")
async def generate_characters(request: Request, req: GenerateCharactersRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        client = LLMClient(cfg.get_agent_llm("architect"))
        # 注入已有设定约束 + 角色设计指南
        from novel_agent.templates.style_guide_loader import get_task_guide
        consistency = _build_consistency_constraint(repo, project)
        character_guide = get_task_guide("character")
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
            existing_world=consistency + "\n\n" + character_guide,
            existing_characters="",
        )

        result = await _generate_json_with_repair(
            client, prompt, system="你是网文角色设计师，擅长设计立体角色。只输出 JSON。", root_key="characters")
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
        characters = result.get("characters") or result.get("chars") or result.get("roles") or []
        if not characters:
            raise HTTPException(422, "LLM 未返回有效角色项，请检查模型配置或重试")
        # 预览模式：不写库，只返回带临时 ID 的 items，用户确认后再调 /characters/import
        items = []
        for i, c in enumerate(characters):
            items.append({
                "id": i,
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
            })
        return GenerateCharactersResponse(created=len(items), items=items)
    finally:
        if client is not None:
            await client.close()
        db.close()


class ImportWorldRequest(BaseModel):
    project_id: int
    items: list[dict]


class ImportCharactersRequest(BaseModel):
    project_id: int
    items: list[dict]


@router.post("/world/import")
def import_world(req: ImportWorldRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        created = []
        for item in req.items:
            obj = repo.create_world_setting(
                category=item.get("category", "其他"),
                title=item.get("title", ""),
                content=item.get("content", ""),
            )
            created.append({"id": obj.id, "title": obj.title})
        return {"created": len(created), "items": created}
    finally:
        db.close()


@router.post("/characters/import")
def import_characters(req: ImportCharactersRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        created = []
        for item in req.items:
            obj = repo.create_character(
                name=item.get("name", "未命名"),
                role=item.get("role", "配角"),
                age=item.get("age", ""),
                gender=item.get("gender", ""),
                appearance=item.get("appearance", ""),
                background=item.get("background", ""),
                personality=item.get("personality", ""),
                motivation=item.get("motivation", ""),
                arc=item.get("arc", ""),
                secrets=item.get("secrets", ""),
            )
            created.append({"id": obj.id, "name": obj.name})
        return {"created": len(created), "items": created}
    finally:
        db.close()


def _build_consistency_constraint(repo, project) -> str:
    """构建设定一致性约束文本，注入所有生成 prompt。

    汇总项目已有全部设定（题材模板/世界观/角色/势力/伏笔/大纲/怪物/章节摘要），
    强制 LLM 生成内容与已有设定关联，不得凭空捏造矛盾内容。
    """
    from novel_agent.templates.style_guide_loader import get_core_constraints

    parts = []

    # 题材模板（始终注入，确保所有生成内容遵循题材约束）
    if project.genre:
        try:
            cg = canonical_genre(project.genre)
            template_text = GenreLoader().load(cg)
            if template_text:
                parts.append(f"【题材模板：{cg}】\n{template_text}")
        except Exception as e:
            logger.warning("题材模板加载失败: %s", e)

    # 核心写作约束（始终注入）
    core = get_core_constraints()
    if core:
        parts.append(core)

    # 世界观
    world = repo.list_world_settings()
    if world:
        parts.append("【已有世界观设定】\n" + "\n".join(
            f"- [{w.category}] {w.title}：{w.content}" for w in world
        ))

    # 角色
    chars = repo.list_characters()
    if chars:
        parts.append("【已有角色】\n" + "\n".join(
            f"- {c.name}（{c.role}）：{c.personality or ''}；动机：{c.motivation or ''}"
            f" | 位置：{c.current_location or '未知'} | 情绪：{c.current_emotion or '未知'}"
            for c in chars
        ))

    # 势力
    factions = repo.list_factions()
    if factions:
        parts.append("【已有势力】\n" + "\n".join(
            f"- {f.name}（{f.tier}/{f.alignment}）：{f.goals or f.description or ''}"
            for f in factions
        ))

    # 伏笔
    foreshadows = repo.list_foreshadows()
    if foreshadows:
        parts.append("【已有伏笔】\n" + "\n".join(
            f"- {f.foreshadow_id}（{f.status}）：{f.description}（埋于第{f.plant_chapter}章，计划第{f.planned_resolve_chapter}章回收）"
            for f in foreshadows
        ))

    # 大纲
    outlines = repo.list_outlines()
    if outlines:
        parts.append("【已有大纲】\n" + "\n".join(
            f"- [{o.level}] 第{o.order}章《{o.title}》：{o.summary}"
            for o in outlines
        ))

    # 怪物
    monsters = repo.list_monsters()
    if monsters:
        parts.append("【已有怪物】\n" + "\n".join(
            f"- {m.name}（{m.tier}/{m.rank}）：{m.behavior or ''} | 弱点：{m.weaknesses or '未知'}"
            for m in monsters
        ))

    # 近期章节摘要
    summaries = repo.list_chapter_summaries(limit=5)
    if summaries:
        parts.append("【近期章节摘要】\n" + "\n".join(
            f"- 第{s.chapter}章《{s.title}》：{s.core_events}"
            for s in sorted(summaries, key=lambda x: x.chapter)
        ))

    if not parts:
        return ""

    return (
        "\n\n【已有设定 — 生成内容的唯一基础，必须严格遵守】\n"
        "以下是项目中已建立的全部设定。你生成的所有内容必须基于这些已有设定展开，"
        "与已有设定保持一致、无缝衔接。已有设定是创作的地基，所有新剧情都在其上生长。\n\n"
        + "\n\n".join(parts)
        + "\n\n【遵守已有设定的具体要求】\n"
        "1. 力量体系（或题材对应的境界/异能/序列体系）— 使用上述已有的体系设定，角色能力表现需符合体系规则\n"
        "2. 地理区域/安全区/城市 — 使用上述已有的世界观地理设定，场景地点需在已有范围内\n"
        "3. 势力/组织/阵营 — 使用上述已有的势力设定，势力关系和格局需与已有设定一致\n"
        "4. 角色性格/能力/关系/位置 — 已有角色必须保持设定中的连续性，行为符合人设\n"
        "5. 伏笔状态 — 已回收的伏笔不能重新埋设，未回收的需按计划推进回收\n"
        "6. 世界观规则 — 已有规则是硬约束，事件发展不得突破体系限制\n"
        "7. 大纲脉络 — 剧情发展需符合已有大纲脉络，自然衔接不跳跃\n\n"
        "新剧情、新事件、新冲突应当是已有设定的自然发展和延伸，而非脱离已有设定的凭空创造。\n"
        "在生成每一条大纲时，请先思考：这条大纲用到了哪些已有设定？它与已有设定如何衔接？"
    )


def _build_context_text(repo, project, cfg, context_type: str, context_id):
    """构建当前上下文文本。

    - outline：读取单个大纲项 + 父级/子级大纲
    - chapter：读取章节正文
    - 其他：注入近期章节摘要 + 最近正文片段，让 LLM 知道前文剧情
    """
    if context_type == "outline":
        o = repo.get_outline(int(context_id)) if context_id else None
        if not o:
            return "暂无"
        parts = [f"[{o.level}] 第{o.order}章《{o.title}》：{o.summary}"]
        # 注入同级大纲上下文（前一章 + 后一章）
        siblings = repo.list_outlines(level=o.level)
        for s in siblings:
            if s.order == o.order - 1:
                parts.append(f"前一章：第{s.order}章《{s.title}》：{s.summary}")
            elif s.order == o.order + 1:
                parts.append(f"后一章：第{s.order}章《{s.title}》：{s.summary}")
        return "\n".join(parts)
    if context_type == "chapter":
        recall = RecallMemory(cfg, project_id=repo.project_id)
        text = recall.read_chapter_text(int(context_id)) if context_id else ""
        return text or "当前章节暂无正文"
    # 其他场景（world/character/monster/faction/relationship）：
    # 注入近期章节摘要 + 最近正文片段
    parts = ["基于项目全局上下文"]
    summaries = repo.list_chapter_summaries(limit=5)
    if summaries:
        parts.append("【近期章节摘要】\n" + "\n".join(
            f"- 第{s.chapter}章《{s.title}》：{s.core_events}"
            for s in sorted(summaries, key=lambda x: x.chapter)
        ))
    # 最近一章完整正文
    try:
        recall = RecallMemory(cfg, project_id=repo.project_id)
        latest_chapters = sorted(recall.list_chapters(), reverse=True)[:1]
        if latest_chapters:
            tail = recall.read_chapter_text(latest_chapters[0])
            parts.append(f"【最近正文（第{latest_chapters[0]}章）】\n{tail}")
    except Exception as e:
        logger.warning("加载最近正文失败: %s", e)
    return "\n\n".join(parts)


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
        return "\n".join(f"- {s.category}/{s.title}: {s.content}" for s in items) if items else ""
    if suggest_type == "character":
        items = repo.list_characters()
        return "\n".join(f"- {c.name}({c.role}): {c.personality or c.background or ''}" for c in items) if items else ""
    return ""


def _format_world_for_prompt(repo) -> str:
    """格式化世界观设定，注入 suggest prompt 的 $world_text。"""
    items = repo.list_world_settings()
    if not items:
        return "暂无"
    return "\n".join(f"- [{w.category}] {w.title}：{w.content}" for w in items)


def _format_chars_for_prompt(repo) -> str:
    """格式化角色列表，含动态状态（位置、情绪、已知信息、关系）。"""
    chars = repo.list_characters()
    if not chars:
        return "暂无"
    lines = []
    for c in chars:
        parts = [f"- {c.name}（{c.role or '角色'}）"]
        if c.personality:
            parts.append(f"性格：{c.personality}")
        if c.motivation:
            parts.append(f"动机：{c.motivation}")
        if c.core_contradiction:
            parts.append(f"内在矛盾：{c.core_contradiction}")
        # 动态状态（随剧情更新）
        if c.current_location:
            parts.append(f"当前位置：{c.current_location}")
        if c.current_emotion:
            parts.append(f"当前情绪：{c.current_emotion}")
        if c.known_info:
            parts.append(f"已知信息：{c.known_info}")
        if c.relationships:
            parts.append(f"关系：{c.relationships}")
        if c.secrets:
            parts.append(f"秘密：{c.secrets}")
        if c.arc:
            parts.append(f"角色弧光：{c.arc}")
        if c.absolute_taboos:
            parts.append(f"绝对禁忌：{c.absolute_taboos}")
        lines.append("；".join(parts))
    return "\n".join(lines)


def _format_foreshadows_for_prompt(repo) -> str:
    """格式化伏笔列表，按状态分组，突出待回收的伏笔。"""
    fs = repo.list_foreshadows()
    if not fs:
        return "暂无"
    # 按状态分组
    pending = [f for f in fs if f.status in ("pending", "planted", "developing")]
    resolved = [f for f in fs if f.status in ("resolved", "abandoned")]
    lines = []
    if pending:
        lines.append("【待回收伏笔（本章应考虑推进或回收）】")
        for f in pending:
            lines.append(
                f"- {f.foreshadow_id}（{f.status}）：{f.description}"
                f"（埋于第{f.plant_chapter}章，计划第{f.planned_resolve_chapter}章回收）"
            )
    if resolved:
        lines.append("【已回收伏笔（不要重复回收）】")
        for f in resolved:
            lines.append(f"- {f.foreshadow_id}（{f.status}）：{f.description}")
    return "\n".join(lines) if lines else "暂无"


def _format_collection_for_prompt(repo, current_chapter: int) -> str:
    """格式化「伏笔/欠账催收」清单：已逾期伏笔 + 应回收伏笔 + 未兑现欠账。

    到期催收的核心：把「欠账未还、伏笔过期」显式推给写手，强制其在本章
    推进或回收，避免遗忘导致设定崩坏。无内容时返回空串（不注入）。
    """
    parts: list[str] = []
    overdue = repo.get_overdue_foreshadows(current_chapter)
    if overdue:
        lines = [f"- {f.foreshadow_id}（原计划第{f.planned_resolve_chapter}章回收）：{f.description}"
                 for f in overdue]
        parts.append("【逾期未回收伏笔·必须尽快处理】\n" + "\n".join(lines))

    due = [f for f in repo.get_foreshadows_to_resolve(current_chapter)
           if f.status not in ("resolved", "abandoned")]
    if due:
        lines = [f"- {f.foreshadow_id}：{f.description}" for f in due]
        parts.append("【本章应回收伏笔】\n" + "\n".join(lines))

    debts = repo.list_open_debts()
    if debts:
        lines = [f"- {d.debt_type}（压力{d.pressure}/5，产生于第{d.created_chapter}章）：{d.description}"
                 for d in debts]
        parts.append("【未兑现剧情欠账·需回应或推进】\n" + "\n".join(lines))

    if not parts:
        return ""
    return "【伏笔/欠账催收】\n" + "\n\n".join(parts)


def _extract_chapter_entities(repo, chapter: int, recent_texts: list[str]) -> list[str]:
    """提取本章可能涉及的实体（角色名）。

    来源合并去重（写手上下文三合一第 2 步）：
    1. 大纲 character_constraints 的 key（本章显式约束的角色）
    2. 最近几章正文中出现的已知角色名（名字匹配）

    注意：候选必须同时是「已知角色名」——get_outline_by_chapter 会回退到
    arc/volume 级大纲，其 character_constraints 可能含 character_focus/
    emotion_arc 等结构化字段，不过滤会把它们误当实体名。
    """
    names: set[str] = set()
    # 已知角色名（权威集合）
    try:
        known = {c.name for c in repo.list_characters()}
    except Exception:
        known = set()
    # 1. 大纲约束角色（必须是已知角色）
    try:
        outline = repo.get_outline_by_chapter(chapter)
        if outline and outline.character_constraints:
            cc = json.loads(outline.character_constraints)
            if isinstance(cc, dict):
                names.update(k for k in cc.keys() if k and k in known)
    except Exception:
        pass
    # 2. 最近章节正文中的已知角色
    for text in recent_texts:
        for n in known:
            if n and len(n) >= 2 and n in text:
                names.add(n)
    return sorted(names)


def _format_entity_history_for_prompt(repo, chapter: int, entity_names: list[str]) -> str:
    """实体历史提及：查每个实体在更早章节的出现记录，喂给写手做跨章节呼应。

    重点提示两类（写手三合一核心）：
    - role=mention（提及式出场，如新闻里只提到名字）→ 本章可呼应，勿当新设定重介绍
    - 最早出现与当前章差距 >= 10 章（久远实体）→ 防遗忘/防重复介绍
    """
    if not entity_names:
        return ""
    lines: list[str] = []
    for name in entity_names:
        try:
            apps = repo.list_entity_appearances(entity_type="character", entity_id=name)
        except Exception:
            continue
        past = [a for a in apps if a.chapter < chapter]
        if not past:
            continue
        earliest = min(past, key=lambda a: a.chapter)
        gap = chapter - earliest.chapter
        role = earliest.role_in_chapter or "mention"
        snippet = (earliest.context_snippet or "").replace("\n", " ").strip()
        if len(snippet) > 60:
            snippet = snippet[:60] + "..."
        role_label = {
            "lead": "主角戏", "participant": "参与",
            "mention": "提及", "background": "背景",
        }.get(role, role)
        # 只提示"需要呼应的"：提及式出场（跨章伏笔）、久远实体（防遗忘）
        if role == "mention" or gap >= 10:
            line = f"- {name}：最早第{earliest.chapter}章【{role_label}】出现"
            if snippet:
                line += f"（上下文：{snippet}）"
            line += f"；至今共出场{len(past)}次"
            if gap >= 5:
                line += f"；距上次已有{gap}章"
            lines.append(line)
    if not lines:
        return ""
    return (
        "【实体历史提及--跨章节呼应】\n"
        "注意：以下实体在更早章节出现过，本章若提及应与之呼应（延续既有设定），"
        "不要把它当成新人物重新介绍：\n"
        + "\n".join(lines)
    )


def _format_volume_summary_for_prompt(repo, chapter: int, chapter_summaries: list) -> str:
    """卷/弧摘要：最近若干章的摘要概览，给写手保全局方向。

    ChapterSummary 已由章节提交时生成（✅已有），这里只做注入。
    取最近 10 章的 core_events 拼接，控制 token 开销。
    """
    if not chapter_summaries:
        return ""
    lines: list[str] = []
    for s in sorted(chapter_summaries, key=lambda x: x.chapter)[-10:]:
        if getattr(s, "core_events", ""):
            lines.append(f"第{s.chapter}章：{(s.core_events or '')[:120]}")
    if not lines:
        return ""
    return "【近期剧情摘要--全局方向参考】\n" + "\n".join(lines)


def _list_chapter_summaries(repo) -> list:
    """查 ChapterSummary 列表（按章节升序）。"""
    try:
        from novel_agent.bible.models import ChapterSummary
        return (
            repo.db.query(ChapterSummary)
            .filter(ChapterSummary.project_id == repo.project_id)
            .order_by(ChapterSummary.chapter.asc())
            .all()
        )
    except Exception:
        return []


def _format_subplots_for_prompt(repo) -> str:
    """格式化支线进度板。"""
    from novel_agent.bible.models import SubplotBoard
    subplots = (
        repo.db.query(SubplotBoard)
        .filter(SubplotBoard.project_id == repo.project_id)
        .order_by(SubplotBoard.is_main.desc(), SubplotBoard.updated_chapter.desc())
        .all()
    )
    if not subplots:
        return ""
    lines = ["【支线进度】"]
    for s in subplots:
        tag = "主线" if s.is_main else "支线"
        status_tag = f"（{s.status}）" if s.status != "active" else ""
        lines.append(
            f"- [{tag}]{s.name}{status_tag}：进度{s.progress}%"
            f"（更新至第{s.updated_chapter}章）"
            + (f"→下一目标：{s.next_goal}" if s.next_goal else "")
        )
    return "\n".join(lines)


def _format_character_relationships_for_prompt(repo) -> str:
    """格式化角色关系动态。"""
    rels = repo.list_character_relationships()
    if not rels:
        return ""
    active = [r for r in rels if r.status == "active"]
    if not active:
        return ""
    lines = ["【角色关系动态】"]
    for r in active[:20]:  # 最多20条，避免过长
        change = f"：{r.description}" if r.description else ""
        lines.append(f"- {r.source_character} → {r.target_character}（{r.relation_type}）{change}")
    return "\n".join(lines)


def _format_faction_dynamics_for_prompt(repo) -> str:
    """格式化势力关系动态。"""
    factions = repo.list_factions()
    if not factions:
        return ""
    rels = repo.list_faction_relationships()
    lines = ["【势力格局】"]
    for f in factions:
        lines.append(f"- {f.name}（{f.tier or '未知层级'}/{f.alignment or '中立'}）：{f.goals or f.description or '目标未知'}")
    if rels:
        active_rels = [r for r in rels if r.status == "active"]
        if active_rels:
            lines.append("势力关系：")
            for r in active_rels[:10]:
                lines.append(f"- {r.relation_type}（强度{r.strength}）：{r.description or ''}")
    return "\n".join(lines)


def _find_arc_for_chapter(repo, chapter_num: int) -> Outline | None:
    """根据章节号推断当前所属的细纲（arc）。

    优先根据已有章级大纲的 parent_id 向上查找；若找不到，则按 arc order 做简单推断。
    """
    chapters = repo.list_outlines(level="chapter")
    # 找到小于等于当前章号的最近一章，看它的父级 arc
    prev_chapters = [c for c in chapters if c.order <= chapter_num]
    if prev_chapters:
        nearest = max(prev_chapters, key=lambda c: c.order)
        if nearest.parent_id:
            parent = repo.db.query(Outline).filter(
                Outline.project_id == repo.project_id,
                Outline.id == nearest.parent_id,
                Outline.level == "arc",
            ).first()
            if parent:
                return parent

    # 兜底：按 arc order 简单推断当前 chapter 落在哪个 arc
    arcs = repo.list_outlines(level="arc")
    if not arcs:
        return None
    arcs_sorted = sorted(arcs, key=lambda o: o.order)
    # 如果没有章级大纲，默认每个 arc 覆盖的章节数 = 总章节数 / arc 数
    # 这里用保守推断：chapter_num 落在第 idx 个 arc，idx = min((chapter_num - 1), len(arcs) - 1)
    idx = min(max(chapter_num - 1, 0), len(arcs_sorted) - 1)
    return arcs_sorted[idx]


# 用于识别「按细纲分章创作」指令，例如：
# "按照细纲《黑市逃亡》完成第1章，共5章"
# "按细纲黑市逃亡写第2章，总共5章"
_ARC_SPLIT_PATTERN = re.compile(
    r"(?:按照|按|根据|依据)\s*细纲\s*[《\"']?(?P<arc_name>.+?)[》\"']?\s*(?:完成|写|创作|生成)?\s*第\s*(?P<current>\d+)\s*章\s*[，,]?\s*(?:总共|共|计)\s*(?P<total>\d+)\s*章",
    re.IGNORECASE | re.UNICODE,
)


def _parse_arc_split_command(message: str) -> tuple[str, int, int] | None:
    """解析用户按细纲分章创作的指令。

    返回 (细纲名称, 当前是第几章, 总共几章)。未匹配返回 None。
    """
    if not message:
        return None
    m = _ARC_SPLIT_PATTERN.search(message.strip())
    if not m:
        return None
    arc_name = m.group("arc_name").strip()
    try:
        current = int(m.group("current"))
        total = int(m.group("total"))
    except (ValueError, TypeError):
        return None
    if current <= 0 or total <= 0 or current > total:
        return None
    return arc_name, current, total


# 判断用户消息是否明确表达创作意图（用于问答模式）
_CREATION_COMMAND_PATTERNS = [
    re.compile(r"创作第\s*[\d一二三四五六七八九十百]+\s*章"),
    re.compile(r"写第\s*[\d一二三四五六七八九十百]+\s*章"),
    re.compile(r"生成第\s*[\d一二三四五六七八九十百]+\s*章"),
    re.compile(r"写下一章"),
    re.compile(r"创作下一章"),
    re.compile(r"生成下一章"),
    re.compile(r"继续写"),
    re.compile(r"开始写"),
    re.compile(r"写正文"),
    re.compile(r"生成正文"),
    re.compile(r"创作正文"),
    re.compile(r"写故事"),
    re.compile(r"生成故事"),
    re.compile(r"写下去"),
    re.compile(r"启动.*生成"),
    re.compile(r"开始.*生成"),
    re.compile(r"写.*章.*正文"),
]


def _looks_like_creation_command(message: str) -> bool:
    """判断用户消息是否明确表达创作意图。"""
    if not message:
        return False
    # 按细纲分章指令属于明确创作意图
    if _parse_arc_split_command(message):
        return True
    m = message.strip().lower()
    return any(p.search(m) for p in _CREATION_COMMAND_PATTERNS)


def _find_arc_by_name(repo, arc_name: str) -> Outline | None:
    """按名称模糊查找细纲（arc）。"""
    arcs = repo.list_outlines(level="arc")
    if not arcs:
        return None
    name_lower = arc_name.lower()
    # 先精确匹配
    for arc in arcs:
        if (arc.title or "").strip().lower() == name_lower:
            return arc
    # 再模糊匹配
    for arc in arcs:
        if name_lower in (arc.title or "").lower() or (arc.title or "").lower() in name_lower:
            return arc
    return None


def _build_arc_split_instruction(arc: Outline, current_chapter: int, total_chapters: int) -> str:
    """构造按细纲分章创作的强约束指令。"""
    lines = [
        f"【按细纲分章创作 - 第 {current_chapter}/{total_chapters} 章】",
        f"用户要求按照细纲《{arc.title}》完成第 {current_chapter} 章，该细纲全段共计划 {total_chapters} 章。",
        "",
        "【你必须执行的分章规则】",
        f"1. 自动分析下面《{arc.title}》的细纲内容，将其整体剧情合理切分为 {total_chapters} 份。",
        f"2. 当前章节必须取切分后的第 {current_chapter} 份进行创作，不得跳份、不得重复、不得混淆。",
        "3. 当前份的剧情必须充分展开，严禁一笔带过。",
        "",
        "【反流水账铁律 - 必须遵守】",
        "如果第 {current_chapter} 份的剧情点较少、不足以支撑完整一章，你绝对禁止用以下方式凑字数：".format(current_chapter=current_chapter),
        "- 禁止大段环境描写开头或填充",
        "- 禁止独角戏、纯内心独白、重复心理活动",
        "- 禁止数钱、买东西、排队、赶路、吃饭、整理物资等纯日常流水",
        "- 禁止用重复叙述、说明性设定灌输来拉长篇幅",
        "",
        "【内容不足时必须主动添加（任选其一或组合）】",
        "- 小剧情：与主线或本份剧情强相关的微型冲突、事件、遭遇",
        "- 支线：引入一个临时的次要目标、任务或委托",
        "- 任务：让角色接到、执行、完成或失败一个具体任务",
        "- 转折：制造意外、反转、识破、反杀、突破、碾压等爽点",
        "- 新元素：引入符合世界观的小角色、势力、怪物、道具、规则，推动本份剧情",
        "",
        "【底线】",
        "所有新增内容必须服务当前份剧情，不得偏离细纲核心走向；新角色/势力/怪物/设定必须符合世界观。",
        "",
        "【细纲原文】",
        f"标题：{arc.title}",
    ]
    if arc.summary:
        lines.append(f"概要：{arc.summary}")
    if arc.act:
        lines.append(f"节奏定位：{arc.act}")
    if arc.strand:
        lines.append(f"故事线：{arc.strand}")
    if arc.required_beats:
        lines.append(f"必要节拍：{arc.required_beats}")
    if arc.required_hooks:
        lines.append(f"钩子方向：{arc.required_hooks}")
    if arc.character_constraints:
        lines.append(f"角色约束：{arc.character_constraints}")
    if arc.owed_debts:
        lines.append(f"剧情债务：{arc.owed_debts}")
    lines.append("")
    lines.append(f"【当前章节要求】")
    lines.append(f"- 细纲内位置：第 {current_chapter} 章 / 共 {total_chapters} 章")
    lines.append(f"- 必须覆盖的细纲份数：第 {current_chapter} 份")
    lines.append(f"- 字数、反流水账铁律、章末钩子等其他约束照常执行")
    return "\n".join(lines)


def _format_chapter_outline_for_prompt(repo, chapter_num: int) -> str:
    """格式化当前章节的大纲约束（如果存在），强制要求 AI 参考，同时保留自由创作边界。"""
    outline = repo.get_outline_by_chapter(chapter_num)
    if outline:
        parts = [
            "【本章大纲约束 - 必须严格参考】",
            "以下约束具有最高优先级。你必须执行其核心事件、节奏、必要节拍、角色状态和章末钩子；",
            "在满足以下核心框架的前提下，你可以自由添加任何能推进剧情发展的内容（新角色、新势力、新怪物、新冲突、新转折），但这些新元素必须符合世界观设定，不得违背本章的核心目标。",
            f"标题：{outline.title}",
        ]
        if outline.summary:
            parts.append(f"剧情概要：{outline.summary}")
        if outline.act:
            parts.append(f"节奏：{outline.act}")
        if outline.strand:
            parts.append(f"故事线：{outline.strand}")
        if outline.phase and outline.phase != "regular":
            parts.append(f"章节阶段：{outline.phase}")
        if outline.required_beats:
            parts.append(f"必要节拍（必须出现）：{outline.required_beats}")
        if outline.character_constraints:
            parts.append(f"角色约束（必须遵守）：{outline.character_constraints}")
        if outline.owed_debts:
            parts.append(f"剧情债务（必须回应或推进）：{outline.owed_debts}")
        if outline.required_hooks:
            parts.append(f"章末钩子（必须落地）：{outline.required_hooks}")
        return "\n".join(parts)

    # 无章级大纲时，尝试引用所属细纲（arc）作为整体方向
    arc = _find_arc_for_chapter(repo, chapter_num)
    if arc:
        parts = [
            "【当前弧段方向 - 必须参考整体走向】",
            f"本章节处于细纲《{arc.title}》的范围内。没有更细的章级大纲，但你必须参考以下整体方向，保证本章与该弧段的核心目标一致；",
            "同时允许你自由添加任何能推进剧情发展的内容（新角色、新势力、新怪物、新冲突、新转折），但这些新元素必须符合世界观设定。",
        ]
        if arc.summary:
            parts.append(f"弧段概要：{arc.summary}")
        if arc.act:
            parts.append(f"节奏定位：{arc.act}")
        if arc.strand:
            parts.append(f"故事线：{arc.strand}")
        if arc.required_beats:
            parts.append(f"建议节拍：{arc.required_beats}")
        if arc.required_hooks:
            parts.append(f"弧段钩子方向：{arc.required_hooks}")
        return "\n".join(parts)

    return ""


def _format_outlines_for_prompt(repo) -> str:
    """格式化大纲列表，注入 suggest prompt 的 $outline_text。"""
    outlines = repo.list_outlines()
    if not outlines:
        return "暂无"
    return "\n".join(
        f"- [{o.level}] 第{o.order}章《{o.title}》：{o.summary}"
        for o in outlines
    )


def _format_factions_for_prompt(repo) -> str:
    """格式化势力列表，注入 suggest prompt 的 $faction_text。"""
    factions = repo.list_factions()
    if not factions:
        return "暂无"
    return "\n".join(
        f"- {f.name}（{f.tier}/{f.alignment}）：{f.goals or f.description or ''}"
        for f in factions
    )


@router.post("/volumes/generate", response_model=GenerateOutlinesResponse)
@limiter.limit("10/minute")
async def generate_volumes(request: Request, req: GenerateVolumesRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        client = LLMClient(cfg.get_agent_llm("outliner"))
        consistency = _build_consistency_constraint(repo, project)
        system = "你是资深网文架构师，擅长设计长篇小说的卷级大纲。你的设计以结构严谨、伏笔绵密、节奏精准著称。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》生成 {req.count} 个卷级大纲。

题材：{project.genre}
简介：{project.summary}
风格/要求：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

{consistency}

【强制要求】
1. 必须严格生成 {req.count} 个卷级大纲，不多不少。每卷标题必须不同，不得重复。
2. 卷级大纲必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的卷剧情。
3. 每一卷的剧情主线必须与世界观中的力量体系/势力格局/地理设定直接关联。
4. 卷概要中必须提到至少 2 个已有角色或势力，体现世界观约束。
5. 如果已有伏笔，卷级规划必须安排伏笔的推进或回收。

【卷级结构设计指南——基于人类作家写作模式】
每卷应采用"新地图 + 新目标 + 新势力网络 + 一次体系质变 + 一次根基扩张"的骨架结构。卷与卷之间通过地理迁移和目标升级形成递进。

每卷内部采用波浪式节奏推进，包含以下节奏段（交替出现，避免单一类型疲劳）：
- 适应与扎根期：铺设新地图、物价、人物关系、装备基础
- 团队整合与矛盾铺垫期：新势力登场，外部冲突加剧
- 独立爆发期：连续战斗/行动+战力升级高潮
- 团队危机与势力建构期：由外转内，智斗与博弈为主
- 权力清算与决战期：多方博弈最大冲突
- 过渡收束期：告别、交接、启程

【summary 必须包含以下要素】
- 核心冲突：本卷的主要矛盾是什么？谁与谁的冲突？冲突的根源是什么？
- 剧情主线：本卷从什么状态开始，经历什么转折，到达什么结局？因果链条必须清晰。
- 角色弧光：主要角色在本卷中有什么成长或变化？目标和动机如何演变？身份是否发生跃迁？
- 世界观推进：本卷揭示了世界观的哪个新层面？（采用"洋葱式"层层剥开，每卷揭示一层）
- 伏笔布局：本卷埋设哪些伏笔？回收哪些伏笔？区分短期（当卷回收）、中期（跨卷回收）、长期（全书谜团）三层伏笔。
- 节奏段划分：本卷的节奏段如何安排？战斗升级段与势力博弈段交替出现的节奏是什么？
- 卷末钩子：本卷结尾留下什么悬念驱动读者进入下一卷？

每个卷还包含：
- act：开端/发展/小高潮/转折/大高潮/结局
- key_events：关键事件列表，每个事件需描述其因果和影响，格式为包含 event/cause/effect 的 JSON 数组
- foreshadow_plan：本卷伏笔计划，格式为包含 action(plant/advance/resolve)/foreshadow_id/tier(short/medium/long)/description 的 JSON 数组

请输出 JSON，格式为：{{"volumes": [{{"order": 1, "title": "", "summary": "", "act": "", "key_events": [], "foreshadow_plan": []}}]}}

【最终检查 — 生成前必须确认】
在输出每一条卷级大纲前，请逐条确认：
- 这条大纲用到了哪些已有世界观设定？请在 summary 中明确引用。
- 力量体系、地理区域、势力组织是否与已有设定一致？
- 已有角色是否保持了性格、能力、关系的连续性？
- 伏笔的埋设和回收是否与已有伏笔状态一致？
确认无误后再输出。"""

        result = await _generate_json_with_repair(
            client, prompt, system=system, max_tokens=128000, root_key="volumes"
        )
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
        volumes = result.get("volumes") or result.get("outlines") or []
        if not volumes:
            raise HTTPException(422, "LLM 未返回有效卷级大纲，请检查模型配置或重试")
        # 去重：按标题去重
        seen_titles: set[str] = set()
        unique_volumes: list[dict] = []
        for v in volumes:
            t = _clean_text(v.get("title", "")).strip()
            if t and t in seen_titles:
                continue
            if t:
                seen_titles.add(t)
            unique_volumes.append(v)
        # 检测已有卷纲
        existing_volumes = repo.list_outlines(level="volume")
        existing_titles = {_clean_text(v.title).strip() for v in existing_volumes}
        # 编号：填补空缺，从 1 开始找第一个未使用的编号
        used_orders = {v.order for v in existing_volumes if v.order}

        def _next_vol_order() -> int:
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        items = []
        skipped = 0
        for idx, o in enumerate(unique_volumes):
            title = _clean_text(o.get("title", f"第{idx + 1}卷"))
            if title in existing_titles:
                skipped += 1
                continue
            order = _next_vol_order()
            created = repo.create_outline(
                level="volume",
                order=order,
                title=title,
                summary=_clean_text(o.get("summary", "")),
                act=_clean_text(o.get("act", "")),
                strand="",
                key_events=json.dumps(o.get("key_events") or [], ensure_ascii=False),
            )
            # P0#7：卷纲伏笔计划落库（ForeshadowImplant）
            _save_foreshadow_plans(repo, o.get("foreshadow_plan") or [])
            existing_titles.add(title)
            items.append({
                "id": created.id, "level": "volume", "parent_id": None,
                "order": created.order, "title": created.title,
                "summary": created.summary, "act": created.act, "strand": created.strand,
            })
        warning = ""
        if len(items) < req.count:
            warning = f"请求生成 {req.count} 个卷纲，实际生成 {len(items)} 个"
            if skipped > 0:
                warning += f"（跳过 {skipped} 个与已有重复的）"
        return GenerateOutlinesResponse(created=len(items), items=items, warning=warning)
    finally:
        if client is not None:
            await client.close()
        db.close()


@router.post("/arcs/generate", response_model=GenerateOutlinesResponse)
@limiter.limit("10/minute")
async def generate_arcs(request: Request, req: GenerateArcsRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        volume = repo.get_outline(req.parent_id)
        if not volume or volume.level != "volume":
            raise HTTPException(404, "卷级大纲不存在")

        client = LLMClient(cfg.get_agent_llm("outliner"))
        consistency = _build_consistency_constraint(repo, project)

        # 已有细纲（用于去重 + 作为前情提要）
        existing_arcs = repo.list_outlines(level="arc", parent_id=req.parent_id)
        existing_titles = {_clean_text(a.title).strip() for a in existing_arcs}
        used_orders = {a.order for a in existing_arcs if a.order}

        def _next_arc_order() -> int:
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        # ========== 全局节奏规划 pre-pass ==========
        # 先读完整卷纲，规划全部 N 个细纲的 act 分布和剧情骨架，避免分批生成时每批自闭合
        total_to_generate = req.count
        blueprint: list[dict] = []
        try:
            blueprint_system = "你是资深网文大纲师，擅长全局规划一卷的节奏分布。只输出 JSON。"
            blueprint_prompt = f"""请为以下卷规划 {total_to_generate} 个细纲小节的节奏蓝图。

卷标题：{volume.title}
卷概要：{volume.summary}
题材：{project.genre}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

【act 分配铁律】
- 全卷只有 1 个"大高潮"（倒数第 2-3 节）
- 全卷只有 1 个"结局"（最后 1 节）
- "小高潮"不超过总数的 1/4，分散在发展期
- "转折"不超过总数的 1/4，分散在发展期
- 前 10-15% 用"开端"
- 中间大部分用"发展"
- 禁止"终章"

【输出要求】
为每个小节输出 act 和一句剧情骨架（20字内）。
各节剧情须因果递进，从卷概要有机生长。

JSON：{{"blueprint": [{{"order": 1, "act": "开端", "title_hint": "", "plot_hint": ""}}]}}

严格输出 {total_to_generate} 个条目。"""
            print(f"[arcs/generate/stream] 蓝图pre-pass开始: 规划{total_to_generate}节...", flush=True)
            blueprint_result = await asyncio.wait_for(
                _generate_json_with_repair(
                    client, blueprint_prompt, system=blueprint_system, max_tokens=128000, root_key="blueprint"
                ),
                timeout=2100.0  # 35 分钟，与前端 GEN_TIMEOUT 统一
            )
            if blueprint_result and blueprint_result.get("blueprint"):
                blueprint = blueprint_result["blueprint"][:total_to_generate]
                print(f"[arcs/generate/stream] 蓝图pre-pass完成: {len(blueprint)}节", flush=True)
            else:
                print(f"[arcs/generate/stream] 蓝图pre-pass无结果，回退无蓝图模式", flush=True)
        except asyncio.TimeoutError:
            print(f"[arcs/generate/stream] 蓝图pre-pass超时(600s)，回退无蓝图模式", flush=True)
        except Exception as e:
            print(f"[arcs/generate/stream] 蓝图pre-pass异常: {e}，回退无蓝图模式", flush=True)  # 蓝图失败则回退到无蓝图模式

        # ========== 分批生成 ==========
        BATCH_SIZE = 5
        remaining = req.count
        all_items: list[dict] = []
        total_skipped = 0
        batch_no = 0

        while remaining > 0:
            batch_no += 1
            batch_count = min(BATCH_SIZE, remaining)
            remaining -= batch_count

            # 查询当前已有细纲作为前情提要
            prior_arcs = repo.list_outlines(level="arc", parent_id=req.parent_id)
            prior_brief = ""
            if prior_arcs:
                prior_arcs.sort(key=lambda x: (x.order or 0, x.id))
                lines = [f"  {i+1}. {a.title}：{a.summary}"
                         for i, a in enumerate(prior_arcs)]
                prior_brief = "\n\n【前情提要--已生成的细纲，请保持剧情连贯续写】\n" + "\n".join(lines) + \
                              f"\n\n请从第 {len(prior_arcs)+1} 节开始续写 {batch_count} 个新小节，与上述已有小节剧情连贯、不得重复。"

            # 蓝图注入：告诉 LLM 当前批次的全局位置和 act 约束
            blueprint_context = ""
            if blueprint:
                start_idx = len(all_items)
                batch_bp = blueprint[start_idx:start_idx + batch_count]
                if batch_bp:
                    bp_lines = []
                    for i, bp in enumerate(batch_bp):
                        global_pos = start_idx + i + 1
                        bp_lines.append(
                            f"  第{global_pos}/{total_to_generate}节 act={bp.get('act', '发展')}："
                            f"{bp.get('title_hint', '')} - {bp.get('plot_hint', '')}"
                        )
                    blueprint_context = (
                        f"\n\n【全局节奏蓝图--本批次在全书中的位置】\n"
                        f"总细纲数：{total_to_generate}，"
                        f"当前批次：第{start_idx+1}~{start_idx+batch_count}节\n"
                        + "\n".join(bp_lines)
                        + "\n\n【act 硬约束】本批次的 act 必须严格按上述蓝图分配，"
                        "不得自行添加\"大高潮\"或\"结局\"（除非蓝图中明确指定）。"
                        "绝对禁止出现\"终章\"。"
                    )

            system = (
                "你是资深网文大纲师，擅长把一卷拆成多个小节（arc）。"
                "每个小节是全局节奏链的一环，而非独立闭环。"
                "小节之间通过因果递进串联，共同构成一卷的完整弧线。只输出 JSON。"
            )
            prompt = f"""请为小说《{project.title}》的以下卷生成 {batch_count} 个细纲小节：
卷标题：{volume.title}
卷概要：{volume.summary}

题材：{project.genre}
风格/要求：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

{consistency}{prior_brief}{blueprint_context}

【强制要求】
1. 必须严格生成 {batch_count} 个细纲小节，不多不少。每个小节标题必须不同，不得重复。
2. 细纲小节必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的剧情。
3. 每个小节的剧情必须与世界观中的力量体系/势力格局/地理设定直接关联。
4. 小节概要中必须出现至少 1 个已有角色或势力名称。
5. 如果已有伏笔，需在适当小节安排伏笔的推进或回收。
6. 若有前情提要，新小节必须紧接前情继续推进剧情，不得重复前情内容。
7. 若有全局节奏蓝图，本批次每个小节的 act 必须与蓝图一致，不得擅自改为"大高潮"或"结局"。

【反流水账铁律——这是最重要的规则】
7. 每个小节必须包含至少 1 个明确的对抗/冲突场景（战斗、争吵、谈判、追逐、识破等），不得是纯日常生存流水账（如"数钱、买东西、排队、赶路"）。
8. 每个小节必须有至少 2 个角色出场且有互动（对话/对抗/合作），禁止整节只有主角一个人的独角戏。
9. 开篇小节（第一个细纲）必须有引发事件（inciting incident）——打破主角日常的突发事件，不能只是"介绍主角的生活"。
10. 禁止"说明书式"设定传递——设定必须通过冲突和对话自然展现，不得用大段旁白/角色翻文件/导师讲解。
11. 每个小节必须有至少 1 个反转或意外——事情不能按主角计划顺利进行，必须有波折。

【小节设计指南——基于人类作家写作模式】
每个小节是全局节奏链的一个环节，承担特定叙事功能。小节之间通过"资源-情报-势力"循环相互咬合：猎神/行动收获（资源）→ 转化为交易筹码（情报）→ 兑换为盟友/地位（势力）→ 反哺行动装备/材料（资源）。

小节类型应交替出现，避免单一类型疲劳：
- 行动爆发型：连续战斗/冒险/行动，战力升级高潮
- 智斗博弈型：谈判、识破、收服、政治手腕
- 信息揭示型：发现秘密、世界观揭露、关键情报获取（但不能是整节唯一内容，必须伴随冲突）
- 危机压迫型：暴露风险、多方围堵、被迫反击
- 情感调剂型：温情日常、关系深化、节奏放缓（每卷最多 1 个，不得作为开篇）

【summary 必须包含以下要素】
- 叙事目标：本小节在整个卷中承担什么叙事功能？推进了什么主线？
- 核心场景：发生什么事件？在什么地点？涉及哪些角色？
- 角色动机与行动：主要角色在本小节中的目标是什么？采取了什么行动？遇到了什么阻碍？
- 冲突与转折：本小节的核心冲突是什么？有什么关键转折？转折的因果关系是什么？（转折不在读者预期的时间点发生，而是在几乎遗忘时以意想不到的方式引爆）
- 信息揭示：本小节向读者揭示什么新信息？这些信息如何改变局势？（采用"先抛现象、后揭机制"策略，不一次性倾泻设定）
- 危机线推进：本小节推进了哪些危机线？（同时维持多条危机线交替施压，危机不一次性解决，而是层层叠加互相牵连）
- 小节末状态：本小节结束时，角色和局势处于什么状态？留了什么悬念？

每个小节还包含：
- act：开端/发展/小高潮/转折/大高潮/结局
- strand：主线quest/感情fire/世界观constellation
- key_characters：本小节出场的角色名列表
- emotional_arc：情绪曲线，如"紧张→愤怒→绝望→希望"

请输出 JSON：{{"arcs": [{{"order": 1, "title": "", "summary": "", "act": "", "strand": "quest", "key_characters": [], "emotional_arc": ""}}]}}

【最终检查 — 生成前必须确认】
- 每个小节是否使用了已有世界观设定中的力量体系/地理/势力？
- 出场角色是否与已有角色设定一致（性格、能力、关系）？
- 伏笔推进是否与已有伏笔状态匹配？
- act 是否与蓝图一致？是否有不该出现的大高潮/结局/终章？
确认无误后再输出。"""

            result = await _generate_json_with_repair(
                client, prompt, system=system, max_tokens=128000, root_key="arcs"
            )
            if not result:
                break
            arcs = result.get("arcs") or result.get("sections") or []
            if not arcs:
                break
            # 去重
            seen_titles: set[str] = set()
            unique_arcs: list[dict] = []
            for a in arcs:
                t = _clean_text(a.get("title", "")).strip()
                if t and t in seen_titles:
                    continue
                if t:
                    seen_titles.add(t)
                unique_arcs.append(a)
            # 落库
            for idx, o in enumerate(unique_arcs):
                title = _clean_text(o.get("title", f"小节{idx + 1}"))
                if title in existing_titles:
                    total_skipped += 1
                    continue
                order = _next_arc_order()
                created = repo.create_outline(
                    level="arc",
                    parent_id=req.parent_id,
                    order=order,
                    title=title,
                    summary=_clean_text(o.get("summary", "")),
                    act=_clean_text(o.get("act", "")),
                    strand=_clean_text(o.get("strand", "quest")),
                    key_characters=json.dumps(o.get("key_characters") or [], ensure_ascii=False),
                    emotional_arc=json.dumps(o.get("emotional_arc") or [], ensure_ascii=False),
                )
                existing_titles.add(title)
                all_items.append({
                    "id": created.id, "level": "arc", "parent_id": created.parent_id,
                    "order": created.order, "title": created.title,
                    "summary": created.summary, "act": created.act, "strand": created.strand,
                })

        warning = ""
        if len(all_items) < req.count:
            warning = f"请求生成 {req.count} 个细纲，实际生成 {len(all_items)} 个"
            if total_skipped > 0:
                warning += f"（跳过 {total_skipped} 个与已有重复的）"
            warning += "。可再次点击生成补充。"
        elif batch_no > 1:
            warning = f"已分 {batch_no} 批生成完成，共 {len(all_items)} 个细纲。"
        return GenerateOutlinesResponse(created=len(all_items), items=all_items, warning=warning)
    finally:
        if client is not None:
            await client.close()
        db.close()


@router.post("/chapters/generate", response_model=GenerateOutlinesResponse)
@limiter.limit("10/minute")
async def generate_chapters(request: Request, req: GenerateChaptersRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        arc = repo.get_outline(req.parent_id)
        if not arc or arc.level != "arc":
            raise HTTPException(404, "细纲小节不存在")

        client = LLMClient(cfg.get_agent_llm("outliner"))
        consistency = _build_consistency_constraint(repo, project)

        # 收集已占用 order，新章纲填补空缺（删除后重新生成不会跳号）
        used_orders = {c.order for c in repo.list_outlines(level="chapter")}

        def _next_order() -> int:
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        system = "你是资深网文大纲师，擅长把细纲小节拆成具体章节，每章有明确的叙事目标、场景设计和节奏控制。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》的以下细纲小节生成 {req.count} 个章纲：
小节标题：{arc.title}
小节概要：{arc.summary}

题材：{project.genre}
风格/要求：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

{consistency}

【强制要求】
1. 必须严格生成 {req.count} 个章纲，不多不少。每章标题必须不同，不得重复。
2. 章纲必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的剧情。
3. 章节内容必须与世界观中的力量体系/势力格局/地理设定直接关联。
4. 章纲摘要中必须出现至少 1 个已有角色或势力名称。
5. 如果已有伏笔，需在适当章节安排伏笔的埋设、推进或回收。

【反流水账铁律——违反任何一条即为废稿】
6. 每章必须有至少 2 个角色出场且有对话互动，禁止整章只有主角一个人的独角戏。
7. opening阶段（前3章）每章必须有至少 2 个 beats（1 small + 1 medium），不得只有 1 个 small beat。
8. 爽点必须有主动行为（打脸/反杀/突破/识破/碾压），"被动信息获得"只能作为辅助 beat，不得作为唯一 beat。
9. 每章必须有至少 1 个对抗/冲突场景（战斗、争吵、谈判、追逐、识破等），禁止纯日常流水账（数钱、买东西、排队、赶路、吃饭）。
10. 禁止大段环境描写开头——必须用动作或对话开篇（in media res），环境描写穿插在行动中，不得超过总字数的 15%。
11. 每章必须有至少 1 个反转或意外——事情不能按主角计划顺利进行。

【章节设计指南——基于人类作家写作模式】
每章采用"功能节拍+信息节拍+爽点/悬念节拍"三元结构。每章必留钩子，绝不允许平淡收尾。

章节开篇类型（根据进度选择）：
- 黄金三章（opening阶段）：必须用动作/对话/冲突开篇，借冲突自然带出设定，绝不生硬旁白或环境描写堆砌
- 常规章节：优先使用 in media res（直入行动/对话/思考），减少铺垫，节奏更快
- 视角切换型：偶尔用配角视角开篇，创造信息差（读者比角色知道更多/更少）

章末钩子类型（每章必选其一）：
- 身份/安全威胁型：被识破秘密、暴露危机（制造焦虑，最强钩子）
- 重大发现型：发现珍贵资源/关键情报（制造渴望）
- 反转揭示型：颠覆预期、角色黑暗面暴露
- 悬念型：未解之谜、新危机出现
- 爽点型：战斗碾压、智斗胜利、地位提升（情绪释放）
- 金句型：角色台词/独白收束，用第一人称视角+感叹号/反问

张力维持铁律：
- 同时维持2-3条张力线（身份保密、人际冲突、成长战斗、政治博弈），即使一条线暂时平静，其他线仍在推进
- 主角永远处于 precarious position（金钱不足、暴露边缘、战斗劣势、多方觊觎）
- 每章至少一个 near-miss 或反转（看似安全→危机出现，或看似无望→转机出现）
- 爽感与危机感交替，不让单一情绪持续太久

信息释放策略：
- 信息即用即揭——在角色需要时才揭示相关知识，通过研究/对话/战斗自然传递
- 利用信息差制造戏剧性反讽——读者常常比角色知道更多
- 设定悖论暗示更深真相——某项研究是禁忌→暗示权力在掩盖什么

【summary 必须包含以下要素】
- 核心事件：发生了什么？谁做了什么？因果关系是什么？
- 场景设计：本章的主要场景（地点、时间、氛围），环境描写的重点
- 角色目标与行动：主角本章想达成什么？实际达成了什么？遇到了什么阻碍？
- 信息位：读者本章能获得什么新信息？这些信息如何推进剧情？
- 情绪节奏：开头-中段-结尾的情绪走向
- 章末钩子：本章结尾留什么钩子？属于什么类型？
- 张力线推进：本章推进了哪些张力线？是否有 near-miss 或反转？

每章需要包含约束载荷：
- required_beats: 爽点计划 [{{"tier":"small/medium/large","type":"类型","intensity":1-10,"desc":"具体描述这个爽点的触发和效果"}}]
  - small: 小爽点（信息获得、小胜、化解危机），每章1-2个
  - medium: 中爽点（打脸、反杀、突破、识破、碾压），opening阶段每章至少1个，常规每3章至少1个
  - large: 大爽点（大复仇、大揭秘、大逆袭），每卷1-2个
  - 爽点必须有主动行为，"被动信息获得"只能作为辅助，不得作为唯一beat
  - 爽点放大手法：围观群众震惊反应、具体数字刺激、反差对比、额外收益、幸灾乐祸反衬
- owed_debts: 欠账 [{{"type":"复仇/承诺/秘密/因果","desc":"具体欠什么","pressure":1-5,"term":"short(本卷偿还)/long(跨卷长线)"}}]
- required_hooks: 章末钩 {{"type":"身份威胁/重大发现/反转揭示/悬念/爽点/金句","target_strength":1-10,"desc":"钩子具体内容"}}
- character_focus: 角色重点 [{{"name":"","goal":"本章目标","emotion":"情绪状态","arc_beat":"角色弧光推进点"}}]
  - 配角有独立利益驱动，不是纯工具人
- scene_beats: 场景节拍 [{{"scene":"场景","action":"行动","purpose":"推进什么"}}]
  - 每章2-4个场景节拍，采用三元结构（功能-信息-爽点/悬念）
- emotion_arc: 情感弧线 "{{"start":"开头情绪","end":"结尾情绪","shift":"情绪转变的触发事件"}}"
  - 情绪必须是具体的（如"警惕→震惊→决意"），不要抽象词（如"悲伤→希望"）
- pacing_intent: 节奏意图 "{{"speed":"加速/减速/维持","density":"信息密集/行动密集/情感密集","note":"节奏说明"}}"
  - 加速=短句多、动作快、信息量大；减速=长句多、描写细、情绪深
- theme_progression: 主题推进 "本章在全书主题上推进了什么（一句话）"
- phase: 前3章=opening（黄金三章需特殊设计），上架章=shangjia，其余=regular

每个章纲包含：title、summary、act、strand、required_beats、owed_debts、required_hooks、character_focus、scene_beats、emotion_arc、pacing_intent、theme_progression、phase（章节序号由后端自动分配，无需输出 order）。
请输出 JSON：{{"chapters": [{{"title": "", "summary": "", "act": "", "strand": "quest", "required_beats": [], "owed_debts": [], "required_hooks": {{}}, "character_focus": [], "scene_beats": [], "emotion_arc": {{}}, "pacing_intent": {{}}, "theme_progression": "", "phase": "regular"}}]}}

【最终检查 — 生成前必须确认】
- 每章是否使用了已有世界观设定中的力量体系/地理/势力？
- 角色行为是否与已有角色设定一致（性格、能力、位置、关系）？
- 伏笔的埋设/推进/回收是否与已有伏笔状态匹配？
- 场景地点是否在已有世界观地理设定范围内？
确认无误后再输出。"""

        result = await _generate_json_with_repair(
            client, prompt, system=system, max_tokens=128000, root_key="chapters"
        )
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
        chapters = result.get("chapters") or result.get("chapter_outlines") or []
        if not chapters:
            raise HTTPException(422, "LLM 未返回有效章纲，请检查模型配置或重试")
        # 去重：按标题去重
        seen_titles: set[str] = set()
        unique_chapters: list[dict] = []
        for c in chapters:
            t = _clean_text(c.get("title", "")).strip()
            if t and t in seen_titles:
                continue
            if t:
                seen_titles.add(t)
            unique_chapters.append(c)
        items = []
        for idx, o in enumerate(unique_chapters):
            order = _next_order()
            created = repo.create_outline(
                level="chapter",
                parent_id=req.parent_id,
                order=order,
                title=_clean_text(o.get("title", f"第{order}章")),
                summary=_clean_text(o.get("summary", "")),
                act=_clean_text(o.get("act", "")),
                strand=_clean_text(o.get("strand", "quest")),
                required_beats=json.dumps(o.get("required_beats", []), ensure_ascii=False),
                owed_debts=json.dumps(o.get("owed_debts", []), ensure_ascii=False),
                required_hooks=json.dumps(o.get("required_hooks", {}), ensure_ascii=False),
                character_constraints=json.dumps({
                    "character_focus": o.get("character_focus", []),
                    "scene_beats": o.get("scene_beats", []),
                    "emotion_arc": o.get("emotion_arc", {}),
                    "pacing_intent": o.get("pacing_intent", {}),
                    "theme_progression": o.get("theme_progression", ""),
                }, ensure_ascii=False),
                phase=o.get("phase", "regular"),
            )
            # 同步写入欠账账本
            for d in o.get("owed_debts", []):
                try:
                    repo.create_plot_debt(
                        debt_type=d.get("type", ""),
                        description=_clean_text(d.get("desc", "")),
                        pressure=int(d.get("pressure", 3)),
                        term=d.get("term", "short"),
                        created_chapter=order,
                        status="open",
                    )
                except Exception as e:
                    logger.warning("写入欠账失败: %s", e)
            items.append({
                "id": created.id, "level": "chapter", "parent_id": created.parent_id,
                "order": created.order, "title": created.title,
                "summary": created.summary, "act": created.act, "strand": created.strand,
            })
        warning = ""
        if len(items) < req.count:
            warning = f"目标 {req.count} 章，实际生成 {len(items)} 章。可再次点击生成补充剩余章节（序号会自动填补空缺）。"
        return GenerateOutlinesResponse(created=len(items), items=items, warning=warning)
    finally:
        if client is not None:
            await client.close()
        db.close()


async def _generate_chapters_for_arc(
    *,
    arc, project, repo, client, consistency,
    count: int, prev_context: str, custom_prompt: str,
    next_order_fn,
) -> tuple[list[dict], str, str]:
    """为单个细纲生成章纲（方案B：逐细纲生成）。

    返回 (items, last_tail, warning)：
    - items: 新建章纲列表
    - last_tail: 本细纲最后一章概要，供下一细纲衔接
    - warning: 本细纲生成问题（空串=无问题）
    """
    if count <= 0:
        return [], prev_context, ""

    prev_hint = (
        f"\n\n【前文衔接 — 上一章概要（务必自然承接，不要重复其内容）】\n{prev_context}"
        if prev_context else ""
    )

    system = "你是资深网文大纲师，擅长把细纲小节拆成具体章节，每章有明确的叙事目标、场景设计和节奏控制。只输出 JSON。"
    prompt = f"""请为小说《{project.title}》的以下细纲小节生成 {count} 个章纲（必须正好 {count} 个，不得少）：
小节标题：{arc.title}
小节概要：{arc.summary}

题材：{project.genre}
风格/要求：{project.style}
{custom_prompt and "额外要求：" + custom_prompt}{prev_hint}

{consistency}

【强制要求】
1. 必须严格生成 {count} 个章纲，不多不少。每章标题必须不同，不得重复。
2. 只为上述这一个细纲生成，不要生成属于其他细纲的章节
3. 章纲必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的剧情
4. 章纲摘要中必须出现至少 1 个已有角色或势力名称
5. 如果已有伏笔，需在适当章节安排伏笔的埋设、推进或回收
6. 若提供了前文衔接，本章必须自然承接前文，不得重复前文已发生的事件

【章节设计指南】
每章采用"功能节拍+信息节拍+爽点/悬念节拍"三元结构。每章必留钩子，绝不允许平淡收尾。
章末钩子类型：身份/安全威胁型、重大发现型、反转揭示型、悬念型、爽点型、金句型。

【summary 必须包含】
- 核心事件、场景设计、角色目标与行动、信息位、情绪节奏、章末钩子、张力线推进

每章需要包含约束载荷：
- required_beats: 爽点计划 [{{"tier":"small/medium/large","type":"类型","intensity":1-10,"desc":"描述"}}]
- owed_debts: 欠账 [{{"type":"复仇/承诺/秘密/因果","desc":"具体欠什么","pressure":1-5,"term":"short/long"}}]
- required_hooks: 章末钩 {{"type":"类型","target_strength":1-10,"desc":"钩子内容"}}
- character_focus: 角色重点 [{{"name":"","goal":"本章目标","emotion":"情绪","arc_beat":"弧光推进点"}}]
- scene_beats: 场景节拍 [{{"scene":"场景","action":"行动","purpose":"推进什么"}}]
- emotion_arc: 情感弧线 "{{"start":"开头情绪","end":"结尾情绪","shift":"触发事件"}}"
- pacing_intent: 节奏意图 "{{"speed":"加速/减速/维持","density":"信息/行动/情感密集","note":"说明"}}"
- theme_progression: 主题推进 "一句话"
- phase: 前3章=opening，上架章=shangjia，其余=regular

每个章纲包含：title、summary、act、strand、required_beats、owed_debts、required_hooks、character_focus、scene_beats、emotion_arc、pacing_intent、theme_progression、phase（章节序号由后端自动分配，无需输出 order）。
请输出 JSON：{{"chapters": [{{"title": "", "summary": "", "act": "", "strand": "quest", "required_beats": [], "owed_debts": [], "required_hooks": {{}}, "character_focus": [], "scene_beats": [], "emotion_arc": {{}}, "pacing_intent": {{}}, "theme_progression": "", "phase": "regular"}}]}}"""

    try:
        result = await _generate_json_with_repair(
            client, prompt, system=system, max_tokens=128000, root_key="chapters"
        )
    except Exception as e:
        return [], prev_context, f"细纲《{arc.title}》LLM 调用失败：{e}"

    if not result:
        return [], prev_context, f"细纲《{arc.title}》返回 JSON 无法解析"

    chapters = result.get("chapters") or result.get("chapter_outlines") or []
    if not chapters:
        return [], prev_context, f"细纲《{arc.title}》未返回有效章纲"

    items: list[dict] = []
    last_tail = prev_context
    for o in chapters:
        if len(items) >= count:
            break
        order = next_order_fn()
        created = repo.create_outline(
            level="chapter",
            parent_id=arc.id,
            order=order,
            title=_clean_text(o.get("title", f"第{order}章")),
            summary=_clean_text(o.get("summary", "")),
            act=_clean_text(o.get("act", "")),
            strand=_clean_text(o.get("strand", "quest")),
            required_beats=json.dumps(o.get("required_beats", []), ensure_ascii=False),
            owed_debts=json.dumps(o.get("owed_debts", []), ensure_ascii=False),
            required_hooks=json.dumps(o.get("required_hooks", {}), ensure_ascii=False),
            character_constraints=json.dumps({
                "character_focus": o.get("character_focus", []),
                "scene_beats": o.get("scene_beats", []),
                "emotion_arc": o.get("emotion_arc", {}),
                "pacing_intent": o.get("pacing_intent", {}),
                "theme_progression": o.get("theme_progression", ""),
            }, ensure_ascii=False),
            phase=o.get("phase", "regular"),
        )
        for d in o.get("owed_debts", []):
            try:
                repo.create_plot_debt(
                    debt_type=d.get("type", ""),
                    description=_clean_text(d.get("desc", "")),
                    pressure=int(d.get("pressure", 3)),
                    term=d.get("term", "short"),
                    created_chapter=order,
                    status="open",
                )
            except Exception as e:
                logger.warning("写入欠账失败: %s", e)
        items.append({
            "id": created.id, "level": "chapter", "parent_id": created.parent_id,
            "order": created.order, "title": created.title,
            "summary": created.summary, "act": created.act, "strand": created.strand,
        })
        last_tail = f"第{order}章《{created.title}》：{created.summary}"

    warn = ""
    if len(items) < count:
        warn = f"细纲《{arc.title}》目标 {count} 章，实际 {len(items)} 章"
    return items, last_tail, warn


@router.post("/chapters/generate-by-volume", response_model=GenerateOutlinesResponse)
@limiter.limit("10/minute")
async def generate_chapters_by_volume(request: Request, req: GenerateChaptersByVolumeRequest):
    """按卷纲生成章纲（方案B：逐细纲生成 + 卷级统筹调度）。

    遍历该卷所有细纲，对每个细纲单独调用单细纲生成逻辑，
    通过 prev_context 传递前序章节概要实现跨细纲衔接。

    与旧逻辑的区别：
    - 旧：一次性把全部细纲喂给 LLM 统筹，长上下文下 LLM 易跑偏、漏细纲、内容乱
    - 新：逐细纲生成，LLM 每次只看 1 个细纲 + 前序概要，遵循度高，不可能漏细纲
    - parent_id 直接用当前细纲 id，不再按比例分配，章纲不会挂错细纲
    - 单细纲失败不中断整卷，记录 warning 继续下一细纲
    """
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        volume = repo.get_outline(req.volume_id)
        if not volume or volume.level != "volume":
            raise HTTPException(404, "卷级大纲不存在")

        arcs = repo.list_outlines(level="arc", parent_id=req.volume_id)
        if not arcs:
            raise HTTPException(400, "该卷下没有细纲，请先生成细纲")

        arcs_sorted = sorted(arcs, key=lambda x: x.order)
        n_arcs = len(arcs_sorted)
        arc_id_set = {a.id for a in arcs_sorted}

        client = LLMClient(cfg.get_agent_llm("outliner"))
        consistency = _build_consistency_constraint(repo, project)

        # 收集已占用 order，新章纲填补空缺（删除后重新生成不会跳号）
        used_orders = {c.order for c in repo.list_outlines(level="chapter")}

        def _next_order() -> int:
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        # 已有章纲按细纲分组（续生成场景）
        existing_by_arc: dict[int, list] = {}
        for c in repo.list_outlines(level="chapter"):
            if c.parent_id in arc_id_set:
                existing_by_arc.setdefault(c.parent_id, []).append(c)

        # 分摊目标章数到各细纲
        target_count = req.count if req.count > 0 else n_arcs * 4
        base = max(1, target_count // n_arcs)
        remainder = target_count - base * n_arcs

        arc_targets = []
        for i, arc in enumerate(arcs_sorted):
            target = base + (1 if i < remainder else 0)
            existing_count = len(existing_by_arc.get(arc.id, []))
            need = max(0, target - existing_count)
            arc_targets.append((arc, target, existing_count, need))

        total_need = sum(need for _, _, _, need in arc_targets)
        if total_need == 0:
            return GenerateOutlinesResponse(
                created=0, items=[],
                warning=f"所有细纲均已达到目标章数（共 {target_count} 章），无需生成。"
            )

        # 初始化 prev_context：续生成时取已生成最后一章概要
        prev_context = ""
        existing_all = [c for cs in existing_by_arc.values() for c in cs]
        if existing_all:
            existing_sorted = sorted(existing_all, key=lambda x: x.order)
            last = existing_sorted[-1]
            prev_context = f"第{last.order}章《{last.title}》：{last.summary}"

        # 遍历细纲逐个生成
        all_items: list[dict] = []
        warnings: list[str] = []

        for arc, target, existing_count, need in arc_targets:
            if need <= 0:
                # 该细纲已足够，更新 prev_context 到该细纲最后一章
                arc_chapters = sorted(existing_by_arc.get(arc.id, []), key=lambda x: x.order)
                if arc_chapters:
                    last = arc_chapters[-1]
                    prev_context = f"第{last.order}章《{last.title}》：{last.summary}"
                continue

            items, last_tail, warn = await _generate_chapters_for_arc(
                arc=arc, project=project, repo=repo, client=client,
                consistency=consistency, count=need, prev_context=prev_context,
                custom_prompt=req.custom_prompt, next_order_fn=_next_order,
            )
            all_items.extend(items)
            if last_tail:
                prev_context = last_tail
            if warn:
                warnings.append(warn)

        # 构建 warning
        warning_parts = []
        if len(all_items) < total_need:
            warning_parts.append(
                f"目标 {total_need} 章，实际生成 {len(all_items)} 章。"
            )
        if warnings:
            warning_parts.append("未达目标细纲：" + "；".join(warnings) + "。")
        if warnings and not all_items:
            warning_parts.append("可再次点击生成补充剩余章节（序号会自动填补空缺）。")

        warning = " ".join(warning_parts)
        return GenerateOutlinesResponse(created=len(all_items), items=all_items, warning=warning)
    finally:
        if client is not None:
            await client.close()
        db.close()


@router.post("/outlines/generate", response_model=GenerateOutlinesResponse)
@limiter.limit("10/minute")
async def generate_outlines(request: Request, req: GenerateOutlinesRequest):
    """统一的大纲生成入口：根据 level 自动委托到卷/弧/章生成。"""
    if req.level == "volume":
        return await generate_volumes(request, GenerateVolumesRequest(
            project_id=req.project_id, count=req.count, custom_prompt=req.custom_prompt))
    if req.level == "arc":
        if req.parent_id is None:
            raise HTTPException(400, "生成细纲需要提供 parent_id（卷级大纲 id）")
        return await generate_arcs(request, GenerateArcsRequest(
            project_id=req.project_id, parent_id=req.parent_id,
            count=req.count, custom_prompt=req.custom_prompt))
    if req.level == "chapter":
        if req.parent_id is None:
            raise HTTPException(400, "生成章纲需要提供 parent_id（细纲 id）")
        return await generate_chapters(request, GenerateChaptersRequest(
            project_id=req.project_id, parent_id=req.parent_id,
            count=req.count, custom_prompt=req.custom_prompt))
    raise HTTPException(400, f"不支持的 level：{req.level}，必须是 volume/arc/chapter")


class EnrichOutlineRequest(BaseModel):
    project_id: int
    outline_id: int
    custom_prompt: str = ""


@router.post("/outlines/enrich")
@limiter.limit("10/minute")
async def enrich_outline(request: Request, req: EnrichOutlineRequest):
    """丰富单条大纲内容：对已有大纲的 summary 进行扩写和结构化补充。"""
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        outline = repo.get_outline(req.outline_id)
        if not outline:
            raise HTTPException(404, "大纲不存在")

        consistency = _build_consistency_constraint(repo, project)
        client = LLMClient(cfg.get_agent_llm("outliner"))

        # 获取同级上下文（前后大纲）
        siblings = repo.list_outlines(level=outline.level, parent_id=outline.parent_id)
        prev_sibling = next((s for s in siblings if s.order == outline.order - 1), None)
        next_sibling = next((s for s in siblings if s.order == outline.order + 1), None)
        # 获取子级上下文（如果是卷/弧）
        children = repo.list_outlines(parent_id=outline.id) if outline.level in ("volume", "arc") else []

        context_parts = []
        if prev_sibling:
            context_parts.append(f"【前一条大纲】{prev_sibling.title}：{prev_sibling.summary}")
        if next_sibling:
            context_parts.append(f"【后一条大纲】{next_sibling.title}：{next_sibling.summary}")
        if children:
            child_text = "\n".join(f"- {c.title}：{c.summary}" for c in children[:10])
            context_parts.append(f"【已有子级大纲】\n{child_text}")
        sibling_context = "\n".join(context_parts) if context_parts else "无同级上下文"

        level_name = {"volume": "卷", "arc": "细纲小节", "chapter": "章纲"}[outline.level]

        system = "你是资深网文大纲师，擅长扩写和丰富大纲内容，使其具备可执行性和创作指导价值。只输出 JSON。"

        if outline.level == "chapter":
            prompt = f"""请丰富以下{level_name}的内容，使其能充分指导正文写作。

原始大纲：
- 标题：{outline.title}
- 摘要：{outline.summary}
- act：{outline.act}
- strand：{outline.strand}

{sibling_context}

题材：{project.genre}
风格：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

{consistency}

【丰富要求】
请扩写 summary，必须包含：
- 核心事件：发生了什么？谁做了什么？因果关系是什么？
- 场景设计：本章的主要场景（地点、时间、氛围），环境描写的重点
- 角色目标与行动：主角本章想达成什么？实际达成了什么？遇到了什么阻碍？
- 信息位：读者本章能获得什么新信息？这些信息如何推进剧情？
- 情绪节奏：开头-中段-结尾的情绪走向
- 章末钩子：本章结尾留什么钩子？属于什么类型？
- 张力线推进：本章推进了哪些张力线？是否有 near-miss 或反转？

同时补充约束载荷：
- required_beats: 爽点计划 [{{"tier":"small/medium/large","type":"类型","intensity":1-10,"desc":"具体描述"}}]
- owed_debts: 欠账 [{{"type":"类型","desc":"具体内容","pressure":1-5,"term":"short/long"}}]
- required_hooks: 章末钩 {{"type":"悬念/反转/危机/揭秘","target_strength":1-10,"desc":"钩子内容"}}
- character_focus: 角色重点 [{{"name":"","goal":"","emotion":"","arc_beat":"角色弧光推进点"}}]
- scene_beats: 场景节拍 [{{"scene":"","action":"","purpose":"推进什么"}}]
- emotion_arc: 情感弧线 {{"start":"","end":"","shift":""}}
- pacing_intent: 节奏意图 {{"speed":"","density":"","note":""}}
- theme_progression: 主题推进（一句话）

请输出 JSON：{{"summary": "扩写后的摘要", "required_beats": [], "owed_debts": [], "required_hooks": {{}}, "character_focus": [], "scene_beats": [], "emotion_arc": {{}}, "pacing_intent": {{}}, "theme_progression": ""}}"""
        elif outline.level == "arc":
            prompt = f"""请丰富以下{level_name}的内容，使其具备完整的戏剧弧线。

原始大纲：
- 标题：{outline.title}
- 摘要：{outline.summary}
- act：{outline.act}
- strand：{outline.strand}

{sibling_context}

题材：{project.genre}
风格：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

{consistency}

【丰富要求】
请扩写 summary，必须包含：
- 叙事目标：本小节在整卷中承担什么叙事功能？
- 核心场景：发生什么事件？在什么地点？涉及哪些角色？
- 角色动机与行动：主要角色的目标、行动、阻碍
- 冲突与转折：核心冲突是什么？关键转折的因果关系
- 信息揭示：向读者揭示什么新信息？如何改变局势？
- 危机线推进：本小节推进了哪些危机线？
- 小节末状态：结束时角色和局势的状态，留下什么悬念

同时补充：
- key_characters: 出场角色名列表
- emotional_arc: 情绪曲线，如"紧张→愤怒→绝望→希望"

请输出 JSON：{{"summary": "扩写后的摘要", "key_characters": [], "emotional_arc": ""}}"""
        else:
            prompt = f"""请丰富以下{level_name}的内容，使其具备完整的卷级规划。

原始大纲：
- 标题：{outline.title}
- 摘要：{outline.summary}
- act：{outline.act}

{sibling_context}

题材：{project.genre}
风格：{project.style}
{req.custom_prompt and "额外要求：" + req.custom_prompt}

{consistency}

【丰富要求】
请扩写 summary，必须包含：
- 核心冲突：本卷的主要矛盾，谁与谁的冲突，冲突根源
- 剧情主线：从什么状态开始，经历什么转折，到达什么结局
- 角色弧光：主要角色的成长变化，目标和动机的演变
- 世界观推进：揭示世界观的哪些新层面，力量体系/势力格局的变化
- 伏笔布局：埋设和回收哪些伏笔，区分短中长三层
- 节奏段划分：本卷的节奏段如何安排
- 卷末钩子：结尾留下什么悬念

同时补充：
- key_events: 2-4个关键事件 [{{"event":"","cause":"","effect":""}}]
- foreshadow_plan: 伏笔计划 [{{"action":"plant/advance/resolve","description":""}}]

请输出 JSON：{{"summary": "扩写后的摘要", "key_events": [], "foreshadow_plan": []}}"""

        result = await _generate_json_with_repair(client, prompt, system=system)
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")

        # 更新大纲
        update_kwargs = {}
        if "summary" in result:
            update_kwargs["summary"] = _clean_text(result["summary"])
        if outline.level == "chapter":
            if "required_beats" in result:
                update_kwargs["required_beats"] = json.dumps(result["required_beats"], ensure_ascii=False)
            if "owed_debts" in result:
                update_kwargs["owed_debts"] = json.dumps(result["owed_debts"], ensure_ascii=False)
            if "required_hooks" in result:
                update_kwargs["required_hooks"] = json.dumps(result["required_hooks"], ensure_ascii=False)
            if "character_focus" in result or "scene_beats" in result:
                existing_cc = {}
                try:
                    if outline.character_constraints:
                        existing_cc = json.loads(outline.character_constraints)
                except Exception as e:
                    logger.warning("解析角色约束JSON失败: %s", e)
                if "character_focus" in result:
                    existing_cc["character_focus"] = result["character_focus"]
                if "scene_beats" in result:
                    existing_cc["scene_beats"] = result["scene_beats"]
                if "emotion_arc" in result:
                    existing_cc["emotion_arc"] = result["emotion_arc"]
                if "pacing_intent" in result:
                    existing_cc["pacing_intent"] = result["pacing_intent"]
                if "theme_progression" in result:
                    existing_cc["theme_progression"] = result["theme_progression"]
                update_kwargs["character_constraints"] = json.dumps(existing_cc, ensure_ascii=False)

        # B4：扩写不再只更新 summary——卷纲 key_events、细纲 key_characters/emotional_arc 一并落库
        if "key_events" in result and outline.level == "volume":
            update_kwargs["key_events"] = json.dumps(result["key_events"], ensure_ascii=False)
        if "key_characters" in result and outline.level == "arc":
            update_kwargs["key_characters"] = json.dumps(result["key_characters"], ensure_ascii=False)
        if "emotional_arc" in result and outline.level == "arc":
            update_kwargs["emotional_arc"] = json.dumps(result["emotional_arc"], ensure_ascii=False)

        if update_kwargs:
            repo.update_outline(outline.id, **update_kwargs)

        # P0#7：章纲 new_foreshadows / 卷纲 foreshadow_plan 落库到 ForeshadowImplant
        _save_foreshadow_plans(
            repo,
            result.get("new_foreshadows") or result.get("foreshadow_plan") or [],
            default_chapter=outline.order if outline.level == "chapter" else 0,
        )

        updated = repo.get_outline(outline.id)
        return {
            "ok": True,
            "outline_id": outline.id,
            "updated_fields": list(update_kwargs.keys()),
            "summary": updated.summary,
        }
    finally:
        if client is not None:
            await client.close()
        db.close()


# ---- 章节写作一致性系统（学习 webnovel-writer 架构，自主实现） ----

class ChapterBriefRequest(BaseModel):
    project_id: int
    chapter: int
    title: str = ""


class ChapterBriefSaveRequest(BaseModel):
    project_id: int
    chapter: int
    title: str = ""
    brief: dict
    brief_text: str = ""
    context_stats: dict = {}


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


def _build_memory_pack(repo, project, chapter, cfg):
    """构建记忆包：复用 CoreMemoryAssembler 保证上下文一致性。"""
    from novel_agent.memory.core import CoreMemoryAssembler
    assembler = CoreMemoryAssembler(repo, archival=None)  # brief 不走 archival
    working = assembler.assemble(chapter=chapter, max_chars=6000)
    # brief 特有：章纲详细信息
    outline = next((o for o in repo.list_outlines(level="chapter") if o.order == chapter), None)
    episodic = f"第{chapter}章《{outline.title}》：{outline.summary}" if outline else ""
    # semantic: 项目级信息
    semantic = f"《{project.title}》{project.genre}：{project.summary}"
    return {"working": working, "episodic": episodic, "semantic": semantic}


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
@limiter.limit("10/minute")
async def generate_chapter_brief(request: Request, req: ChapterBriefRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        cg = canonical_genre(project.genre)
        outlines = repo.list_outlines(level="chapter")
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

        client = LLMClient(cfg.get_agent_llm("outliner"))
        brief_dict = await _generate_json_with_repair(
            client,
            prompt,
            system="你是网文Context Agent，擅长加载上下文并输出结构化五段写作任务书。只输出JSON。",
        )
        await client.close()
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
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning("LLM client关闭失败: %s", e)
        db.close()


@router.post("/chapter/brief/save")
def save_chapter_brief(req: ChapterBriefSaveRequest):
    """保存章节任务书到项目目录。"""
    cfg = load_config()
    brief_dir = cfg.project_dir(req.project_id) / "briefs"
    brief_dir.mkdir(parents=True, exist_ok=True)
    import json
    data = {
        "chapter": req.chapter,
        "title": req.title,
        "brief": req.brief,
        "brief_text": req.brief_text,
        "context_stats": req.context_stats,
    }
    filepath = brief_dir / f"chapter_{req.chapter:03d}.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "chapter": req.chapter, "path": str(filepath)}


@router.get("/chapter/brief")
def get_chapter_brief(project_id: int, chapter: int):
    """读取已保存的章节任务书。"""
    cfg = load_config()
    brief_path = cfg.project_dir(project_id) / "briefs" / f"chapter_{chapter:03d}.json"
    if not brief_path.exists():
        raise HTTPException(404, f"第{chapter}章任务书未保存")
    import json
    data = json.loads(brief_path.read_text(encoding="utf-8"))
    return data


@router.post("/chapter/review")
async def review_chapter(req: ChapterReviewRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        recall = RecallMemory(cfg, project_id=req.project_id)
        text = recall.read_chapter_text(req.chapter)
        if not text:
            raise HTTPException(404, "章节正文不存在")

        outlines = repo.list_outlines(level="chapter")
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
            "stakes": "检查高潮赌注递进是否合理：本章/本卷高潮赌注等级（个人→团队→体系→区域→世界存亡）相较上一卷/上一高潮是否跳级超过一级或倒退；跳级过大或倒退则 blocking=true, severity=critical。",
            "constraints": "检查章节是否违反【全书铁律】/【立意禁忌】/【角色绝对禁令】/【世界设定】。任一违反则 blocking=true, severity=critical。",
        }
        dimension_text = "\n".join([f"{k}: {v}" for k, v in dimension_rules.items()])

        # 裁决规则
        adjudication = ReferenceSearch().adjudication_rules(cg)
        adjudication_text = "\n".join([f"- {r.get('关键词', '')}: {r.get('核心摘要', '')}" for r in adjudication[:5]])

        # 显式注入禁令上下文，保证 constraints 维度有据可查（即使 working_memory 被预算截断也不丢）
        constraints_parts = []
        if getattr(project, 'constitution', ''):
            constraints_parts.append(f"【全书铁律（绝对不得违反）】\n{project.constitution}")
        if getattr(project, 'golden_finger', ''):
            try:
                gf = json.loads(project.golden_finger) if isinstance(project.golden_finger, str) else project.golden_finger
                gf_text = gf if isinstance(gf, str) else json.dumps(gf, ensure_ascii=False)
                constraints_parts.append(f"【金手指设定（必须遵守其机制/限制/代价）】\n{gf_text}")
            except Exception:
                constraints_parts.append(f"【金手指设定（必须遵守其机制/限制/代价）】\n{project.golden_finger}")
        if getattr(project, 'central_concept', ''):
            try:
                concept = json.loads(project.central_concept) if isinstance(project.central_concept, str) else project.central_concept
                taboos = concept.get('taboos', []) if isinstance(concept, dict) else []
                taboos_list = taboos if isinstance(taboos, list) else ([taboos] if taboos else [])
                taboos_text = ', '.join(str(t) for t in taboos_list) if taboos_list else '无'
                constraints_parts.append(f"【立意禁忌（违反则废稿）】\n{taboos_text}")
            except Exception:
                constraints_parts.append(f"【立意】\n{project.central_concept}")
        constraints_block = "\n\n".join(constraints_parts)
        if constraints_block:
            pack["working"] = pack["working"] + "\n\n" + constraints_block

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

        client = LLMClient(cfg.get_agent_llm("auditor"))
        result = await _generate_json_with_repair(
            client, prompt, system="你是网文Reviewer Agent，只做事实一致性审查，只输出JSON。"
        )
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
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


async def chapter_postprocess(
    repo,
    cfg,
    chapter: int,
    content: str,
    title: str = "",
    client: LLMClient | None = None,
    *,
    write_summary: bool = False,
    write_char_state: bool = False,
    index: bool = True,
) -> dict:
    """统一「章节后处理」钩子（阶段0核心，计划书 P0#1/#2 + P1#8/#10/#11）。

    正文落库后自动补齐数据闭环：
      1. Data Agent 提取事实（复用 commit 的提取/自修复逻辑）
      2. 出场记录 EntityAppearance：角色/势力/怪物（幂等，先删本章再写）
      3. 关系落库：角色关系表 + 关系变更表（applier 内已补写，不再只写事件流）
      4. 新实体/世界观/伏笔更新/事件 → DeltaApplier 落库
      5. （可选）章节摘要 / 角色状态（summarize_chapter 已写时传 False 防双写）
      6. （可选）Archival 索引供语义检索

    幂等性：出场记录按章重写；新实体/世界观按名字去重；伏笔状态重复置位无害。
    """
    from novel_agent.memory.archival import ArchivalMemory
    from novel_agent.protocol.applier import DeltaApplier

    own_client = client is None
    if own_client:
        client = LLMClient(cfg.get_agent_llm("summarizer"))
    try:
        # ---- 1. Data Agent 提取 ----
        prompt = (
            "从以下正文中提取所有结构化事实，只输出 JSON，不要解释：\n"
            "{\n"
            ' "summary": "100字内核心剧情摘要",\n'
            ' "state_deltas": [{"entity": "角色", "entity_id": "名字", "field": "current_location|current_emotion|known_info", "old_value": "", "new_value": ""}],\n'
            ' "relationships": [{"character_a": "A", "character_b": "B", "relation": "师徒", "strength": 5, "description": "变化说明"}],\n'
            ' "events": [{"event_type": "剧情|战斗|相遇|离别|其他", "subject": "谁", "description": "发生了什么"}],\n'
            ' "foreshadow_updates": [{"foreshadow_id": "伏笔名", "status": "planted|developing|resolved"}],\n'
            ' "new_characters": [{"name": "", "role": "配角", "appearance": "", "personality": "", "motivation": "", "current_location": ""}],\n'
            ' "new_factions": [{"name": "", "type": "其他", "description": "", "goals": ""}],\n'
            ' "new_monsters": [{"name": "", "species": "", "rank": "普通", "description": "", "habitats": ""}],\n'
            ' "new_world_settings": [{"category": "力量体系|地理|势力|文化|其他", "title": "", "content": ""}]\n'
            "}\n\n"
            f"【正文】\n{content}\n\n只输出 JSON。"
        )
        result = await _generate_json_with_repair(
            client, prompt,
            system="你是小说事实提取器（Data Agent），从正文中提取所有结构化事实：出场角色、新角色、新组织、新怪物、新世界观设定、状态变更、关系、事件、伏笔更新。只输出 JSON。",
        )
        if not isinstance(result, dict):
            return {"chapter": chapter, "ok": False, "error": "LLM 返回无法解析为有效 JSON"}

        state_deltas = result.get("state_deltas") or []
        relationships = result.get("relationships") or []
        events = result.get("events") or []
        fore_updates = result.get("foreshadow_updates") or []
        new_characters = result.get("new_characters") or []
        new_factions = result.get("new_factions") or []
        new_monsters = result.get("new_monsters") or []
        new_world_settings = result.get("new_world_settings") or []

        applier = DeltaApplier(repo, archival=None)

        # ---- 2. 出场记录（P0#1：全链路自动写入） ----
        appearances = []
        names: set[str] = set()
        for s in state_deltas:
            if s.get("entity_id") and str(s.get("entity_type") or s.get("entity") or "").strip() in ("角色", "character"):
                names.add(str(s["entity_id"]).strip())
        for c in new_characters:
            if c.get("name"):
                names.add(str(c["name"]).strip())
        for n in sorted(names):
            appearances.append({"entity_type": "character", "entity_id": n, "chapter": chapter})
        for f in new_factions:
            if f.get("name"):
                appearances.append({"entity_type": "faction", "entity_id": str(f["name"]).strip(), "chapter": chapter})
        for m in new_monsters:
            if m.get("name"):
                appearances.append({"entity_type": "monster", "entity_id": str(m["name"]).strip(), "chapter": chapter})
        if appearances:
            repo.record_appearances(chapter, appearances)

        # ---- 3/4. 关系/新实体/事件/伏笔/世界观 → DeltaApplier 落库 ----
        delta_list = []
        if write_char_state:
            delta_list += [{"type": "state_change", **s, "chapter": chapter} for s in state_deltas]
        delta_list += [{"type": "relationship_update", **r, "chapter": chapter} for r in relationships]
        delta_list += [
            {"type": "event", "event_type": e.get("event_type", "剧情"), "subject": e.get("subject", ""),
             "payload": e.get("payload") or {"description": e.get("description", "")}, "chapter": chapter}
            for e in events
        ]
        delta_list += [
            {"type": "foreshadow_update", "foreshadow_id": f.get("foreshadow_id", ""),
             "status": f.get("status", "planted"), "chapter": chapter}
            for f in fore_updates
        ]
        delta_list += [_build_create_delta(c, chapter, "character_create") for c in new_characters]
        delta_list += [_build_create_delta(f, chapter, "faction_create", rename_type="faction_type") for f in new_factions]
        delta_list += [_build_create_delta(m, chapter, "monster_create") for m in new_monsters]
        delta_list += [_build_create_delta(w, chapter, "world_setting_create") for w in new_world_settings]
        if delta_list:
            applier.apply_deltas(delta_list, chapter=chapter)

        # ---- 5. 摘要（可选） ----
        if write_summary:
            summary_text = _clean_text(result.get("summary", "")) or content[:200]
            repo.create_or_update_chapter_summary(
                chapter=chapter, title=title or f"第{chapter}章",
                core_events=summary_text,
                characters_present=", ".join(sorted(names)),
                word_count=count_chinese_chars(content),
            )

        # ---- 6. 索引（可选） ----
        archived = False
        if index:
            try:
                archival = ArchivalMemory(cfg, project_id=repo.project_id)
                archival.index_chapter(chapter, title or f"第{chapter}章", content)
                archived = True
            except Exception as e:
                logger.warning("chapter_postprocess: archival 索引失败: %s", e)

        return {
            "chapter": chapter, "ok": True, "archived": archived,
            "appearances": len(appearances),
            "relationships": len(relationships),
            "events": len(events),
            "foreshadow_updates": len(fore_updates),
            "new_characters": len(new_characters),
            "new_factions": len(new_factions),
            "new_monsters": len(new_monsters),
            "new_world_settings": len(new_world_settings),
        }
    finally:
        if own_client and client is not None:
            try:
                await client.close()
            except Exception:
                pass


@router.post("/chapter/commit")
@limiter.limit("10/minute")
async def commit_chapter(request: Request, req: ChapterCommitRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        recall = RecallMemory(cfg, project_id=req.project_id)
        text = recall.read_chapter_text(req.chapter)
        if not text:
            raise HTTPException(404, "章节正文不存在")

        # 只匹配章级大纲（volume/arc 的 order 与章号同数字空间，不过滤会错配"第N卷/第N弧"）
        outlines = repo.list_outlines(level="chapter")
        outline = next((o for o in outlines if o.order == req.chapter), None)
        # 交互式创作模式可能没有大纲，从章节文件提取标题
        if outline:
            outline_order = outline.order
            outline_title = outline.title
            outline_summary = outline.summary or ""
        else:
            outline_order = req.chapter
            _title_match = re.search(r"^#\s*第\d+章\s+(.+)$", text, re.MULTILINE)
            outline_title = _title_match.group(1).strip() if _title_match else f"第{req.chapter}章"
            outline_summary = "（交互式创作，无章纲约束）"
        cg = canonical_genre(project.genre)
        pack = _build_memory_pack(repo, project, req.chapter, cfg)

        prompt = PromptLoader().render(
            "commit",
            title=project.title,
            genre=project.genre,
            canonical_genre=cg,
            chapter=req.chapter,
            outline_order=outline_order,
            outline_title=outline_title,
            outline_summary=outline_summary,
            working_memory=pack["working"],
            episodic_memory=pack["episodic"],
            semantic_memory=pack["semantic"],
            chapter_text=text,
        )

        client = LLMClient(cfg.get_agent_llm("summarizer"))
        result = await _generate_json_with_repair(
            client, prompt, system="你是小说事实提取器（Data Agent），从正文中提取所有结构化事实：新角色、新组织、新怪物、新世界观设定、状态变更、关系、事件、伏笔更新。只输出 JSON。"
        )
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
        summary = _clean_text(result.get("summary", ""))
        deltas = result.get("state_deltas", [])
        relationships = result.get("relationships", [])
        events = result.get("events", [])
        fore_updates = result.get("foreshadow_updates", [])
        new_characters = result.get("new_characters", [])
        new_factions = result.get("new_factions", [])
        new_monsters = result.get("new_monsters", [])
        new_world_settings = result.get("new_world_settings", [])

        # 构造统一 deltas，改走 DeltaApplier 保证数据流闭环
        applier = DeltaApplier(repo, archival=None)
        delta_list = []
        delta_list += [{"type": "state_change", **s} for s in deltas]
        delta_list += [{"type": "relationship_update", **r} for r in relationships]
        delta_list += [
            {
                "type": "event",
                "event_type": e.get("event_type", "剧情"),
                "subject": e.get("subject", ""),
                "payload": e.get("payload", {}),
                "chapter": req.chapter,
            }
            for e in events
        ]
        delta_list += [
            {
                "type": "foreshadow_update",
                "foreshadow_id": f.get("foreshadow_id", ""),
                "status": f.get("status", "planted"),
                "chapter": req.chapter,
            }
            for f in fore_updates
        ]
        delta_list += [_build_create_delta(c, req.chapter, "character_create") for c in new_characters]
        delta_list += [_build_create_delta(f, req.chapter, "faction_create", rename_type="faction_type") for f in new_factions]
        delta_list += [_build_create_delta(m, req.chapter, "monster_create") for m in new_monsters]
        delta_list += [_build_create_delta(w, req.chapter, "world_setting_create") for w in new_world_settings]
        delta_list.append(
            {
                "type": "chapter_commit",
                "chapter": req.chapter,
                "title": outline_title,
                "summary": summary,
                "word_count": len(text),
            }
        )

        # A4+A5: commit 前确定性校验——防止幻觉事实直写圣经
        validation_issues = []
        existing_chars = {c.name for c in repo.list_characters()}
        existing_fores = {f.foreshadow_id for f in repo.list_foreshadows()}

        # 校验新角色名不与已有角色重复
        for c in new_characters:
            name = c.get("name", "")
            if name and name in existing_chars:
                validation_issues.append({"severity": "critical",
                    "message": f"新角色'{name}'已存在，Data Agent可能误提取已有角色为新角色"})

        # 校验伏笔ID存在（planted状态可能是首次埋设，不校验；resolved/developing必须已存在）
        for f in fore_updates:
            fid = f.get("foreshadow_id", "")
            status = f.get("status", "")
            if fid and status in ("resolved", "developing") and fid not in existing_fores:
                validation_issues.append({"severity": "critical",
                    "message": f"伏笔'{fid}'不存在但状态为{status}，Data Agent可能捏造了伏笔ID"})

        # 校验state_change引用的角色存在
        for s in deltas:
            entity_id = s.get("entity_id", "")
            if entity_id and entity_id not in existing_chars:
                validation_issues.append({"severity": "important",
                    "message": f"状态变更引用角色'{entity_id}'不存在"})

        # 校验state_change的old_value与数据库当前值一致性（防LLM幻觉篡改既有状态）
        # 仅对角色的 current_location/current_emotion 检查；known_info 是累积字段跳过
        for s in deltas:
            entity_type = s.get("entity_type") or s.get("entity", "")
            entity_id = s.get("entity_id", "")
            field = s.get("field", "")
            old_value = str(s.get("old_value") if "old_value" in s else s.get("old", "")).strip()
            if (entity_type in ("角色", "character") and entity_id
                    and field in ("current_location", "current_emotion") and old_value):
                try:
                    char = repo.get_character(entity_id)
                except Exception:
                    char = None
                if char:
                    current_val = str(getattr(char, field, "") or "").strip()
                    # 互为子串视为一致（容忍LLM只提取关键部分）；空值不校验
                    if (current_val
                            and old_value.lower() not in current_val.lower()
                            and current_val.lower() not in old_value.lower()):
                        validation_issues.append({"severity": "important",
                            "message": f"角色'{entity_id}'的{field}：Data Agent提取旧值='{old_value}'，"
                                       f"但圣经当前值为'{current_val}'，疑似幻觉篡改，请人审"})

        blocking_issues = [i for i in validation_issues if i["severity"] == "critical"]
        if blocking_issues:
            return {
                "chapter": req.chapter,
                "committed": False,
                "summary": "",
                "deltas": 0,
                "relationships": 0,
                "events": 0,
                "foreshadow_updates": 0,
                "new_characters": 0,
                "new_factions": 0,
                "new_monsters": 0,
                "new_world_settings": 0,
                "archived": False,
                "validation_issues": validation_issues,
                "message": "commit校验失败：发现critical问题，已阻止delta写入圣经",
            }

        # 用事务保证 commit 原子性
        with repo.unit_of_work():
            applier.apply_deltas(delta_list, chapter=req.chapter)

            # P0#1：自动写出场记录（幂等，先删本章再写）
            appearances = []
            pp_names: set[str] = set()
            for s in deltas:
                if s.get("entity_id") and str(s.get("entity_type") or s.get("entity") or "").strip() in ("角色", "character"):
                    pp_names.add(str(s["entity_id"]).strip())
            for c in new_characters:
                if c.get("name"):
                    pp_names.add(str(c["name"]).strip())
            for n in sorted(pp_names):
                appearances.append({"entity_type": "character", "entity_id": n, "chapter": req.chapter})
            for f in new_factions:
                if f.get("name"):
                    appearances.append({"entity_type": "faction", "entity_id": str(f["name"]).strip(), "chapter": req.chapter})
            for m in new_monsters:
                if m.get("name"):
                    appearances.append({"entity_type": "monster", "entity_id": str(m["name"]).strip(), "chapter": req.chapter})
            if appearances:
                repo.record_appearances(req.chapter, appearances)

            # 断链③：提交后叙事线轻扫（写章即更新线进度/断线预警，LLM 深度扫描仍手动）
            try:
                from novel_agent.bible.models import Storyline
                from novel_agent.storyline.scanner import light_scan_chapter
                _lines = db.query(Storyline).filter_by(project_id=req.project_id).all()
                light_scan_chapter(db, req.project_id, req.chapter, text or "", _lines)
            except Exception as _e:
                logger.warning("提交第%d章后叙事线轻扫失败: %s", req.chapter, _e)

            # 生成/更新章节摘要
            repo.create_or_update_chapter_summary(
                chapter=req.chapter,
                title=outline_title,
                core_events=summary,
                characters_present=", ".join({d.get("entity_id", "") for d in deltas if d.get("entity_type") in ("角色", "character")}),
                foreshadow_dynamics=", ".join([f"{fu.get('foreshadow_id', '')}->{fu.get('status', '')}" for fu in fore_updates]),
                word_count=count_chinese_chars(text),
            )

            # 地图联动：本章正文出现的地点标记为"第 N 章起解锁"（只保留最早解锁章节）。
            # 世界地图据此显示剧情解锁进度：第一章到过的区/街道 → 地图上点亮。
            from novel_agent.bible.models import Location
            if text:
                locs = db.query(Location).filter(Location.project_id == req.project_id).all()
                for loc in locs:
                    if loc.name and loc.name in text:
                        if not loc.unlocked_chapter or req.chapter < loc.unlocked_chapter:
                            loc.unlocked_chapter = req.chapter

        # 提交成功后索引到 ArchivalMemory，供后续语义检索
        try:
            archival = ArchivalMemory(cfg, project_id=repo.project_id)
            archival.index_chapter(req.chapter, outline_title, text)
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
            "new_characters": len(new_characters),
            "new_factions": len(new_factions),
            "new_monsters": len(new_monsters),
            "new_world_settings": len(new_world_settings),
            "archived": archived,
        }
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning("LLM client关闭失败: %s", e)
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
@limiter.limit("10/minute")
async def suggest(request: Request, req: SuggestRequest):
    db, repo, project, cfg = _get_repo(req.project_id)
    client = None
    try:
        client = LLMClient(cfg.get_agent_llm("architect"))
        consistency = _build_consistency_constraint(repo, project)
        # 注入任务专属设计指南
        from novel_agent.templates.style_guide_loader import get_guides_for_generation
        task_guide = get_guides_for_generation(f"suggest_{req.suggest_type}")
        context_text = _build_context_text(repo, project, cfg, req.context_type, req.context_id)
        asset_text = _list_asset_text(repo, req.suggest_type)

        # 按模板变量语义注入真实数据（之前硬编码为空）
        world_text = _format_world_for_prompt(repo)
        char_text = _format_chars_for_prompt(repo)
        fore_text = _format_foreshadows_for_prompt(repo)
        outline_text = _format_outlines_for_prompt(repo)
        # 同类资产参考（仅对对应 suggest_type 额外注入）
        if req.suggest_type == "monster":
            monster_text = asset_text
        else:
            monster_text = ""
        if req.suggest_type in ("faction", "character"):
            faction_text = asset_text if req.suggest_type == "faction" else _format_factions_for_prompt(repo)
        else:
            faction_text = ""
        if req.suggest_type == "relationship":
            relationship_text = asset_text
        else:
            relationship_text = ""

        template_name = f"suggest_{req.suggest_type}"
        prompt = PromptLoader().render(
            template_name,
            title=project.title,
            genre=project.genre,
            style=project.style,
            context_type=req.context_type,
            context_text=context_text + consistency + ("\n\n" + task_guide if task_guide else ""),
            world_text=world_text,
            char_text=char_text,
            fore_text=fore_text,
            outline_text=outline_text,
            monster_text=monster_text,
            faction_text=faction_text,
            relationship_text=relationship_text,
            count=req.count,
            custom_prompt=req.custom_prompt,
        )

        system = "你是网文创作助手，擅长基于已有设定生成一致且高质量的后续内容。不得凭空捏造与已有设定矛盾的内容。只输出 JSON。"
        result = await _generate_json_with_repair(client, prompt, system=system, root_key="suggestions")
        if not result:
            raise HTTPException(422, "LLM 返回内容无法解析为有效 JSON，请检查模型配置或重试")
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
        if client is not None:
            await client.close()
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
                    _strength = _safe_int(p.get("strength", 0), 0)
                    if p.get("source_faction_id"):
                        _src_fid = _safe_int(p.get("source_faction_id"), 0)
                        _tgt_fid = _safe_int(p.get("target_faction_id"), 0)
                        if _src_fid and _tgt_fid:
                            created_obj = repo.create_faction_relationship(
                                source_faction_id=_src_fid,
                                target_faction_id=_tgt_fid,
                                relation_type=p.get("relation_type", "neutral"),
                                strength=_strength,
                                description=s.summary,
                            )
                            created["relationships"].append({"id": created_obj.id})
                        else:
                            # faction_id 非数字，降级为角色关系
                            created_obj = repo.create_character_relationship(
                                source_character=str(p.get("source_faction_id", "")),
                                target_character=str(p.get("target_faction_id", "")),
                                relation_type=p.get("relation_type", "其他"),
                                relation_subtype=p.get("relation_subtype", ""),
                                strength=_strength,
                                description=s.summary,
                            )
                            created["relationships"].append({"id": created_obj.id})
                    else:
                        created_obj = repo.create_character_relationship(
                            source_character=p.get("source_character", ""),
                            target_character=p.get("target_character", ""),
                            relation_type=p.get("relation_type", "其他"),
                            relation_subtype=p.get("relation_subtype", ""),
                            strength=_strength,
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


# ---- BookRunner 批量生成 + resume（阶段4b 元认知监控） ----

class BookRunRequest(BaseModel):
    project_id: int
    start_chapter: int
    end_chapter: int


class BookRunResponse(BaseModel):
    completed: list[int] = []
    failed: list[dict] = []
    volume_summary: str = ""


class BookResumeRequest(BaseModel):
    project_id: int


class BookStatusResponse(BaseModel):
    project_id: int
    checkpoint: dict = {}


@router.post("/book/run", response_model=BookRunResponse)
async def book_run(req: BookRunRequest):
    """批量生成一卷章节，失败章节记录并继续，支持后续 resume。"""
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        from novel_agent.orchestrator.book_runner import BookRunner
        runner = BookRunner(cfg, repo)
        try:
            result = await runner.run_volume(req.start_chapter, req.end_chapter)
            return BookRunResponse(**result)
        finally:
            await runner.close()
    finally:
        db.close()


@router.post("/book/resume", response_model=BookRunResponse)
async def book_resume(req: BookResumeRequest):
    """从上次 BookRunner checkpoint 恢复生成。"""
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        checkpoint = repo.get_generation_checkpoint()
        if not checkpoint:
            raise HTTPException(404, "没有可恢复的生成任务")
        start_chapter = int(checkpoint.get("start_chapter", 1))
        end_chapter = int(checkpoint.get("end_chapter", start_chapter))

        from novel_agent.orchestrator.book_runner import BookRunner
        runner = BookRunner(cfg, repo)
        try:
            result = await runner.run_volume(start_chapter, end_chapter, resume=True)
            return BookRunResponse(**result)
        finally:
            await runner.close()
    finally:
        db.close()


@router.get("/book/status/{project_id}", response_model=BookStatusResponse)
async def book_status(project_id: int):
    """查看当前批量生成 checkpoint（元认知监控）。"""
    db, repo, project, cfg = _get_repo(project_id)
    try:
        checkpoint = repo.get_generation_checkpoint()
        return BookStatusResponse(project_id=project_id, checkpoint=checkpoint)
    finally:
        db.close()


@router.post("/book/run/stream")
async def book_run_stream(request: Request, req: BookRunRequest):
    """批量生成 SSE 端点。逐章推送进度。

    事件流：
    - chapter_start: {"chapter": N}
    - chapter_done:  {"chapter": N, "status": "completed"/"failed", "error": "..."}
    - done:          {"total": N, "completed": N, "failed": N}
    - error:         {"error": "..."}
    """
    from sse_starlette.sse import EventSourceResponse
    from novel_agent.orchestrator.book_runner import BookRunner
    from novel_agent.orchestrator.runner import ChapterRunner

    db, repo, project, cfg = _get_repo(req.project_id)

    async def event_generator():
        runner: ChapterRunner | None = None
        book_runner: BookRunner | None = None
        try:
            book_runner = BookRunner(cfg, repo)
            runner = ChapterRunner(cfg, repo)
            completed = 0
            failed = 0
            total = req.end_chapter - req.start_chapter + 1
            for ch in range(req.start_chapter, req.end_chapter + 1):
                if await _check_disconnected(request):
                    return
                yield _sse_event("chapter_start", {"chapter": ch})
                try:
                    result = await book_runner.run_single(
                        ch, runner, req.start_chapter, req.end_chapter)
                    status = result.get("status", "failed")
                    if status == "failed":
                        failed += 1
                        yield _sse_event("chapter_done", {
                            "chapter": ch, "status": "failed",
                            "error": result.get("error", "未知错误"),
                        })
                    else:
                        # completed 或 pending_review 均视为已生成
                        completed += 1
                        yield _sse_event("chapter_done", {
                            "chapter": ch, "status": "completed",
                            "warning": "需人工确认" if status == "pending_review" else "",
                        })
                except Exception as e:
                    failed += 1
                    yield _sse_event("chapter_done", {
                        "chapter": ch, "status": "failed", "error": str(e),
                    })
            yield _sse_event("done", {
                "total": total, "completed": completed, "failed": failed,
            })
        except Exception as e:
            yield _sse_event("error", {"error": str(e)})
        finally:
            if runner:
                try:
                    await runner.close()
                except Exception:
                    pass
            if book_runner:
                try:
                    await book_runner.close()
                except Exception:
                    pass
            db.close()

    return EventSourceResponse(event_generator(), ping=15)


# ==================== 交互式创作模式 ====================

class InteractiveGenerateRequest(BaseModel):
    project_id: int
    chapter_number: int = 0  # 0 = 自动检测下一章
    user_direction: str = ""  # 用户的剧情走向描述，空 = AI自主发展
    custom_prompt: str = ""  # 额外要求


class InteractiveGenerateResponse(BaseModel):
    chapter: int
    title: str
    content: str
    word_count: int
    suggested_next: str  # AI对下一章的建议
    brief: str  # 生成的任务书摘要


@router.post("/interactive/generate-chapter", response_model=InteractiveGenerateResponse)
@limiter.limit("5/minute")
async def interactive_generate_chapter(request: Request, req: InteractiveGenerateRequest):
    """交互式创作：无需大纲，直接生成章节正文。支持用户指定剧情走向或AI自主发展。"""
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        from novel_agent.memory.recall import RecallMemory
        from novel_agent.templates.style_guide_loader import get_core_constraints
        from novel_agent.audit.validator import count_chinese_chars

        recall = RecallMemory(cfg, project_id=req.project_id)

        # 确定章节号
        existing_chapters = recall.list_chapters()
        if req.chapter_number > 0:
            chapter = req.chapter_number
        elif existing_chapters:
            chapter = max(existing_chapters) + 1
        else:
            chapter = 1

        # 构建上下文：世界观 + 角色 + 伏笔
        world_text = _format_world_for_prompt(repo)
        chars_text = _format_chars_for_prompt(repo)
        foreshadow_text = _format_foreshadows_for_prompt(repo)
        collection_text = _format_collection_for_prompt(repo, chapter)
        core_constraints = get_core_constraints()

        # 构建前文摘要（最近5章）
        recent_chapters = sorted(existing_chapters)[-5:] if existing_chapters else []
        prev_summary = ""
        recent_texts: list[str] = []
        if recent_chapters:
            summary_lines = []
            for ch_num in recent_chapters:
                ch_text = recall.read_chapter_text(ch_num)
                if ch_text:
                    recent_texts.append(ch_text)
                    # 完整正文作为前文参考
                    snippet = ch_text.replace("\n", " ")
                    summary_lines.append(f"第{ch_num}章：{snippet}...")
            if summary_lines:
                prev_summary = "【前文参考--最近章节完整内容】\n" + "\n".join(summary_lines)

        # 写手上下文三合一（P0）：实体历史提及 + 卷/弧摘要（最近章节正文已在上面）
        entity_history_text = _format_entity_history_for_prompt(
            repo, chapter, _extract_chapter_entities(repo, chapter, recent_texts))
        volume_summary_text = _format_volume_summary_for_prompt(repo, chapter, _list_chapter_summaries(repo))

        # 剧情走向
        direction_text = ""
        if req.user_direction.strip():
            direction_text = f"\n\n【作者指定的本章剧情走向】\n{req.user_direction.strip()}\n请严格按照作者指定的剧情走向创作本章。"
        else:
            direction_text = "\n\n【本章剧情走向】\n请基于世界观设定和前文情节，自主决定本章的剧情走向。要求：\n1. 必须推进主线剧情，不能是日常流水账\n2. 必须有冲突和角色互动\n3. 必须有至少1个爽点（打脸/反杀/突破/识破/碾压）\n4. 章末必须留钩子"

        # 额外要求
        extra_req = ""
        if req.custom_prompt.strip():
            extra_req = f"\n\n【额外要求】\n{req.custom_prompt.strip()}"

        # 字数控制：统一从 节奏阈值.csv 读取（与 write_chapter/audit 共用同一真源）
        from novel_agent.audit.validator import _get_threshold
        word_min = int(_get_threshold("字数下限", 2500))
        word_max = int(_get_threshold("字数上限", 4000))
        word_min_important = int(_get_threshold("字数下限_重要章节", 3000))
        is_important = chapter <= 3
        target_min = word_min_important if is_important else word_min

        # CSV 参考资料检索：按 user_direction + 题材 检索爽点/桥段/场景/写作技法
        csv_ref_block = ""
        try:
            from novel_agent.references.search import ReferenceSearch, canonical_genre as _cg
            cg_text = _cg(project.genre) if project.genre else ""
            ref_search = ReferenceSearch()
            ref_query = req.user_direction.strip() or project.genre or "通用"
            ref_rows = ref_search.search(
                query=ref_query,
                canonical_genre=cg_text,
                skills=["webnovel-write"],
                limit=8,
            )
            if ref_rows:
                ref_lines = []
                for r in ref_rows:
                    cat = r.get("分类", "")
                    kw = r.get("关键词", "")
                    inst = r.get("指令", "")
                    detail = r.get("详细展开", "")
                    line = f"- [{cat}] {kw}"
                    if inst:
                        line += f"：{inst}"
                    if detail:
                        line += f"（{detail}）"
                    ref_lines.append(line)
                csv_ref_block = "\n\n【参考资料·CSV约束（按本章题材/方向检索）】\n" + "\n".join(ref_lines)
        except Exception as e:
            logger.warning("interactive_generate_chapter: CSV参考资料注入失败: %s", e)

        # 题材模板：推荐约束包 + 规则类型 + 文风标杆
        genre_template_block = ""
        try:
            from novel_agent.references.search import canonical_genre as _cg2
            from novel_agent.templates.loader import GenreLoader
            if project.genre:
                cg = _cg2(project.genre)
                loader = GenreLoader()
                if loader.exists(cg):
                    parts = []
                    rec = loader.extract_recommended_constraints(cg)
                    if rec:
                        parts.append(rec)
                    rt = loader.extract_rule_types(cg)
                    if rt:
                        parts.append(rt)
                    bench = loader.extract_style_benchmark(cg)
                    if bench:
                        parts.append(bench)
                    if parts:
                        genre_template_block = "\n\n【题材模板】\n" + "\n\n".join(parts)
        except Exception as e:
            logger.warning("interactive_generate_chapter: 题材模板注入失败: %s", e)

        # few-shot 范文（通用样本）
        few_shot_block = ""
        try:
            from novel_agent.templates.style_guides.few_shot_samples import get_few_shot_for_beat
            few_shot = get_few_shot_for_beat("")
            if few_shot:
                few_shot_block = f"\n\n【风格标杆·范文样本】\n{few_shot}"
        except Exception as e:
            logger.warning("interactive_generate_chapter: few-shot注入失败: %s", e)

        # 人类网文风格参考（按题材过滤，防止跨题材污染）
        human_style_block = ""
        try:
            from novel_agent.orchestrator.nodes import _load_random_human_chapter
            human_chapter = _load_random_human_chapter(max_chars=2500, genre=project.genre or "")
            if human_chapter:
                human_style_block = (
                    "\n\n【人类网文风格参考】\n"
                    "学习以下人类网文作家的写法技巧（叙事节奏、句式变化、对话处理、场景转换），"
                    "但不要抄袭其内容，只学写法不抄故事：\n" + human_chapter
                )
        except Exception as e:
            logger.warning("interactive_generate_chapter: 人类网文样本加载失败: %s", e)

        # 复用 writer 的完整 system prompt（含反流水账铁律 + 网文语感铁律 + AI味黑名单）
        from novel_agent.orchestrator.prompts import build_writer_system_prompt
        system_prompt = build_writer_system_prompt()

        prompt = f"""请为小说《{project.title}》创作第{chapter}章正文。

题材：{project.genre}
风格/要求：{project.style}

【世界观设定】
{world_text}

【角色设定】
{chars_text}

【伏笔状态】
{foreshadow_text}
{collection_text}
{prev_summary}
{entity_history_text}
{volume_summary_text}
{direction_text}
{extra_req}
{genre_template_block}
{csv_ref_block}
{few_shot_block}
{human_style_block}

【写作风格约束——核心约束（反AI味/文风/节奏/爽点）】
{core_constraints}

【字数要求】
正文 {target_min}-{word_max} 字。{word_max} 字是硬性天花板，超过即为废稿。
宁可剧情紧凑字数偏少，也不要注水。写每个段落前都问自己：这段话推进剧情了吗？没有就删。

请输出 JSON：
{{"title": "章节标题", "content": "正文内容（纯文本，不要markdown格式）", "suggested_next": "对下一章剧情的建议（1-2句话）", "brief": "本章任务书摘要（本章核心事件、角色目标、爽点设计，100字以内）"}}
"""

        client = LLMClient(cfg.get_agent_llm("writer"))
        result = await _generate_json_with_repair(
            client, prompt, system=system_prompt, max_tokens=128000
        )
        await client.close()

        if not result or "content" not in result:
            raise HTTPException(500, "LLM 返回内容无法解析，请重试")

        title = result.get("title", f"第{chapter}章")
        content = result.get("content", "")
        suggested_next = result.get("suggested_next", "")
        brief = result.get("brief", "")

        if not content.strip():
            raise HTTPException(500, "生成的内容为空，请重试")

        # 保存章节
        recall.save_chapter_text(chapter, title, content)

        word_count = count_chinese_chars(content)

        return InteractiveGenerateResponse(
            chapter=chapter,
            title=title,
            content=content,
            word_count=word_count,
            suggested_next=suggested_next,
            brief=brief,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"生成失败：{e}")
    finally:
        db.close()


# ==================== 交互式聊天创作模式 ====================

class InteractiveChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    msg_type: str = "chat"  # "chat" | "chapter"
    chapter: int | None = None
    title: str | None = None
    brief: str | None = None
    suggested_next: str | None = None


class InteractiveChatRequest(BaseModel):
    project_id: int
    message: str
    history: list[InteractiveChatMessage] = []
    mode: str = "qa"  # "qa" | "free"
    use_workflow: bool = False  # True=走 MVP 26-agent 工作流（含资产桥接），False=单 agent 直生成
    num_variants: int = 1  # 抽卡模式版本数：默认 1=不抽卡（向后兼容）；>1=一次生成 N 个候选版本，用户选 1 后再走后续流程


class InteractiveChatResponse(BaseModel):
    type: str  # "chapter" | "chat"
    message: str  # AI 的文字回复（chat 类型）或章节摘要（chapter 类型）
    chapter: int | None = None
    title: str | None = None
    content: str | None = None
    word_count: int | None = None
    suggested_next: str | None = None
    brief: str | None = None


@router.post("/interactive/chat", response_model=InteractiveChatResponse)
@limiter.limit("5/minute")
async def interactive_chat(request: Request, req: InteractiveChatRequest):
    """交互式聊天创作：支持一问一答。
    AI 自动判断用户意图——是要生成章节，还是只是讨论/提问。
    """
    db, repo, project, cfg = _get_repo(req.project_id)
    try:
        from novel_agent.memory.recall import RecallMemory
        from novel_agent.templates.style_guide_loader import get_core_constraints
        from novel_agent.audit.validator import count_chinese_chars, _get_threshold
        from novel_agent.orchestrator.prompts import build_writer_system_prompt
        from novel_agent.references.search import ReferenceSearch, canonical_genre as _cg
        from novel_agent.templates.loader import GenreLoader
        from novel_agent.templates.style_guides.few_shot_samples import get_few_shot_for_beat

        recall = RecallMemory(cfg, project_id=req.project_id)

        # 确定章节号
        existing_chapters = recall.list_chapters()
        chapter = (max(existing_chapters) + 1) if existing_chapters else 1

        # 构建上下文
        world_text = _format_world_for_prompt(repo)
        chars_text = _format_chars_for_prompt(repo)
        foreshadow_text = _format_foreshadows_for_prompt(repo)
        collection_text = _format_collection_for_prompt(repo, chapter)
        core_constraints = get_core_constraints()

        # 前文摘要（最近3章）
        recent_chapters = sorted(existing_chapters)[-3:] if existing_chapters else []
        prev_summary = ""
        recent_texts: list[str] = []
        if recent_chapters:
            summary_lines = []
            for ch_num in recent_chapters:
                ch_text = recall.read_chapter_text(ch_num)
                if ch_text:
                    recent_texts.append(ch_text)
                    snippet = ch_text.replace("\n", " ")
                    summary_lines.append(f"第{ch_num}章：{snippet}...")
            if summary_lines:
                prev_summary = "【前文参考--最近章节完整内容】\n" + "\n".join(summary_lines)

        # 写手上下文三合一（P0）：实体历史提及 + 卷/弧摘要
        entity_history_text = _format_entity_history_for_prompt(
            repo, chapter, _extract_chapter_entities(repo, chapter, recent_texts))
        volume_summary_text = _format_volume_summary_for_prompt(repo, chapter, _list_chapter_summaries(repo))

        # 对话历史（精简：用户消息全保留，AI 的章节回复只保留摘要）
        history_text = ""
        if req.history:
            hist_lines = []
            for msg in req.history[-10:]:  # 最近10条
                if msg.role == "user":
                    hist_lines.append(f"用户：{msg.content}")
                else:
                    if msg.msg_type == "chapter" and msg.chapter:
                        brief = msg.brief or ""
                        hist_lines.append(f"助手：已生成第{msg.chapter}章《{msg.title or ''}》。{brief}")
                    else:
                        hist_lines.append(f"助手：{msg.content}")
            history_text = "【对话历史】\n" + "\n".join(hist_lines)

        # 字数阈值从 CSV 读取
        word_min = int(_get_threshold("字数下限", 2500))
        word_max = int(_get_threshold("字数上限", 4000))
        word_min_important = int(_get_threshold("字数下限_重要章节", 3000))
        is_important = chapter <= 3
        target_min = word_min_important if is_important else word_min

        # CSV 参考资料检索
        csv_ref_block = ""
        try:
            cg_text = _cg(project.genre) if project.genre else ""
            ref_search = ReferenceSearch()
            ref_query = req.message.strip() or project.genre or "通用"
            ref_rows = ref_search.search(
                query=ref_query, canonical_genre=cg_text,
                skills=["webnovel-write"], limit=8,
            )
            if ref_rows:
                ref_lines = []
                for r in ref_rows:
                    cat = r.get("分类", "")
                    kw = r.get("关键词", "")
                    inst = r.get("指令", "")
                    detail = r.get("详细展开", "")
                    line = f"- [{cat}] {kw}"
                    if inst:
                        line += f"：{inst}"
                    if detail:
                        line += f"（{detail}）"
                    ref_lines.append(line)
                csv_ref_block = "\n\n【参考资料·CSV约束】\n" + "\n".join(ref_lines)
        except Exception as e:
            logger.warning("interactive_chat: CSV参考资料注入失败: %s", e)

        # 题材模板
        genre_template_block = ""
        try:
            if project.genre:
                cg = _cg(project.genre)
                loader = GenreLoader()
                if loader.exists(cg):
                    parts = []
                    for extractor in [loader.extract_recommended_constraints,
                                      loader.extract_rule_types,
                                      loader.extract_style_benchmark]:
                        r = extractor(cg)
                        if r:
                            parts.append(r)
                    if parts:
                        genre_template_block = "\n\n【题材模板】\n" + "\n\n".join(parts)
        except Exception as e:
            logger.warning("interactive_chat: 题材模板注入失败: %s", e)

        # few-shot 范文
        few_shot_block = ""
        try:
            few_shot = get_few_shot_for_beat("")
            if few_shot:
                few_shot_block = f"\n\n【风格标杆·范文样本】\n{few_shot}"
        except Exception as e:
            logger.warning("few-shot范文加载失败: %s", e)

        # 人类网文风格参考（按题材过滤，防止跨题材污染）
        human_style_block = ""
        try:
            from novel_agent.orchestrator.nodes import _load_random_human_chapter
            _human_chap = _load_random_human_chapter(max_chars=2500, genre=project.genre or "")
            if _human_chap:
                human_style_block = (
                    "\n\n【人类网文风格参考】\n"
                    "学习以下人类网文作家的写法技巧（叙事节奏、句式变化、对话处理、场景转换），"
                    "但不要抄袭其内容，只学写法不抄故事：\n" + _human_chap
                )
        except Exception as e:
            logger.warning("人类网文风格参考加载失败: %s", e)

        # 自由模式：直接生成章节
        # 问答模式：AI 判断是生成章节还是聊天讨论
        if req.mode == "free":
            intent_instruction = (
                "用户使用自由模式，请直接生成下一章正文。"
                f"下一章是第{chapter}章。"
            )
        else:
            intent_instruction = (
                "请根据用户的消息判断意图：\n"
                "A. 如果用户要求写/生成章节、描述剧情走向、说「继续」「下一章」「好」「就这么写」等，"
                f"则生成第{chapter}章正文。输出 type=\"chapter\"。\n"
                "B. 如果用户在提问、讨论设定、修改建议、问角色发展等，不需要生成正文，"
                "用文字回复即可。输出 type=\"chat\"。\n"
                "C. 如果用户说「重写第X章」「修改第X章」，告诉用户请在「写作」页编辑该章后重新生成，"
                "输出 type=\"chat\"。\n"
            )

        system_prompt = build_writer_system_prompt() + (
            "\n\n【交互模式附加规则】"
            "你在和一个作者进行一问一答式的创作对话。"
            + intent_instruction +
            "\n无论生成章节还是聊天回复，都输出 JSON：\n"
            "- 生成章节：{ \"type\": \"chapter\", \"title\": \"...\", \"content\": \"正文...\", "
            "\"suggested_next\": \"下一章建议...\", \"brief\": \"本章摘要...\" }\n"
            "- 纯聊天：{ \"type\": \"chat\", \"message\": \"回复内容...\" }\n"
            "只输出 JSON，不要输出其他内容。"
        )

        user_msg = req.message.strip()
        if req.mode == "free" and not user_msg:
            user_msg = f"请生成第{chapter}章。"

        prompt = f"""小说《{project.title}》第{chapter}章创作。

题材：{project.genre}
风格：{project.style}

【世界观设定】
{world_text}

【角色设定】
{chars_text}

【伏笔状态】
{foreshadow_text}
{collection_text}
{prev_summary}
{entity_history_text}
{volume_summary_text}
{history_text}

【用户消息】
{user_msg}
{genre_template_block}
{csv_ref_block}
{few_shot_block}
{human_style_block}

【写作风格约束】
{core_constraints}

【字数要求】（仅生成章节时适用）
正文 {target_min}-{word_max} 字。{word_max} 字是硬性天花板，超过即为废稿。

请输出 JSON。
"""

        client = LLMClient(cfg.get_agent_llm("writer"))
        result = await _generate_json_with_repair(
            client, prompt, system=system_prompt, max_tokens=128000
        )
        await client.close()

        if not result:
            raise HTTPException(422, "LLM 返回无法解析，请重试")

        resp_type = result.get("type", "chat")

        if resp_type == "chapter":
            title = result.get("title", f"第{chapter}章")
            content = result.get("content", "")
            suggested_next = result.get("suggested_next", "")
            brief = result.get("brief", "")

            if not content.strip():
                raise HTTPException(422, "生成的内容为空，请重试")

            recall.save_chapter_text(chapter, title, content)
            word_count = count_chinese_chars(content)

            return InteractiveChatResponse(
                type="chapter",
                message=f"第 {chapter} 章已生成（{word_count} 字）",
                chapter=chapter,
                title=title,
                content=content,
                word_count=word_count,
                suggested_next=suggested_next,
                brief=brief,
            )
        else:
            message = result.get("message", "")
            if not message.strip():
                message = "（AI 未返回有效回复，请重试）"
            return InteractiveChatResponse(
                type="chat",
                message=message,
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"聊天失败：{e}")
    finally:
        db.close()


# ── 交互式创作流式端点（SSE） ──


def _check_similarity(generated: str, original: str) -> dict:
    """检查生成正文与原文的相似度（套壳改写红线检查）。

    返回:
        {
            "max_continuous_match": int,   # 最长连续匹配字数
            "similarity_ratio": float,      # 4-gram重叠率（0.0-1.0）
            "matched_ngrams": int,          # 匹配的4-gram数
            "total_ngrams": int,            # 生成文本的4-gram总数
        }
    """
    import re
    # 只比较中文字符（去除标点、空白、标记）
    gen_clean = re.sub(r'[^\u4e00-\u9fff]', '', generated)
    orig_clean = re.sub(r'[^\u4e00-\u9fff]', '', original)

    if not gen_clean or not orig_clean:
        return {"max_continuous_match": 0, "similarity_ratio": 0.0, "matched_ngrams": 0, "total_ngrams": 0}

    # 1. 最长连续匹配子串（提前终止：找到>=20字即可判定违规）
    max_continuous = 0
    orig_len = len(orig_clean)
    gen_len = len(gen_clean)
    EARLY_STOP = 20  # 找到20字连续匹配即可终止（远超13字红线）
    for i in range(orig_len):
        if max_continuous >= EARLY_STOP:
            break
        for j in range(gen_len):
            k = 0
            while i + k < orig_len and j + k < gen_len and orig_clean[i + k] == gen_clean[j + k]:
                k += 1
            if k > max_continuous:
                max_continuous = k
                if max_continuous >= EARLY_STOP:
                    break

    # 2. 4-gram重叠率（Jaccard相似度）
    n = 4
    gen_ngrams = set()
    for i in range(len(gen_clean) - n + 1):
        gen_ngrams.add(gen_clean[i:i + n])
    orig_ngrams = set()
    for i in range(len(orig_clean) - n + 1):
        orig_ngrams.add(orig_clean[i:i + n])

    if not gen_ngrams:
        return {"max_continuous_match": max_continuous, "similarity_ratio": 0.0, "matched_ngrams": 0, "total_ngrams": 0}

    matched = gen_ngrams & orig_ngrams
    similarity = len(matched) / len(gen_ngrams) if gen_ngrams else 0.0

    return {
        "max_continuous_match": max_continuous,
        "similarity_ratio": similarity,
        "matched_ngrams": len(matched),
        "total_ngrams": len(gen_ngrams),
    }


async def _run_mvp_workflow_for_interactive(
    request: Request, req: InteractiveChatRequest, cfg,
    chapter_num: int, user_direction: str,
    min_words: int, max_words: int,
):
    """触发 MVP 26-agent 工作流生成章节（资产桥接彻底接通）。

    流程：DB→文件(script_db_export) → 26 agents 逐个执行 → 文件→DB(script_db_import)
    每个 agent 按 AGENT_TYPE_TO_ROLE 映射使用对应角色模型（跨模型审校）。
    工作流事件实时推送为 thinking SSE，让用户看到 26 个 agent 的执行进度。

    Yields:
        SSE 事件 dict（thinking/error），最后 yield {"__wf_result__": (text, title, disconnected)}。
        工作流失败时 text="" 调用方应中止。
    """
    import asyncio
    from novel_agent.workflows import run_workflow

    workspace = cfg.project_dir(req.project_id)
    chapter_str = f"{chapter_num:04d}"
    prev_chapter_str = f"{chapter_num - 1:04d}" if chapter_num > 1 else "0000"

    # 组装工作流输入变量
    wf_inputs = {
        "chapter_number": chapter_str,
        "prev_chapter": prev_chapter_str,
        "human_intent": user_direction or "（无特定意图，请基于世界观和前文自主推进剧情）",
        "world_intent": "",  # 世界层意图留空，按正常世界规则自主推演
        "target_word_count": f"{min_words}-{max_words}",
        "writer_type": "single",  # 单写手模式（一稿成型），比写手群更快
        "language": "中文",
    }

    yield _sse_event("thinking", {
        "stage": "启动 MVP 工作流",
        "detail": f"正在启动 26-agent 创作管线（第 {chapter_num} 章），包含资产桥接 DB↔文件..."
    })

    # 事件队列：工作流在后台 task 执行，主协程从队列取事件推送 SSE
    queue: asyncio.Queue = asyncio.Queue()
    NODE_LABELS = {
        "script_db_export": "资产桥接·DB→文件",
        "script_sync_down": "准备章节上下文",
        "agent_we": "世界状态机推演",
        "script_we_post": "世界状态后处理",
        "script_render_we": "渲染世界状态",
        "sync_up_we": "存档·世界状态",
        "agent_id": "意图分发",
        "script_parse_intent": "意图解析",
        "agent_od": "大纲导演",
        "script_od_post": "大纲后处理",
        "script_render_od": "渲染章纲/伏笔/债务",
        "sync_up_od": "存档·大纲",
        "agent_cm": "角色状态维护",
        "script_cm_post": "角色状态后处理",
        "script_render_cm": "渲染角色状态",
        "sync_up_cm": "存档·角色",
        "agent_se": "意图导演",
        "script_se_post": "意图导演后处理",
        "agent_trimmer": "上下文裁剪",
        "script_trimmer_post": "裁剪后处理",
        "script_render_trimmer": "渲染裁剪版世界观",
        "script_render_trimmed_chars": "渲染裁剪版角色",
        "agent_nw": "骨架写手",
        "agent_sw": "单写手（一稿成型）",
        "agent_dw": "对话写手",
        "agent_aw": "动作写手",
        "agent_iw": "内心写手",
        "agent_dsw": "描写写手",
        "agent_tw": "过渡写手",
        "agent_si": "整合写手",
        "script_si_post": "正文后处理",
        "script_render_si": "渲染章节正文",
        "sync_up_si": "存档·正文",
        "script_db_import": "资产桥接·文件→DB",
    }

    async def on_event(event: dict) -> None:
        await queue.put(event)

    wf_result: dict = {}
    wf_error: str = ""

    async def _run_wf():
        nonlocal wf_result, wf_error
        client = None
        try:
            client = LLMClient(cfg.get_agent_llm("writer"))
            result = await run_workflow(
                "mvp", wf_inputs, client, workspace,
                on_event=on_event,
                project_id=req.project_id,
                cfg=cfg,
            )
            wf_result = result
            await queue.put({"type": "__done__", "result": result})
        except Exception as e:
            logger.error("interactive MVP workflow 失败: %s", e, exc_info=True)
            wf_error = str(e)
            await queue.put({"type": "__error__", "error": str(e)})
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
            await queue.put(None)  # 结束哨兵

    task = asyncio.create_task(_run_wf())
    is_disconnected = False
    try:
        while True:
            if await request.is_disconnected():
                is_disconnected = True
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue  # 超时后回去检查断开
            if event is None:
                break
            etype = event.get("type", "")
            if etype == "__done__":
                wf_result = event.get("result", {})
                break
            if etype == "__error__":
                yield _sse_event("error", {"error": f"MVP 工作流执行失败：{event.get('error', '未知错误')}"})
                yield {"__wf_result__": ("", "", True)}
                return
            if etype == "node_start":
                node_id = event.get("node", "")
                label = NODE_LABELS.get(node_id, event.get("label", node_id))
                yield _sse_event("thinking", {"stage": label, "detail": f"正在执行：{label}..."})
            elif etype == "node_done":
                node_id = event.get("node", "")
                elapsed = event.get("elapsed_s", 0)
                label = NODE_LABELS.get(node_id, node_id)
                yield _sse_event("thinking", {"stage": f"✓ {label}", "detail": f"已完成（{elapsed:.1f}s）"})
            elif etype == "node_failed":
                node_id = event.get("node", "")
                label = NODE_LABELS.get(node_id, node_id)
                err = event.get("error", "未知错误")
                yield _sse_event("thinking", {"stage": f"⚠ {label} 失败", "detail": f"节点失败：{err}，尝试继续..."})
            elif etype == "workflow_done":
                yield _sse_event("thinking", {"stage": "工作流完成", "detail": "26-agent 管线执行完毕，正在读取生成的章节..."})
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass

    if is_disconnected:
        logger.info("interactive MVP workflow: 客户端断开")
        yield {"__wf_result__": ("", "", True)}
        return

    if not wf_result or wf_result.get("status") != "completed":
        # 工作流可能部分成功（有 fail_auto_skip 节点），检查文件是否产出
        logger.warning("interactive MVP workflow: status=%s, 检查文件产出",
                       wf_result.get("status") if wf_result else "unknown")

    # 读取工作流产出的章节正文
    chapter_dir = workspace / "story" / chapter_str
    chapter_md = chapter_dir / "chapter.md"
    if not chapter_md.exists():
        # 尝试其他可能的路径格式
        for d in (workspace / "story").glob("*"):
            if d.name.lstrip("0") == str(chapter_num) or d.name == chapter_str:
                chapter_md = d / "chapter.md"
                if chapter_md.exists():
                    break
        else:
            chapter_md = workspace / "story" / chapter_str / "chapter.md"

    if not chapter_md.exists():
        logger.error("interactive MVP workflow: 章节文件不存在: %s", chapter_md)
        yield _sse_event("error", {"error": "MVP 工作流未产出章节正文文件，请检查工作流日志"})
        yield {"__wf_result__": ("", "", False)}
        return

    chapter_text = chapter_md.read_text(encoding="utf-8").strip()
    if not chapter_text:
        yield _sse_event("error", {"error": "MVP 工作流产出的章节正文为空"})
        yield {"__wf_result__": ("", "", False)}
        return

    # 从正文提取标题（第一行可能是 "第N章 标题" 格式，也可能没有标题行）
    title = f"第{chapter_num}章"
    parts = chapter_text.split("\n", 1)
    first_line = parts[0].strip() if parts else ""
    title_match = re.match(r"^#*\s*第\d+章\s*(.+)?", first_line)
    if title_match:
        extra = title_match.group(1)
        if extra:
            title = f"第{chapter_num}章 {extra.strip()}"
        # 去掉标题行，保留正文
        chapter_text = parts[1].strip() if len(parts) > 1 else ""
    # 没有标题行时，整段都是正文，title 保持默认

    word_count = count_chinese_chars(chapter_text)
    logger.info("interactive MVP workflow: 章节读取成功，字数=%d, title=%s", word_count, title)
    yield _sse_event("thinking", {
        "stage": "章节生成完成",
        "detail": f"MVP 工作流产出 {word_count} 字，准备进入审校环节..."
    })

    yield {"__wf_result__": (chapter_text, title, False)}


async def _stream_workflow(
    request: Request, workflow_name: str, wf_inputs: dict, cfg,
    workspace, project_id: int, node_labels: dict, stage_msg: str,
):
    """运行一个工作流，流式推送节点进度（thinking SSE），末尾 yield 结果哨兵。

    通用阶段执行器：mvp / polish 等不同工作流都走这里，避免重复队列逻辑。
    Yields: node_start/node_done/node_failed/workflow_done 的 thinking 事件，
    最后 yield {"__wf_done__": (result, disconnected, error)}。
    """
    import asyncio
    from novel_agent.workflows import run_workflow

    yield _sse_event("thinking", {"stage": stage_msg, "detail": f"正在执行：{stage_msg}..."})

    queue: asyncio.Queue = asyncio.Queue()
    wf_result: dict = {}
    wf_error: str = ""
    disconnected = False

    async def on_event(event: dict) -> None:
        await queue.put(event)

    async def _run():
        nonlocal wf_result, wf_error
        client = None
        try:
            client = LLMClient(cfg.get_agent_llm("writer"))
            wf_result = await run_workflow(
                workflow_name, wf_inputs, client, workspace,
                on_event=on_event, project_id=project_id, cfg=cfg,
            )
            await queue.put({"type": "__done__", "result": wf_result})
        except Exception as e:
            logger.error("workflow %s 失败: %s", workflow_name, e, exc_info=True)
            wf_error = str(e)
            await queue.put({"type": "__error__", "error": str(e)})
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
            await queue.put(None)

    task = asyncio.create_task(_run())
    try:
        while True:
            if await request.is_disconnected():
                disconnected = True
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue  # 超时后回去检查断开
            if event is None:
                break
            etype = event.get("type", "")
            if etype == "__done__":
                wf_result = event.get("result", {})
                break
            if etype == "__error__":
                wf_error = event.get("error", "")
                break
            if etype == "node_start":
                node_id = event.get("node", "")
                label = node_labels.get(node_id, event.get("label", node_id))
                yield _sse_event("thinking", {"stage": label, "detail": f"正在执行：{label}..."})
            elif etype == "node_done":
                node_id = event.get("node", "")
                elapsed = event.get("elapsed_s", 0)
                label = node_labels.get(node_id, node_id)
                yield _sse_event("thinking", {"stage": f"✓ {label}", "detail": f"已完成（{elapsed:.1f}s）"})
            elif etype == "node_failed":
                node_id = event.get("node", "")
                label = node_labels.get(node_id, node_id)
                err = event.get("error", "未知错误")
                yield _sse_event("thinking", {"stage": f"⚠ {label} 失败", "detail": f"节点失败：{err}，尝试继续..."})
            elif etype == "workflow_done":
                yield _sse_event("thinking", {"stage": "工作流完成", "detail": f"{stage_msg}执行完毕..."})
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass

    yield {"__wf_done__": (wf_result, disconnected, wf_error)}


POLISH_NODE_LABELS = {
    "script_db_export": "导出本章正文到工作区",
    "script_sync_down": "检查章节存档",
    "script_ai_detect": "AI 味检测",
    "agent_sc": "自审（AI味）",
    "agent_vc": "声线审校",
    "agent_pc": "情感落地审校",
    "agent_pl": "人文化润色",
    "agent_pp": "专业润色",
    "script_polish_post": "润色落盘",
    "script_sync_polish": "存档·润色",
}


async def _run_polish_for_interactive(request: Request, cfg, project_id: int, chapter_num: int, workspace):
    """在 MVP 毛坯后运行 polish.json：三路审校（AI味/声线/情感）+ 双重润色。

    读 story/{chapter}/chapter.md（MVP 已产出），审校润色后写回同一文件，
    末尾 yield {"__polish_result__": polished_text}。
    """
    chapter_str = f"{chapter_num:04d}"
    wf_inputs = {
        "chapter_number": chapter_str,
        "language": "中文",
    }
    result = None
    error = ""
    async for evt in _stream_workflow(
        request, "polish", wf_inputs, cfg, workspace, project_id,
        POLISH_NODE_LABELS, "三路审校 + 双重润色",
    ):
        if "__wf_done__" in evt:
            result, _disconnected, error = evt["__wf_done__"]
        else:
            yield evt

    if error:
        yield _sse_event("thinking", {
            "stage": "⚠ 润色管线异常",
            "detail": f"{error}，将沿用 MVP 毛坯正文继续",
        })

    # 读取润色后的正文（polish_post 已把专业润色稿写回 story/chapter.md）
    polished = ""
    chapter_md = workspace / "story" / chapter_str / "chapter.md"
    if chapter_md.exists():
        polished = chapter_md.read_text(encoding="utf-8").strip()
    yield {"__polish_result__": polished}


async def _run_mvp_and_polish_for_interactive(
    request: Request, req: InteractiveChatRequest, cfg,
    chapter_num: int, user_direction: str,
    min_words: int, max_words: int,
):
    """26-Agent MVP 产出毛坯后，自动接 polish.json 三路审校 + 双重润色。

    解决旧假设：mvp 26 agent 其实没有 polisher，直接进审校的是"毛坯"。
    现在 MVP 跑完自动接润色管线，产出"三路审校 + 双重润色"的成品。
    Yields: 两个阶段的 thinking SSE，最后 yield {"__wf_result__": (text, title, disconnected)}。
    """
    # 阶段1：MVP 26-agent 生成毛坯
    mvp_result = None
    async for evt in _run_mvp_workflow_for_interactive(
        request, req, cfg, chapter_num, user_direction, min_words, max_words
    ):
        if "__wf_result__" in evt:
            mvp_result = evt["__wf_result__"]
        else:
            yield evt

    if mvp_result is None:
        yield {"__wf_result__": ("", "", False)}
        return

    text, title, disconnected = mvp_result
    if disconnected or not text:
        yield {"__wf_result__": (text, title, disconnected)}
        return

    # 阶段2：三路审校 + 双重润色
    workspace = cfg.project_dir(req.project_id)
    polished = None
    async for evt in _run_polish_for_interactive(request, cfg, req.project_id, chapter_num, workspace):
        if "__polish_result__" in evt:
            polished = evt["__polish_result__"]
        else:
            yield evt

    if polished:
        text = polished
        yield _sse_event("thinking", {
            "stage": "✓ 润色完成",
            "detail": f"三路审校 + 双重润色完成，成品 {count_chinese_chars(text)} 字，进入审校环节...",
        })

    yield {"__wf_result__": (text, title, False)}


def _extract_chapter_title_clean(full_text: str, chapter_num: int) -> tuple[str, str]:
    """从 [CHAPTER] 标记的正文中提取标题和干净正文。

    与阶段9的提取逻辑保持一致，供抽卡模式（每个候选版本）复用。
    返回 (title, clean)。
    """
    title = ""
    temp = full_text
    if temp.startswith("[CHAPTER]"):
        temp = temp[9:].lstrip("\n")
    lines = temp.split("\n", 2)
    if len(lines) >= 2:
        title = lines[0].strip() if lines[0].strip() else lines[1].strip()
        temp = lines[2] if len(lines) > 2 else temp
    else:
        title = f"第{chapter_num}章"
    clean = temp
    if clean.startswith("[CHAPTER]"):
        clean = clean[9:].lstrip("\n")
    title_pattern = re.compile(r"^#*\s*第\d+章\s+.+?\n", re.MULTILINE)
    clean = title_pattern.sub("", clean, count=1)
    clean = clean.strip()
    if not title:
        title = f"第{chapter_num}章"
    return title, clean


async def _interactive_chapter_postprocess(
    request: Request,
    cfg,
    repo: BibleRepository,
    client,
    chapter_num: int,
    clean: str,
    title: str,
    skip_auto_polish: bool = False,
    thread_id: str | None = None,
):
    """阶段9核心流程（复用）：从"已有 clean 正文"开始 -> 润色 -> 暂存 -> draft -> audit -> review_pending。

    供单 agent 路径（原阶段9）与抽卡选择路径（variant resume）复用，避免代码重复。
    以 async generator 形式 yield SSE 事件。
    """
    word_count = count_chinese_chars(clean)
    save_title = title if title else f"第{chapter_num}章"
    if not save_title.startswith(f"第{chapter_num}章"):
        save_title = f"第{chapter_num}章 {save_title}"

    import uuid as _uuid
    get_session_store().cleanup_expired_interactive()  # 顺带清理过期会话
    if not thread_id:
        thread_id = f"interactive_{repo.project_id}_{chapter_num}_{_uuid.uuid4().hex[:8]}"

    # ── 阶段9.5：自动润色去 AI 味（与正常写作模式的 style_refine 节点对齐） ──
    polished_clean = clean
    polish_issues: list[str] = []
    if skip_auto_polish:
        # 工作流路径：26 agents（含 polisher 角色）已打磨，跳过自动润色
        yield _sse_event("thinking", {"stage": "跳过自动润色", "detail": "MVP 工作流的 26-agent 管线已包含润色环节，直接进入审校..."})
        logger.info("interactive postprocess: 第%d章跳过自动润色（工作流路径）", chapter_num)
    else:
        yield _sse_event("thinking", {"stage": "润色去 AI 味", "detail": f"正在对第 {chapter_num} 章进行文风净化（清除AI味+标点修复）..."})
        try:
            polish_state = {
                "chapter": chapter_num,
                "title": save_title,
                "draft": clean,
                "drafts": [{"version": 1, "text": clean, "score": 0}],
            }
            # 进度回调：推送润色子步骤
            _auto_progress: list[tuple[str, str]] = []
            async def _auto_progress_cb(stage: str, detail: str):
                _auto_progress.append((stage, detail))
            if await request.is_disconnected():
                return
            polish_result = await polish_chapter(polish_state, client, skip_deslop=True, progress_cb=_auto_progress_cb)
            if await request.is_disconnected():
                return
            for stage, detail in _auto_progress:
                yield _sse_event("thinking", {"stage": stage, "detail": detail})
            if polish_result.get("polished"):
                polished_clean = polish_result["polished"]
                polish_issues = polish_result.get("polish_review_issues", [])
                word_count = count_chinese_chars(polished_clean)
                logger.info("interactive postprocess: 第%d章润色完成，字数 %d", chapter_num, word_count)
        except Exception as e:
            logger.warning("interactive postprocess: 润色失败，使用原稿: %s", e)

    # ── 阶段9.6：相似度红线检查（套壳改写模式） ──
    try:
        from novel_agent.bible.models import ImportedChapter
        imp_ch = repo.db.query(ImportedChapter).filter(
            ImportedChapter.project_id == repo.project_id,
            ImportedChapter.chapter_order == chapter_num
        ).first()
        if imp_ch and imp_ch.raw_content:
            yield _sse_event("thinking", {"stage": "相似度检查", "detail": "正在检查正文与原文的相似度（红线合规）..."})
            sim_result = _check_similarity(polished_clean, imp_ch.raw_content)
            if sim_result["max_continuous_match"] >= 13 or sim_result["similarity_ratio"] > 0.30:
                polish_issues.append(
                    f"⚠️ 红线警告：与原文相似度={sim_result['similarity_ratio']:.1%}，"
                    f"最长连续匹配={sim_result['max_continuous_match']}字"
                    f"（红线：相似度≤30%，连续匹配≤13字）"
                )
                logger.warning(
                    "interactive postprocess: 第%d章相似度红线警告 - 相似度=%.1f%%, 连续匹配=%d字",
                    chapter_num, sim_result["similarity_ratio"] * 100, sim_result["max_continuous_match"]
                )
    except Exception as e:
        logger.warning("interactive postprocess: 相似度检查失败: %s", e)

    get_session_store().save_interactive(thread_id, repo.project_id, {
        "project_id": repo.project_id,
        "chapter_num": chapter_num,
        "title": save_title,
        "draft": polished_clean,
        "raw_draft": clean,
        "word_count": word_count,
        "polished": polished_clean,
        "audit_report": None,
        "review_iterations": 0,
        "polish_issues": polish_issues,
        "created_at": datetime.utcnow().isoformat(),
    })

    # 推送初稿给前端展示（已润色版）
    yield _sse_event("draft", {
        "chapter": chapter_num,
        "title": save_title,
        "content": polished_clean,
        "word_count": word_count,
        "thread_id": thread_id,
        "polish_issues": polish_issues,
    })

    # ── 阶段10：跑 audit 节点（独立 Auditor LLM + 确定性检查） ──
    yield _sse_event("thinking", {"stage": "AI 审校中", "detail": f"正在对第 {chapter_num} 章进行三视角审校（用户/专家/编辑）..."})
    audit_report_dict = None
    from novel_agent.audit.auditor import Auditor
    auditor_client = LLMClient(cfg.get_agent_llm("auditor"))
    try:
        debater_client = LLMClient(cfg.get_agent_llm("debater"))
        try:
            auditor = Auditor(auditor_client, writer_client=client, debater_client=debater_client)
            audit_report = await auditor.audit(
                chapter=chapter_num, title=save_title, draft=polished_clean, repo=repo,
            )
            audit_report_dict = audit_report.model_dump()
            get_session_store().update_interactive(thread_id, repo.project_id, audit_report=audit_report_dict)
        except Exception as e:
            logger.error("interactive postprocess: audit 失败: %s", e, exc_info=True)
            audit_report_dict = {
                "passed": True, "overall_score": 0,
                "summary": f"⚠️ 审校异常（{e}），请人工确认后再决定",
                "issues": [{"dimension": "audit", "severity": "important",
                            "message": f"审校服务异常：{e}，建议人工审阅"}],
                "user_perspective": {"score": 0, "passed": True, "issues": [], "summary": "审校异常"},
                "expert_perspective": {"score": 0, "passed": True, "issues": [], "summary": "审校异常"},
                "editor_perspective": {"score": 0, "passed": True, "issues": [], "summary": "审校异常"},
                "suggestions": ["审校异常，请仔细人工审阅后决定是否通过"],
            }
            get_session_store().update_interactive(thread_id, repo.project_id, audit_report=audit_report_dict)
        finally:
            await debater_client.close()
    finally:
        await auditor_client.close()

    # 推送 audit 报告 + review_pending（等待用户决定）
    yield _sse_event("audit", {
        "thread_id": thread_id,
        "report": audit_report_dict,
    })
    yield _sse_event(*_build_review_pending_event(
        thread_id, chapter_num, save_title, word_count, audit_report_dict,
        polished=False,
    ))
    # 注意：这里不 yield done，等 /resume 端点触发后续流程
    logger.info("interactive postprocess: 已推送 review_pending thread_id=%s", thread_id)
    return


async def interactive_chat_stream(request: Request, req: InteractiveChatRequest):
    """交互式创作流式端点。发送思考过程 + 正文 token 流。

    SSE 事件类型：
    - thinking: {"stage": "...", "detail": "..."} — 思考过程
    - type: {"type": "chapter" | "chat"} — 判断回复类型
    - chunk: {"content": "..."} — 正文 token 流
    - done: {"chapter": ..., "title": ..., "content": ..., "word_count": ..., "brief": ..., "suggested_next": ...}
    - error: {"error": "..."}
    """
    # 参考文件读取已改为 agent 工具 read_reference_files，不再用前置指令拦截
    db = SessionLocal()
    client = None  # 提前初始化，避免 finally 中 NameError
    try:
        logger.info("interactive_chat_stream: 开始，project_id=%d, mode=%s", req.project_id, req.mode)
        cfg = load_config(Path(os.environ.get("NOVEL_CONFIG_PATH", "config.yaml")))
        set_config(cfg)
        project = db.query(Project).filter(Project.id == req.project_id).first()
        if not project:
            yield _sse_event("error", {"error": f"项目 {req.project_id} 不存在"})
            return

        repo = BibleRepository(db, req.project_id)
        recall = RecallMemory(cfg, project_id=req.project_id)

        # ── 阶段1：加载记忆 ──
        logger.warning("interactive_chat_stream: 阶段1 - 加载项目数据")
        yield _sse_event("thinking", {"stage": "加载项目数据", "detail": f"正在加载《{project.title}》的世界观和角色..."})
        world_text = _format_world_for_prompt(repo)
        chars_text = _format_chars_for_prompt(repo)
        fores_text = _format_foreshadows_for_prompt(repo)

        # ── 阶段2：构建分层前文记忆 ──
        yield _sse_event("thinking", {"stage": "构建前文记忆", "detail": "正在回顾全部已写章节..."})
        chapters = recall.list_chapters_with_titles()
        prev_summary = ""       # 全部章节结构化摘要
        prev_full_text = ""     # 前三章完整正文（文风参考）
        prev_ending = ""        # 上一章结尾（直接衔接）
        if chapters:
            bible_repo = BibleRepository(db, req.project_id)
            all_summaries = []
            for ch in chapters:
                try:
                    ch_num = ch["chapter"]
                    ch_title = ch.get("title", "")
                    text = recall.read_chapter_text(ch["chapter"])

                    # 优先使用数据库中的结构化摘要
                    cs = bible_repo.get_chapter_summary(ch_num)
                    if cs and cs.core_events:
                        # 有结构化摘要：组装关键信息
                        parts = [f"第{ch_num}章《{ch_title}》"]
                        if cs.time_location:
                            parts.append(f"时间地点：{cs.time_location}")
                        parts.append(f"核心事件：{cs.core_events}")
                        if cs.characters_present:
                            parts.append(f"出场角色：{cs.characters_present}")
                        if cs.emotion_changes:
                            parts.append(f"情感变化：{cs.emotion_changes}")
                        if cs.foreshadow_dynamics:
                            parts.append(f"伏笔动态：{cs.foreshadow_dynamics}")
                        if cs.chapter_hook:
                            parts.append(f"章末钩子：{cs.chapter_hook}")
                        all_summaries.append(" | ".join(parts))
                    else:
                        # 无结构化摘要：从正文提取简要信息
                        snippet = text.replace("\n", " ").strip()
                        all_summaries.append(f"第{ch_num}章《{ch_title}》：{snippet}")

                    # 前三章完整正文
                    if ch_num <= 3:
                        prev_full_text += f"\n--- 第{ch_num}章《{ch_title}》正文 ---\n{text}\n"

                    # 最后一章结尾（完整文本，供衔接参考）
                    if ch_num == chapters[-1]["chapter"] and text:
                        prev_ending = text.strip()

                except Exception as e:
                    logger.warning("interactive_chat_stream: 构建第%d章摘要失败: %s", ch.get("chapter"), e)

            prev_summary = "\n".join(all_summaries)

        # 确定章节号
        chapter_num = 0
        if chapters:
            chapter_num = max(c["chapter"] for c in chapters) + 1
        else:
            chapter_num = 1

        # ── 问答模式：非创作指令时直接走普通对话分支 ──
        # 用户话语权重最高，未明确说创作就绝对不能生成章节正文
        if req.mode == "qa" and not _looks_like_creation_command(req.message or ""):
            yield _sse_event("thinking", {"stage": "普通对话", "detail": "用户未表达创作意图，进入问答/讨论模式..."})
            chat_system = (
                "【模式规则 - 问答式创作助手】\n"
                "你是用户的专属小说创作顾问。你的职责是帮助用户梳理剧情、完善设定、激发灵感、解决创作难题。\n\n"
                "【核心原则】\n"
                "- 用户当前这条消息具有最高权重。\n"
                "- 绝对禁止输出 [CHAPTER] 标记，绝对禁止生成章节正文。\n"
                "- 绝对禁止写小说正文、故事片段、章节内容。即使用户的消息看起来像小说开头或故事素材，你也只能讨论它，不能代替用户创作。\n\n"
                "【主动提问 - 必须用 present_options 工具】\n"
                "- 你不是被动回答机器。每次回复末尾，你必须调用 present_options 工具弹出可点击的选项按钮让用户选择。\n"
                "- 【绝对禁止】在文本里直接提问（如写\"A方向还是B方向？\"\"你倾向哪个？\"），必须用 present_options 工具。\n"
                "- 选项设计参考：\n"
                "  · 剧情方向：2-3个不同走向的选项\n"
                "  · 角色动机：2-3个可能的动机选项\n"
                "  · 设定细节：2-3个设定方向选项\n"
                "- 调用 present_options 后不要继续生成文本，等用户点击选项。\n\n"
                "【创作素材识别】\n"
                "- 如果用户的消息看起来像是小说开头、故事片段、或创作素材（而非提问或讨论），请说：\n"
                "  「你输入的内容像是创作素材，写得不错。如果要生成章节正文，请切换到【自由创作模式】，或使用指令如『写第1章』『创作下一章』。在那之前，我们可以先讨论一下这段素材怎么融入主线？」\n\n"
                "【回答原则】\n"
                "- 如果用户问的是项目设定、角色、剧情，请基于下面的项目上下文回答。\n"
                "- 如果用户让你分析、建议、讨论，请给出有针对性的、具体的回复，不要泛泛而谈。\n"
                "- 回复要言之有物，但不要写故事/小说正文。\n\n"
                "【项目上下文】\n"
                f"{world_text}\n\n"
                f"{chars_text}\n\n"
                f"{fores_text}\n\n"
                f"【已写章节摘要】\n{prev_summary or '（尚无已写章节）'}"
            )
            # 用 ChatAgent 替代 client.generate：带 history + tools + tool-calling
            # history 直接用前端传的 req.history（InteractiveChatMessage 有 role/content）
            from novel_agent.chat.agent import ChatAgent
            from novel_agent.chat.executor import ActionExecutor
            from novel_agent.chat.session_context import SessionContextManager
            executor = ActionExecutor(repo, cfg)
            _qa_client = LLMClient(cfg.get_agent_llm("orchestrator"))  # 用 DeepSeek（主 llm），工具调用更稳定
            agent = ChatAgent(repo, cfg, executor=executor, llm_client=_qa_client)
            # 设置会话上下文（coding_tools 依赖 workspace_path 做文件读写安全沙箱）
            workspace = cfg.project_dir(req.project_id)
            SessionContextManager().set_context(
                session_id=f"qa-{req.project_id}-{req.session_id if getattr(req, 'session_id', None) else ''}",
                agent_type="orchestrator",
                workspace_path=str(workspace),
            )
            try:
                full_text = ""
                actions = []
                logger.info("问答模式: history=%d 条, msg=%s", len(req.history), (req.message or "")[:80])
                if await request.is_disconnected():
                    return
                # 创建 cancel_event，让用户点停止后能真正中断 agent 的工具循环
                qa_cancel = asyncio.Event()
                async for chunk in agent.stream_reply(req.message, req.history, chat_system, cancel_event=qa_cancel):
                    if await request.is_disconnected():
                        qa_cancel.set()  # 客户端断开，通知 agent 停止
                        return
                    if chunk["type"] == "reasoning":
                        yield _sse_event("reasoning", {"content": chunk["content"]})
                    elif chunk["type"] == "text":
                        full_text += chunk["content"]
                        yield _sse_event("chunk", {"content": chunk["content"]})
                    elif chunk["type"] == "action":
                        actions.append(chunk["action"])
                        yield _sse_event("action", chunk["action"])
                if await request.is_disconnected():
                    return
                if not full_text:
                    # AI 调了工具（如 present_options）但没生成文本时，不报错
                    full_text = "请选择上方选项，或直接输入你的想法。" if actions else "（AI 没有返回有效内容，请重试）"
                full_text = full_text.replace("[CHAPTER]", "").strip()
                # 兜底：AI 没调 present_options 时，自动检测文本里的选项格式
                if not any(a.get("type") == "present_options" for a in actions):
                    from novel_agent.chat.tools import _extract_options_from_text
                    options = _extract_options_from_text(full_text)
                    if options:
                        logger.info("自动提取选项: %d 个", len(options))
                        yield _sse_event("action", {"type": "present_options", "status": "done", "options": options})
                    else:
                        logger.info("未提取到选项（full_text 长度=%d）", len(full_text))
                logger.info("interactive_chat_stream: 问答模式（ChatAgent+tools+history），未触发创作")
                yield _sse_event("done", {
                    "type": "chat",
                    "message": full_text,
                    "title": None,
                    "chapter": None,
                    "content": None,
                    "word_count": None,
                    "brief": None,
                    "suggested_next": None,
                })
                return
            except Exception as e:
                logger.error("interactive_chat_stream: 问答模式普通对话失败: %s", e, exc_info=True)
                yield _sse_event("error", {"error": f"对话失败：{e}"})
                return
            finally:
                await agent.close()

        # ── 阶段3：加载核心约束 ──
        yield _sse_event("thinking", {"stage": "加载写作约束", "detail": "正在加载反流水账铁律和网文语感规则..."})
        core_constraints = ""
        try:
            from novel_agent.templates.style_guide_loader import get_core_constraints
            core_constraints = get_core_constraints()
        except Exception as e:
            logger.warning("interactive_chat_stream: 核心约束加载失败: %s", e)

        # ── 阶段4：写作技能语料按需加载（桥段/场景/人设/题材库已做成默认语料 skill，
        # 由下方 load_enabled_skills_for_injection_with_context 按本章上下文检索注入；
        # csv_refs 保留空串兼容下游引用，不再直读 CSV 避免重复注入） ──
        yield _sse_event("thinking", {"stage": "加载写作技能", "detail": "正在按剧情方向检索桥段/场景/技法语料..."})
        csv_refs = ""

        # ── 阶段5：加载题材模板（与正常写作模式一致：三件套全加载） ──
        yield _sse_event("thinking", {"stage": "加载题材模板", "detail": f"正在加载{project.genre}题材约束..."})
        genre_constraints = ""
        try:
            cg = canonical_genre(project.genre)
            loader = GenreLoader()
            if loader.exists(cg):
                parts = []
                rec = loader.extract_recommended_constraints(cg)
                if rec:
                    parts.append(rec)
                rt = loader.extract_rule_types(cg)
                if rt:
                    parts.append(rt)
                bench = loader.extract_style_benchmark(cg)
                if bench:
                    parts.append(bench)
                if parts:
                    genre_constraints = "\n\n".join(parts)
        except Exception as e:
            logger.warning("interactive_chat_stream: 题材模板加载失败: %s", e)

        # ── 阶段6：加载范文样本 + 人类网文风格参考 ──
        yield _sse_event("thinking", {"stage": "加载范文样本", "detail": "正在加载人类网文写作样本..."})
        few_shot = ""
        try:
            from novel_agent.templates.style_guides.few_shot_samples import get_few_shot_for_beat
            # 尝试从本章大纲提取 beat_type（与正常写作模式 assemble_context 一致）
            beat_type = ""
            try:
                outline = repo.get_outline_by_chapter(chapter_num)
                if outline and outline.required_beats:
                    import json as _json
                    beats = _json.loads(outline.required_beats) if isinstance(outline.required_beats, str) else outline.required_beats
                    if isinstance(beats, list) and beats:
                        if isinstance(beats[0], dict):
                            beat_type = beats[0].get("type", "")
                        elif isinstance(beats[0], str):
                            # beats 是字符串列表（如 ["果断锁门（small: 生存决策爽点）", ...]）
                            # 拼接全部 beat 文本作为 beat_type，让下游关键词匹配生效
                            beat_type = " ".join(beats)
            except Exception as e:
                logger.warning("解析required_beats失败: %s", e)
            few_shot = get_few_shot_for_beat(beat_type) or ""
            if beat_type:
                logger.info("interactive_chat_stream: few-shot按beat_type=%s加载", beat_type[:80])
        except Exception as e:
            logger.warning("interactive_chat_stream: few-shot加载失败: %s", e)

        # 抽取人类网文章节作为风格参考（按题材过滤，防止跨题材污染）
        human_style_ref = ""
        try:
            from novel_agent.orchestrator.nodes import _load_random_human_chapter
            human_chapter = _load_random_human_chapter(max_chars=2500, genre=project.genre or "")
            if human_chapter:
                human_style_ref = human_chapter
                logger.info("interactive_chat_stream: 已加载人类网文风格参考（genre=%s, %d字）",
                            project.genre, len(human_style_ref))
        except Exception as e:
            logger.warning("interactive_chat_stream: 人类网文样本加载失败: %s", e)

        # ── 阶段6.5：注入语料库真实章末钩子示例 ──
        yield _sse_event("thinking", {"stage": "提取语料钩子", "detail": "正在从小说语料库抽取真实章末写法..."})
        corpus_hook_block = ""
        try:
            hook_examples = load_corpus_hook_examples(total=5, max_chars_per_example=100)
            if hook_examples:
                lines = ["以下是从热门网文语料库中抽取的真实章末结尾，供你学习「如何留钩子」，不要抄袭情节，只学写法："]
                for ex in hook_examples:
                    lines.append(f"- [{ex['type']} | {ex['source']}] {ex['text']}")
                corpus_hook_block = "\n".join(lines)
                logger.info("interactive_chat_stream: 已注入 %d 条语料章末钩子示例", len(hook_examples))
        except Exception as e:
            logger.warning("interactive_chat_stream: 语料钩子加载失败: %s", e)

        # ── 阶段6.5b：加载梗库文件（像CSV一样自动注入） ──
        gag_library_text = ""
        try:
            gag_file = cfg.project_dir(req.project_id) / "gag_library.md"
            if gag_file.exists():
                gag_library_text = gag_file.read_text(encoding="utf-8", errors="replace")
            if gag_library_text:
                # 梗库全量注入（"看全"才能选梗），梗库通常几千字，不截断
                gag_library_text = (
                    "【梗库参考--每章必须用至少1个梗】\n"
                    "以下是本书的梗库，包含笑点/桥段/彩蛋的详细用法。"
                    "创作时从中选择适合当前剧情的梗自然融入，不能生硬植入。\n\n"
                    f"{gag_library_text}"
                )
                logger.debug("[DIAG] interactive_chat_stream 第%d章：注入梗库参考，gag_library=%d字", chapter_num, len(gag_library_text))
        except Exception as e:
            logger.warning("interactive_chat_stream: 梗库加载失败: %s", e)

        # ── 阶段6.6：加载用户通过指令主动加载的参考文件（不自动读取） ──
        # 参考文件与项目已有资产（世界观/角色/剧情）分离，仅在用户明确说「读参考文件」后注入
        user_reference_block = ""
        user_refs = _PROJECT_REFERENCE_TEXT.get(req.project_id, "")
        if user_refs:
            user_reference_block = (
                "【用户导入的参考文件】\n"
                "以下是你通过指令要求我读取的参考文件内容，创作时必须参考其中的设定、规则、风格或剧情线索，"
                "但不能直接抄袭其故事情节。如果参考文件与圣经数据库冲突，以圣经数据库为准。\n\n"
                f"{user_refs}"
            )
            logger.info("interactive_chat_stream: 注入用户参考文件，共 %d 字符", len(user_reference_block))

        # ── 阶段7：组装 prompt ──
        yield _sse_event("thinking", {"stage": "组装 prompt", "detail": "正在拼装最终 prompt..."})

        from novel_agent.orchestrator.prompts import build_writer_system_prompt

        # 历史
        hist_lines = []
        for msg in (req.history or [])[-10:]:
            if msg.role == "user":
                hist_lines.append(f"用户：{msg.content}")
            else:
                if msg.msg_type == "chapter" and msg.chapter:
                    brief = msg.brief or ""
                    hist_lines.append(f"助手：已生成第{msg.chapter}章《{msg.title or ''}》。{brief}")
                else:
                    hist_lines.append(f"助手：{msg.content}")
        history_text = "\n".join(hist_lines) if hist_lines else "（无历史）"

        # 字数阈值：与正常写作模式(nodes.py)共用同一真源（节奏阈值.csv 中文key）
        from novel_agent.audit.validator import _get_threshold
        min_words = int(_get_threshold("字数下限", 2200))
        max_words = int(_get_threshold("字数上限", 3500))
        word_min_important = int(_get_threshold("字数下限_重要章节", 2500))
        if chapter_num <= 3:
            min_words = word_min_important

        user_direction = req.message.strip() if req.message else ""

        # 识别「按细纲分章创作」指令，例如："按照细纲《黑市逃亡》完成第1章，共5章"
        arc_split_cmd = _parse_arc_split_command(user_direction)
        if arc_split_cmd:
            arc_name, arc_current, arc_total = arc_split_cmd
            logger.info("interactive_chat_stream: 识别到按细纲分章指令，arc=%s, current=%d, total=%d", arc_name, arc_current, arc_total)
            yield _sse_event("thinking", {"stage": "识别分章指令", "detail": f"正在按细纲《{arc_name}》拆分第 {arc_current}/{arc_total} 章..."})
            arc_for_split = _find_arc_by_name(repo, arc_name)
            if arc_for_split:
                user_direction = _build_arc_split_instruction(arc_for_split, arc_current, arc_total)
                yield _sse_event("thinking", {"stage": "加载细纲分章约束", "detail": f"已加载细纲《{arc_for_split.title}》的第 {arc_current}/{arc_total} 章约束"})
            else:
                logger.warning("interactive_chat_stream: 未找到细纲 %s", arc_name)
                yield _sse_event("thinking", {"stage": "警告", "detail": f"未找到细纲《{arc_name}》，将按普通指令处理"})

        is_free = req.mode == "free"
        mode_hint = "自由创作模式" if is_free else "问答式创作模式"

        # 根据模式决定默认行为
        if is_free:
            mode_rule = (
                "【模式规则 - 自由创作】\n"
                "- 默认行为：根据前文和世界观自主创作下一章。\n"
                "- 如果用户只是闲聊、问问题、讨论设定，直接进行文字回复，不要输出 [CHAPTER]。\n"
                "- 如果用户明确要求创作/生成章节，则输出 [CHAPTER] 并写正文。\n"
            )
        else:
            mode_rule = (
                "【模式规则 - 问答式创作】\n"
                "- 默认行为：与用户进行正常的问答、讨论、剧情梳理、设定解释。直接回复文字。\n"
                "- 只有用户明确表达创作意图时，才生成章节正文。触发创作的关键词包括但不限于：\n"
                "  '创作第X章'、'写第X章'、'生成第X章'、'写下一章'、'创作下一章'、'生成下一章'、\n"
                "  '继续写'、'开始写'、'写正文'、'生成正文' 等。\n"
                "- 如果用户没有明确要求创作（例如问'主角能力是什么'、'这段剧情怎么发展'、'帮我分析一下'），\n"
                "  你只能进行普通对话/分析/建议，绝对不要输出 [CHAPTER]。\n"
                "- 当用户要求创作时，输出 [CHAPTER] 并写正文；否则直接回复文字。\n"
            )

        # task-specific guides：按本章 beat_type 加载战斗/角色/世界观/势力写法指南
        task_guides = ""
        try:
            from novel_agent.orchestrator.nodes import _style_guides_for_beat
            # 复用阶段6提取的 beat_type（如已存在）
            _bt_for_guides = beat_type  # 直接复用前面提取的 beat_type
            if not _bt_for_guides:
                try:
                    _outline_for_guides = repo.get_outline_by_chapter(chapter_num)
                    if _outline_for_guides and _outline_for_guides.required_beats:
                        import json as _bg_json
                        _beats_for_guides = _bg_json.loads(_outline_for_guides.required_beats) if isinstance(_outline_for_guides.required_beats, str) else _outline_for_guides.required_beats
                        if isinstance(_beats_for_guides, list) and _beats_for_guides:
                            if isinstance(_beats_for_guides[0], dict):
                                _bt_for_guides = _beats_for_guides[0].get("type", "")
                            elif isinstance(_beats_for_guides[0], str):
                                _bt_for_guides = " ".join(_beats_for_guides)
                except Exception as e:
                    logger.warning("解析required_beats失败: %s", e)
            task_guides = _style_guides_for_beat(_bt_for_guides, _bt_for_guides) or ""
            if task_guides:
                logger.info("interactive_chat_stream: 注入 task-specific guides (beat=%s)", _bt_for_guides or "通用")
        except Exception as e:
            logger.warning("interactive_chat_stream: task guides 加载失败: %s", e)

        # genre RAG：题材门控，末日/克苏鲁/异能/恐怖题材从 chromadb 检索真实片段
        genre_rag_slices = ""
        try:
            if getattr(cfg, "enable_genre_rag", False) and project.genre:
                from novel_agent.orchestrator.utils import genre_matches_corpus, books_for_beat
                if genre_matches_corpus(project.genre):
                    import chromadb
                    from novel_agent.memory.archival import _build_embedding_function
                    _chroma_dir = cfg.chroma_dir
                    _client_chroma = chromadb.PersistentClient(path=str(_chroma_dir))
                    _ef_chroma = _build_embedding_function(cfg)
                    _coll_chroma = _client_chroma.get_or_create_collection(
                        name="genre_archive_doomsday",
                        metadata={"hnsw:space": "cosine"},
                        embedding_function=_ef_chroma,
                    )
                    if _coll_chroma.count() > 0:
                        _rag_query = (req.message or "") or "通用剧情"
                        _target_books = books_for_beat(_bt_for_guides) if _bt_for_guides else []
                        _rag_kwargs: dict = {"query_texts": [_rag_query], "n_results": 5}
                        if _target_books:
                            _rag_kwargs["where"] = {"source_book": {"$in": _target_books}}
                        _rag_res = _coll_chroma.query(**_rag_kwargs)
                        _rag_docs = _rag_res.get("documents", [[]])[0]
                        _rag_dists = _rag_res.get("distances", [[]])[0]
                        _rag_slices_list = []
                        for _doc, _dist in zip(_rag_docs, _rag_dists):
                            if _dist > 0.7:
                                continue
                            if _doc and _doc.strip():
                                _rag_slices_list.append(_doc)
                        if _rag_slices_list:
                            genre_rag_slices = "\n\n【题材语感切片（来自同类作品，仅供学习写法，不要照抄情节）】\n" + "\n---\n".join(_rag_slices_list)
                            logger.info("interactive_chat_stream: 注入 genre RAG %d 条切片", len(_rag_slices_list))
        except Exception as e:
            logger.warning("interactive_chat_stream: genre RAG 加载失败: %s", e)

        system_prompt = (
            build_writer_system_prompt()
            + "\n\n" + mode_rule
            + "\n\n【重要】无论前文给了多少创作背景资料，你都必须优先遵守上面的【模式规则】。"
            + "\n\n" + core_constraints
            + ("\n\n" + user_reference_block if user_reference_block else "")
            + ("\n\n" + genre_constraints if genre_constraints else "")
            + ("\n\n【CSV参考资料】\n" + csv_refs if csv_refs else "")
            + ("\n\n" + gag_library_text if gag_library_text else "")
            + ("\n\n【语料库章末钩子示例】\n" + corpus_hook_block if corpus_hook_block else "")
            + ("\n\n【人类网文风格参考】\n学习以下人类网文作家的写法技巧（叙事节奏、句式变化、对话处理、场景转换），"
               "但不要抄袭其内容，只学写法不抄故事：\n" + human_style_ref if human_style_ref else "")
            + ("\n\n【人类网文范文】\n" + few_shot if few_shot else "")
            + ("\n\n" + task_guides if task_guides else "")
            + (genre_rag_slices if genre_rag_slices else "")
        )

        prompt = (
            f"【作品信息】\n标题：{project.title}\n题材：{project.genre}\n\n"
        )
        # 项目级硬约束（与 CoreMemoryAssembler._format_project 一致）
        if project.summary:
            prompt += f"【简介】\n{project.summary}\n\n"
        if project.style:
            prompt += f"【风格规范】\n{project.style}\n\n"
        if getattr(project, 'constitution', ''):
            prompt += f"【全书铁律】绝对不得违反\n{project.constitution}\n\n"
        if getattr(project, 'golden_finger', ''):
            try:
                import json as _gf_json
                gf = _gf_json.loads(project.golden_finger) if isinstance(project.golden_finger, str) else project.golden_finger
                gf_text = gf if isinstance(gf, str) else _gf_json.dumps(gf, ensure_ascii=False)
                prompt += f"【金手指核心机制】写作时必须遵守其限制与代价\n{gf_text}\n\n"
            except Exception:
                prompt += f"【金手指核心机制】写作时必须遵守其限制与代价\n{project.golden_finger}\n\n"
        if getattr(project, 'central_concept', ''):
            try:
                import json as _cc_json
                concept = _cc_json.loads(project.central_concept) if isinstance(project.central_concept, str) else project.central_concept
                if isinstance(concept, dict):
                    prompt += f"【全书立意】\n核心爽点：{concept.get('core_hook','')}\n主角长期目标：{concept.get('protagonist_goal','')}\n\n"
                    taboos = concept.get('taboos', [])
                    if taboos:
                        prompt += f"【立意禁忌】违反则废稿\n{', '.join(taboos) if isinstance(taboos, list) else taboos}\n\n"
            except Exception:
                prompt += f"【全书立意】\n{project.central_concept}\n\n"
        if getattr(project, 'target_audience', ''):
            prompt += f"【目标读者】\n{project.target_audience}\n\n"
        prompt += (
            f"【世界观设定】\n{world_text}\n\n"
            f"【角色设定（含动态状态）】\n{chars_text}\n\n"
            f"【伏笔状态】\n{fores_text}\n\n"
            f"【前文记忆 - 全部章节摘要】\n{prev_summary or '（这是第一章，无前文）'}\n\n"
        )
        # 动态注入：角色关系
        char_rels_text = _format_character_relationships_for_prompt(repo)
        if char_rels_text:
            prompt += f"{char_rels_text}\n\n"
        # 动态注入：势力格局
        faction_text = _format_faction_dynamics_for_prompt(repo)
        if faction_text:
            prompt += f"{faction_text}\n\n"
        # 动态注入：支线进度
        subplot_text = _format_subplots_for_prompt(repo)
        if subplot_text:
            prompt += f"{subplot_text}\n\n"
        # 动态注入：当前故事线（主线 + 断线预警 + 最近支线，与叙事线系统联动）
        try:
            from novel_agent.memory.core import format_active_storylines
            storyline_text = format_active_storylines(repo, chapter_num)
            if storyline_text:
                prompt += f"{storyline_text}\n\n"
        except Exception as e:
            logger.debug("交互式创作注入故事线失败: %s", e)
        # 动态注入：上一章结尾
        if prev_ending:
            prompt += (
                f"【上一章结尾（请自然衔接，不要重复）】\n{prev_ending}\n\n"
                "【衔接铁律】本章开头必须紧接上一章结尾的剧情，不得突然换场景、换时间、换人物视角而不做任何过渡；"
                "新剧情必须在已有设定的地基上生长，不能推翻上一章已经发生的事。\n\n"
            )
        # 动态注入：前三章完整正文
        if prev_full_text:
            prompt += f"【前三章完整正文（学习文风、角色语气、世界观细节，不要抄袭情节）】\n{prev_full_text}\n\n"
        # 动态注入：本章大纲约束（若已启用按细纲分章指令，则跳过此处弧段方向注入，避免重复）
        outline_text = ""
        if not arc_split_cmd:
            outline_text = _format_chapter_outline_for_prompt(repo, chapter_num)
        if outline_text:
            prompt += f"{outline_text}\n\n"

        # ── 注入：导入章纲（套壳改写模式） ──
        imported_outline_text = ""
        try:
            from novel_agent.bible.models import ImportedChapter
            imp_ch = repo.db.query(ImportedChapter).filter(
                ImportedChapter.project_id == repo.project_id,
                ImportedChapter.chapter_order == chapter_num
            ).first()
            if imp_ch:
                imported_outline_text = (
                    f"【导入章纲--套壳改写基底（第{chapter_num}章）】\n"
                    f"标题：{imp_ch.title}\n"
                )
                if imp_ch.meta_info:
                    imported_outline_text += f"元信息：{imp_ch.meta_info}\n"
                if imp_ch.chapter_outline:
                    imported_outline_text += f"章纲：{imp_ch.chapter_outline}\n"
                if imp_ch.detail_outline:
                    imported_outline_text += f"细纲：{imp_ch.detail_outline}\n"
                if imp_ch.pleasure_hooks:
                    imported_outline_text += f"爽点/钩子：{imp_ch.pleasure_hooks}\n"
                if imp_ch.shell_annotation:
                    imported_outline_text += f"套壳标注：{imp_ch.shell_annotation}\n"
                imported_outline_text += (
                    "\n【套壳改写要求】\n"
                    "- 严格按照上述章纲和细纲的剧情骨架写正文\n"
                    "- 套壳标注中【骨】保留的部分绝对不可改变\n"
                    "- 套壳标注中【皮】可改的部分可以换皮（人名/地名/系统名等）\n"
                    "- 爽点和钩子必须完整交付\n\n"
                )
                prompt += imported_outline_text
        except Exception as e:
            logger.warning("interactive_chat_stream: 导入章纲加载失败: %s", e)

        # ── 注入：红线（绝对约束） ──
        red_line_text = ""
        try:
            from novel_agent.bible.models import RedLine
            red_lines = repo.db.query(RedLine).filter(
                RedLine.project_id == repo.project_id,
                RedLine.enabled == True
            ).filter(
                (RedLine.scope == "project") |
                ((RedLine.scope == "chapter") & (RedLine.chapter_num == chapter_num))
            ).all()
            if red_lines:
                hard_lines = [r for r in red_lines if r.severity == "hard"]
                soft_lines = [r for r in red_lines if r.severity == "soft"]
                if hard_lines:
                    red_line_text += "【红线--绝对不可违反（违反则废稿）】\n"
                    for i, r in enumerate(hard_lines, 1):
                        scope_tag = f"[第{r.chapter_num}章]" if r.scope == "chapter" else "[全书]"
                        red_line_text += f"{i}. {scope_tag} {r.content}\n"
                    red_line_text += "\n"
                if soft_lines:
                    red_line_text += "【软约束--尽量遵守】\n"
                    for i, r in enumerate(soft_lines, 1):
                        scope_tag = f"[第{r.chapter_num}章]" if r.scope == "chapter" else "[全书]"
                        red_line_text += f"{i}. {scope_tag} {r.content}\n"
                    red_line_text += "\n"
                prompt += red_line_text
        except Exception as e:
            logger.warning("interactive_chat_stream: 红线加载失败: %s", e)

        # ── 注入：梗（笑点/桥段/彩蛋） ──
        gag_text = ""
        try:
            from novel_agent.bible.models import Gag
            gags = repo.db.query(Gag).filter(
                Gag.project_id == repo.project_id,
                Gag.status.in_(["待用", "使用中"])
            ).all()
            if gags:
                gag_text += "【梗--自然融入剧情，不要生硬植入】\n"
                for g in gags:
                    gag_text += f"- [{g.category}] {g.name}：{g.description}\n"
                    if g.usage_notes:
                        gag_text += f"  使用备注：{g.usage_notes}\n"
                gag_text += "\n"
                prompt += gag_text
        except Exception as e:
            logger.warning("interactive_chat_stream: 梗加载失败: %s", e)

        # ── 注入：Skills（启用的能力约束，带上下文按需加载） ──
        try:
            from novel_agent.api.routes_skills import load_enabled_skills_for_injection_with_context
            # 用章节标题+大纲作为上下文，让 book-to-skill 技能按需加载相关 section
            skill_context = f"第{chapter_num}章 {outline_title or ''} {outline_summary or ''}"
            skills_inject_text = load_enabled_skills_for_injection_with_context(skill_context)
            if skills_inject_text:
                prompt += skills_inject_text + "\n"
        except Exception as e:
            logger.warning("interactive_chat_stream: Skills 加载失败: %s", e)

        prompt += (
            f"【创作模式】{mode_hint}\n"
            f"【当前章节号】第 {chapter_num} 章\n"
        )
        if user_direction:
            prompt += f"【作者指示】{user_direction}\n\n"
        else:
            prompt += "【作者指示】（无特定指示，请基于世界观和前文自主推进剧情）\n\n"

        # 问答模式下，如果不是明确创作指令，再次强调不要生成章节
        if not is_free and not _looks_like_creation_command(user_direction):
            prompt += (
                "【当前消息判断】用户刚才的这条消息只是普通对话/提问/讨论，没有表达创作意图。\n"
                "你必须直接回复文字进行回答或讨论，绝对禁止输出 [CHAPTER] 标记，绝对禁止生成章节正文。\n\n"
            )

        prompt += history_text + "\n\n"
        prompt += (
            f"请根据上述【模式规则】判断用户意图，然后选择以下一种方式回复：\n"
            f"- 如果要生成第 {chapter_num} 章正文，第一行必须写 [CHAPTER]，第二行写标题（格式：第{chapter_num}章 标题），第三行开始写正文。字数要求：{min_words}-{max_words} 字。\n"
            f"- 如果只是普通对话/讨论/问答，直接回复文字，不要加 [CHAPTER] 标记。\n"
        )

        # ── 阶段8：调用 LLM 流式生成 ──
        # 诊断日志：确认各约束组件是否成功加载
        logger.debug(
            "interactive_chat_stream: 阶段8诊断 - mode=%s, chapter=%d, "
            "core_constraints=%d字, csv_refs=%d字, genre_constraints=%d字, "
            "few_shot=%d字, human_style=%d字, corpus_hooks=%d字, "
            "user_refs=%d字, task_guides=%d字, genre_rag=%d字, "
            "outline=%d字, prev_summary=%d字, prev_full=%d字, prev_ending=%d字, "
            "imported_outline=%d字, red_lines=%d字, gags=%d字, gag_library=%d字, "
            "prompt_total=%d字, system_total=%d字",
            req.mode, chapter_num,
            len(core_constraints or ""), len(csv_refs or ""), len(genre_constraints or ""),
            len(few_shot or ""), len(human_style_ref or ""), len(corpus_hook_block or ""),
            len(user_reference_block or ""), len(task_guides or ""), len(genre_rag_slices or ""),
            len(outline_text or ""), len(prev_summary or ""), len(prev_full_text or ""), len(prev_ending or ""),
            len(imported_outline_text or ""), len(red_line_text or ""), len(gag_text or ""),
            len(gag_library_text or ""),
            len(prompt or ""), len(system_prompt or ""),
        )
        yield _sse_event("thinking", {
            "stage": "AI 正在创作",
            "detail": f"正在生成第 {chapter_num} 章... 预计 {min_words}-{max_words} 字，需要 3-15 分钟"
        })

        # 检查客户端断开
        is_disconnected = False
        skip_auto_polish = False  # 工作流路径：三路审校+双重润色已在 _run_mvp_and_polish 内完成，跳过阶段9.5自动润色

        client = None
        accumulated = ""
        is_chapter = None  # None=未确定, True/False=已确定
        title = ""
        title_extracted = False

        # 工作流模式仅在明确创作指令时触发（QA 模式已在上方过滤，free 模式需二次检查）
        should_use_workflow = req.use_workflow and (
            not is_free or _looks_like_creation_command(user_direction)
        )

        if should_use_workflow:
            # ── 阶段8-WF：MVP 26-agent 工作流路径（资产桥接彻底接通） ──
            yield _sse_event("type", {"type": "chapter"})
            is_chapter = True
            wf_result_tuple = None
            try:
                async for wf_evt in _run_mvp_and_polish_for_interactive(
                    request, req, cfg, chapter_num, user_direction, min_words, max_words
                ):
                    if "__wf_result__" in wf_evt:
                        wf_result_tuple = wf_evt["__wf_result__"]
                    else:
                        yield wf_evt
            except Exception as e:
                logger.error("interactive_chat_stream: MVP工作流异常: %s", e, exc_info=True)
                yield _sse_event("error", {"error": f"MVP 工作流异常：{e}"})
                return

            if wf_result_tuple is None:
                yield _sse_event("error", {"error": "MVP 工作流未返回结果"})
                return

            accumulated, title, is_disconnected = wf_result_tuple
            title_extracted = True  # 工作流已提取标题
            skip_auto_polish = True  # 三路审校+双重润色已完成，阶段9.5无需再润色

            if is_disconnected:
                logger.info("interactive_chat_stream: 工作流客户端断开连接")
                return

            if not accumulated:
                logger.error("interactive_chat_stream: MVP工作流未产出正文")
                return

            # 推送正文给前端（一次性推送，非流式 token）
            yield _sse_event("chunk", {"content": accumulated})
            logger.info("interactive_chat_stream: MVP工作流完成, content_len=%d", len(accumulated))

        else:
            # ── 阶段8-SA：单 agent 直生成路径（原有逻辑） ──
            client = LLMClient(cfg.get_agent_llm("writer"))

            if req.num_variants > 1:
                # ── 阶段8-V：抽卡模式（生成 N 个候选版本，等待用户选 1） ──
                # 仅单 agent 路径支持抽卡；生成完后推送 variants + await_variant_choice，
                # 不进入润色/审校/人审，等用户选择后由 variant/resume 端点继续。
                variants: list[dict] = []
                try:
                    for vi in range(req.num_variants):
                        if await request.is_disconnected():
                            is_disconnected = True
                            break
                        yield _sse_event("thinking", {
                            "stage": f"抽卡生成第 {vi + 1}/{req.num_variants} 版",
                            "detail": f"正在生成第 {vi + 1} 个候选版本（共 {req.num_variants} 个）..."
                        })
                        acc = ""
                        async for chunk in client.stream_generate(prompt, system=system_prompt, max_tokens=128000):
                            if await request.is_disconnected():
                                is_disconnected = True
                                break
                            acc += chunk
                            if chunk:
                                # 保持流式：逐 token 推送当前版本生成进度
                                yield _sse_event("variant_chunk", {"index": vi, "content": chunk})
                        if is_disconnected:
                            break
                        if not acc.strip():
                            yield _sse_event("thinking", {"stage": f"第 {vi + 1} 版生成失败", "detail": "AI 返回空内容，跳过该版本..."})
                            continue
                        v_title, v_clean = _extract_chapter_title_clean(acc, chapter_num)
                        variants.append({
                            "index": vi,
                            "title": v_title,
                            "content": v_clean,
                            "word_count": count_chinese_chars(v_clean),
                        })
                except Exception as e:
                    logger.error("interactive_chat_stream: 抽卡模式生成失败: %s", e, exc_info=True)
                    yield _sse_event("error", {"error": f"抽卡模式生成失败：{e}"})
                    return

                if is_disconnected:
                    logger.info("interactive_chat_stream: 抽卡模式客户端断开连接")
                    return

                if not variants:
                    yield _sse_event("error", {"error": "抽卡模式所有候选版本均生成失败，请重试"})
                    return

                # 暂存 N 个版本到 session store，供 variant/resume 端点取用
                import uuid as _uuid
                get_session_store().cleanup_expired_interactive()
                thread_id = f"interactive_variants_{req.project_id}_{chapter_num}_{_uuid.uuid4().hex[:8]}"
                get_session_store().save_interactive(thread_id, req.project_id, {
                    "project_id": req.project_id,
                    "chapter_num": chapter_num,
                    "title": variants[0]["title"],
                    "variants": variants,
                    "num_variants": len(variants),
                    "created_at": datetime.utcnow().isoformat(),
                })

                # 推送候选版本 + 等待用户选择事件，随后结束本函数
                yield _sse_event("variants", {
                    "thread_id": thread_id,
                    "variants": variants,
                })
                yield _sse_event("await_variant_choice", {
                    "thread_id": thread_id,
                    "message": f"已生成 {len(variants)} 个候选版本，请选择一版后继续（润色→审校→人审）",
                })
                logger.info("interactive_chat_stream: 抽卡模式完成，thread_id=%s, 版本数=%d", thread_id, len(variants))
                return

            try:
                async for chunk in client.stream_generate(prompt, system=system_prompt, max_tokens=128000):
                    if await request.is_disconnected():
                        is_disconnected = True
                        break

                    accumulated += chunk

                    # 阶段A：确定回复类型
                    if is_chapter is None:
                        if "[CHAPTER]" in accumulated[:100]:
                            is_chapter = True
                            yield _sse_event("type", {"type": "chapter"})
                        elif len(accumulated) >= 100:
                            is_chapter = False
                            yield _sse_event("type", {"type": "chat"})
                            yield _sse_event("chunk", {"content": accumulated})
                        else:
                            continue  # 继续积累，等足够内容再判断

                    # 阶段B（仅章节模式）：提取标题行
                    if is_chapter and not title_extracted:
                        if accumulated.count("\n") >= 2:
                            lines = accumulated.split("\n", 2)
                            title = lines[1].strip()
                            content = lines[2] if len(lines) > 2 else ""
                            title_extracted = True
                            if content:
                                yield _sse_event("chunk", {"content": content})
                        continue  # 继续等待标题行完成

                    # 阶段C：正常流式输出
                    if chunk:
                        yield _sse_event("chunk", {"content": chunk})
            except Exception as e:
                logger.error("interactive_chat_stream: LLM流式生成失败: %s", e, exc_info=True)
                yield _sse_event("error", {"error": f"AI 生成失败：{e}"})
                return

            if is_disconnected:
                logger.info("interactive_chat_stream: 客户端断开连接")
                return

            logger.info("interactive_chat_stream: LLM流式完成, is_chapter=%s, content_len=%d", is_chapter, len(accumulated))

        # ── 阶段9：后处理 + 质检（AI 工作室模式：生成->audit->人审->润色->提交） ──
        full_text = accumulated
        if not full_text.strip():
            yield _sse_event("error", {"error": "AI 返回了空内容，请重试"})
            return
        if is_chapter:
            # 提取标题和正文
            if not title:
                # 先剥离 [CHAPTER] 标记，避免误提取为标题
                temp = full_text
                if temp.startswith("[CHAPTER]"):
                    temp = temp[9:].lstrip("\n")
                lines = temp.split("\n", 2)
                if len(lines) >= 2:
                    title = lines[0].strip() if lines[0].strip() else lines[1].strip()
                    full_text = lines[2] if len(lines) > 2 else full_text
                else:
                    title = f"第{chapter_num}章"
            # 清理正文中的 [CHAPTER] 标记和标题行
            clean = full_text
            if clean.startswith("[CHAPTER]"):
                clean = clean[9:].lstrip("\n")
            title_pattern = re.compile(r"^#*\s*第\d+章\s+.+?\n", re.MULTILINE)
            clean = title_pattern.sub("", clean, count=1)
            clean = clean.strip()

            # 复用阶段9核心流程（润色→暂存→draft→audit→review_pending）
            async for _evt in _interactive_chapter_postprocess(
                request, cfg, repo, client, chapter_num, clean, title,
                skip_auto_polish=skip_auto_polish,
            ):
                yield _evt
            # 注意：这里不 yield done，等 /resume 端点触发后续流程
        else:
            # 普通对话
            yield _sse_event("done", {
                "type": "chat",
                "message": full_text,
            })

    except Exception as e:
        logger.error("interactive_chat_stream: 未捕获异常: %s", e, exc_info=True)
        yield _sse_event("error", {"error": f"服务器错误：{e}"})
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning("LLM client关闭失败: %s", e)
        db.close()


@router.post("/interactive/chat/stream")
async def interactive_chat_stream_endpoint(request: Request, req: InteractiveChatRequest):
    """交互式创作流式端点。SSE 响应。"""
    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(interactive_chat_stream(request, req), ping=15)


# ==================== 交互式创作：人审决策恢复 ====================

class InteractiveResumeRequest(BaseModel):
    thread_id: str
    decision: str = "approve"   # approve / rewrite / polish
    feedback: str = ""          # 用户的修改意见（rewrite 时注入）
    project_id: int = 0         # 用于重建 db session
    deep_polish: bool = False   # 是否启用 oh-story 深度润色（默认关闭，速度更快）


async def _interactive_summarize_and_commit(
    content: str, chapter: int, title: str,
    repo: BibleRepository, recall: RecallMemory, cfg,
    save_to_recall: bool = True,
) -> dict:
    """调用 summarize_chapter 节点 + DeltaApplier 提交圣经。
    返回提交结果 dict（含 summary/deltas/events/foreshadows 等）。
    """
    from novel_agent.orchestrator.nodes import summarize_chapter
    from novel_agent.memory.archival import ArchivalMemory
    from novel_agent.protocol.applier import DeltaApplier

    # 保存正文到 recall（正式落盘）
    if save_to_recall:
        recall.save_chapter_text(chapter, title, content)

    summarizer_client = LLMClient(cfg.get_agent_llm("summarizer"))
    try:
        archival = ArchivalMemory(cfg, project_id=repo.project_id)
    except Exception as e:
        logger.warning("ArchivalMemory 初始化失败，降级为 None: %s", e)
        archival = None
    applier = DeltaApplier(repo, archival=archival)
    try:
        state = {
            "chapter": chapter,
            "title": title,
            "draft": content,
            "polished": content,
            "word_count": count_chinese_chars(content),
        }
        result = await summarize_chapter(state, summarizer_client, applier, repo=repo)
        # summarize_chapter 返回 {"status": ..., "summary_id": ...}
        # 提取实际写入的摘要
        cs = repo.get_chapter_summary(chapter)
        summary_text = cs.core_events if cs and cs.core_events else content[:200]
        # 索引到 archival 供后续语义检索
        try:
            archival.index_chapter(chapter, title, content)
        except Exception as e:
            logger.warning("interactive commit: archival 索引失败: %s", e)

        # 阶段0：统一章节后处理——补出场记录/新实体/关系/事件/世界观/伏笔更新（P0#1/#2、P1#8/#10/#11）
        # summarize_chapter 已写摘要与角色状态，这里传 False 防双写；archival 已索引，index=False
        pp_stats: dict = {}
        try:
            pp_client = LLMClient(cfg.get_agent_llm("summarizer"))
            try:
                pp = await chapter_postprocess(
                    repo, cfg, chapter, content, title,
                    client=pp_client, write_summary=False, write_char_state=False, index=False,
                )
                if pp.get("ok"):
                    pp_stats = {k: pp.get(k, 0) for k in (
                        "appearances", "relationships", "events", "foreshadow_updates",
                        "new_characters", "new_factions", "new_monsters", "new_world_settings",
                    )}
            finally:
                await pp_client.close()
        except Exception as e:
            logger.warning("interactive commit: 章节后处理失败（不影响提交）: %s", e)

        return {
            "status": result.get("status", "completed"),
            "summary": summary_text,
            "chapter_summary": {
                "title": cs.title if cs else title,
                "core_events": cs.core_events if cs else "",
                "characters_present": cs.characters_present if cs else "",
                "foreshadow_dynamics": cs.foreshadow_dynamics if cs else "",
                "chapter_hook": cs.chapter_hook if cs else "",
                "word_count": cs.word_count if cs else 0,
            } if cs else {},
            "postprocess": pp_stats,
        }
    finally:
        await summarizer_client.close()


@router.post("/interactive/chat/resume")
@limiter.limit("10/minute")
async def interactive_chat_resume(request: Request, req: InteractiveResumeRequest):
    """交互式创作人审决策恢复端点。

    流程原则：人审永远在润色之后，用户看到的版本就是可能提交的最终版本。

    decision:
    - approve: 直接对当前润色版走 summarize+commit（不再二次润色）
    - polish:  先对当前润色版再做一次 style_refine，然后 audit -> review_pending
    - rewrite: 根据用户 feedback 重新生成 -> 自动润色 -> audit -> review_pending
    """
    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        db = SessionLocal()
        try:
            cfg = load_config(Path(os.environ.get("NOVEL_CONFIG_PATH", "config.yaml")))
            set_config(cfg)
            session = get_session_store().get_interactive(req.thread_id)
            if not session:
                yield _sse_event("error", {"error": f"会话 {req.thread_id} 不存在或已过期"})
                return

            project_id = req.project_id or session["project_id"]
            chapter_num = session["chapter_num"]
            save_title = session["title"]

            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                yield _sse_event("error", {"error": f"项目 {project_id} 不存在"})
                return
            repo = BibleRepository(db, project_id)
            recall = RecallMemory(cfg, project_id=project_id)

            decision = req.decision.strip().lower()
            if decision not in ("approve", "rewrite", "polish"):
                yield _sse_event("error", {"error": f"未知决策：{decision}（支持 approve/rewrite/polish）"})
                return

            # ── rewrite 分支：重新生成 + 自动润色 + audit + review_pending ──
            if decision == "rewrite":
                yield _sse_event("thinking", {"stage": "重写中", "detail": f"根据反馈重新生成第 {chapter_num} 章..."})

                if await request.is_disconnected():
                    logger.info("interactive resume rewrite: 客户端已断开，提前结束")
                    return

                feedback = (req.feedback or "").strip()
                from novel_agent.audit.validator import _get_threshold as _gh_thr

                # 收集上一轮审校和确定性检查发现的 AI 味/文风问题，作为重写硬约束
                prev_audit = session.get("audit_report") or {}
                prev_issues = prev_audit.get("issues", []) or []
                ai_flavor_issues = [
                    i for i in prev_issues
                    if i.get("dimension") in ("限频词", "句长分布", "对话占比", "段落碎片化")
                    or "AI" in (i.get("dimension") or "")
                    or "AI" in (i.get("message") or "")
                    or i.get("dimension", "").startswith("AI模式-")
                ]
                # 跑确定性检查，把具体命中词/模式补充进去
                det_check = run_deterministic_checks(
                    session.get("draft", ""),
                    word_min=int(_gh_thr("字数下限", 2200)),
                    word_max=int(_gh_thr("字数上限", 3500)),
                )
                det_issues = det_check.get("issues", [])
                det_ai_issues = [i for i in det_issues if i.get("dimension") in ("限频词", "句长分布", "对话占比", "段落碎片化") or i.get("dimension", "").startswith("AI模式-")]

                client = LLMClient(cfg.get_agent_llm("writer"))
                try:
                    rewrite_prompt = (
                        f"请重写小说《{project.title}》第{chapter_num}章《{save_title}》。\n\n"
                        f"【原稿（请勿照抄，仅参考剧情骨架）】\n{session['draft']}\n\n"
                    )
                    if feedback:
                        rewrite_prompt += f"【用户反馈（必须解决）】\n{feedback}\n\n"
                    if ai_flavor_issues or det_ai_issues:
                        rewrite_prompt += "【上一轮 AI 审校发现的语言质量问题（本轮必须避免）】\n"
                        for i in ai_flavor_issues + det_ai_issues:
                            rewrite_prompt += f"- [{i.get('severity', 'important')}] {i.get('dimension')}: {i.get('message')}\n"
                        rewrite_prompt += "\n"
                    rewrite_prompt += (
                        f"【重写铁律】\n"
                        f"1. 保留原稿的核心剧情骨架、角色互动、伏笔回收和爽点设计\n"
                        f"2. 针对用户反馈和上述语言质量问题逐条改进，不得再犯同样问题\n"
                        f"3. 严格控制 AI 味：禁用深吸一口气、心跳如擂鼓、嘴角上扬、瞳孔一缩、后背发凉等黑名单表达\n"
                        f"4. 抽象情绪必须转化为具体动作或生理反应，禁止'他感到一阵XX涌上心头'\n"
                        f"5. 每千字比喻不超过1-2个，喻体用日常具象物，禁止华丽抒情比喻\n"
                        f"6. 感叹号每段最多2个，叙事描写不用感叹号\n"
                        f"7. 连续4个以上相同句式必须打断，只保留前2个\n"
                        f"8. 对话提示语精简，连续对话靠语气区分角色\n"
                        f"9. 字数 {_gh_thr('字数下限', 2200):.0f}-{_gh_thr('字数上限', 3500):.0f}\n"
                        f"10. 第一行 [CHAPTER]，第二行标题，第三行开始正文\n"
                    )
                    from novel_agent.templates.style_guide_loader import get_core_constraints
                    from novel_agent.orchestrator.prompts import build_writer_system_prompt
                    system_prompt = build_writer_system_prompt() + "\n\n" + (get_core_constraints() or "")

                    accumulated = ""
                    async for chunk in client.stream_generate(rewrite_prompt, system=system_prompt, max_tokens=128000):
                        if await request.is_disconnected():
                            break
                        accumulated += chunk
                        # 流式推送重写过程
                        if chunk:
                            yield _sse_event("chunk", {"content": chunk, "stage": "rewrite"})

                    # 用户断开则立即终止，避免继续执行润色+审校（各 1-3 分钟 LLM 调用）
                    if await request.is_disconnected():
                        logger.info("interactive resume rewrite: 用户断开，终止后续润色/审校")
                        return

                    # 清理提取
                    clean = accumulated
                    if clean.startswith("[CHAPTER]"):
                        clean = clean[9:].lstrip("\n")
                    title_pattern = re.compile(r"^#*\s*第\d+章\s+.+?\n", re.MULTILINE)
                    clean = title_pattern.sub("", clean, count=1).strip()

                    if not clean:
                        yield _sse_event("error", {"error": "重写生成的内容为空"})
                        return

                    # ── 重写后自动润色去 AI 味 ──
                    yield _sse_event("thinking", {"stage": "润色去 AI 味", "detail": "正在对重写稿进行文风净化..."})
                    polished_clean = clean
                    polish_issues: list[str] = []
                    try:
                        polish_state = {
                            "chapter": chapter_num,
                            "title": save_title,
                            "draft": clean,
                            "drafts": [{"version": 1, "text": clean, "score": 0}],
                        }
                        polish_result = await polish_chapter(polish_state, client, skip_deslop=True)
                        if polish_result.get("polished"):
                            polished_clean = polish_result["polished"]
                            polish_issues = polish_result.get("polish_review_issues", [])
                    except Exception as e:
                        logger.warning("interactive resume rewrite: 润色失败，使用原稿: %s", e)

                    new_word_count = count_chinese_chars(polished_clean)
                    # 更新 session
                    session["draft"] = polished_clean
                    session["raw_draft"] = clean
                    session["word_count"] = new_word_count
                    session["polished"] = polished_clean
                    session["polish_issues"] = polish_issues
                    session["review_iterations"] = session.get("review_iterations", 0) + 1
                    get_session_store().save_interactive(req.thread_id, project_id, session)

                    yield _sse_event("draft", {
                        "chapter": chapter_num,
                        "title": save_title,
                        "content": polished_clean,
                        "word_count": new_word_count,
                        "thread_id": req.thread_id,
                        "iteration": session["review_iterations"],
                        "polish_issues": polish_issues,
                    })

                    # 重跑 audit
                    yield _sse_event("thinking", {"stage": "AI 审校中", "detail": "正在对重写+润色稿进行三视角审校..."})
                    from novel_agent.audit.auditor import Auditor
                    auditor_client = LLMClient(cfg.get_agent_llm("auditor"))
                    debater_client = LLMClient(cfg.get_agent_llm("debater"))
                    auditor = Auditor(auditor_client, writer_client=client, debater_client=debater_client)
                    try:
                        audit_report = await auditor.audit(
                            chapter=chapter_num, title=save_title, draft=polished_clean, repo=repo,
                        )
                        audit_report_dict = audit_report.model_dump()
                    finally:
                        await auditor_client.close()
                        await debater_client.close()

                    session["audit_report"] = audit_report_dict
                    get_session_store().save_interactive(req.thread_id, project_id, session)
                    yield _sse_event("audit", {"thread_id": req.thread_id, "report": audit_report_dict})
                    yield _sse_event(*_build_review_pending_event(
                        req.thread_id, chapter_num, save_title, new_word_count, audit_report_dict,
                        polished=True, iteration=session["review_iterations"],
                    ))
                    return
                finally:
                    if client is not None:
                        try:
                            await client.close()
                        except Exception as e:
                            logger.warning("LLM client关闭失败: %s", e)

            # ── polish 分支：再润色 -> audit -> review_pending（给人再审） ──
            if decision == "polish":
                yield _sse_event("thinking", {"stage": "AI 润色中", "detail": f"正在对第 {chapter_num} 章进行三路审校 + 双重润色（AI味/声线/情感 + 人文化/专业润色）..."})

                if await request.is_disconnected():
                    logger.info("interactive resume polish: 客户端已断开，提前结束")
                    return

                draft_to_refine = session["draft"]

                # 把当前草稿写入工作区 story/{chapter}/chapter.md，供 polish.json 读取
                workspace = cfg.project_dir(project_id)
                chapter_str = f"{chapter_num:04d}"
                story_dir = workspace / "story" / chapter_str
                story_dir.mkdir(parents=True, exist_ok=True)
                (story_dir / "chapter.md").write_text(draft_to_refine, encoding="utf-8")

                # 运行 polish.json（三路审校 + 双重润色），替代老的单模型 polish_chapter。
                # 注：polish.json 的 agent_pp（专业润色）已覆盖旧 deep_polish 的效果，
                #     故此处不再按 req.deep_polish 分叉；deep_polish 字段保留供前端兼容。
                polished = draft_to_refine
                polish_issues: list[str] = []
                try:
                    async for evt in _run_polish_for_interactive(request, cfg, project_id, chapter_num, workspace):
                        if "__polish_result__" in evt:
                            _res = evt["__polish_result__"]
                            if _res and _res.strip():
                                polished = _res
                        else:
                            yield evt
                except Exception as e:
                    logger.error("interactive resume: polish.json 润色失败: %s", e, exc_info=True)
                    yield _sse_event("thinking", {"stage": "⚠ 润色管线异常", "detail": f"润色失败：{e}，沿用当前版本"})
                if not polished or not polished.strip():
                    polished = draft_to_refine

                # 收集 AI 味检测报告作为 polish_issues（供前端展示）
                _ai_txt = workspace / "cache" / "ai_issues.txt"
                if _ai_txt.exists():
                    _content = _ai_txt.read_text(encoding="utf-8").strip()
                    if _content:
                        polish_issues = [l for l in _content.splitlines() if l.strip()][:20]

                # 深度润色：polish.json 已做专业润色，开启深度时再追加 oh-story 7 Gate 后处理（仅1遍）
                if req.deep_polish and polished and polished.strip():
                    yield _sse_event("thinking", {"stage": "深度润色", "detail": "已开启深度润色，正在追加 oh-story 7 Gate 后处理..."})
                    try:
                        from novel_agent.orchestrator.nodes import polish_chapter
                        _deep_client = LLMClient(cfg.get_agent_llm("polisher"))
                        try:
                            _state = {
                                "chapter": chapter_num,
                                "title": save_title,
                                "draft": polished,
                                "drafts": [{"version": 1, "text": polished}],
                                "word_count": count_chinese_chars(polished),
                            }
                            _res = await polish_chapter(
                                _state, _deep_client, repo=repo,
                                skip_deslop=False, max_passes=1,
                            )
                            if _res.get("polished"):
                                polished = _res["polished"]
                        finally:
                            await _deep_client.close()
                    except Exception as e:
                        logger.warning("interactive resume polish: 深度润色失败，沿用 polish.json 结果: %s", e)

                if await request.is_disconnected():
                    logger.info("interactive resume polish: 润色完成后客户端已断开，不再推送后续事件")
                    return

                session["polished"] = polished
                session["polish_issues"] = polish_issues
                get_session_store().save_interactive(req.thread_id, project_id, session)
                polished_wc = count_chinese_chars(polished)

                # 推送润色后的新版本（前端替换展示），但先不提交
                yield _sse_event("refined", {
                    "thread_id": req.thread_id,
                    "chapter": chapter_num,
                    "title": save_title,
                    "content": polished,
                    "word_count": polished_wc,
                    "polish_issues": polish_issues,
                    "original_word_count": session["word_count"],
                })

                # 重跑 audit
                yield _sse_event("thinking", {"stage": "AI 审校中", "detail": "正在对润色稿进行三视角审校..."})
                from novel_agent.audit.auditor import Auditor
                auditor_client = LLMClient(cfg.get_agent_llm("auditor"))
                debater_client = LLMClient(cfg.get_agent_llm("debater"))
                try:
                    auditor = Auditor(auditor_client, debater_client=debater_client)
                    audit_report = await auditor.audit(
                        chapter=chapter_num, title=save_title, draft=polished, repo=repo,
                    )
                    audit_report_dict = audit_report.model_dump()
                finally:
                    await auditor_client.close()
                    await debater_client.close()

                session["audit_report"] = audit_report_dict
                get_session_store().save_interactive(req.thread_id, project_id, session)
                yield _sse_event("audit", {"thread_id": req.thread_id, "report": audit_report_dict})
                yield _sse_event(*_build_review_pending_event(
                    req.thread_id, chapter_num, save_title, polished_wc, audit_report_dict,
                    polished=True, iteration=session.get("review_iterations", 0),
                ))
                return

            # ── approve 分支：直接提交当前润色版（不再二次润色） ──
            polished = session.get("polished") or session["draft"]
            polished_wc = count_chinese_chars(polished)

            yield _sse_event("thinking", {"stage": "提交圣经", "detail": f"正在提取章节事实并写入圣经（角色状态/伏笔/摘要）..."})

            if await request.is_disconnected():
                logger.info("interactive resume approve: 客户端已断开，提前结束")
                return

            try:
                commit_result = await _interactive_summarize_and_commit(
                    polished, chapter_num, save_title, repo, recall, cfg,
                    save_to_recall=True,
                )
            except Exception as e:
                logger.error("interactive resume: 提交失败: %s", e, exc_info=True)
                yield _sse_event("error", {"error": f"圣经提交失败：{e}"})
                return

            # 检查提交结果有无错误
            commit_status = commit_result.get("status", "")
            if commit_status == "failed":
                yield _sse_event("error", {"error": f"提交圣经失败：{commit_result.get('error', '未知错误')}"})
                return

            yield _sse_event("commit", {
                "thread_id": req.thread_id,
                "chapter": chapter_num,
                "title": save_title,
                "result": commit_result,
            })

            # 清理会话
            get_session_store().delete_interactive(req.thread_id)

            yield _sse_event("done", {
                "type": "chapter_committed",
                "chapter": chapter_num,
                "title": save_title,
                "content": polished,
                "word_count": polished_wc,
                "brief": commit_result.get("summary", ""),
                "commit_result": commit_result,
            })
        except Exception as e:
            logger.error("interactive_chat_resume: 未捕获异常: %s", e, exc_info=True)
            yield _sse_event("error", {"error": f"服务器错误：{e}"})
        finally:
            db.close()

    # ping=15：每 15 秒发心跳注释行，防止 LLM 调用期间（首 token 前 1-3 分钟）
    # 经 Vite/Nginx 代理（默认 60s 超时）被切断连接。
    return EventSourceResponse(event_generator(), ping=15)


class InteractiveVariantResumeRequest(BaseModel):
    thread_id: str
    selected_index: int          # 用户选中的候选版本下标（0 起）
    project_id: int = 0          # 用于重建 db session


@router.post("/interactive/variant/resume")
@limiter.limit("10/minute")
async def interactive_variant_resume(request: Request, req: InteractiveVariantResumeRequest):
    """抽卡模式：用户选中第几版后，对该版本继续 润色->审校->人审。

    从 session store 取出抽卡时暂存的 N 个候选版本，根据 selected_index 取
    出选中版本，然后复用阶段9核心流程（_interactive_chapter_postprocess）。
    """
    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        db = SessionLocal()
        client = None
        try:
            cfg = load_config(Path(os.environ.get("NOVEL_CONFIG_PATH", "config.yaml")))
            set_config(cfg)
            session = get_session_store().get_interactive(req.thread_id)
            if not session:
                yield _sse_event("error", {"error": f"会话 {req.thread_id} 不存在或已过期"})
                return

            variants = session.get("variants") or []
            if not variants:
                yield _sse_event("error", {"error": "未找到候选版本，请重新抽卡"})
                return

            if req.selected_index < 0 or req.selected_index >= len(variants):
                yield _sse_event("error", {"error": f"selected_index 越界：{req.selected_index}（共 {len(variants)} 版）"})
                return

            selected = variants[req.selected_index]
            clean = selected.get("content", "")
            title = selected.get("title", "")
            if not clean.strip():
                yield _sse_event("error", {"error": f"选中版本（第 {req.selected_index + 1} 版）内容为空，请选择其他版本"})
                return

            project_id = req.project_id or session["project_id"]
            chapter_num = session["chapter_num"]

            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                yield _sse_event("error", {"error": f"项目 {project_id} 不存在"})
                return
            repo = BibleRepository(db, project_id)

            yield _sse_event("thinking", {
                "stage": "已选中候选版本",
                "detail": f"你选择了第 {req.selected_index + 1} 版，正在对它进行润色→审校→人审..."
            })

            client = LLMClient(cfg.get_agent_llm("writer"))
            try:
                async for evt in _interactive_chapter_postprocess(
                    request, cfg, repo, client, chapter_num, clean, title,
                    skip_auto_polish=False,
                    thread_id=req.thread_id,
                ):
                    yield evt
            finally:
                if client is not None:
                    await client.close()
                client = None
        except Exception as e:
            logger.error("interactive_variant_resume: 未捕获异常: %s", e, exc_info=True)
            yield _sse_event("error", {"error": f"服务器错误：{e}"})
        finally:
            db.close()

    return EventSourceResponse(event_generator(), ping=15)


# ============================================================
# 流式生成端点（SSE）：生成一条推送一条，支持前端中断
# ============================================================

def _sse_event(event: str, data: dict) -> dict:
    """构造一个 SSE 事件 dict。"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}


def _build_review_pending_event(
    thread_id: str,
    chapter_num: int,
    title: str,
    word_count: int,
    audit_report: dict,
    polished: bool,
    iteration: int | None = None,
) -> tuple[str, dict]:
    """组装 review_pending SSE 事件（收敛三处重复推送逻辑）。

    首次审校（_interactive_chapter_postprocess）无 iteration 字段；
    rewrite / polish 分支带 iteration（重写/润色轮次，供前端区分）。
    """
    payload: dict = {
        "thread_id": thread_id,
        "chapter": chapter_num,
        "title": title,
        "word_count": word_count,
        "passed": audit_report.get("passed", False),
        "overall_score": audit_report.get("overall_score", 0),
        "summary": audit_report.get("summary", ""),
        "issues": audit_report.get("issues", []),
        "suggestions": audit_report.get("suggestions", []),
        "options": ["approve", "rewrite", "polish"],
        "polished": polished,
    }
    if iteration is not None:
        payload["iteration"] = iteration
    return "review_pending", payload


async def _check_disconnected(request: Request) -> bool:
    """检查前端是否已断开连接（用户点了停止按钮）。"""
    try:
        return await request.is_disconnected()
    except Exception:
        return False


@router.get("/arcs/generate/stream")
async def generate_arcs_stream(request: Request, project_id: int, parent_id: int,
                               count: int = 5, custom_prompt: str = ""):
    """细纲生成流式端点。每生成一条落库后推送 item 事件。"""
    from sse_starlette.sse import EventSourceResponse

    init_error = None
    db = repo = project = cfg = client = volume = None
    try:
        db, repo, project, cfg = _get_repo(project_id)
        volume = repo.get_outline(parent_id)
        if not volume or volume.level != "volume":
            init_error = "卷级大纲不存在"
        else:
            client = LLMClient(cfg.get_agent_llm("outliner"))
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"

    async def event_generator():
        if init_error:
            yield _sse_event("error", {"error": init_error, "partial_count": 0})
            if db:
                db.close()
            return

        consistency = _build_consistency_constraint(repo, project)
        existing_arcs = repo.list_outlines(level="arc", parent_id=parent_id)
        existing_titles = {_clean_text(a.title).strip() for a in existing_arcs}
        used_orders = {a.order for a in existing_arcs if a.order}

        def _next_arc_order():
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        # ========== 全局节奏规划 pre-pass ==========
        total_to_generate = count
        blueprint: list[dict] = []
        try:
            blueprint_system = "你是资深网文大纲师，擅长全局规划一卷的节奏分布。只输出 JSON。"
            blueprint_prompt = f"""请为以下卷规划 {total_to_generate} 个细纲小节的节奏蓝图。

卷标题：{volume.title}
卷概要：{volume.summary}
题材：{project.genre}
{custom_prompt and "额外要求：" + custom_prompt}

【act 分配铁律】
- 全卷只有 1 个"大高潮"（倒数第 2-3 节）
- 全卷只有 1 个"结局"（最后 1 节）
- "小高潮"不超过总数的 1/4，分散在发展期
- "转折"不超过总数的 1/4，分散在发展期
- 前 10-15% 用"开端"
- 中间大部分用"发展"
- 禁止"终章"

【输出要求】
为每个小节输出 act 和一句剧情骨架（20字内）。
各节剧情须因果递进，从卷概要有机生长。

JSON：{{"blueprint": [{{"order": 1, "act": "开端", "title_hint": "", "plot_hint": ""}}]}}

严格输出 {total_to_generate} 个条目。"""
            print(f"[arcs/generate/stream] 蓝图pre-pass开始: 规划{total_to_generate}节...", flush=True)
            blueprint_result = await asyncio.wait_for(
                _generate_json_with_repair(
                    client, blueprint_prompt, system=blueprint_system, max_tokens=128000, root_key="blueprint"
                ),
                timeout=2100.0  # 35 分钟，与前端 GEN_TIMEOUT 统一
            )
            if blueprint_result and blueprint_result.get("blueprint"):
                blueprint = blueprint_result["blueprint"][:total_to_generate]
                print(f"[arcs/generate/stream] 蓝图pre-pass完成: {len(blueprint)}节", flush=True)
            else:
                print(f"[arcs/generate/stream] 蓝图pre-pass无结果，回退无蓝图模式", flush=True)
        except asyncio.TimeoutError:
            print(f"[arcs/generate/stream] 蓝图pre-pass超时(600s)，回退无蓝图模式", flush=True)
        except Exception as e:
            print(f"[arcs/generate/stream] 蓝图pre-pass异常: {e}，回退无蓝图模式", flush=True)

        # ========== 分批生成 ==========
        BATCH_SIZE = 5
        remaining = count
        total_generated = 0
        total_skipped = 0
        batch_no = 0

        try:
            while remaining > 0:
                if await _check_disconnected(request):
                    yield _sse_event("done", {"total_generated": total_generated, "skipped": total_skipped, "interrupted": True})
                    break

                batch_no += 1
                batch_count = min(BATCH_SIZE, remaining)
                remaining -= batch_count

                prior_arcs = repo.list_outlines(level="arc", parent_id=parent_id)
                prior_brief = ""
                if prior_arcs:
                    prior_arcs.sort(key=lambda x: (x.order or 0, x.id))
                    lines = [f"  {i+1}. {a.title}：{a.summary}"
                             for i, a in enumerate(prior_arcs)]
                    prior_brief = "\n\n【前情提要--已生成的细纲，请保持剧情连贯续写】\n" + "\n".join(lines) + \
                                  f"\n\n请从第 {len(prior_arcs)+1} 节开始续写 {batch_count} 个新小节，与上述已有小节剧情连贯、不得重复。"

                # 蓝图注入：告诉 LLM 当前批次的全局位置和 act 约束
                blueprint_context = ""
                if blueprint:
                    start_idx = total_generated
                    batch_bp = blueprint[start_idx:start_idx + batch_count]
                    if batch_bp:
                        bp_lines = []
                        for i, bp in enumerate(batch_bp):
                            global_pos = start_idx + i + 1
                            bp_lines.append(
                                f"  第{global_pos}/{total_to_generate}节 act={bp.get('act', '发展')}："
                                f"{bp.get('title_hint', '')} - {bp.get('plot_hint', '')}"
                            )
                        blueprint_context = (
                            f"\n\n【全局节奏蓝图--本批次在全书中的位置】\n"
                            f"总细纲数：{total_to_generate}，"
                            f"当前批次：第{start_idx+1}~{start_idx+batch_count}节\n"
                            + "\n".join(bp_lines)
                            + "\n\n【act 硬约束】本批次的 act 必须严格按上述蓝图分配，"
                            "不得自行添加\"大高潮\"或\"结局\"（除非蓝图中明确指定）。"
                            "绝对禁止出现\"终章\"。"
                        )

                system = (
                    "你是资深网文大纲师，擅长把一卷拆成多个小节（arc）。"
                    "每个小节是全局节奏链的一环，而非独立闭环。"
                    "小节之间通过因果递进串联，共同构成一卷的完整弧线。只输出 JSON。"
                )
                prompt = f"""请为小说《{project.title}》的以下卷生成 {batch_count} 个细纲小节：
卷标题：{volume.title}
卷概要：{volume.summary}

题材：{project.genre}
风格/要求：{project.style}
{custom_prompt and "额外要求：" + custom_prompt}

{consistency}{prior_brief}{blueprint_context}

【强制要求】
1. 必须严格生成 {batch_count} 个细纲小节，不多不少。每个小节标题必须不同，不得重复。
2. 细纲小节必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的剧情。
3. 每个小节的剧情必须与世界观中的力量体系/势力格局/地理设定直接关联。
4. 小节概要中必须出现至少 1 个已有角色或势力名称。
5. 如果已有伏笔，需在适当小节安排伏笔的推进或回收。
6. 若有前情提要，新小节必须紧接前情继续推进剧情，不得重复前情内容。
7. 若有全局节奏蓝图，本批次每个小节的 act 必须与蓝图一致，不得擅自改为"大高潮"或"结局"。

【反流水账铁律——这是最重要的规则】
7. 每个小节必须包含至少 1 个明确的对抗/冲突场景（战斗、争吵、谈判、追逐、识破等），不得是纯日常生存流水账（如"数钱、买东西、排队、赶路"）。
8. 每个小节必须有至少 2 个角色出场且有互动（对话/对抗/合作），禁止整节只有主角一个人的独角戏。
9. 开篇小节（第一个细纲）必须有引发事件（inciting incident）——打破主角日常的突发事件，不能只是"介绍主角的生活"。
10. 禁止"说明书式"设定传递——设定必须通过冲突和对话自然展现，不得用大段旁白/角色翻文件/导师讲解。
11. 每个小节必须有至少 1 个反转或意外——事情不能按主角计划顺利进行，必须有波折。

【小节设计指南——基于人类作家写作模式】
每个小节是全局节奏链的一个环节，承担特定叙事功能。小节之间通过"资源-情报-势力"循环相互咬合。

小节类型应交替出现，避免单一类型疲劳：
- 行动爆发型：连续战斗/冒险/行动，战力升级高潮
- 智斗博弈型：谈判、识破、收服、政治手腕
- 信息揭示型：发现秘密、世界观揭露、关键情报获取（但不能是整节唯一内容，必须伴随冲突）
- 危机压迫型：暴露风险、多方围堵、被迫反击
- 情感调剂型：温情日常、关系深化、节奏放缓（每卷最多 1 个，不得作为开篇）

【summary 必须包含以下要素】
- 叙事目标：本小节在整个卷中承担什么叙事功能？推进了什么主线？
- 核心场景：发生什么事件？在什么地点？涉及哪些角色？
- 角色动机与行动：主要角色在本小节中的目标是什么？采取了什么行动？遇到了什么阻碍？
- 冲突与转折：本小节的核心冲突是什么？有什么关键转折？转折的因果关系是什么？
- 信息揭示：本小节向读者揭示什么新信息？这些信息如何改变局势？
- 危机线推进：本小节推进了哪些危机线？
- 小节末状态：本小节结束时，角色和局势处于什么状态？留了什么悬念？

每个小节还包含：
- act：开端/发展/小高潮/转折/大高潮/结局
- strand：主线quest/感情fire/世界观constellation
- key_characters：本小节出场的角色名列表
- emotional_arc：情绪曲线，如"紧张→愤怒→绝望→希望"

请输出 JSON：{{"arcs": [{{"order": 1, "title": "", "summary": "", "act": "", "strand": "quest", "key_characters": [], "emotional_arc": ""}}]}}

【最终检查 — 生成前必须确认】
- 每个小节是否使用了已有世界观设定中的力量体系/地理/势力？
- 出场角色是否与已有角色设定一致（性格、能力、关系）？
- 伏笔推进是否与已有伏笔状态匹配？
- act 是否与蓝图一致？是否有不该出现的大高潮/结局/终章？
确认无误后再输出。"""

                result = await _generate_json_with_repair(
                    client, prompt, system=system, max_tokens=128000, root_key="arcs"
                )
                if not result:
                    break
                arcs = result.get("arcs") or result.get("sections") or []
                if not arcs:
                    break

                seen_titles = set()
                unique_arcs = []
                for a in arcs:
                    t = _clean_text(a.get("title", "")).strip()
                    if t and t in seen_titles:
                        continue
                    if t:
                        seen_titles.add(t)
                    unique_arcs.append(a)

                for idx, o in enumerate(unique_arcs):
                    title = _clean_text(o.get("title", f"小节{idx + 1}"))
                    if title in existing_titles:
                        total_skipped += 1
                        continue
                    order = _next_arc_order()
                    created = repo.create_outline(
                        level="arc",
                        parent_id=parent_id,
                        order=order,
                        title=title,
                        summary=_clean_text(o.get("summary", "")),
                        act=_clean_text(o.get("act", "")),
                        strand=_clean_text(o.get("strand", "quest")),
                        key_characters=json.dumps(o.get("key_characters") or [], ensure_ascii=False),
                        emotional_arc=json.dumps(o.get("emotional_arc") or [], ensure_ascii=False),
                    )
                    existing_titles.add(title)
                    item_data = {
                        "id": created.id, "level": "arc", "parent_id": created.parent_id,
                        "order": created.order, "title": created.title,
                        "summary": created.summary, "act": created.act, "strand": created.strand,
                    }
                    total_generated += 1
                    yield _sse_event("item", item_data)

                yield _sse_event("progress", {"generated": total_generated, "total": count, "skipped": total_skipped, "batch": batch_no})
            else:
                yield _sse_event("done", {"total_generated": total_generated, "skipped": total_skipped, "interrupted": False})
        except Exception as e:
            yield _sse_event("error", {"error": str(e), "partial_count": total_generated})
        finally:
            if client:
                await client.close()
            if db:
                db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/volumes/generate/stream")
async def generate_volumes_stream(request: Request, project_id: int,
                                  count: int = 3, custom_prompt: str = ""):
    """卷纲生成流式端点。"""
    from sse_starlette.sse import EventSourceResponse

    init_error = None
    db = repo = project = cfg = client = None
    try:
        db, repo, project, cfg = _get_repo(project_id)
        client = LLMClient(cfg.get_agent_llm("outliner"))
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"

    async def event_generator():
        if init_error:
            yield _sse_event("error", {"error": init_error, "partial_count": 0})
            if db:
                db.close()
            return

        consistency = _build_consistency_constraint(repo, project)
        system = "你是资深网文架构师，擅长设计长篇小说的卷级大纲。你的设计以结构严谨、伏笔绵密、节奏精准著称。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》生成 {count} 个卷级大纲。

题材：{project.genre}
简介：{project.summary}
风格/要求：{project.style}
{custom_prompt and "额外要求：" + custom_prompt}

{consistency}

【强制要求】
1. 必须严格生成 {count} 个卷级大纲，不多不少。每卷标题必须不同，不得重复。
2. 卷级大纲必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的卷剧情。
3. 每一卷的剧情主线必须与世界观中的力量体系/势力格局/地理设定直接关联。
4. 卷概要中必须提到至少 2 个已有角色或势力，体现世界观约束。
5. 如果已有伏笔，卷级规划必须安排伏笔的推进或回收。

【卷级结构设计指南——基于人类作家写作模式】
每卷应采用"新地图 + 新目标 + 新势力网络 + 一次体系质变 + 一次根基扩张"的骨架结构。

每卷内部采用波浪式节奏推进，包含以下节奏段（交替出现）：
- 适应与扎根期：铺设新地图、人物关系、装备基础
- 团队整合与矛盾铺垫期：新势力登场，外部冲突加剧
- 独立爆发期：连续战斗/行动+战力升级高潮
- 团队危机与势力建构期：由外转内，智斗与博弈为主
- 权力清算与决战期：多方博弈最大冲突
- 过渡收束期：告别、交接、启程

【summary 必须包含以下要素】
- 核心冲突、剧情主线、角色弧光、世界观推进、伏笔布局、节奏段划分、卷末钩子

每个卷还包含：
- act：开端/发展/小高潮/转折/大高潮/结局
- key_events：关键事件列表
- foreshadow_plan：本卷伏笔计划

请输出 JSON，格式为：{{"volumes": [{{"order": 1, "title": "", "summary": "", "act": "", "key_events": [], "foreshadow_plan": []}}]}}

【最终检查 — 生成前必须确认】
- 这条大纲用到了哪些已有世界观设定？
- 力量体系、地理区域、势力组织是否与已有设定一致？
- 已有角色是否保持了性格、能力、关系的连续性？
- 伏笔的埋设和回收是否与已有伏笔状态一致？
确认无误后再输出。"""

        total_generated = 0
        total_skipped = 0
        try:
            if await _check_disconnected(request):
                yield _sse_event("done", {"total_generated": 0, "skipped": 0, "interrupted": True})
                return

            result = await _generate_json_with_repair(
                client, prompt, system=system, max_tokens=128000, root_key="volumes"
            )
            if not result:
                yield _sse_event("error", {"error": "LLM 返回内容无法解析为有效 JSON", "partial_count": 0})
                return
            volumes = result.get("volumes") or result.get("outlines") or []
            if not volumes:
                yield _sse_event("error", {"error": "LLM 未返回有效卷级大纲", "partial_count": 0})
                return

            seen_titles = set()
            unique_volumes = []
            for v in volumes:
                t = _clean_text(v.get("title", "")).strip()
                if t and t in seen_titles:
                    continue
                if t:
                    seen_titles.add(t)
                unique_volumes.append(v)

            existing_volumes = repo.list_outlines(level="volume")
            existing_titles = {_clean_text(v.title).strip() for v in existing_volumes}
            used_orders = {v.order for v in existing_volumes if v.order}

            def _next_vol_order():
                o = 1
                while o in used_orders:
                    o += 1
                used_orders.add(o)
                return o

            for idx, o in enumerate(unique_volumes):
                if await _check_disconnected(request):
                    yield _sse_event("done", {"total_generated": total_generated, "skipped": total_skipped, "interrupted": True})
                    break
                title = _clean_text(o.get("title", f"第{idx + 1}卷"))
                if title in existing_titles:
                    total_skipped += 1
                    continue
                order = _next_vol_order()
                created = repo.create_outline(
                    level="volume",
                    order=order,
                    title=title,
                    summary=_clean_text(o.get("summary", "")),
                    act=_clean_text(o.get("act", "")),
                    strand="",
                    key_events=json.dumps(o.get("key_events") or [], ensure_ascii=False),
                )
                # B2：SSE 流式卷纲的伏笔计划也要落库（POST 版已落库）
                _save_foreshadow_plans(repo, o.get("foreshadow_plan") or [])
                existing_titles.add(title)
                item_data = {
                    "id": created.id, "level": "volume", "parent_id": None,
                    "order": created.order, "title": created.title,
                    "summary": created.summary, "act": created.act, "strand": created.strand,
                }
                total_generated += 1
                yield _sse_event("item", item_data)
            else:
                yield _sse_event("done", {"total_generated": total_generated, "skipped": total_skipped, "interrupted": False})
        except Exception as e:
            yield _sse_event("error", {"error": str(e), "partial_count": total_generated})
        finally:
            if client:
                await client.close()
            if db:
                db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/chapters/generate/stream")
async def generate_chapters_stream(request: Request, project_id: int, parent_id: int,
                                   count: int = 10, custom_prompt: str = ""):
    """章纲生成流式端点（按细纲生成）。"""
    from sse_starlette.sse import EventSourceResponse

    init_error = None
    db = repo = project = cfg = client = arc = None
    try:
        db, repo, project, cfg = _get_repo(project_id)
        arc = repo.get_outline(parent_id)
        if not arc or arc.level != "arc":
            init_error = "细纲小节不存在"
        else:
            client = LLMClient(cfg.get_agent_llm("outliner"))
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"

    async def event_generator():
        if init_error:
            yield _sse_event("error", {"error": init_error, "partial_count": 0})
            if db:
                db.close()
            return

        consistency = _build_consistency_constraint(repo, project)
        used_orders = {c.order for c in repo.list_outlines(level="chapter")}

        def _next_order():
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        system = "你是资深网文大纲师，擅长把细纲小节拆成具体章节，每章有明确的叙事目标、场景设计和节奏控制。只输出 JSON。"
        prompt = f"""请为小说《{project.title}》的以下细纲小节生成 {count} 个章纲：
小节标题：{arc.title}
小节概要：{arc.summary}

题材：{project.genre}
风格/要求：{project.style}
{custom_prompt and "额外要求：" + custom_prompt}

{consistency}

【强制要求】
1. 必须严格生成 {count} 个章纲，不多不少。每章标题必须不同，不得重复。
2. 章纲必须基于上述已有世界观设定、角色、势力展开，不得凭空捏造与已有设定矛盾的剧情。
3. 章节内容必须与世界观中的力量体系/势力格局/地理设定直接关联。
4. 章纲摘要中必须出现至少 1 个已有角色或势力名称。
5. 如果已有伏笔，需在适当章节安排伏笔的埋设、推进或回收。

【反流水账铁律——违反任何一条即为废稿】
6. 每章必须有至少 2 个角色出场且有对话互动，禁止整章只有主角一个人的独角戏。
7. opening阶段（前3章）每章必须有至少 2 个 beats（1 small + 1 medium），不得只有 1 个 small beat。
8. 爽点必须有主动行为（打脸/反杀/突破/识破/碾压），"被动信息获得"只能作为辅助 beat，不得作为唯一 beat。
9. 每章必须有至少 1 个对抗/冲突场景（战斗、争吵、谈判、追逐、识破等），禁止纯日常流水账（数钱、买东西、排队、赶路、吃饭）。
10. 禁止大段环境描写开头——必须用动作或对话开篇（in media res），环境描写穿插在行动中，不得超过总字数的 15%。
11. 每章必须有至少 1 个反转或意外——事情不能按主角计划顺利进行。

【章节设计指南——基于人类作家写作模式】
每章采用"功能节拍+信息节拍+爽点/悬念节拍"三元结构。每章必留钩子，绝不允许平淡收尾。

章末钩子类型（每章必选其一）：
- 身份/安全威胁型、重大发现型、反转揭示型、悬念型、爽点型、金句型

张力维持铁律：
- 同时维持2-3条张力线，即使一条线暂时平静，其他线仍在推进
- 主角永远处于 precarious position
- 每章至少一个 near-miss 或反转
- 爽感与危机感交替

信息释放策略：
- 信息即用即揭
- 利用信息差制造戏剧性反讽
- 设定悖论暗示更深真相

【summary 必须包含以下要素】
- 核心事件、场景设计、角色目标与行动、信息位、情绪节奏、章末钩子、张力线推进

每章需要包含约束载荷：
- required_beats: 爽点计划
- owed_debts: 欠账
- required_hooks: 章末钩
- character_focus: 角色重点
- scene_beats: 场景节拍
- emotion_arc: 情感弧线
- pacing_intent: 节奏意图
- theme_progression: 主题推进
- phase: 前3章=opening，上架章=shangjia，其余=regular

每个章纲包含：title、summary、act、strand、required_beats、owed_debts、required_hooks、character_focus、scene_beats、emotion_arc、pacing_intent、theme_progression、phase（章节序号由后端自动分配，无需输出 order）。
请输出 JSON：{{"chapters": [{{"title": "", "summary": "", "act": "", "strand": "quest", "required_beats": [], "owed_debts": [], "required_hooks": {{}}, "character_focus": [], "scene_beats": [], "emotion_arc": {{}}, "pacing_intent": {{}}, "theme_progression": "", "phase": "regular"}}]}}

【最终检查 — 生成前必须确认】
- 每章是否使用了已有世界观设定中的力量体系/地理/势力？
- 角色行为是否与已有角色设定一致（性格、能力、位置、关系）？
- 伏笔的埋设/推进/回收是否与已有伏笔状态匹配？
- 场景地点是否在已有世界观地理设定范围内？
确认无误后再输出。"""

        total_generated = 0
        try:
            if await _check_disconnected(request):
                yield _sse_event("done", {"total_generated": 0, "interrupted": True})
                return

            result = await _generate_json_with_repair(
                client, prompt, system=system, max_tokens=128000, root_key="chapters"
            )
            if not result:
                yield _sse_event("error", {"error": "LLM 返回内容无法解析为有效 JSON", "partial_count": 0})
                return
            chapters = result.get("chapters") or result.get("chapter_outlines") or []
            if not chapters:
                yield _sse_event("error", {"error": "LLM 未返回有效章纲", "partial_count": 0})
                return

            seen_titles = set()
            unique_chapters = []
            for c in chapters:
                t = _clean_text(c.get("title", "")).strip()
                if t and t in seen_titles:
                    continue
                if t:
                    seen_titles.add(t)
                unique_chapters.append(c)

            for idx, o in enumerate(unique_chapters):
                if await _check_disconnected(request):
                    yield _sse_event("done", {"total_generated": total_generated, "interrupted": True})
                    break
                order = _next_order()
                created = repo.create_outline(
                    level="chapter",
                    parent_id=parent_id,
                    order=order,
                    title=_clean_text(o.get("title", f"第{order}章")),
                    summary=_clean_text(o.get("summary", "")),
                    act=_clean_text(o.get("act", "")),
                    strand=_clean_text(o.get("strand", "quest")),
                    required_beats=json.dumps(o.get("required_beats", []), ensure_ascii=False),
                    owed_debts=json.dumps(o.get("owed_debts", []), ensure_ascii=False),
                    required_hooks=json.dumps(o.get("required_hooks", {}), ensure_ascii=False),
                    character_constraints=json.dumps({
                        "character_focus": o.get("character_focus", []),
                        "scene_beats": o.get("scene_beats", []),
                        "emotion_arc": o.get("emotion_arc", {}),
                        "pacing_intent": o.get("pacing_intent", {}),
                        "theme_progression": o.get("theme_progression", ""),
                    }, ensure_ascii=False),
                    phase=o.get("phase", "regular"),
                )
                for d in o.get("owed_debts", []):
                    try:
                        repo.create_plot_debt(
                            debt_type=d.get("type", ""),
                            description=_clean_text(d.get("desc", "")),
                            pressure=int(d.get("pressure", 3)),
                            term=d.get("term", "short"),
                            created_chapter=order,
                            status="open",
                        )
                    except Exception as e:
                        logger.warning("写入欠账失败: %s", e)
                item_data = {
                    "id": created.id, "level": "chapter", "parent_id": created.parent_id,
                    "order": created.order, "title": created.title,
                    "summary": created.summary, "act": created.act, "strand": created.strand,
                }
                total_generated += 1
                yield _sse_event("item", item_data)
            else:
                yield _sse_event("done", {"total_generated": total_generated, "interrupted": False})
        except Exception as e:
            yield _sse_event("error", {"error": str(e), "partial_count": total_generated})
        finally:
            if client:
                await client.close()
            if db:
                db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/chapters/generate-by-volume/stream")
async def generate_chapters_by_volume_stream(request: Request, project_id: int, volume_id: int,
                                             count: int = 0, custom_prompt: str = ""):
    """按卷纲生成章纲流式端点（方案B：逐细纲生成 + 卷级统筹调度）。"""
    from sse_starlette.sse import EventSourceResponse

    init_error = None
    db = repo = project = cfg = client = volume = arcs_sorted = None
    try:
        db, repo, project, cfg = _get_repo(project_id)
        volume = repo.get_outline(volume_id)
        if not volume or volume.level != "volume":
            init_error = "卷级大纲不存在"
        else:
            arcs = repo.list_outlines(level="arc", parent_id=volume_id)
            if not arcs:
                init_error = "该卷下没有细纲，请先生成细纲"
            else:
                arcs_sorted = sorted(arcs, key=lambda x: x.order)
                client = LLMClient(cfg.get_agent_llm("outliner"))
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"

    async def event_generator():
        if init_error:
            yield _sse_event("error", {"error": init_error, "partial_count": 0})
            if db:
                db.close()
            return

        consistency = _build_consistency_constraint(repo, project)
        used_orders = {c.order for c in repo.list_outlines(level="chapter")}

        def _next_order():
            o = 1
            while o in used_orders:
                o += 1
            used_orders.add(o)
            return o

        arc_id_set = {a.id for a in arcs_sorted}
        n_arcs = len(arcs_sorted)
        existing_by_arc = {}
        for c in repo.list_outlines(level="chapter"):
            if c.parent_id in arc_id_set:
                existing_by_arc.setdefault(c.parent_id, []).append(c)

        target_count = count if count > 0 else n_arcs * 4
        base = max(1, target_count // n_arcs)
        remainder = target_count - base * n_arcs

        arc_targets = []
        for i, arc in enumerate(arcs_sorted):
            target = base + (1 if i < remainder else 0)
            existing_count = len(existing_by_arc.get(arc.id, []))
            need = max(0, target - existing_count)
            arc_targets.append((arc, target, existing_count, need))

        total_need = sum(need for _, _, _, need in arc_targets)
        if total_need == 0:
            yield _sse_event("done", {"total_generated": 0, "interrupted": False,
                                     "warning": f"所有细纲均已达到目标章数（共 {target_count} 章），无需生成。"})
            return

        prev_context = ""
        existing_all = [c for cs in existing_by_arc.values() for c in cs]
        if existing_all:
            existing_sorted = sorted(existing_all, key=lambda x: x.order)
            last = existing_sorted[-1]
            prev_context = f"第{last.order}章《{last.title}》：{last.summary}"

        total_generated = 0
        try:
            for arc, target, existing_count, need in arc_targets:
                if need <= 0:
                    arc_chapters = sorted(existing_by_arc.get(arc.id, []), key=lambda x: x.order)
                    if arc_chapters:
                        last = arc_chapters[-1]
                        prev_context = f"第{last.order}章《{last.title}》：{last.summary}"
                    continue

                if await _check_disconnected(request):
                    yield _sse_event("done", {"total_generated": total_generated, "interrupted": True})
                    break

                items, last_tail, warn = await _generate_chapters_for_arc(
                    arc=arc, project=project, repo=repo, client=client,
                    consistency=consistency, count=need, prev_context=prev_context,
                    custom_prompt=custom_prompt, next_order_fn=_next_order,
                )
                for item in items:
                    if await _check_disconnected(request):
                        yield _sse_event("done", {"total_generated": total_generated, "interrupted": True})
                        break
                    total_generated += 1
                    yield _sse_event("item", item)
                if last_tail:
                    prev_context = last_tail
                yield _sse_event("progress", {"generated": total_generated, "total": total_need,
                                              "current_arc": arc.title})
            else:
                yield _sse_event("done", {"total_generated": total_generated, "interrupted": False})
        except Exception as e:
            yield _sse_event("error", {"error": str(e), "partial_count": total_generated})
        finally:
            if client:
                await client.close()
            if db:
                db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/outlines/generate/stream")
async def generate_outlines_stream(request: Request, project_id: int,
                                   level: str = "chapter", parent_id: int | None = None,
                                   count: int = 10, custom_prompt: str = ""):
    """统一大纲生成流式入口：根据 level 委托到对应流式端点。"""
    if level == "volume":
        return await generate_volumes_stream(request, project_id, count, custom_prompt)
    if level == "arc":
        if parent_id is None:
            from sse_starlette.sse import EventSourceResponse
            async def err_gen():
                yield _sse_event("error", {"error": "生成细纲需要提供 parent_id（卷级大纲 id）", "partial_count": 0})
            return EventSourceResponse(err_gen())
        return await generate_arcs_stream(request, project_id, parent_id, count, custom_prompt)
    if level == "chapter":
        if parent_id is None:
            from sse_starlette.sse import EventSourceResponse
            async def err_gen():
                yield _sse_event("error", {"error": "生成章纲需要提供 parent_id（细纲 id）", "partial_count": 0})
            return EventSourceResponse(err_gen())
        return await generate_chapters_stream(request, project_id, parent_id, count, custom_prompt)
    from sse_starlette.sse import EventSourceResponse
    async def err_gen():
        yield _sse_event("error", {"error": f"不支持的 level：{level}", "partial_count": 0})
    return EventSourceResponse(err_gen())


@router.get("/world/generate/stream")
async def generate_world_stream(request: Request, project_id: int,
                                requirements: str = "设计多层世界观", style: str = "热血"):
    """世界观生成流式端点。"""
    from sse_starlette.sse import EventSourceResponse

    init_error = None
    db = repo = project = cfg = client = None
    try:
        db, repo, project, cfg = _get_repo(project_id)
        client = LLMClient(cfg.get_agent_llm("architect"))
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"

    async def event_generator():
        if init_error:
            yield _sse_event("error", {"error": init_error, "partial_count": 0})
            if db:
                db.close()
            return

        try:
            from novel_agent.templates.style_guide_loader import get_task_guide
            consistency = _build_consistency_constraint(repo, project)
            worldview_guide = get_task_guide("worldview")
            prompt = PromptLoader().render(
                "world",
                title=project.title,
                genre=project.genre,
                summary=project.summary,
                style=project.style,
                requirements=(requirements or "") + "\n\n" + worldview_guide,
                style_hint=style,
                existing_world=consistency,
                categories=_get_categories_for_genre(project.genre),
            )

            if await _check_disconnected(request):
                yield _sse_event("done", {"total_generated": 0, "interrupted": True})
                return

            result = await _generate_json_with_repair(
                client, prompt, system="你是网文设定师，擅长设计多层世界观。只输出 JSON。", root_key="world_settings")
            if not result:
                yield _sse_event("error", {"error": "LLM 返回内容无法解析为有效 JSON", "partial_count": 0})
                return
            settings = result.get("world_settings") or result.get("worlds") or result.get("settings") or []
            if not settings:
                yield _sse_event("error", {"error": "LLM 未返回有效设定项", "partial_count": 0})
                return

            total_generated = 0
            for i, s in enumerate(settings):
                if await _check_disconnected(request):
                    yield _sse_event("done", {"total_generated": total_generated, "interrupted": True})
                    break
                item_data = {
                    "id": i,
                    "category": _clean_text(s.get("category", "其他")),
                    "title": _clean_text(s.get("title", "未命名")),
                    "content": _clean_text(s.get("content", "")),
                    "order": i,
                }
                total_generated += 1
                yield _sse_event("item", item_data)
            else:
                yield _sse_event("done", {"total_generated": total_generated, "interrupted": False})
        except Exception as e:
            yield _sse_event("error", {"error": str(e), "partial_count": 0})
        finally:
            if client:
                await client.close()
            if db:
                db.close()

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/characters/generate/stream")
async def generate_characters_stream(request: Request, project_id: int,
                                     protagonist_count: int = 1, supporting_count: int = 3,
                                     antagonist_count: int = 2, style: str = "热血"):
    """角色生成流式端点。"""
    from sse_starlette.sse import EventSourceResponse

    init_error = None
    db = repo = project = cfg = client = None
    try:
        db, repo, project, cfg = _get_repo(project_id)
        client = LLMClient(cfg.get_agent_llm("architect"))
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"

    async def event_generator():
        if init_error:
            yield _sse_event("error", {"error": init_error, "partial_count": 0})
            if db:
                db.close()
            return

        try:
            from novel_agent.templates.style_guide_loader import get_task_guide
            consistency = _build_consistency_constraint(repo, project)
            character_guide = get_task_guide("character")
            prompt = PromptLoader().render(
                "characters",
                title=project.title,
                genre=project.genre,
                summary=project.summary,
                style=project.style,
                protagonist_count=protagonist_count,
                supporting_count=supporting_count,
                antagonist_count=antagonist_count,
                style_hint=style,
                existing_world=consistency + "\n\n" + character_guide,
                existing_characters="",
            )

            if await _check_disconnected(request):
                yield _sse_event("done", {"total_generated": 0, "interrupted": True})
                return

            result = await _generate_json_with_repair(
                client, prompt, system="你是网文角色设计师，擅长设计立体角色。只输出 JSON。", root_key="characters")
            if not result:
                yield _sse_event("error", {"error": "LLM 返回内容无法解析为有效 JSON", "partial_count": 0})
                return
            characters = result.get("characters") or result.get("chars") or result.get("roles") or []
            if not characters:
                yield _sse_event("error", {"error": "LLM 未返回有效角色项", "partial_count": 0})
                return

            total_generated = 0
            for i, c in enumerate(characters):
                if await _check_disconnected(request):
                    yield _sse_event("done", {"total_generated": total_generated, "interrupted": True})
                    break
                item_data = {
                    "id": i,
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
                total_generated += 1
                yield _sse_event("item", item_data)
            else:
                yield _sse_event("done", {"total_generated": total_generated, "interrupted": False})
        except Exception as e:
            yield _sse_event("error", {"error": str(e), "partial_count": 0})
        finally:
            if client:
                await client.close()
            if db:
                db.close()

    return EventSourceResponse(event_generator(), ping=15)
