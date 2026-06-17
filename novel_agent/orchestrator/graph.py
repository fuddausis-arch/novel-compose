"""StateGraph 定义：assemble → write → save_text → save_summary。

节点函数本身不带依赖（依赖在 runner 注入），graph 只定义拓扑。
节点函数通过 functools.partial 绑定依赖后注册。
"""
from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import StateGraph, START, END

from novel_agent.orchestrator.nodes import (
    assemble_context, write_chapter, save_text, save_summary,
)
from novel_agent.orchestrator.state import ChapterGenState

NODE_NAMES = ["assemble", "write", "save_text", "save_summary"]


def build_graph(deps: dict[str, Any] | None = None):
    """构建流水线图。

    Args:
        deps: 依赖字典，含 repo/llm_client/recall/applier/archival。
              节点函数通过 partial 绑定对应依赖。
    Returns:
        编译后的 StateGraph（未绑定 checkpointer）。
    """
    deps = deps or {}
    graph = StateGraph(ChapterGenState)

    assemble_fn = partial(assemble_context, repo=deps["repo"],
                          archival=deps.get("archival"))
    write_fn = partial(write_chapter, llm_client=deps["llm_client"])
    save_text_fn = partial(save_text, recall=deps["recall"])
    save_summary_fn = partial(save_summary, applier=deps["applier"])

    graph.add_node("assemble", assemble_fn)
    graph.add_node("write", write_fn)
    graph.add_node("save_text", save_text_fn)
    graph.add_node("save_summary", save_summary_fn)

    graph.add_edge(START, "assemble")
    graph.add_edge("assemble", "write")
    graph.add_edge("write", "save_text")
    graph.add_edge("save_text", "save_summary")
    graph.add_edge("save_summary", END)

    return graph.compile()
