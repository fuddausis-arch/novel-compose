"""StateGraph 定义：assemble→write→audit→{达标:human_review→polish→save→summarize | 不达标≤3:rewrite→audit | 超3:END}

写审分离铁律：Writer 与 Auditor 独立；反馈循环 ≤3 次。
人审 checkpoint：审计达标后、润色前挂起，用户通过→polish，驳回→rewrite。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END

from novel_agent.orchestrator.nodes import (
    assemble_context, write_chapter, audit_chapter, rewrite_chapter,
    polish_chapter, save_text_polished, summarize_chapter, route_after_audit,
    human_review,
)
from novel_agent.orchestrator.state import ChapterGenState

NODE_NAMES = ["assemble", "write", "audit", "rewrite", "human_review", "polish", "save_text", "summarize"]


def _route_after_write(state: ChapterGenState) -> str:
    """write/rewrite 后：失败直接 END，成功进 audit。"""
    if state.get("status") == "failed" or not state.get("draft", "").strip():
        return "end_failed"
    return "audit"


def route_after_review(state: ChapterGenState) -> str:
    """条件边：人审通过→polish；驳回→rewrite。"""
    if state.get("review_decision") == "reject":
        return "rewrite"
    return "polish"


def build_graph(deps: dict[str, Any] | None = None):
    """构建写审循环流水线图。

    Args:
        deps: 依赖字典，含 repo/llm_client/recall/applier/archival/auditor。
    Returns:
        编译后的 StateGraph（未绑定 checkpointer）。
    """
    deps = deps or {}
    graph = StateGraph(ChapterGenState)

    assemble_fn = partial(assemble_context, repo=deps["repo"], archival=deps.get("archival"))
    write_fn = partial(write_chapter, llm_client=deps["llm_client"])
    audit_fn = partial(audit_chapter, auditor=deps["auditor"], repo=deps["repo"])
    rewrite_fn = partial(rewrite_chapter, llm_client=deps["llm_client"])
    polish_fn = partial(polish_chapter, llm_client=deps["llm_client"])
    save_fn = partial(save_text_polished, recall=deps["recall"])
    summarize_fn = partial(summarize_chapter, llm_client=deps["llm_client"], applier=deps["applier"], repo=deps.get("repo"))

    graph.add_node("assemble", assemble_fn)
    graph.add_node("write", write_fn)
    graph.add_node("audit", audit_fn)
    graph.add_node("rewrite", rewrite_fn)
    graph.add_node("human_review", human_review)
    graph.add_node("polish", polish_fn)
    graph.add_node("save_text", save_fn)
    graph.add_node("summarize", summarize_fn)

    graph.add_edge(START, "assemble")
    graph.add_edge("assemble", "write")
    # write 后条件路由：失败直接 END，成功进 audit
    graph.add_conditional_edges(
        "write", _route_after_write,
        {"audit": "audit", "end_failed": END},
    )
    # 审计后条件路由：达标→人审 checkpoint，不达标→rewrite/END
    graph.add_conditional_edges(
        "audit", route_after_audit,
        {"polish": "human_review", "rewrite": "rewrite", "end_failed": END},
    )
    # rewrite 后也条件路由：失败直接 END，成功回 audit
    graph.add_conditional_edges(
        "rewrite", _route_after_write,
        {"audit": "audit", "end_failed": END},
    )
    # 人审后：通过→polish，驳回→rewrite
    graph.add_conditional_edges(
        "human_review", route_after_review,
        {"polish": "polish", "rewrite": "rewrite"},
    )
    graph.add_edge("polish", "save_text")
    graph.add_edge("save_text", "summarize")
    graph.add_edge("summarize", END)

    return graph.compile()
