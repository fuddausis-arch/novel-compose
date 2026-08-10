"""StateGraph 定义：world_engine->assemble->context_trimmer->analyze_style->write->audit->{达标:human_review->style_refine->save_text->summarize->post_hoc | 不达标≤3:rewrite->audit | 超3:END}

写审分离铁律：Writer 与 Auditor 独立；反馈循环 ≤3 次。
人审 checkpoint：审计达标后、风格模仿前挂起，用户通过->style_refine，驳回->rewrite。
Phase 1 新增：world_engine（写前世界推演）、context_trimmer（上下文裁剪）、post_hoc（写后裁决）。
Phase 1.6：节点级失败恢复（非关键节点 retry+skip，关键节点 retry+fail_end）。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from functools import partial, wraps
from typing import Any, Callable

from langgraph.graph import StateGraph, START, END

from novel_agent.orchestrator.nodes import (
    assemble_context, analyze_style_benchmark, write_chapter, audit_chapter, rewrite_chapter,
    style_refine_chapter, save_text_polished, summarize_chapter,
    route_after_audit, human_review,
)
from novel_agent.orchestrator.world_nodes import (
    world_engine, context_trimmer, post_hoc,
)
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.state_common import ChapterGenStatus

logger = logging.getLogger(__name__)

NODE_NAMES = [
    "world_engine", "assemble", "context_trimmer", "analyze_style",
    "write", "audit", "rewrite", "human_review", "style_refine",
    "save_text", "summarize", "post_hoc",
]

# 非关键节点：失败后 skip（返回空/默认值，不阻塞流水线）
_NON_CRITICAL_NODES = {"world_engine", "context_trimmer", "post_hoc", "analyze_style", "style_refine"}


def _with_retry(node_name: str, max_retries: int = 1):
    """节点级失败恢复包装器。

    非关键节点：retry max_retries 次，仍失败则 log warning 并返回 skip 状态。
    关键节点：retry max_retries 次，仍失败则返回 failed 状态（触发 END）。

    Args:
        node_name: 节点名称（用于日志和判断是否关键节点）
        max_retries: 最大重试次数（不含首次执行）
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(state: ChapterGenState) -> dict:
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    result = fn(state)
                    # 兼容同步节点（如 assemble_context/save_text_polished，返回 dict）
                    # 与异步节点（返回 coroutine）：只有 awaitable 才 await，否则直接返回
                    if inspect.isawaitable(result):
                        result = await result
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warning("节点 %s 第%d次执行失败，重试中: %s", node_name, attempt + 1, e)
                        await asyncio.sleep(1.0 * (attempt + 1))  # 指数退避
                    else:
                        logger.error("节点 %s 重试 %d 次后仍失败: %s", node_name, max_retries, e)

            # 重试耗尽：非关键节点 skip，关键节点 fail
            if node_name in _NON_CRITICAL_NODES:
                logger.warning("节点 %s 失败（非关键，skip 不阻塞流水线）", node_name)
                return {}
            else:
                logger.error("节点 %s 失败（关键节点，终止流水线）", node_name)
                return {"status": ChapterGenStatus.FAILED.value, "error": f"{node_name} 节点失败: {last_error}"}

        return wrapper
    return decorator


def _route_after_write(state: ChapterGenState) -> str:
    """write/rewrite 后：失败直接 END，成功进 audit。"""
    import logging
    logger = logging.getLogger(__name__)
    status = state.get("status")
    draft_len = len(state.get("draft", "").strip())
    logger.warning("_route_after_write 第%s章：status=%s draft_len=%d", state.get("chapter"), status, draft_len)
    if status == ChapterGenStatus.FAILED.value or not draft_len:
        logger.warning("_route_after_write 第%s章进入 end_failed：status=%s draft_len=%d", state.get("chapter"), status, draft_len)
        return "end_failed"
    return "audit"


def route_after_review(state: ChapterGenState) -> str:
    """条件边：人审通过->style_refine；驳回->rewrite。"""
    if state.get("review_decision") == "reject":
        return "rewrite"
    return "style_refine"


def _route_after_post_hoc(state: ChapterGenState) -> str:
    """条件边：post_hoc 后验裁决后，critical 级世界事实冲突触发定向返工。

    借鉴 DeterminFlow reject_upstream 机制：下游节点（post_hoc）可拒绝
    上游节点（save_text）的结果，路由回 style_refine 重写。
    - critical_count > 0 且 review_iterations < 3 -> style_refine（返工）
    - 否则 -> END
    """
    post_hoc_results = state.get("post_hoc_results", {})
    arbiter = post_hoc_results.get("arbiter", {})
    summary = arbiter.get("summary", {})
    critical_count = summary.get("critical_count", 0)
    review_iterations = state.get("review_iterations", 0)

    if critical_count > 0 and review_iterations < 3:
        logger.warning(
            "_route_after_post_hoc 第%s章：后验裁决发现 %d 个 critical 问题，"
            "返工计数 %d < 3，路由到 style_refine 重写",
            state.get("chapter"), critical_count, review_iterations,
        )
        return "rework"
    return "end"


