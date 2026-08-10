"""圆桌会议事件广播器。

替代 DeterminFlow 的全局 event_bus：每个 RoundtableSession 持有一个
EventBroadcaster 实例，runner 通过 emit() 推送事件，SSE 端点通过
subscribe() 获取 asyncio.Queue 消费事件。

设计要点：
- 支持多订阅者（fan-out）：多个 SSE 客户端可同时订阅同一会话
- put_nowait + maxsize：慢订阅者不会阻塞 runner，溢出时丢弃事件
- 订阅者断开后 unsubscribe，防止内存泄漏
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("roundtable")


class EventBroadcaster:
    """每个圆桌会话的事件广播器。"""

    def __init__(self, queue_maxsize: int = 2000):
        self._subscribers: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize

    async def emit(self, event: dict) -> None:
        """向所有订阅者广播一个事件（非阻塞，慢订阅者丢事件）。"""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 订阅者消费太慢，丢弃该事件并记录
                logger.warning(f"EventBroadcaster: 订阅者队列已满，丢弃事件 {event.get('type', '?')}")

    def emit_sync(self, event: dict) -> None:
        """同步广播（在非 async 上下文中使用，如异常处理）。"""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"EventBroadcaster: 订阅者队列已满，丢弃事件 {event.get('type', '?')}")

    def subscribe(self) -> asyncio.Queue:
        """订阅事件流，返回一个 asyncio.Queue。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """取消订阅。"""
        if q in self._subscribers:
            self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def clear(self) -> None:
        """清除所有订阅者。"""
        self._subscribers.clear()
