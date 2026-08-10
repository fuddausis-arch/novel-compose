"""通信工具：complete_task / send_message / reject_upstream。

借鉴 DeterminFlow tools/communication_tools.py：
- complete_task: 完成当前任务
- send_message: 发送消息到其他会话
- reject_upstream: 拒绝上游结果（触发定向返工）

所有工具返回 OpenAI function calling 格式的响应。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _ok(result: dict[str, Any]) -> str:
    """构造成功响应（OpenAI function calling 返回格式）。"""
    return json.dumps(result, ensure_ascii=False)


def _fail(error: str) -> str:
    """构造失败响应。"""
    return json.dumps({"status": "failed", "error": error}, ensure_ascii=False)


def complete_task(result: str) -> dict[str, Any]:
    """完成当前任务。

    借鉴 DeterminFlow communication_tools.complete_task：
    标记当前节点任务完成，将结果传递给下游。

    Args:
        result: 任务完成结果文本

    Returns:
        OpenAI function calling 格式的响应 dict：
        {"status": "completed", "result": ..., "timestamp": ...}
    """
    if not result or not result.strip():
        logger.warning("complete_task: result 为空")
        return {
            "status": "failed",
            "error": "result 不能为空",
        }
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.info("complete_task: 任务已完成")
    return {
        "status": "completed",
        "result": result,
        "timestamp": timestamp,
    }


def send_message(target_session: str, message: str) -> dict[str, Any]:
    """发送消息到其他会话。

    借鉴 DeterminFlow communication_tools.send_message：
    跨会话通信，让不同分支/子流程之间可以传递信息。

    Args:
        target_session: 目标会话 ID
        message: 消息内容

    Returns:
        OpenAI function calling 格式的响应 dict
    """
    if not target_session or not target_session.strip():
        logger.warning("send_message: target_session 为空")
        return {
            "status": "failed",
            "error": "target_session 不能为空",
        }
    if not message or not message.strip():
        logger.warning("send_message: message 为空")
        return {
            "status": "failed",
            "error": "message 不能为空",
        }
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.info("send_message: 消息已发送到会话 %s", target_session)
    return {
        "status": "sent",
        "target_session": target_session,
        "message": message,
        "timestamp": timestamp,
    }


def reject_upstream(reason: str, target_node: str = "") -> dict[str, Any]:
    """拒绝上游结果（触发定向返工）。

    借鉴 DeterminFlow communication_tools.reject_upstream：
    下游节点发现上游产出有问题时，拒绝接受并要求上游重做。
    与 orchestrator/graph.py 的 _route_after_post_hoc 配合使用。

    Args:
        reason: 拒绝原因
        target_node: 要返工的上游节点名（可选，为空时由路由决定）

    Returns:
        OpenAI function calling 格式的响应 dict
    """
    if not reason or not reason.strip():
        logger.warning("reject_upstream: reason 为空")
        return {
            "status": "failed",
            "error": "reason 不能为空",
        }
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.info("reject_upstream: 拒绝上游结果，target_node=%s, reason=%s", target_node, reason[:100])
    return {
        "status": "rejected",
        "reason": reason,
        "target_node": target_node,
        "action": "rework",
        "timestamp": timestamp,
    }


# ── OpenAI function calling schema 定义 ──────────────────────

COMMUNICATION_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "完成当前任务，将结果传递给下游节点。任务执行完毕后必须调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "任务完成结果文本",
                    },
                },
                "required": ["result"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "发送消息到其他会话（跨会话通信）。用于并行分支或子流程之间的信息传递。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_session": {
                        "type": "string",
                        "description": "目标会话 ID",
                    },
                    "message": {
                        "type": "string",
                        "description": "消息内容",
                    },
                },
                "required": ["target_session", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_upstream",
            "description": "拒绝上游结果，触发定向返工。下游节点发现上游产出有问题时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "拒绝原因",
                    },
                    "target_node": {
                        "type": "string",
                        "description": "要返工的上游节点名（可选，为空时由路由决定）",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
