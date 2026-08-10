"""Phase 6 融合测试：验证各模块基础功能。

测试项：
- test_json_output: 测试 5 策略修复
- test_token_usage: 测试 Token 账本
- test_ai_detect: 测试 AI 味检测
- test_tool_permissions: 测试工具权限
- test_workflow_snapshot: 测试 Workflow 冻结
- test_context_compressor: 测试压缩引擎
"""
from __future__ import annotations

import json
import pytest

from novel_agent.utils.json_output import (
    parse_json_safe,
    strip_fence,
    normalize_quotes,
    extract_body,
    fix_trailing_comma,
    escape_newlines,
)
from novel_agent.utils.token_usage import TokenLedger
from novel_agent.audit.ai_detect import detect_ai_style
from novel_agent.chat.tool_permissions import is_tool_allowed, filter_tools_for_role
from novel_agent.orchestrator.workflow_snapshot import WorkflowSnapshot, freeze_workflow
from novel_agent.utils.context_compressor import (
    ContextCompressor,
    CompressionStrategy,
    estimate_tokens,
)


# ── test_json_output: 测试 5 策略修复 ──────────────────────────

class TestJsonOutput:
    """JSON 输出校验 + 安全修复流水线测试。"""

    def test_strip_fence(self):
        """策略1：去除 ```json 围栏。"""
        assert strip_fence("```json\n{\"a\":1}\n```") == '{"a":1}'

    def test_normalize_quotes(self):
        """策略2：中文引号 -> ASCII 直引号。"""
        text = '{"key":\u201cvalue\u201d}'
        result = normalize_quotes(text)
        assert "\u201c" not in result
        assert "\u201d" not in result

    def test_extract_body(self):
        """策略3：从混合文本提取 JSON 主体。"""
        text = '解释文字\n{"a":1}\n更多解释'
        assert extract_body(text) == '{"a":1}'

    def test_fix_trailing_comma(self):
        """策略4：去除尾逗号。"""
        assert fix_trailing_comma('{"a":1,}') == '{"a":1}'
        assert fix_trailing_comma('[1,2,3,]') == '[1,2,3]'

    def test_escape_newlines(self):
        """策略5：转义字符串中的裸换行。"""
        text = '{"text":"line1\nline2"}'
        result = escape_newlines(text)
        # 转义后字符串内的换行变成 \n 字面量
        assert "\\n" in result

    def test_parse_json_safe_valid(self):
        """合法 JSON 直接解析。"""
        result = parse_json_safe('{"a":1,"b":"hello"}')
        assert result is not None
        assert result["a"] == 1

    def test_parse_json_safe_with_fence(self):
        """带围栏的 JSON 修复。"""
        result = parse_json_safe('```json\n{"a":1}\n```')
        assert result is not None
        assert result["a"] == 1

    def test_parse_json_safe_trailing_comma(self):
        """尾逗号修复。"""
        result = parse_json_safe('{"a":1,"b":2,}')
        assert result is not None
        assert result["b"] == 2

    def test_parse_json_safe_invalid(self):
        """完全无效的输入返回 None。"""
        assert parse_json_safe("这不是JSON") is None
        assert parse_json_safe("") is None

    def test_parse_json_safe_chinese_quotes(self):
        """中文引号修复。"""
        result = parse_json_safe('{"key":\u201cvalue\u201d}')
        assert result is not None
        assert result["key"] == "value"


# ── test_token_usage: 测试 Token 账本 ──────────────────────────

