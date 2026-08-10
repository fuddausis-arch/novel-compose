"""测试 Token 账本 C1 埋点扩展：finish_reason 截断统计 + prompt 缓存命中统计。"""
from __future__ import annotations

from novel_agent.utils.token_usage import TokenLedger


def _fresh_ledger():
    l = TokenLedger()
    l.record(node_name="writer", model="deepseek-v4-pro",
             input_tokens=1000, output_tokens=500, cache_hit_tokens=600)
    l.record(node_name="writer", model="deepseek-v4-pro",
             input_tokens=900, output_tokens=300, finish_reason="length")
    l.record(node_name="auditor", model="deepseek-v4-flash",
             input_tokens=800, output_tokens=200)
    return l


class TestTokenUsageCache:
    def test_record_fields(self):
        l = TokenLedger()
        r = l.record(node_name="writer", model="deepseek-v4-pro",
                     input_tokens=1000, output_tokens=500, finish_reason="stop",
                     cache_hit_tokens=700)
        assert r.finish_reason == "stop"
        assert r.cache_hit_tokens == 700
        assert r.cache_miss_tokens == 300  # 1000 - 700

    def test_to_dict_has_new_fields(self):
        l = TokenLedger()
        r = l.record(node_name="writer", model="m", input_tokens=10, output_tokens=5,
                     finish_reason="length", cache_hit_tokens=4)
        d = r.to_dict()
        assert d["finish_reason"] == "length"
        assert d["cache_hit_tokens"] == 4
        assert d["cache_miss_tokens"] == 6

    def test_get_total_truncation(self):
        l = _fresh_ledger()
        total = l.get_total()
        # 3 次调用，1 次截断（finish_reason=length）
        assert total["call_count"] == 3
        assert total["truncated_calls"] == 1
        assert total["truncated_rate"] == round(1 / 3, 4)
        # 缓存：总输入 1000+900+800=2700，命中 600
        assert total["cache_hit_tokens"] == 600
        assert total["cache_hit_rate"] == round(600 / 2700, 4)

    def test_get_by_node_truncation(self):
        l = _fresh_ledger()
        by_node = l.get_by_node()
        writer = by_node["writer"]
        assert writer["truncated_calls"] == 1
        assert writer["call_count"] == 2
        assert writer["cache_hit_tokens"] == 600
        assert writer["cache_hit_rate"] == round(600 / 1900, 4)
        assert by_node["auditor"]["truncated_calls"] == 0

    def test_get_by_model_truncation(self):
        l = _fresh_ledger()
        by_model = l.get_by_model()
        assert by_model["deepseek-v4-pro"]["truncated_calls"] == 1
        assert by_model["deepseek-v4-flash"]["truncated_calls"] == 0

    def test_cache_never_negative(self):
        """cache_hit 超过 input 时 miss 不为负"""
        l = TokenLedger()
        r = l.record(node_name="n", model="m", input_tokens=100, output_tokens=10,
                     cache_hit_tokens=150)
        assert r.cache_miss_tokens == 0
