"""会话上下文管理。

借鉴 DeterminFlow session/ 模块：
- contextvars 实现线程/协程安全的会话上下文传递
- 统一的 prompt 构建和工具组装

设计要点：
- SessionContextManager 基于 contextvars.ContextVar，每个 asyncio Task 拿到的是
  自己的上下文副本，set 不会污染其他协程，天然线程/协程安全。
- build_system_prompt 统一注入会话信息 + PromptManager section + 模板变量替换。
- assemble_tools 委托 tool_permissions.filter_tools_for_role 做角色级工具过滤。
"""
from __future__ import annotations

import contextvars
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 当前协程的会话上下文（默认 None，未设置时 get_context 返回 None）
_session_ctx_var: contextvars.ContextVar[SessionContext | None] = contextvars.ContextVar(
    "novel_agent_session_ctx", default=None
)

# 模板变量正则：匹配 {{variable}}，与 PromptManager 保持一致
_TEMPLATE_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


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


def _render_template_vars(text: str, variables: dict) -> str:
    """替换 text 中的 {{variable}} 模板变量。

    未提供值的变量保留原样（与 PromptManager._render_template 行为一致），
    便于分阶段填充。
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return str(variables.get(key, match.group(0)))

    return _TEMPLATE_VAR_RE.sub(_replace, text)


def build_system_prompt(
    agent_type: str,
    base_prompt: str,
    variables: dict,
) -> str:
    """统一 prompt 构建：注入 PromptManager section + base_prompt + 会话信息。

    组装顺序：
    1. PromptManager 中该 agent_type 的 section（若存在）
    2. base_prompt（替换 {{variable}} 模板变量）
    3. 当前会话上下文信息（session_id / workspace / agent_type）

    Args:
        agent_type: Agent 角色类型（用于取 PromptManager section）
        base_prompt: 基础提示词，支持 {{variable}} 模板变量
        variables: 模板变量字典

    Returns:
        拼接后的完整系统提示词
    """
    parts: list[str] = []

    # 1. PromptManager section（如果该 agent_type 有 section 定义）
    try:
        from novel_agent.prompts.section_manager import PromptManager

        pm = PromptManager()
        section_prompt = pm.build_prompt(agent_type, variables)
        if section_prompt:
            parts.append(section_prompt)
    except Exception as e:
        # PromptManager 不可用不影响主流程
        logger.debug("加载 PromptManager section 失败，跳过: %s", e)

    # 2. base_prompt（替换模板变量）
    if base_prompt:
        parts.append(_render_template_vars(base_prompt, variables))

    # 3. 注入当前会话上下文信息
    ctx = SessionContextManager().get_context()
    if ctx is not None:
        parts.append(
            "【会话上下文】\n"
            f"会话ID: {ctx.session_id}\n"
            f"工作空间: {ctx.workspace_path or '(未指定)'}\n"
            f"Agent类型: {ctx.agent_type}"
        )

    return "\n\n".join(parts)


def assemble_tools(agent_type: str, all_tools: dict) -> dict:
    """统一工具组装：调用 tool_permissions.filter_tools_for_role 做角色级过滤。

    借鉴 DeterminFlow session/tool_assembler.py 的统一组装入口思路，
    把权限过滤收敛到一处，避免各 agent 各自重复实现。

    Args:
        agent_type: Agent 角色类型（writer / auditor / planner 等）
        all_tools: 全部工具集合，支持 dict[str, dict] 或 list[dict]（OpenAI 格式）

    Returns:
        过滤后的工具字典 {工具名: 工具定义}
    """
    from novel_agent.chat.tool_permissions import filter_tools_for_role

    return filter_tools_for_role(agent_type, all_tools)