class TestTokenUsage:
    """Token 账本测试。"""

    def test_record_and_total(self):
        """记录调用并查总计。"""
        ledger = TokenLedger()
        ledger.record("writer", "deepseek-v4-pro", 1000, 500)
        ledger.record("auditor", "deepseek-v4-pro", 800, 200)
        total = ledger.get_total()
        assert total["call_count"] == 2
        assert total["input_tokens"] == 1800
        assert total["output_tokens"] == 700
        assert total["total_cost"] > 0

    def test_get_by_node(self):
        """按节点聚合统计。"""
        ledger = TokenLedger()
        ledger.record("writer", "deepseek-v4-pro", 1000, 500)
        ledger.record("writer", "deepseek-v4-pro", 500, 300)
        ledger.record("auditor", "gpt-4o", 2000, 1000)
        by_node = ledger.get_by_node()
        assert "writer" in by_node
        assert "auditor" in by_node
        assert by_node["writer"]["call_count"] == 2
        assert by_node["auditor"]["call_count"] == 1

    def test_get_by_model(self):
        """按模型聚合统计。"""
        ledger = TokenLedger()
        ledger.record("writer", "deepseek-v4-pro", 1000, 500)
        ledger.record("auditor", "gpt-4o", 2000, 1000)
        by_model = ledger.get_by_model()
        assert "deepseek-v4-pro" in by_model
        assert "gpt-4o" in by_model

    def test_clear(self):
        """清空记录。"""
        ledger = TokenLedger()
        ledger.record("writer", "deepseek-v4-pro", 100, 50)
        ledger.clear()
        assert ledger.get_total()["call_count"] == 0

    def test_unknown_model_zero_cost(self):
        """未知模型记 0 成本。"""
        ledger = TokenLedger()
        ledger.record("test", "unknown-model", 1000, 500)
        total = ledger.get_total()
        assert total["total_cost"] == 0.0

    def test_to_dict(self):
        """序列化。"""
        ledger = TokenLedger()
        ledger.record("writer", "deepseek-v4-pro", 100, 50)
        records = ledger.to_dict()
        assert len(records) == 1
        assert records[0]["node_name"] == "writer"


# ── test_ai_detect: 测试 AI 味检测 ─────────────────────────────

class TestAiDetect:
    """AI 味检测引擎测试。"""

    def test_clean_text_high_score(self):
        """干净文本（无 AI 味）评分高。"""
        text = "他走进酒馆，要了壶酒。掌柜的看了他一眼，没说话。"
        result = detect_ai_style(text)
        assert result["overall_score"] >= 80

    def test_ai_style_text_low_score(self):
        """AI 味文本评分低。"""
        text = (
            "他深吸一口气，嘴角微微上扬，仿佛时间凝固了。"
            "瞳孔一缩，心跳如擂鼓，后背一阵发凉。"
            "不禁感叹，这是一个复杂的人。"
        )
        result = detect_ai_style(text)
        assert result["overall_score"] < 80
        assert len(result["word_issues"]) > 0

    def test_empty_text(self):
        """空文本返回默认高分。"""
        result = detect_ai_style("")
        assert result["overall_score"] == 100

    def test_detect_word_issues(self):
        """检测词级问题。"""
        text = "他仿佛看到了什么，宛如一场梦。"
        result = detect_ai_style(text)
        word_names = [w["word"] for w in result["word_issues"]]
        assert "仿佛" in word_names
        assert "宛如" in word_names

    def test_detect_sentence_issues(self):
        """检测句级问题。"""
        text = "这不是勇气，而是鲁莽。"
        result = detect_ai_style(text)
        # 应检测到"不是X而是Y"句式
        sentence_issues = result["sentence_issues"]
        assert len(sentence_issues) > 0


# ── test_tool_permissions: 测试工具权限 ────────────────────────

class TestToolPermissions:
    """工具权限控制测试。"""

    def test_admin_all_tools(self):
        """admin 角色可以使用所有工具。"""
        assert is_tool_allowed("admin", "any_tool") is True
        assert is_tool_allowed("admin", "delete_everything") is True

    def test_writer_readonly(self):
        """writer 角色只能用只读工具。"""
        assert is_tool_allowed("writer", "read_chapter") is True
        assert is_tool_allowed("writer", "write_outline") is False

    def test_auditor_no_write(self):
        """auditor 角色不能写库。"""
        assert is_tool_allowed("auditor", "read_chapter") is True
        assert is_tool_allowed("auditor", "write_outline") is False

    def test_unknown_role_denied(self):
        """未知角色默认拒绝。"""
        assert is_tool_allowed("unknown_role", "any_tool") is False

    def test_filter_tools_for_role(self):
        """按角色过滤工具列表。"""
        all_tools = [
            {"type": "function", "function": {"name": "read_chapter"}},
            {"type": "function", "function": {"name": "write_outline"}},
            {"type": "function", "function": {"name": "delete_everything"}},
        ]
        filtered = filter_tools_for_role("writer", all_tools)
        assert "read_chapter" in filtered
        assert "write_outline" not in filtered


