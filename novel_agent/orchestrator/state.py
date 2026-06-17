"""流水线状态 schema（LangGraph StateGraph 用 TypedDict）。

状态在节点间传递，每个节点读取所需字段、写回产出字段。
"""
from __future__ import annotations

from typing import TypedDict


class ChapterGenState(TypedDict, total=False):
    """单章生成的流水线状态。"""
    project_id: int          # 项目 id
    chapter: int             # 章节号
    title: str               # 章节标题
    context: str             # 装配的上下文（core memory + archival 检索）
    draft: str               # Writer 产出的正文草稿
    status: str              # pending / assembled / drafted / saved / completed / failed
    error: str               # 失败时的错误信息
    word_count: int          # 章节字数
