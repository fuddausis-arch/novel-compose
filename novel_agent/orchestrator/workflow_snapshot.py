"""Workflow 定义快照 + 配置漂移防护。

借鉴 DeterminFlow runtime_guards.py：
- Task 启动时冻结 Workflow 定义（节点列表 + 边 + 参数）
- 运行时校验当前 graph 是否与快照一致（sha256）
- 不一致则 warning（不阻塞，但记录漂移）
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 快照 schema 版本标识（借鉴 DeterminFlow RUNTIME_GUARD_SCHEMA）
SNAPSHOT_SCHEMA = "workflow_snapshot.v1"


def _canonicalize(node_names: list[str], edges: list[tuple]) -> str:
    """将节点名和边规范化为确定性 JSON 字符串。

    借鉴 DeterminFlow runtime_guards.py 的 file_sha256 思路：
    对定义内容做哈希前先规范化（排序），确保元素顺序不影响哈希结果。
    """
    payload = {
        "nodes": sorted(node_names),
        # 边统一转 tuple 再排序，兼容 list/tuple 混合输入
        "edges": sorted([tuple(e) for e in edges]),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _compute_sha256(node_names: list[str], edges: list[tuple]) -> str:
    """计算节点列表 + 边的 sha256 指纹。"""
    canonical = _canonicalize(node_names, edges)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_workflow(node_names: list[str], edges: list[tuple]) -> dict:
    """冻结 Workflow 定义，返回快照 dict（含 sha256 指纹）。

    借鉴 DeterminFlow freeze_workflow_runtime_guards：在 Task 启动时
    对定义做不可变快照，后续运行时据此检测漂移。

    Args:
        node_names: 节点名称列表
        edges: 边列表，每条边是 (source, target) 元组

    Returns:
        快照 dict，包含 schema_version、nodes、edges、sha256
    """
    sha = _compute_sha256(node_names, edges)
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "nodes": sorted(node_names),
        "edges": sorted([tuple(e) for e in edges]),
        "sha256": sha,
    }


def verify_workflow(snapshot: dict, node_names: list[str], edges: list[tuple]) -> bool:
    """校验当前 graph 是否与快照一致。

    不一致时只记 warning 不抛异常（漂移防护不阻塞流水线）。

    Args:
        snapshot: freeze_workflow 返回的快照 dict
        node_names: 当前节点名称列表
        edges: 当前边列表

    Returns:
        True 表示一致（无漂移），False 表示检测到漂移
    """
    current_sha = _compute_sha256(node_names, edges)
    snapshot_sha = snapshot.get("sha256", "")
    if current_sha != snapshot_sha:
        logger.warning(
            "检测到 Workflow 配置漂移：快照 sha256=%s, 当前 sha256=%s",
            snapshot_sha[:16], current_sha[:16],
        )
        return False
    return True


class WorkflowSnapshot:
    """Workflow 定义快照管理器：freeze/verify/serialize/deserialize。

    借鉴 DeterminFlow runtime_guards.py 的 freeze/refresh 双阶段模式：
    - freeze() 在 Task 启动时冻结定义，生成不可变指纹
    - verify() 运行时校验当前定义是否与快照一致
    - serialize()/deserialize() 支持快照持久化（存 DB / 跨进程传递）
    """

    def __init__(self, node_names: list[str] | None = None, edges: list[tuple] | None = None):
        self._snapshot: dict | None = None
        if node_names is not None and edges is not None:
            self.freeze(node_names, edges)

    def freeze(self, node_names: list[str], edges: list[tuple]) -> dict:
        """冻结当前 Workflow 定义，返回快照 dict。"""
        self._snapshot = freeze_workflow(node_names, edges)
        logger.info("Workflow 定义已冻结，sha256=%s", self._snapshot["sha256"][:16])
        return self._snapshot

    def verify(self, node_names: list[str], edges: list[tuple]) -> bool:
        """校验当前定义是否与冻结的快照一致。

        未冻结时返回 True（无快照可校验，视为通过）。
        """
        if self._snapshot is None:
            return True
        return verify_workflow(self._snapshot, node_names, edges)

    def serialize(self) -> str:
        """序列化快照为 JSON 字符串，用于持久化存储。"""
        if self._snapshot is None:
            raise ValueError("快照未冻结，无法序列化")
        return json.dumps(self._snapshot, ensure_ascii=False)

    @classmethod
    def deserialize(cls, data: str | dict) -> WorkflowSnapshot:
        """从 JSON 字符串或 dict 反序列化快照。"""
        if isinstance(data, str):
            snapshot = json.loads(data)
        else:
            snapshot = data
        obj = cls()
        obj._snapshot = snapshot
        return obj

    @property
    def snapshot(self) -> dict | None:
        """获取当前快照（可能为 None）。"""
        return self._snapshot

    @property
    def sha256(self) -> str | None:
        """获取快照的 sha256 指纹（可能为 None）。"""
        return self._snapshot.get("sha256") if self._snapshot else None