# ── test_workflow_snapshot: 测试 Workflow 冻结 ────────────────

class TestWorkflowSnapshot:
    """Workflow 定义快照 + 配置漂移防护测试。"""

    def test_freeze_and_verify_consistent(self):
        """冻结后校验一致的定义。"""
        nodes = ["write", "audit", "polish"]
        edges = [("write", "audit"), ("audit", "polish")]
        snapshot = freeze_workflow(nodes, edges)
        assert "sha256" in snapshot
        assert snapshot["sha256"] != ""

    def test_verify_drift_detected(self):
        """检测到配置漂移。"""
        nodes = ["write", "audit", "polish"]
        edges = [("write", "audit"), ("audit", "polish")]
        snap = WorkflowSnapshot(nodes, edges)
        # 修改节点列表 -> 漂移
        assert snap.verify(["write", "audit"], edges) is False

    def test_verify_no_drift(self):
        """无漂移时返回 True。"""
        nodes = ["write", "audit"]
        edges = [("write", "audit")]
        snap = WorkflowSnapshot(nodes, edges)
        assert snap.verify(nodes, edges) is True

    def test_serialize_deserialize(self):
        """序列化/反序列化。"""
        nodes = ["a", "b"]
        edges = [("a", "b")]
        snap = WorkflowSnapshot(nodes, edges)
        serialized = snap.serialize()
        restored = WorkflowSnapshot.deserialize(serialized)
        assert restored.sha256 == snap.sha256

    def test_unfrozen_verify_passes(self):
        """未冻结时校验直接通过。"""
        snap = WorkflowSnapshot()
        assert snap.verify(["any"], [("a", "b")]) is True


# ── test_context_compressor: 测试压缩引擎 ──────────────────────

class TestContextCompressor:
    """上下文压缩引擎测试。"""

    def test_estimate_tokens(self):
        """token 估算。"""
        msgs = [{"role": "user", "content": "hello world"}]
        tokens = estimate_tokens(msgs)
        assert tokens > 0

    def test_should_compress(self):
        """检测是否需要压缩。"""
        compressor = ContextCompressor()
        # 短消息不需要压缩
        short_msgs = [{"role": "user", "content": "hi"}]
        assert compressor.should_compress(short_msgs, max_tokens=10000) is False
        # 长消息需要压缩
        long_msgs = [{"role": "user", "content": "x" * 50000}]
        assert compressor.should_compress(long_msgs, max_tokens=1000) is True

    def test_micro_compress(self):
        """微压缩：替换旧工具结果。"""
        import asyncio
        compressor = ContextCompressor()
        # 构造超过保留数量的 tool 消息
        msgs = [{"role": "user", "content": "q"}]
        for i in range(10):
            msgs.append({"role": "assistant", "content": f"a{i}", "tool_calls": [{"id": str(i), "function": {"name": "f", "arguments": "{}"}}]})
            msgs.append({"role": "tool", "content": f"result_{i}" * 100, "tool_call_id": str(i)})
        compressed = compressor._micro_compress(msgs)
        # 应有部分 tool 消息被替换为占位符
        placeholders = [m for m in compressed if m.get("content") == "[工具结果已压缩]"]
        assert len(placeholders) > 0

    def test_none_strategy(self):
        """NONE 策略原样返回。"""
        import asyncio
        compressor = ContextCompressor()
        msgs = [{"role": "user", "content": "hello"}]
        result = asyncio.get_event_loop().run_until_complete(
            compressor.compress(msgs, CompressionStrategy.NONE)
        )
        assert result == msgs

    def test_reactive_compress(self):
        """渐进式丢弃：从最旧消息开始删除。"""
        compressor = ContextCompressor()
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"msg_{i} " * 100})
            msgs.append({"role": "assistant", "content": f"resp_{i} " * 100})
        compressed = compressor._reactive_compress(msgs, target_tokens=500)
        # 压缩后 token 数应减少
        assert estimate_tokens(compressed) < estimate_tokens(msgs)
        # system 消息应保留
        assert compressed[0]["role"] == "system"
