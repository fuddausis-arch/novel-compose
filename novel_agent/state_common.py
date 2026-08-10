"""各域状态常量集中定义。

背景：此前状态字符串散落在 20+ 个文件里硬编码，"运行中"有 6 种写法、
"失败"有 3 种写法，且同名事件（review_pending）在不同路径结构不同。
本模块把各域的状态常量收拢到一处，便于统一查阅与修改，并做两件事：

1. 对齐命名规范：运行中一律用 *running*、失败一律用 *failed*、
   等待人工审校一律用 *review_pending*（DB 存量历史值除外，见下）。
2. 不强行合并不同领域的生命周期：规划/蒸馏/圆桌/工作流各有独立状态机，
   它们唯一的共同点只是都叫 status 字段，强行合并会让领域语义丢失。

注意（兼容性红线）：
- DB 已存量的历史值（如蒸馏的 "distilling"、梗的 "待用/使用中/已用"）保持原样，
  新增代码用新规范，存量数据不做迁移，避免历史记录错乱。
- 各枚举值均为字符串，.value 即原字符串，替换硬编码时直接用 .value 或字符串字面量均可。
"""
from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    """任务级通用状态（checkpoint / 工作流执行 / 批量生成 / 执行控制）。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    PENDING_REVIEW = "pending_review"  # 历史写法，新代码统一用 ReviewStatus.REVIEW_PENDING


class ChapterGenStatus(str, Enum):
    """单章生成流水线状态（LangGraph orchestrator / routes_chapters）。"""

    PENDING = "pending"
    ASSEMBLED = "assembled"
    DRAFTED = "drafted"
    AUDITED = "audited"
    NEEDS_REWRITE = "needs_rewrite"
    REVIEWED = "reviewed"
    REVIEW_PENDING = "review_pending"  # 等待人审
    POLISHED = "polished"
    SAVED = "saved"
    COMPLETED = "completed"
    FAILED = "failed"
    END_FAILED = "end_failed"  # LangGraph 特殊终态（审校未过且无法重写）


class ReviewStatus(str, Enum):
    """人审相关状态：统一"等待人工"语义。

    历史散落的同义写法：audited / review_pending / pending_review / needs_rewrite / reviewed，
    新代码统一：审校通过走 audited，等待人审走 review_pending，
    驳回重写走 needs_rewrite，人审后恢复走 reviewed。
    """

    AUDITED = "audited"
    REVIEW_PENDING = "review_pending"
    NEEDS_REWRITE = "needs_rewrite"
    REVIEWED = "reviewed"


class PlanningStatus(str, Enum):
    """规划流程状态（planning/）。"""

    PENDING = "pending"
    PLANNED = "planned"
    DESIGNED = "designed"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class DistillStatus(str, Enum):
    """蒸馏流程状态（distillation/）。

    DISTILLING 为 DB 存量历史值，保持原样不迁移；新代码如需"运行中"语义
    请沿用 DISTILLING 以兼容存量数据。
    """

    PENDING = "pending"
    DISTILLING = "distilling"
    DONE = "done"
    FAILED = "failed"
    DONE_WITH_ERRORS = "done_with_errors"


class RoundtableStatus(str, Enum):
    """圆桌会议状态（roundtable/）。"""

    # 会话级
    WAITING = "waiting"
    DISCUSSING = "discussing"
    PAUSED = "paused"
    ENDED = "ended"
    # 座位级
    IDLE = "idle"
    SPEAKING = "speaking"
    THINKING = "thinking"
    DONE = "done"


class WorkflowNodeStatus(str, Enum):
    """工作流引擎节点状态（workflows/loader.py）。"""

    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
