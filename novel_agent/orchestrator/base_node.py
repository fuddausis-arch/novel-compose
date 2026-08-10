"""通用 Core Node 抽象基类。

借鉴 DeterminFlow 的 4 类 Core Node：
- AgentNode: LLM 调用节点
- ScriptNode: 确定性脚本节点
- ApprovalNode: 人工审批节点（文件审批，复用 human_review 机制）
- SubprocessNode: 子流程嵌套节点（支持深度限制，防无限递归）
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 子流程嵌套最大深度（防止无限递归导致栈溢出）
_MAX_SUBPROCESS_DEPTH = 5


class BaseNode(ABC):
    """通用 Core Node 抽象基类。

    所有节点类型继承此类，实现 execute() 方法。
    提供 validate_input / validate_output 钩子供子类覆盖。
    """

    def __init__(self, name: str, node_type: str = "base") -> None:
        self.name = name
        self.node_type = node_type

    @abstractmethod
    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """执行节点逻辑，返回状态更新 dict。

        Args:
            state: 当前流水线状态

        Returns:
            状态更新字典（与 LangGraph 节点返回格式一致）
        """
        ...

    def validate_input(self, state: dict[str, Any]) -> bool:
        """输入校验：检查 state 是否包含节点所需字段。

        子类可覆盖以实现具体校验逻辑。
        默认返回 True（不校验）。
        """
        return True

    def validate_output(self, result: dict[str, Any]) -> bool:
        """输出校验：检查执行结果是否合法。

        子类可覆盖以实现具体校验逻辑。
        默认返回 True（不校验）。
        """
        return True

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """带输入/输出校验的执行入口。

        先校验输入，执行节点，再校验输出。
        校验失败时返回 failed 状态（不抛异常，保持流水线健壮性）。
        """
        if not self.validate_input(state):
            logger.warning("节点 %s 输入校验失败", self.name)
            return {"status": "failed", "error": f"节点 {self.name} 输入校验失败"}
        result = await self.execute(state)
        if not self.validate_output(result):
            logger.warning("节点 %s 输出校验失败", self.name)
            return {"status": "failed", "error": f"节点 {self.name} 输出校验失败"}
        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} type={self.node_type!r}>"


class AgentNode(BaseNode):
    """LLM 调用节点的基类。

    子类需实现 execute()，在其中调用 LLMClient 生成内容。
    提供 llm_client 属性供子类使用。
    """

    def __init__(self, name: str, llm_client: Any = None) -> None:
        super().__init__(name, node_type="agent")
        self.llm_client = llm_client

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """子类实现：调用 LLM 生成内容并返回状态更新。"""
        raise NotImplementedError("AgentNode 子类必须实现 execute()")

    def validate_input(self, state: dict[str, Any]) -> bool:
        """AgentNode 输入校验：确保有 llm_client 可用。"""
        return self.llm_client is not None


class ScriptNode(BaseNode):
    """确定性脚本节点的基类。

    不调用 LLM，执行纯确定性逻辑（如文件读写、数据处理、规则检查）。
    子类实现 execute() 完成具体脚本逻辑。
    """

    def __init__(self, name: str) -> None:
        super().__init__(name, node_type="script")

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """子类实现：执行确定性脚本逻辑。"""
        raise NotImplementedError("ScriptNode 子类必须实现 execute()")


class ApprovalNode(BaseNode):
    """人工审批节点（文件审批）。

    借鉴 DeterminFlow ApprovalNode + 复用现有 human_review 机制：
    - 读取待审批文件内容
    - 通过 LangGraph interrupt() 暂停执行，等待用户审批
    - 支持三种审批类型：approve / reject / request_changes
    """

    def __init__(
        self,
        name: str,
        file_path: str = "",
        approval_type: str = "approve",
    ) -> None:
        super().__init__(name, node_type="approval")
        self.file_path = file_path
        # approval_type 仅用于记录预期审批类型，实际决策由用户通过 resume 传入
        self.approval_type = approval_type

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """读取文件，等待用户审批，返回审批结果。

        使用 LangGraph interrupt() 暂停执行，等待用户通过 /resume API 传入决策。
        复用现有 human_review 节点的 interrupt 机制。
        """
        from langgraph.types import interrupt

        # 读取待审批文件内容
        file_content = ""
        if self.file_path:
            try:
                path = Path(self.file_path)
                if path.exists():
                    file_content = path.read_text(encoding="utf-8", errors="replace")
                else:
                    logger.warning("ApprovalNode %s: 文件不存在 %s", self.name, self.file_path)
            except Exception as e:
                logger.warning("ApprovalNode %s: 读取文件失败 %s: %s", self.name, self.file_path, e)

        # interrupt 暂停执行，等待用户审批
        # resume_value 兼容字符串和字典格式
        resume_value = interrupt({
            "node": self.name,
            "approval_type": self.approval_type,
            "file_path": self.file_path,
            "file_preview": file_content[:2000] if file_content else "",
        })

        # 解析审批结果
        if isinstance(resume_value, dict):
            decision = resume_value.get("decision", "approve")
            feedback = (resume_value.get("feedback", "") or "").strip()
        else:
            decision = resume_value or "approve"
            feedback = ""

        logger.info("ApprovalNode %s: 审批结果=%s", self.name, decision)
        update: dict[str, Any] = {
            "approval_decision": decision,
            "status": "approved" if decision == "approve" else "rejected",
        }
        if feedback:
            update["approval_feedback"] = feedback
        return update

    def validate_input(self, state: dict[str, Any]) -> bool:
        """审批节点输入校验：file_path 不能为空。"""
        return bool(self.file_path)


class SubprocessNode(BaseNode):
    """子流程嵌套节点。

    借鉴 DeterminFlow SubprocessNode：
    - 持有一个子流程图（StateGraph）
    - execute() 执行子流程，返回子流程的最终状态
    - 支持嵌套深度限制（防止无限递归）
    """

    def __init__(
        self,
        name: str,
        subgraph: Any = None,
        max_depth: int = _MAX_SUBPROCESS_DEPTH,
    ) -> None:
        super().__init__(name, node_type="subprocess")
        self.subgraph = subgraph
        self.max_depth = max_depth

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """执行子流程，返回子流程的最终状态。

        从 state 中读取 _subprocess_depth（默认 0），递增后传入子流程。
        超过 max_depth 时拒绝执行，返回 failed 状态。
        """
        current_depth = state.get("_subprocess_depth", 0)
        if current_depth >= self.max_depth:
            logger.warning(
                "SubprocessNode %s: 嵌套深度 %d 超过上限 %d，拒绝执行",
                self.name, current_depth, self.max_depth,
            )
            return {
                "status": "failed",
                "error": f"子流程嵌套深度超过上限 {self.max_depth}",
            }

        if self.subgraph is None:
            logger.warning("SubprocessNode %s: 未设置子流程图", self.name)
            return {"status": "failed", "error": "未设置子流程图"}

        # 构建子流程初始状态：继承父状态 + 递增深度
        child_state = dict(state)
        child_state["_subprocess_depth"] = current_depth + 1

        try:
            # 子流程 thread_id 隔离，避免与父流程 checkpoint 冲突
            import uuid
            child_thread_id = f"sub_{self.name}_{uuid.uuid4().hex[:8]}"
            result = await self.subgraph.ainvoke(
                child_state,
                config={"configurable": {"thread_id": child_thread_id}},
            )
            # 清理子流程内部字段，避免污染父状态
            result.pop("_subprocess_depth", None)
            result["_subprocess_completed"] = True
            logger.info("SubprocessNode %s: 子流程执行完成（深度=%d）", self.name, current_depth + 1)
            return result
        except Exception as e:
            logger.warning("SubprocessNode %s: 子流程执行失败: %s", self.name, e)
            return {"status": "failed", "error": f"子流程执行失败: {e}"}

    def validate_input(self, state: dict[str, Any]) -> bool:
        """子流程节点输入校验：subgraph 不能为 None。"""
        return self.subgraph is not None
