"""卷级 StateGraph：plan→design→outline→[人审① interrupt]→apply_to_bible。

人审①：大纲生成后 interrupt 挂起，用户审核后 Command(resume=...) 恢复。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from novel_agent.bible.repository import BibleRepository
from novel_agent.planning.agents import Planner, Architect, Outliner
from novel_agent.planning.state import VolumePlanState
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import (
    Delta, CharacterDelta, OutlineDelta, ForeshadowDelta,
)


async def plan_volume(state, planner, repo):
    project = repo.get_project()
    plan = await planner.plan(project, state.get("chapter_count", 30))
    return {"volume_plan": plan, "status": "planned"}


async def design_settings(state, architect, repo):
    project = repo.get_project()
    settings = await architect.design(project, state.get("volume_plan", {}))
    return {"settings": settings, "status": "designed"}


async def outline_chapters(state, outliner, repo):
    project = repo.get_project()
    outline = await outliner.outline(
        project, state.get("volume", "卷一"), state.get("chapter_count", 30))
    return {"outline": outline, "status": "outlined"}


def human_review_outline(state):
    """人审①：interrupt 挂起等用户审核大纲。"""
    decision = interrupt({
        "type": "outline_review",
        "volume_plan": state.get("volume_plan", {}),
        "settings": state.get("settings", {}),
        "outline": state.get("outline", {}),
    })
    return {"review_decision": decision,
            "status": "approved" if decision.get("approved") else "rejected"}


def route_after_review(state):
    if state.get("review_decision", {}).get("approved"):
        return "apply"
    return "end_rejected"


def apply_to_bible(state, repo, applier):
    """把审核通过的设定/大纲/伏笔写入圣经。"""
    settings = state.get("settings", {})
    # 写角色
    for c in settings.get("characters", []):
        try:
            applier.apply(Delta(
                target="character", action="create", chapter=0,
                data=CharacterDelta(**{k: c.get(k, "") for k in
                    ("name", "role", "personality", "motivation")}),
            ))
        except Exception:
            pass  # 角色已存在等非致命
    # 写世界设定（直接用 repo，world_setting 无 delta handler）
    for ws in settings.get("world_settings", []):
        try:
            repo.create_world_setting(
                category=ws.get("category", ""), title=ws.get("title", ""),
                content=ws.get("content", ""))
        except Exception:
            pass
    # 写大纲
    errors = []
    for ch in state.get("outline", {}).get("chapters", []):
        try:
            applier.apply(Delta(
                target="outline", action="create", chapter=ch.get("chapter", 0),
                data=OutlineDelta(level="chapter", order=ch.get("chapter", 0),
                                  title=ch.get("title", ""), summary=ch.get("summary", "")),
            ))
        except Exception as e:
            errors.append(f"outline ch{ch.get('chapter')}: {e}")
        # 写伏笔
        for f in ch.get("foreshadows", []):
            try:
                applier.apply(Delta(
                    target="foreshadow", action="plant", chapter=f.get("plant_chapter", 0),
                    data=ForeshadowDelta(
                        foreshadow_id=f.get("id", ""), description=f.get("description", ""),
                        plant_chapter=f.get("plant_chapter", 0),
                        planned_resolve_chapter=f.get("resolve_chapter", 0)),
                ))
            except Exception as e:
                errors.append(f"foreshadow {f.get('id')}: {e}")
    if errors:
        return {"status": "approved", "errors": errors}
    # 显式 commit 确保所有 flush 的数据落盘（async 上下文里同步 session 可能不自动提交）
    repo.db.commit()
    return {"status": "approved"}


def build_volume_graph(deps: dict[str, Any] | None = None,
                       checkpointer: Any = None):
    deps = deps or {}
    graph = StateGraph(VolumePlanState)

    graph.add_node("plan", partial(plan_volume, planner=deps["planner"], repo=deps["repo"]))
    graph.add_node("design", partial(design_settings, architect=deps["architect"], repo=deps["repo"]))
    graph.add_node("outline", partial(outline_chapters, outliner=deps["outliner"], repo=deps["repo"]))
    graph.add_node("review", human_review_outline)
    graph.add_node("apply", partial(apply_to_bible, repo=deps["repo"], applier=deps["applier"]))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "design")
    graph.add_edge("design", "outline")
    graph.add_edge("outline", "review")
    graph.add_conditional_edges("review", route_after_review,
                                {"apply": "apply", "end_rejected": END})
    graph.add_edge("apply", END)
    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
