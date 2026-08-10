"""圆桌会议 (Roundtable) 模块

从 DeterminFlow 移植，适配 NovelAgent 的 SQLite 持久化 + LLMClient + SSE 事件推送。

模块组成：
- models.py:    席位、调度策略、共享记忆、会话容器等数据模型
- runner.py:    发言执行引擎 + 会话管理器
- routes.py:    REST API 路由（13+ 端点）+ SSE 实时事件流
- store.py:     SQLite 持久化层
- events.py:    事件广播器（SSE 订阅/推送）
"""
from __future__ import annotations

# 席位数量限制
ROUNDTABLE_MIN_SEATS = 2
ROUNDTABLE_MAX_SEATS = 6

# Moderator 决策策略的最大空闲循环次数（防止无限决策）
ROUNDTABLE_MAX_IDLE_CYCLES = 30

__all__ = [
    "ROUNDTABLE_MIN_SEATS",
    "ROUNDTABLE_MAX_SEATS",
    "ROUNDTABLE_MAX_IDLE_CYCLES",
]
