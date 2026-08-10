"""卷级 StateGraph：plan→design→review→apply（4 节点）。

修订（2026-07）：原 5 节点 plan→design→outline→review→apply 中的 outline 节点
已移除——章纲改由"大纲管理页 AI 生成端点"（/api/generation/chapters/generate）
承担，规划页仅负责全书设定（卷结构+世界观+角色+金手指+立意）。约束载荷
（required_beats/owed_debts/required_hooks/phase）的数据源同步迁移至大纲管理页。

人审①：review 节点后 interrupt 挂起，用户审核卷规划+设定后 Command(resume=...) 恢复。
"""
from __future__ import annotations

import logging
from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from novel_agent.bible.repository import BibleRepository
from novel_agent.planning.agents import Planner, Architect
from novel_agent.planning.state import VolumePlanState
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.state_common import PlanningStatus
from novel_agent.protocol.schemas import (
    Delta, CharacterDelta,
)

logger = logging.getLogger(__name__)


async def plan_volume(state, planner, repo):
    project = repo.get_project()
    plan = await planner.plan(
        project, state.get("chapter_count", 30),
        custom_prompt=state.get("custom_prompt", ""),
        target_volumes=state.get("target_volumes", 0),
        golden_finger=state.get("golden_finger", ""),
        protagonist=state.get("protagonist", ""),
        constitution=state.get("constitution", ""),
    )
    if not isinstance(plan, dict):
        # C9：Planner.plan 两次 JSON 解析失败返回 None，兜底为空规划避免崩溃
        logger.warning("plan_volume: Planner.plan 返回 %s，使用空规划兜底",
                       type(plan).__name__ if plan is not None else "None")
        plan = {}
    # 立意贯通：把Planner产出的central_concept存入Project
    concept = plan.get("central_concept")
    if concept and not (getattr(project, 'central_concept', '') if hasattr(project, 'central_concept') else ''):
        import json as _json
        repo.update_project(central_concept=_json.dumps(concept, ensure_ascii=False))
    return {"volume_plan": plan, "status": PlanningStatus.PLANNED.value}


async def design_settings(state, architect, repo):
    project = repo.get_project()
    existing = _collect_existing_assets(repo)
    settings = await architect.design(
        project, state.get("volume_plan", {}), existing=existing,
        custom_prompt=state.get("custom_prompt", ""),
        golden_finger=state.get("golden_finger", ""),
        protagonist=state.get("protagonist", ""),
        constitution=state.get("constitution", ""),
    )
    return {"settings": settings, "status": PlanningStatus.DESIGNED.value}


def _collect_existing_assets(repo) -> dict:
    """收集项目已有资产供 Architect 做增量设计。"""
    chars = [c.name for c in repo.list_characters()]
    ws = [w.title for w in repo.list_world_settings() if w.title]
    factions = [f.name for f in repo.list_factions()]
    monsters = [m.name for m in repo.list_monsters()]
    foreshadows = [f.foreshadow_id for f in repo.list_foreshadows()]
    return {
        "characters": chars,
        "world_settings": ws,
        "factions": factions,
        "monsters": monsters,
        "foreshadows": foreshadows,
    }


def _ensure_protagonist_in_settings(settings: dict, protagonist_json: str) -> None:
    """如果用户预填了主角，确保 settings.characters 中第一位是主角。

    当 Architect 未产出主角或主角信息不完整时，用用户预填的主角补齐。
    """
    if not protagonist_json or not protagonist_json.strip():
        return
    import json as _json
    try:
        p = _json.loads(protagonist_json) if isinstance(protagonist_json, str) else protagonist_json
    except Exception:
        return
    if not isinstance(p, dict):
        return
    name = (p.get("name") or "").strip()
    if not name:
        return
    characters = settings.setdefault("characters", [])
    # 如果 Architect 已经生成了同名角色，合并用户预填的字段
    for c in characters:
        if (c.get("name") or "").strip() == name:
            c["role"] = c.get("role") or "主角"
            c["importance"] = c.get("importance") or "主角"
            c["personality"] = c.get("personality") or p.get("personality", "")
            c["motivation"] = c.get("motivation") or p.get("motivation", "")
            c["core_contradiction"] = c.get("core_contradiction") or p.get("core_contradiction", "")
            c["sensory_memories"] = c.get("sensory_memories") or p.get("sensory_memories", "")
            c["absolute_taboos"] = c.get("absolute_taboos") or p.get("absolute_taboos", "")
            return
    # 否则把主角插入到第一位
    characters.insert(0, {
        "name": name,
        "role": "主角",
        "importance": "主角",
        "personality": p.get("personality", ""),
        "motivation": p.get("motivation", ""),
        "core_contradiction": p.get("core_contradiction", ""),
        "sensory_memories": p.get("sensory_memories", ""),
        "absolute_taboos": p.get("absolute_taboos", ""),
        "background": p.get("identity", ""),
    })


def human_review_outline(state):
    """人审①：interrupt 挂起等用户审核卷规划与设定（不再含章纲）。"""
    decision = interrupt({
        "type": "outline_review",
        "volume_plan": state.get("volume_plan", {}),
        "settings": state.get("settings", {}),
    })
    return {"review_decision": decision,
            "status": PlanningStatus.APPROVED.value if decision.get("approved") else PlanningStatus.REJECTED.value}


