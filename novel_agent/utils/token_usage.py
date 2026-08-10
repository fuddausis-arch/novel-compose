"""Token 账本：按节点、尝试和模型调用单独记账。

借鉴 DeterminFlow token_usage.py 的设计：
- 每次 LLM 调用记录：node_name, attempt, model, input_tokens, output_tokens, cost
- 聚合统计：per-node, per-model, total
- 成本定价：按模型定价表计算

与 DeterminFlow 的区别：
- 简化为单进程内存账本（DeterminFlow 是持久化 + 时区感知定价）
- 定价表硬编码常用模型（DeepSeek / GPT-4o 系列），未知模型记 0 成本
- 全局单例 ledger，供 LLMClient 自动记账
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── 成本定价表（参考 DeepSeek / OpenAI 官方定价）──────────────
# 单位：美元 / 1K tokens
# input = 输入（prompt）单价，output = 输出（completion）单价
PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {"input": 0.002, "output": 0.006},
    "deepseek-v4-flash": {"input": 0.0003, "output": 0.001},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
}

# 定价单位（1K tokens = 1000 tokens）
_PRICING_UNIT = 1000


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """按模型定价表计算单次调用成本（美元）。

    未知模型记 0 成本（不报错，保证记账不阻塞主流程）。
    """
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    return (
        input_tokens * rates["input"] / _PRICING_UNIT
        + output_tokens * rates["output"] / _PRICING_UNIT
    )


@dataclass
class TokenUsageRecord:
    """单次 LLM 调用的 token 用量记录。

    Attributes:
        node_name: 调用来源节点名（如 "writer" / "auditor" / "planner"）
        attempt: 第几次尝试（重试计数，从 1 开始）
        model: 模型名（如 "deepseek-v4-pro"）
        input_tokens: 输入 token 数（prompt_tokens）
        output_tokens: 输出 token 数（completion_tokens）
        reasoning_tokens: 推理 token 数（DeepSeek 思考模式）
        cost: 本次调用成本（美元）
        timestamp: 记录时间（UTC ISO 格式字符串）
    """

    node_name: str
    attempt: int
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    finish_reason: str = ""          # stop / length / content_filter / ...
    cache_hit_tokens: int = 0        # prompt 命中缓存 token 数（DeepSeek/OpenAI prompt_tokens_details.cached_tokens）
    cache_miss_tokens: int = 0       # prompt 未命中 token 数 = input_tokens - cache_hit_tokens
    cost: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的 dict。"""
        return {
            "node_name": self.node_name,
            "attempt": self.attempt,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "finish_reason": self.finish_reason,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "cost": round(self.cost, 6),
            "timestamp": self.timestamp,
        }


