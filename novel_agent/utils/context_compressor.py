"""上下文压缩引擎。

借鉴 DeterminFlow compression/ 的 3 策略：
1. FullCompact: 全量压缩（LLM 摘要全部历史消息）
2. MicroCompact: 微压缩（只压缩工具调用结果，保留对话消息）
3. ReactiveCompact: 渐进式丢弃（API 413 错误时触发，从最旧消息开始删除）

本模块面向 OpenAI dict 格式消息（与 novel_agent.chat.context_manager 一致），
不依赖 LangChain BaseMessage，便于在 chat / orchestrator 两层复用。

压缩日志：每次实际压缩（压缩后 token 数减少）会追加一条 JSONL 记录到
project_data/compression_log.jsonl，供 /api/compression 监控端点读取统计。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 压缩日志写锁（多线程追加安全）
_log_lock = threading.Lock()

# 微压缩时保留最近的工具结果条数（借鉴 DeterminFlow keepRecentToolResults）
_MICRO_KEEP_RECENT_TOOLS = 5
# 微压缩占位符
_MICRO_PLACEHOLDER = "[工具结果已压缩]"
# 全量压缩时保留最近消息的 token 预算（借鉴 DeterminFlow keepRecentTokens）
_FULL_KEEP_RECENT_TOKENS = 8000
# 全量压缩摘要最大 token
_FULL_SUMMARY_MAX_TOKENS = 1000
# 保留最近消息条数（与 context_manager.KEEP_RECENT 对齐）
_KEEP_RECENT_MSGS = 6
# 每条消息的固定 token 开销（角色标记、分隔符等）
_PER_MSG_OVERHEAD = 4
# token 估算的字符比（OpenAI 经验值：1 token ≈ 4 字符）
_CHARS_PER_TOKEN = 4

# 模板变量正则：匹配 {{variable}}
_TEMPLATE_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class CompressionStrategy(Enum):
    """压缩策略枚举。"""

    NONE = "none"  # 不压缩
    MICRO = "micro"  # MicroCompact - 工具结果微压缩
    FULL = "full"  # FullCompact - 全量摘要压缩
    REACTIVE = "reactive"  # ReactiveCompact - 渐进式丢弃


def _msg_text(msg: dict) -> str:
    """提取单条消息的可计量文本（content + tool_calls 参数）。"""
    parts: list[str] = []
    content = msg.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        parts.append("".join(str(c) for c in content))
    tcs = msg.get("tool_calls")
    if tcs:
        for tc in tcs:
            parts.append(tc.get("function", {}).get("arguments", "") or "")
    return "".join(parts)


def estimate_tokens(messages: list[dict]) -> int:
    """估算消息列表的 token 数。

    粗略规则：1 token ≈ 4 字符，每条消息额外计 _PER_MSG_OVERHEAD 开销。
    与 novel_agent.chat.context_manager.estimate_chars 同一量级，便于互通。
    """
    total_chars = 0
    for m in messages:
        total_chars += len(_msg_text(m))
        total_chars += _PER_MSG_OVERHEAD
    return max(1, total_chars // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# 压缩日志（JSONL 持久化，供 /api/compression 监控端点统计）
# ---------------------------------------------------------------------------
def _compression_log_path() -> Path | None:
    """压缩日志文件路径：project_data/compression_log.jsonl。"""
    try:
        from novel_agent.config import load_config
        cfg = load_config()
        return cfg.project_data_dir / "compression_log.jsonl"
    except Exception:
        return None


def _record_compression(strategy: str, before_tokens: int, after_tokens: int,
                        before_msgs: int, after_msgs: int) -> None:
    """记录一次压缩事件到 JSONL 日志（线程安全追加，失败静默）。"""
    path = _compression_log_path()
    if path is None or before_tokens <= 0:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "tokens_saved": max(0, before_tokens - after_tokens),
            "ratio": round(max(0.0, 1 - after_tokens / before_tokens), 4),
            "before_messages": before_msgs,
            "after_messages": after_msgs,
        }
        with _log_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("记录压缩日志失败: %s", e)


def load_compression_logs(limit: int = 50, offset: int = 0) -> list[dict]:
    """读取压缩日志（最新在前，支持分页）。"""
    path = _compression_log_path()
    if path is None or not path.exists():
        return []
    try:
        with _log_lock:
            with open(path, encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()]
        records: list[dict] = []
        for ln in lines:
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        records.reverse()  # 最新在前
        return records[offset:offset + limit]
    except Exception as e:
        logger.warning("读取压缩日志失败: %s", e)
        return []


def count_compression_logs() -> int:
    """压缩日志总条数。"""
    path = _compression_log_path()
    if path is None or not path.exists():
        return 0
    try:
        with _log_lock:
            with open(path, encoding="utf-8") as f:
                return sum(1 for ln in f if ln.strip())
    except Exception:
        return 0


def compression_stats() -> dict:
    """从压缩日志聚合统计：总次数 / 平均压缩率 / 累计节省 token。"""
    records = load_compression_logs(limit=10 ** 9)
    total = len(records)
    if total == 0:
        return {"total_compressions": 0, "avg_ratio": 0.0, "total_tokens_saved": 0}
    tokens_saved = sum(r.get("tokens_saved", 0) for r in records)
    ratio_sum = sum(r.get("ratio", 0.0) for r in records)
    return {
        "total_compressions": total,
        "avg_ratio": round(ratio_sum / total, 4),
        "total_tokens_saved": tokens_saved,
    }


class ContextCompressor:
    """上下文压缩器：按策略压缩消息列表。

    所有方法均不修改入参 messages，返回新列表（MICRO/FULL）或裁剪后的副本（REACTIVE）。
    """

    def should_compress(self, messages: list[dict], max_tokens: int) -> bool:
        """检查是否需要压缩：当前估算 token 超过 max_tokens 即触发。"""
        return estimate_tokens(messages) > max_tokens

    async def compress(
        self,
        messages: list[dict],
        strategy: CompressionStrategy,
        llm_client: Any = None,
        target_tokens: int | None = None,
    ) -> list[dict]:
        """执行压缩。

        Args:
            messages: 原始消息列表（OpenAI dict 格式）
            strategy: 压缩策略
            llm_client: LLMClient 实例（仅 FULL 策略需要）
            target_tokens: 目标 token 数（仅 REACTIVE 策略使用，默认压到当前的 70%）

        Returns:
            压缩后的消息列表；NONE 策略或压缩失败时原样返回
        """
        if strategy == CompressionStrategy.NONE:
            return list(messages)
        before = estimate_tokens(messages)
        if strategy == CompressionStrategy.MICRO:
            result = self._micro_compress(messages)
        elif strategy == CompressionStrategy.FULL:
            result = await self._full_compress(messages, llm_client)
        elif strategy == CompressionStrategy.REACTIVE:
            target = target_tokens or int(estimate_tokens(messages) * 0.7)
            result = self._reactive_compress(messages, target)
        else:
            return list(messages)
        # 实际发生压缩（token 减少）时记录日志，供 /api/compression 监控统计
        after = estimate_tokens(result)
        if after < before:
            _record_compression(strategy.value, before, after, len(messages), len(result))
        return result

    # ── MICRO: 只压缩工具结果，保留 system + 最近 N 轮对话 ──────────────
    def _micro_compress(self, messages: list[dict]) -> list[dict]:
        """微压缩：把较旧的工具结果 content 替换为占位符。

        借鉴 DeterminFlow MicroCompactStrategy：
        - 找出所有 tool 角色消息
        - 保留最近 _MICRO_KEEP_RECENT_TOOLS 条工具结果原文
        - 其余 tool 消息 content 替换为占位符（不动 tool_call 配对结构）
        """
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        # 工具结果数量不超过保留数，无需压缩
        if len(tool_indices) <= _MICRO_KEEP_RECENT_TOOLS:
            return list(messages)

        # 保留最近 N 条，其余压缩
        indices_to_compress = tool_indices[:-_MICRO_KEEP_RECENT_TOOLS]
        compressed = [dict(m) for m in messages]  # 浅拷贝，避免污染入参
        for idx in indices_to_compress:
            compressed[idx] = {**compressed[idx], "content": _MICRO_PLACEHOLDER}

        logger.info(
            "MicroCompact: 压缩 %d 条工具结果，保留最近 %d 条",
            len(indices_to_compress), _MICRO_KEEP_RECENT_TOOLS,
        )
        return compressed

    # ── FULL: LLM 摘要全部历史 ──────────────────────────────────────────
    async def _full_compress(self, messages: list[dict], llm_client: Any) -> list[dict]:
        """全量压缩：用 LLM 把旧消息摘要成一段，保留 system + 最近消息。

        借鉴 DeterminFlow FullCompactStrategy：
        1. 分离 system 段、可压缩段、最近段（保证最近段不以 tool 开头，避免拆散配对）
        2. 调 LLM 摘要可压缩段
        3. 返回 system + 摘要 + 最近段
        """
        sys_msgs, to_compress, recent = self._split_messages(messages)
        if len(to_compress) < 3:
            logger.info("FullCompact: 可压缩消息不足 3 条，跳过")
            return list(messages)
        if llm_client is None:
            logger.warning("FullCompact: 未提供 llm_client，降级为原样返回")
            return list(messages)

        # 拼接待压缩文本（每条截取头部控制摘要成本）
        parts: list[str] = []
        for m in to_compress:
            role = m.get("role", "user")
            content = m.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            if role == "assistant" and m.get("tool_calls"):
                tool_names = [
                    tc.get("function", {}).get("name", "")
                    for tc in m["tool_calls"]
                ]
                content = f"{content}\n[调用工具: {', '.join(tool_names)}]"
            elif role == "tool":
                content = f"[工具结果] {content}"
            parts.append(f"[{role}] {content[:800]}")
        transcript = "\n".join(parts)

        summary_prompt = (
            "请把以下对话历史压缩成一段简洁摘要，必须保留：\n"
            "1. 关键决策与用户偏好\n"
            "2. 已查询到的设定要点（角色/伏笔/章纲等关键事实）\n"
            "3. 待办或未完成的事项\n"
            "不要丢掉任何关键事实，不要编造。\n\n"
            f"对话历史：\n{transcript}"
        )
        try:
            summary = await llm_client.generate(
                summary_prompt,
                system="你是对话历史压缩器，只输出一段中文摘要，不加任何解释。",
                max_tokens=_FULL_SUMMARY_MAX_TOKENS,
                temperature=0.3,
                thinking=False,
            )
        except Exception as e:
            logger.warning("FullCompact 摘要失败，保留原文: %s", e)
            return list(messages)

        logger.info(
            "FullCompact: %d 条旧消息 -> 摘要 %d 字符",
            len(to_compress), len(summary),
        )
        return sys_msgs + [
            {"role": "system", "content": f"【早期对话摘要】\n{summary}"}
        ] + recent

    # ── REACTIVE: 渐进式丢弃最旧消息 ───────────────────────────────────
    def _reactive_compress(self, messages: list[dict], target_tokens: int) -> list[dict]:
        """渐进式丢弃：从最旧的非 system 消息开始删除，直到达到目标 token 数。

        借鉴 DeterminFlow ReactiveCompactStrategy：
        - 始终保留 system 消息
        - 按完整轮次丢弃（不拆散 assistant(tool_calls) -> tool 的配对）
        - 保留最近消息，优先删最旧的
        """
        sys_msgs: list[dict] = []
        rest = list(messages)
        while rest and rest[0].get("role") == "system":
            sys_msgs.append(rest.pop(0))

        # 已不足 3 条非 system 消息，不再丢弃
        if len(rest) < 3:
            return list(messages)

        current = rest[:]
        while current and estimate_tokens(sys_msgs + current) > target_tokens:
            if len(current) <= _KEEP_RECENT_MSGS:
                # 剩余消息过少，停止丢弃避免丢失全部上下文
                break
            # 找到第一个完整轮次边界：user -> assistant（含后续 tool）
            drop_until = self._find_first_round_end(current)
            if drop_until is None or drop_until <= 0:
                # 找不到完整轮次，按单条丢弃
                current.pop(0)
            else:
                del current[:drop_until]

        logger.info(
            "ReactiveCompact: %d -> %d 条消息（目标 %d tokens）",
            len(rest), len(current), target_tokens,
        )
        return sys_msgs + current

    # ── 辅助方法 ────────────────────────────────────────────────────────
    def _split_messages(
        self, messages: list[dict]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """把 messages 分成 (system 段, 待压缩段, 最近段)。

        保证最近段不以 tool 开头（避免 tool_call 与 tool_result 被切开），
        逻辑与 novel_agent.chat.context_manager._split_preserving_tool_pairs 对齐。
        """
        sys_msgs: list[dict] = []
        rest = list(messages)
        while rest and rest[0].get("role") == "system":
            sys_msgs.append(rest.pop(0))

        if len(rest) <= _KEEP_RECENT_MSGS:
            return sys_msgs, [], rest

        to_compress = rest[:-_KEEP_RECENT_MSGS]
        recent = rest[-_KEEP_RECENT_MSGS:]

        # 若 recent 第一条是 tool，往前回溯到配对的 assistant(tool_calls)
        while recent and recent[0].get("role") == "tool" and to_compress:
            recent.insert(0, to_compress.pop())

        return sys_msgs, to_compress, recent

    def _find_first_round_end(self, messages: list[dict]) -> int | None:
        """找到第一个完整轮次的结束索引（ exclusive，即删除区间 [0, 返回值)）。

        完整轮次：user -> assistant（含其后续的连续 tool 消息）。
        """
        if not messages:
            return None
        # 找到第一个 assistant（跳过开头的 tool / user）
        assistant_idx = None
        for i, m in enumerate(messages):
            if m.get("role") == "assistant":
                assistant_idx = i
                break
        if assistant_idx is None:
            return None
        # assistant 后续连续的 tool 消息也归入该轮次
        end = assistant_idx + 1
        while end < len(messages) and messages[end].get("role") == "tool":
            end += 1
        return end