def build_graph(deps: dict[str, Any] | None = None, checkpointer: Any = None):
    """构建写审循环流水线图。

    Args:
        deps: 依赖字典，含 repo/llm_client/recall/applier/archival/auditor。
        checkpointer: LangGraph checkpointer（SqliteSaver），用于 interrupt/resume。
    Returns:
        编译后的 StateGraph。
    """
    deps = deps or {}
    graph = StateGraph(ChapterGenState)

    # Phase 1 新节点：世界推演、上下文裁剪、后验裁决
    world_engine_fn = partial(world_engine, llm_client=deps["llm_client"], repo=deps["repo"])
    context_trimmer_fn = partial(context_trimmer, llm_client=deps["llm_client"], repo=deps["repo"])
    post_hoc_fn = partial(post_hoc, llm_client=deps.get("summarizer_client", deps["llm_client"]), repo=deps["repo"])

    async def _post_hoc_with_rework_counter(state: ChapterGenState) -> dict:
        """post_hoc 包装：执行后递增 review_iterations，用于返工循环计数。

        post_hoc -> style_refine 返工路径不走 audit 节点，review_iterations
        不会自然递增，需在此显式递增以防无限循环。
        """
        result = await post_hoc_fn(state)
        if result is None:
            result = {}
        # 递增 review_iterations，防止 post_hoc -> style_refine 无限循环
        result["review_iterations"] = state.get("review_iterations", 0) + 1
        return result

    assemble_fn = partial(assemble_context, repo=deps["repo"], archival=deps.get("archival"))
    analyze_style_fn = partial(analyze_style_benchmark, llm_client=deps["llm_client"], repo=deps.get("repo"))
    write_fn = partial(write_chapter, llm_client=deps["llm_client"], repo=deps.get("repo"), config=deps.get("config"))
    audit_fn = partial(audit_chapter, auditor=deps["auditor"], repo=deps["repo"], config=deps.get("config"))
    rewrite_fn = partial(rewrite_chapter, llm_client=deps["llm_client"], repo=deps.get("repo"))
    style_refine_fn = partial(style_refine_chapter, llm_client=deps.get("polisher_client", deps["llm_client"]))
    save_fn = partial(save_text_polished, recall=deps["recall"])
    summarize_fn = partial(summarize_chapter, llm_client=deps.get("summarizer_client", deps["llm_client"]), applier=deps["applier"], repo=deps.get("repo"))

    # Phase 1.6：节点级失败恢复 -- 非关键节点 retry+skip，关键节点 retry+fail
    graph.add_node("world_engine", _with_retry("world_engine")(world_engine_fn))
    graph.add_node("assemble", _with_retry("assemble")(assemble_fn))
    graph.add_node("context_trimmer", _with_retry("context_trimmer")(context_trimmer_fn))
    graph.add_node("analyze_style", _with_retry("analyze_style")(analyze_style_fn))
    graph.add_node("write", _with_retry("write")(write_fn))
    graph.add_node("audit", _with_retry("audit")(audit_fn))
    graph.add_node("rewrite", _with_retry("rewrite")(rewrite_fn))
    graph.add_node("human_review", human_review)
    graph.add_node("style_refine", _with_retry("style_refine")(style_refine_fn))
    graph.add_node("save_text", _with_retry("save_text")(save_fn))
    graph.add_node("summarize", _with_retry("summarize")(summarize_fn))
    graph.add_node("post_hoc", _with_retry("post_hoc")(_post_hoc_with_rework_counter))

    # Phase 1 新工作流：START -> world_engine -> assemble -> context_trimmer -> analyze_style -> write -> ...
    graph.add_edge(START, "world_engine")
    graph.add_edge("world_engine", "assemble")
    graph.add_edge("assemble", "context_trimmer")
    graph.add_edge("context_trimmer", "analyze_style")
    graph.add_edge("analyze_style", "write")
    # write 后条件路由：失败直接 END，成功进 audit
    graph.add_conditional_edges(
        "write", _route_after_write,
        {"audit": "audit", "end_failed": END},
    )
    # 审计后条件路由：高置信度→直接style_refine，中低置信度→人审，不达标→rewrite/END
    graph.add_conditional_edges(
        "audit", route_after_audit,
        {"style_refine": "human_review", "skip_review": "style_refine", "rewrite": "rewrite", "end_failed": END},
    )
    # rewrite 后也条件路由：失败直接 END，成功回 audit
    graph.add_conditional_edges(
        "rewrite", _route_after_write,
        {"audit": "audit", "end_failed": END},
    )
    # 人审后：通过→style_refine，驳回→rewrite
    graph.add_conditional_edges(
        "human_review", route_after_review,
        {"style_refine": "style_refine", "rewrite": "rewrite"},
    )
    # style_refine 后→save_text
    graph.add_edge("style_refine", "save_text")
    graph.add_edge("save_text", "summarize")
    # Phase 1：summarize 后接 post_hoc（后验裁决），再 END
    graph.add_edge("summarize", "post_hoc")
    # post_hoc 后条件路由：critical 级世界事实冲突 -> style_refine 返工，否则 END
    # 借鉴 DeterminFlow reject_upstream：下游拒绝上游结果，定向返工
    graph.add_conditional_edges(
        "post_hoc", _route_after_post_hoc,
        {"rework": "style_refine", "end": END},
    )

    return graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