class TokenLedger:
    """Token 账本：记录每次 LLM 调用并聚合统计。

    线程/协程安全说明：单事件循环内串行调用安全；跨线程并发写需外部加锁。
    NovelAgent 主流程为 asyncio 单线程，无需额外锁。
    """

    def __init__(self) -> None:
        self._records: list[TokenUsageRecord] = []
        # 按节点维护尝试计数（node_name -> 当前已记录次数）
        self._node_attempts: dict[str, int] = {}

    def record(
        self,
        node_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        finish_reason: str = "",
        cache_hit_tokens: int = 0,
    ) -> TokenUsageRecord:
        """记录一次 LLM 调用。

        Args:
            node_name: 调用来源节点名
            model: 模型名
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            reasoning_tokens: 推理 token 数（可选）
            finish_reason: 结束原因（stop/length/...），用于统计截断率
            cache_hit_tokens: prompt 命中缓存 token 数（可选）

        Returns:
            本次调用对应的 TokenUsageRecord
        """
        # 同一节点的调用次数累加作为 attempt
        self._node_attempts[node_name] = self._node_attempts.get(node_name, 0) + 1
        attempt = self._node_attempts[node_name]

        cost = _calc_cost(model, input_tokens, output_tokens)
        record = TokenUsageRecord(
            node_name=node_name,
            attempt=attempt,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            finish_reason=finish_reason,
            cache_hit_tokens=cache_hit_tokens,
            cache_miss_tokens=max(0, input_tokens - cache_hit_tokens),
            cost=cost,
        )
        self._records.append(record)
        logger.debug(
            "TokenLedger 记账: node=%s attempt=%d model=%s "
            "in=%d out=%d reasoning=%d cache_hit=%d finish=%s cost=$%.6f",
            node_name, attempt, model,
            input_tokens, output_tokens, reasoning_tokens,
            cache_hit_tokens, finish_reason, cost,
        )
        return record

    def get_total(self) -> dict:
        """总计：{total_tokens, total_cost, call_count}。"""
        total_input = sum(r.input_tokens for r in self._records)
        total_output = sum(r.output_tokens for r in self._records)
        total_reasoning = sum(r.reasoning_tokens for r in self._records)
        total_cost = sum(r.cost for r in self._records)
        total_cache_hit = sum(r.cache_hit_tokens for r in self._records)
        truncated = sum(1 for r in self._records if r.finish_reason == "length")
        return {
            "total_tokens": total_input + total_output + total_reasoning,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "reasoning_tokens": total_reasoning,
            "cache_hit_tokens": total_cache_hit,
            "cache_hit_rate": round(total_cache_hit / total_input, 4) if total_input else 0.0,
            "truncated_calls": truncated,
            "truncated_rate": round(truncated / len(self._records), 4) if self._records else 0.0,
            "total_cost": round(total_cost, 6),
            "call_count": len(self._records),
        }

    def get_by_node(self) -> dict[str, dict]:
        """按节点聚合统计。

        Returns:
            {node_name: {total_tokens, total_cost, call_count, ...}}
        """
        result: dict[str, dict] = {}
        for r in self._records:
            bucket = result.setdefault(
                r.node_name,
                {
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "cache_hit_tokens": 0,
                    "truncated_calls": 0,
                    "total_cost": 0.0,
                    "call_count": 0,
                },
            )
            bucket["input_tokens"] += r.input_tokens
            bucket["output_tokens"] += r.output_tokens
            bucket["reasoning_tokens"] += r.reasoning_tokens
            bucket["cache_hit_tokens"] += r.cache_hit_tokens
            if r.finish_reason == "length":
                bucket["truncated_calls"] += 1
            bucket["total_tokens"] += (
                r.input_tokens + r.output_tokens + r.reasoning_tokens
            )
            bucket["total_cost"] += r.cost
            bucket["call_count"] += 1
        for bucket in result.values():
            bucket["total_cost"] = round(bucket["total_cost"], 6)
            bucket["cache_hit_rate"] = (
                round(bucket["cache_hit_tokens"] / bucket["input_tokens"], 4)
                if bucket["input_tokens"] else 0.0
            )
        return result

    def get_by_model(self) -> dict[str, dict]:
        """按模型聚合统计。

        Returns:
            {model: {total_tokens, total_cost, call_count, ...}}
        """
        result: dict[str, dict] = {}
        for r in self._records:
            bucket = result.setdefault(
                r.model,
                {
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "cache_hit_tokens": 0,
                    "truncated_calls": 0,
                    "total_cost": 0.0,
                    "call_count": 0,
                },
            )
            bucket["input_tokens"] += r.input_tokens
            bucket["output_tokens"] += r.output_tokens
            bucket["reasoning_tokens"] += r.reasoning_tokens
            bucket["cache_hit_tokens"] += r.cache_hit_tokens
            if r.finish_reason == "length":
                bucket["truncated_calls"] += 1
            bucket["total_tokens"] += (
                r.input_tokens + r.output_tokens + r.reasoning_tokens
            )
            bucket["total_cost"] += r.cost
            bucket["call_count"] += 1
        for bucket in result.values():
            bucket["total_cost"] = round(bucket["total_cost"], 6)
            bucket["cache_hit_rate"] = (
                round(bucket["cache_hit_tokens"] / bucket["input_tokens"], 4)
                if bucket["input_tokens"] else 0.0
            )
        return result

    def clear(self) -> None:
        """清空所有记录。"""
        self._records.clear()
        self._node_attempts.clear()

    def to_dict(self) -> list[dict]:
        """序列化为 JSON 友好的 list[dict]（每条调用记录）。"""
        return [r.to_dict() for r in self._records]


# 全局实例：供 LLMClient 自动记账，也供业务层查询
ledger = TokenLedger()
