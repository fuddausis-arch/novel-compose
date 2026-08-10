"""上下文压缩：长对话/大工具结果不爆 token。

参考 Claude Code 的 5 级渐进压缩，针对小说创作 chat 场景精简为 2 级：
- L1 截断：单条工具结果超 TOOL_RESULT_LIMIT 字符，截断留头尾 + 提示
- L2 摘要：messages 总字符超 COMPACT_THRESHOLD，旧消息合并成摘要替换

压缩规则（来自 Claude Code 经验）：
- 保留开头的 system 消息
- 保留最近 KEEP_RECENT 条消息
- 不在 tool_call / tool_result 中间切（保证配对完整）
- 摘要不可逆，但保留最近上下文供 LLM 继续推理
"""
from __future__ import annotations

import logging
from typing import Any

from novel_agent.llm.client import LLMClient

logger = logging.getLogger(__name__)

TOOL_RESULT_LIMIT = 80000     # 单条工具结果字符上限（参考文件可能很大）
COMPACT_THRESHOLD = 60000     # messages 总字符超过此值触发摘要
KEEP_RECENT = 6               # 压缩时保留最近 N 条消息（不动）
SUMMARY_MAX_TOKENS = 1000


def truncate_tool_result(result: str, limit: int = TOOL_RESULT_LIMIT) -> str:
    """工具结果超长截断，保留头尾 + 截断提示。"""
    if not result or len(result) <= limit:
        return result
    head = result[: limit // 2]
    tail = result[-(limit // 4):]
    omitted = len(result) - len(head) - len(tail)
    return f"{head}\n\n…（已截断 {omitted} 字符，完整内容请重新查询并缩小范围）…\n\n{tail}"


def estimate_chars(messages: list[dict]) -> int:
    """粗略估算 messages 总字符数（中文 1 字符 ≈ 1.5 token，这里按字符算够用）。"""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(str(c)) for c in content)
        tcs = m.get("tool_calls")
        if tcs:
            for tc in tcs:
                total += len(tc.get("function", {}).get("arguments", "") or "")
    return total


def _split_preserving_tool_pairs(messages: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """把 messages 分成 (system 段, 待压缩段, 最近段)。

    保证最近段不以 tool 角色开头（避免 tool_call 与 tool_result 被切开）。
    """
    sys_msgs: list[dict] = []
    rest = messages[:]
    while rest and rest[0].get("role") == "system":
        sys_msgs.append(rest.pop(0))

    if len(rest) <= KEEP_RECENT:
        return sys_msgs, [], rest

    to_compress = rest[:-KEEP_RECENT]
    recent = rest[-KEEP_RECENT:]

    # 若 recent 第一条是 tool，往前回溯到配对的 assistant(tool_calls)
    while recent and recent[0].get("role") == "tool" and to_compress:
        recent.insert(0, to_compress.pop())

    return sys_msgs, to_compress, recent


async def compact_if_needed(messages: list[dict], llm_client: LLMClient) -> list[dict]:
    """若 messages 过长，把旧消息摘要替换。返回新的 messages。

    未超阈值或可压缩内容不足时原样返回。
    """
    if estimate_chars(messages) <= COMPACT_THRESHOLD:
        return messages

    sys_msgs, to_compress, recent = _split_preserving_tool_pairs(messages)
    if len(to_compress) < 3:
        return messages  # 可压缩内容太少，不值得调一次 LLM

    # 把待压缩段拼成文本（每条截取头部进摘要输入，控制摘要成本）
    parts: list[str] = []
    for m in to_compress:
        role = m.get("role", "user")
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        # 保留工具调用/结果信息，避免摘要丢失工具上下文
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
            max_tokens=SUMMARY_MAX_TOKENS,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning("上下文压缩失败，保留原文: %s", e)
        return messages

    old_chars = sum(len(str(m.get("content", ""))) for m in to_compress)
    logger.info(
        "上下文压缩：%d 条旧消息（%d 字符）-> 摘要 %d 字符",
        len(to_compress), old_chars, len(summary),
    )
    return sys_msgs + [
        {"role": "system", "content": f"【早期对话摘要】\n{summary}"}
    ] + recent
