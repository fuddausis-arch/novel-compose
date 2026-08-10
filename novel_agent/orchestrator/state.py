"""流水线状态 schema（LangGraph StateGraph 用 TypedDict）。

状态在节点间传递，每个节点读取所需字段、写回产出字段。
M3 扩展：写审循环相关字段。
"""
from __future__ import annotations

from typing import TypedDict


class ChapterGenState(TypedDict, total=False):
    """单章生成的流水线状态。

    user_feedback：人审节点收到用户输入的文字意见（如果有），
                  reject 决策时会被 rewrite_chapter 节点注入到重写 prompt。
    """
    project_id: int
    chapter: int
    title: str
    genre: str                  # 项目题材（用于语感库过滤，防止跨题材污染）
    context: str               # 装配的上下文
    style_benchmark_text: str   # 人类网文样本（write前分析用）
    style_analysis: str         # 人类样本写法分析结果（注入write prompt）
    world_state: str            # world_engine 产出的世界状态 JSON（势力动态/暗线/世界事件）
    world_events: str           # world_engine 产出的世界事件 JSON
    trimmed_context: str        # context_trimmer 裁剪后的上下文
    post_hoc_results: dict      # post_hoc 后验裁决结果（observer+arbiter 两轮 LLM）
    draft: str                 # Writer 产出的正文草稿（当前最高分轮）
    drafts: list[dict]         # 所有草稿版本 [{"version":1,"text":"","score":0}]（Self-Refine取最高分）
    draft_version: int         # 当前草稿版本（写审循环计数）
    review_iterations: int     # 已审阅次数（≤3）
    audit_report: dict         # 最近一次审计报告（序列化）
    polished: str              # 润色后正文
    review_decision: str = ""  # 人审决策："approve" / "reject"
    user_feedback: str = ""    # 人审时用户输入的文字意见，reject 时注入 rewrite prompt
    confidence_level: str = ""  # 置信度："high" / "medium" / "low"，高置信度跳过人审
    status: str                # ChapterGenStatus: pending/assembled/drafted/audited/needs_rewrite/reviewed/polished/saved/completed/failed
    error: str
    word_count: int
    _repo: object              # 内部传递的 repo 引用（不序列化）
    _pending_feedback_ids: list[int]  # C2：待标记已应用的用户反馈 id（summarize 成功后消费）
