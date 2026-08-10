"""工作流执行控制层。

借鉴 DeterminFlow workflow/ 的执行控制：
- execution_control: 暂停/恢复/取消（用 asyncio.Event 实现）
- execution_flow: 节点间数据流管理
- execution_loop: 主执行循环

复用现有的 LangGraph 执行机制，ExecutionController 的 pause/resume 用 asyncio.Event 实现。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from novel_agent.state_common import TaskStatus

logger = logging.getLogger(__name__)


class ExecutionController:
    """执行控制器：暂停/恢复/取消工作流。

    用 asyncio.Event 实现暂停/恢复：
    - pause: clear() 事件，节点执行前会阻塞等待
    - resume: set() 事件，解除阻塞
    - cancel: 设置取消标志，节点检查后主动退出

    与 orchestrator/runner.py 的取消令牌机制配合使用。
    """

    def __init__(self) -> None:
        # thread_id -> 执行状态
        self._statuses: dict[str, str] = {}
        # thread_id -> pause 事件（set=运行中, clear=已暂停）
        self._pause_events: dict[str, asyncio.Event] = {}
        # thread_id -> cancel 事件
        self._cancel_events: dict[str, asyncio.Event] = {}

    def _get_pause_event(self, thread_id: str) -> asyncio.Event:
        """获取或创建 thread 的 pause 事件（默认 set=True 即可运行）。"""
        if thread_id not in self._pause_events:
            event = asyncio.Event()
            event.set()  # 默认可运行
            self._pause_events[thread_id] = event
        return self._pause_events[thread_id]

    def _get_cancel_event(self, thread_id: str) -> asyncio.Event:
        """获取或创建 thread 的 cancel 事件。"""
        if thread_id not in self._cancel_events:
            self._cancel_events[thread_id] = asyncio.Event()
        return self._cancel_events[thread_id]

    def pause(self, thread_id: str) -> bool:
        """暂停执行。

        Args:
            thread_id: 线程 ID

        Returns:
            成功暂停返回 True，未找到线程返回 False
        """
        event = self._get_pause_event(thread_id)
        event.clear()
        self._statuses[thread_id] = TaskStatus.PAUSED.value
        logger.info("ExecutionController: 线程 %s 已暂停", thread_id)
        return True

    def resume(self, thread_id: str) -> bool:
        """恢复执行。

        Args:
            thread_id: 线程 ID

        Returns:
            成功恢复返回 True
        """
        event = self._get_pause_event(thread_id)
        event.set()
        self._statuses[thread_id] = TaskStatus.RUNNING.value
        logger.info("ExecutionController: 线程 %s 已恢复", thread_id)
        return True

    def cancel(self, thread_id: str) -> bool:
        """取消执行。

        Args:
            thread_id: 线程 ID

        Returns:
            成功取消返回 True
        """
        cancel_event = self._get_cancel_event(thread_id)
        cancel_event.set()
        self._statuses[thread_id] = TaskStatus.CANCELLED.value
        # 取消时也要 resume pause 事件，否则会永远阻塞
        pause_event = self._get_pause_event(thread_id)
        pause_event.set()
        logger.info("ExecutionController: 线程 %s 已取消", thread_id)
        return True

    def get_status(self, thread_id: str) -> str:
        """获取执行状态。

        Returns:
            状态字符串：running / paused / cancelled / unknown
        """
        if self._get_cancel_event(thread_id).is_set():
            return TaskStatus.CANCELLED.value
        if not self._get_pause_event(thread_id).is_set():
            return TaskStatus.PAUSED.value
        return self._statuses.get(thread_id, "unknown")

    def is_cancelled(self, thread_id: str) -> bool:
        """检查线程是否已被取消。"""
        return self._get_cancel_event(thread_id).is_set()

    async def wait_if_paused(self, thread_id: str) -> None:
        """如果线程被暂停，阻塞等待直到恢复或取消。

        供节点在执行前调用，实现暂停效果。
        """
        pause_event = self._get_pause_event(thread_id)
        await pause_event.wait()

    def cleanup(self, thread_id: str) -> None:
        """清理已完成线程的资源。"""
        self._statuses.pop(thread_id, None)
        self._pause_events.pop(thread_id, None)
        self._cancel_events.pop(thread_id, None)


class DataFlowManager:
    """节点间数据流管理。

    借鉴 DeterminFlow execution_flow.py：
    - pass_data: 节点间显式数据传递（带校验）
    - get_input: 获取节点输入（从 state 中提取所需字段）

    与 LangGraph 的隐式 state 传递互补，提供显式数据流控制点。
    """

    def __init__(self) -> None:
        # (from_node, to_node) -> 传递的数据
        self._data_store: dict[tuple[str, str], dict[str, Any]] = {}

    def pass_data(
        self,
        from_node: str,
        to_node: str,
        data: dict[str, Any],
    ) -> None:
        """节点间数据传递。

        Args:
            from_node: 源节点名
            to_node: 目标节点名
            data: 传递的数据
        """
        key = (from_node, to_node)
        self._data_store[key] = data
        logger.debug("DataFlowManager: %s -> %s 传递 %d 个字段", from_node, to_node, len(data))

    def get_input(self, node_name: str, state: dict[str, Any]) -> dict[str, Any]:
        """获取节点输入。

        合并所有指向 node_name 的传递数据 + 当前 state。
        传递数据优先级高于 state（显式传递覆盖隐式 state）。

        Args:
            node_name: 目标节点名
            state: 当前流水线状态

        Returns:
            合并后的输入字典
        """
        result = dict(state)
        # 收集所有指向该节点的传递数据
        for (from_node, to_node), data in self._data_store.items():
            if to_node == node_name:
                result.update(data)
        return result

    def clear_node_data(self, node_name: str) -> None:
        """清除与某节点相关的所有传递数据。"""
        keys_to_remove = [
            key for key in self._data_store
            if key[0] == node_name or key[1] == node_name
        ]
        for key in keys_to_remove:
            self._data_store.pop(key, None)


class ExecutionLoop:
    """主执行循环。

    借鉴 DeterminFlow execution_loop.py：
    封装 LangGraph 的 ainvoke 调用，集成 ExecutionController 的暂停/取消控制。

    复用现有 LangGraph 执行机制，不重新实现图遍历。
    """

    def __init__(self, controller: ExecutionController | None = None) -> None:
        self.controller = controller or ExecutionController()

    async def run(
        self,
        graph: Any,
        initial_state: dict[str, Any],
        thread_id: str,
    ) -> dict[str, Any]:
        """主执行循环：运行 graph，支持暂停/取消。

        Args:
            graph: 编译后的 LangGraph 图
            initial_state: 初始状态
            thread_id: 线程 ID（用于暂停/取消控制）

        Returns:
            graph 执行结果
        """
        self.controller._statuses[thread_id] = "running"
        try:
            # 在执行前检查是否已取消
            if self.controller.is_cancelled(thread_id):
                return {"status": "cancelled", "error": "执行已被取消"}

            # 如果被暂停，等待恢复
            await self.controller.wait_if_paused(thread_id)

            result = await graph.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )

            if self.controller.is_cancelled(thread_id):
                self.controller._statuses[thread_id] = "cancelled"
                return {"status": "cancelled", "error": "执行已被取消"}
            self.controller._statuses[thread_id] = "completed"
            return result
        except asyncio.CancelledError:
            self.controller._statuses[thread_id] = "cancelled"
            logger.info("ExecutionLoop: 线程 %s 被取消", thread_id)
            return {"status": "cancelled", "error": "执行被取消"}
        except Exception as e:
            self.controller._statuses[thread_id] = "failed"
            logger.warning("ExecutionLoop: 线程 %s 执行失败: %s", thread_id, e)
            raise
        finally:
            # 不立即清理，保留状态供查询；由调用方在合适时机 cleanup
            pass
