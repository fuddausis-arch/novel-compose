"""上下文窗口 token 监控（照搬 Codex context_window.rs 设计）。

跟踪当前对话 token 使用，达阈值触发自动压缩。
Codex 用 ContextWindowTokenStatus 跟踪 active_context_tokens / auto_compact_scope_tokens /
limit / remaining / limit_reached。这里用字符数近似 token（中文 1 字符 ≈ 1.5 token，
粗估够用，精确 token 化需要接 tokenizer，火山引擎模型 tokenizer 不统一，暂用字符）。

阈值与 context_manager.COMPACT_THRESHOLD 共用同一常量，避免漂移。
"""
from __future__ import annotations

from dataclasses import dataclass

from novel_agent.chat.context_manager import estimate_chars, COMPACT_THRESHOLD


@dataclass
class ContextWindowStatus:
    """照搬 Codex ContextWindowTokenStatus。"""
    active_chars: int          # 当前对话总字符（近似 token）
    auto_compact_limit: int    # 触发压缩的阈值
    chars_remaining: int       # 剩余可用
    limit_reached: bool        # 是否达限（触发压缩）


def context_window_status(messages: list[dict],
                          auto_compact_limit: int = COMPACT_THRESHOLD) -> ContextWindowStatus:
    """照搬 Codex context_window_token_status()：计算当前窗口使用 + 是否达限。

    auto_compact_limit 默认用 context_manager.COMPACT_THRESHOLD，和 compact_if_needed 共用阈值。
    """
    active = estimate_chars(messages)
    remaining = max(0, auto_compact_limit - active)
    return ContextWindowStatus(
        active_chars=active,
        auto_compact_limit=auto_compact_limit,
        chars_remaining=remaining,
        limit_reached=active >= auto_compact_limit,
    )
