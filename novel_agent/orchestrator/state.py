"""流水线状态 schema（LangGraph StateGraph 用 TypedDict）。

状态在节点间传递，每个节点读取所需字段、写回产出字段。
M3 扩展：写审循环相关字段。
"""
from __future__ import annotations

from typing import TypedDict


class ChapterGenState(TypedDict, total=False):
    """单章生成的流水线状态。"""
    project_id: int
    chapter: int
    title: str
    context: str               # 装配的上下文
    draft: str                 # Writer 产出的正文草稿
    draft_version: int         # 当前草稿版本（写审循环计数）
    review_iterations: int     # 已审阅次数（≤3）
    audit_report: dict         # 最近一次审计报告（序列化）
    polished: str              # 润色后正文
    status: str                # pending/assembled/drafted/audited/polished/saved/completed/failed
    error: str
    word_count: int
