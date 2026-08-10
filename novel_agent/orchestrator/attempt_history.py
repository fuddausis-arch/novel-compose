"""并行/循环/子流程独立尝试历史。

借鉴 DeterminFlow 的并行/循环节点设计：
- 每个并行分支有独立的 attempt 计数
- 循环节点每次迭代有独立的尝试历史
- 子流程嵌套时保持独立的 attempt 栈
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AttemptRecord:
    """单次尝试记录。

    Attributes:
        node_id: 节点标识
        branch_id: 并行分支标识（主流程为 "main"）
        iteration: 循环迭代轮次（非循环节点为 0）
        attempt_count: 第几次尝试（从 1 开始）
        status: 尝试状态（ok / failed / skipped 等）
        timestamp: 记录时间（UTC ISO 格式字符串）
    """

    node_id: str
    branch_id: str
    iteration: int
    attempt_count: int
    status: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好的 dict。"""
        return {
            "node_id": self.node_id,
            "branch_id": self.branch_id,
            "iteration": self.iteration,
            "attempt_count": self.attempt_count,
            "status": self.status,
            "timestamp": self.timestamp,
        }


class AttemptHistory:
    """尝试历史管理器：按 (node_id, branch_id) 维护独立尝试记录。

    并行分支、循环迭代、子流程嵌套各有独立的 attempt 计数，
    互不干扰。支持查询、清除、序列化。
    """

    def __init__(self) -> None:
        # key: (node_id, branch_id) -> list[AttemptRecord]
        self._records: dict[tuple[str, str], list[AttemptRecord]] = {}
        # key: (node_id, branch_id) -> 当前 attempt 计数
        self._counters: dict[tuple[str, str], int] = {}

    def record(
        self,
        node_id: str,
        branch_id: str,
        iteration: int,
        status: str,
    ) -> AttemptRecord:
        """记录一次尝试。

        Args:
            node_id: 节点标识
            branch_id: 并行分支标识
            iteration: 循环迭代轮次
            status: 尝试状态

        Returns:
            本次尝试对应的 AttemptRecord
        """
        key = (node_id, branch_id)
        self._counters[key] = self._counters.get(key, 0) + 1
        attempt_count = self._counters[key]
        record = AttemptRecord(
            node_id=node_id,
            branch_id=branch_id,
            iteration=iteration,
            attempt_count=attempt_count,
            status=status,
        )
        self._records.setdefault(key, []).append(record)
        logger.debug(
            "AttemptHistory 记录: node=%s branch=%s iter=%d attempt=%d status=%s",
            node_id, branch_id, iteration, attempt_count, status,
        )
        return record

    def get_attempts(
        self, node_id: str, branch_id: str
    ) -> list[AttemptRecord]:
        """获取某节点在某分支的全部尝试历史。"""
        return list(self._records.get((node_id, branch_id), []))

    def get_attempt_count(self, node_id: str, branch_id: str) -> int:
        """获取某节点在某分支的尝试次数。"""
        return self._counters.get((node_id, branch_id), 0)

    def clear(self, node_id: str, branch_id: str) -> None:
        """清除某节点在某分支的尝试历史。"""
        key = (node_id, branch_id)
        self._records.pop(key, None)
        self._counters.pop(key, None)

    def clear_all(self) -> None:
        """清除全部尝试历史。"""
        self._records.clear()
        self._counters.clear()

    def to_dict(self) -> list[dict[str, Any]]:
        """序列化为 JSON 友好的 list[dict]。"""
        result: list[dict[str, Any]] = []
        for records in self._records.values():
            for r in records:
                result.append(r.to_dict())
        return result