def route_after_review(state):
    if state.get("review_decision", {}).get("approved"):
        return "apply"
    return "end_rejected"


def apply_to_bible(state, repo, applier):
    """把审核通过的卷规划与设定写入圣经（带去重校验）。

    全书规划只落：卷大纲(level=volume) + 角色 + 世界设定。
    章纲/伏笔/plot_debt 不在此处生成，交由"大纲管理"页面单独触发。
    """
    import json as _json
    settings = state.get("settings")
    volume_plan = state.get("volume_plan")
    if not isinstance(settings, dict):
        # C9：Architect.design 返回 None 时兜底为空，避免 apply 崩溃
        logger.warning("apply_to_bible: settings 为 %s，兜底为空", type(settings).__name__ if settings is not None else "None")
        settings = {}
    if not isinstance(volume_plan, dict):
        logger.warning("apply_to_bible: volume_plan 为 %s，兜底为空", type(volume_plan).__name__ if volume_plan is not None else "None")
        volume_plan = {}
    # 预读已有资产，用于去重
    existing_chars = {c.name for c in repo.list_characters()}
    existing_ws = {(w.category, w.title) for w in repo.list_world_settings()}
    existing_volume_orders = {o.order for o in repo.list_outlines(level="volume")}
    errors = []
    new_chars = 0
    new_ws = 0
    new_volumes = 0

    # 写卷大纲（level=volume，upsert：同 order 删旧建新）
    for idx, v in enumerate(volume_plan.get("volumes", []), start=1):
        try:
            order = idx
            name = v.get("name", "") or f"卷{idx}"
            theme = v.get("theme", "")
            summary = v.get("summary", "")
            chapters = v.get("chapters", 0)
            climax = v.get("climax", "")
            end_hook = v.get("end_hook", "")
            strand_ratio = v.get("strand_ratio", {})
            # strand 主线占比最高者
            strand = "quest"
            if strand_ratio:
                strand = max(strand_ratio, key=strand_ratio.get) if isinstance(strand_ratio, dict) else "quest"
            if order in existing_volume_orders:
                # 删除旧卷大纲，用新规划覆盖
                try:
                    for old in repo.list_outlines(level="volume"):
                        if old.order == order:
                            repo.db.delete(old)
                except Exception:
                    pass
            repo.create_outline(
                level="volume",
                order=order,
                act=theme,
                strand=strand,
                title=name,
                summary=summary,
                character_constraints=_json.dumps({
                    "chapters": chapters,
                    "climax": climax,
                    "end_hook": end_hook,
                    "strand_ratio": strand_ratio,
                }, ensure_ascii=False),
            )
            existing_volume_orders.add(order)
            new_volumes += 1
        except Exception as e:
            errors.append(f"卷大纲「{v.get('name', idx)}」写入失败: {e}")
            try:
                repo.db.rollback()
            except Exception:
                pass

    # 主角补全：如果用户预填了主角，确保 Architect 产出的角色列表中包含主角
    _ensure_protagonist_in_settings(settings, state.get("protagonist", ""))

    # 写角色（去重：同名跳过）
    for c in settings.get("characters", []):
        name = c.get("name", "").strip()
        if not name:
            continue
        if name in existing_chars:
            errors.append(f"角色「{name}」已存在，跳过")
            continue
        try:
            applier.apply(Delta(
                target="character", action="create", chapter=0,
                data=CharacterDelta(**{k: c.get(k, "") for k in
                    ("name", "role", "personality", "motivation",
                     "core_contradiction", "sensory_memories", "absolute_taboos")}),
            ))
            existing_chars.add(name)
            new_chars += 1
        except Exception as e:
            errors.append(f"角色「{name}」写入失败: {e}")
    # 写世界设定（去重：同 category+title 跳过）
    for ws in settings.get("world_settings", []):
        category = ws.get("category", "").strip()
        title = ws.get("title", "").strip()
        if not title:
            continue
        key = (category, title)
        if key in existing_ws:
            errors.append(f"世界设定「{category}/{title}」已存在，跳过")
            continue
        try:
            repo.create_world_setting(
                category=category, title=title,
                content=ws.get("content", ""))
            existing_ws.add(key)
            new_ws += 1
        except Exception as e:
            errors.append(f"世界设定「{title}」写入失败: {e}")
    repo.db.commit()
    if errors:
        for err in errors:
            logger.warning("apply_to_bible: %s", err)
    return {"status": "approved",
            "stats": {"new_volumes": new_volumes,
                      "new_characters": new_chars,
                      "new_world_settings": new_ws},
            "errors": errors}


def build_volume_graph(deps: dict[str, Any] | None = None,
                       checkpointer: Any = None):
    deps = deps or {}
    graph = StateGraph(VolumePlanState)

    graph.add_node("plan", partial(plan_volume, planner=deps["planner"], repo=deps["repo"]))
    graph.add_node("design", partial(design_settings, architect=deps["architect"], repo=deps["repo"]))
    graph.add_node("review", human_review_outline)
    graph.add_node("apply", partial(apply_to_bible, repo=deps["repo"], applier=deps["applier"]))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "design")
    graph.add_edge("design", "review")
    graph.add_conditional_edges("review", route_after_review,
                                {"apply": "apply", "end_rejected": END})
    graph.add_edge("apply", END)
    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
