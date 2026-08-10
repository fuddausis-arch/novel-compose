"""会话上下文管理。

借鉴 DeterminFlow session/ 模块：
- contextvars 实现线程/协程安全的会话上下文传递

设计要点：
- SessionContextManager 基于 contextvars.ContextVar，每个 asyncio Task 拿到的是
  自己的上下文副本，set 不会污染其他协程，天然线程/协程安全。
  （历史死代码已清理：build_system_prompt / assemble_tools 零调用且与实际
   prompt/工具装配路径不符，chat 路径用 orchestrator.build_writer_system_prompt
   与 chat/tools.TOOLS_SCHEMA，工具权限过滤随 tool_permissions 一并移除）
"""
from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 当前协程的会话上下文（默认 None，未设置时 get_context 返回 None）
_session_ctx_var: contextvars.ContextVar[SessionContext | None] = contextvars.ContextVar(
    "novel_agent_session_ctx", default=None
)


@dataclass
class SessionContext:
    """单次会话的运行时上下文。

    Attributes:
        session_id: 会话唯一 id
        workspace_path: 工作空间路径（项目数据目录等）
        parent_id: 父会话 id（子流程场景，None 表示顶层会话）
        agent_type: Agent 角色类型（writer / auditor / planner 等）
        on_node_complete: 节点完成回调（仅工作流节点场景使用）
    """

    session_id: str
    workspace_path: str = ""
    parent_id: str | None = None
    agent_type: str = ""
    on_node_complete: Any = field(default=None, repr=False)


class SessionContextManager:
    """基于 contextvars 的会话上下文管理器。

    所有方法操作的都是当前协程/线程的上下文副本，set 不影响其他协程。
    """

    def set_context(
        self,
        session_id: str,
        agent_type: str,
        **kwargs: Any,
    ) -> SessionContext:
        """设置当前协程的会话上下文。

        Args:
            session_id: 会话 id
            agent_type: Agent 角色类型
            **kwargs: 可选字段 workspace_path / parent_id / on_node_complete

        Returns:
            刚设置的 SessionContext
        """
        ctx = SessionContext(
            session_id=session_id,
            workspace_path=kwargs.get("workspace_path", ""),
            parent_id=kwargs.get("parent_id"),
            agent_type=agent_type,
            on_node_complete=kwargs.get("on_node_complete"),
        )
        _session_ctx_var.set(ctx)
        logger.debug("已设置会话上下文: session=%s agent=%s", session_id, agent_type)
        return ctx

    def get_context(self) -> SessionContext | None:
        """获取当前协程的会话上下文，未设置时返回 None。"""
        return _session_ctx_var.get()

    def clear_context(self) -> None:
        """清除当前协程的会话上下文。"""
        _session_ctx_var.set(None)
        logger.debug("已清除会话上下文")
