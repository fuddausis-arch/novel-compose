"""json_parser 单元测试。"""
import pytest

from novel_agent.utils.json_parser import parse_json_strict


def test_fullwidth_quotes_with_newlines():
    """LLM 使用全角引号作为 JSON 结构引号且字符串含裸换行时仍可解析。"""
    raw = (
        '{\n'
        '    "volumes": [\n'
        '        {\n'
        '            "order":  1,\n'
        '            "title": "荒地求生",\n'
        '            "summary": "第一卷聚焦于个人温饱与小范围协作阶段，以青石村废弃山谷为起点，经历完整四季循环，展现自然灾害与技术破局的反复较量。\n\n'
        '核心冲突在于人与自然的生存斗争及初期人际信任建立。\n\n'
        '开局仅有一双手一把锄头，面临春涝绝产；夏季干旱逼出自建蓄水池；秋季丰收遭匪徒劫掠；冬季炼出生铁抵御严寒。"\n'
        '        }\n'
        '    ]\n'
        '}'
    )
    result = parse_json_strict(raw)
    assert "volumes" in result
    assert result["volumes"][0]["title"] == "荒地求生"
    assert "核心冲突" in result["volumes"][0]["summary"]


def test_fullwidth_colon_and_comma():
    """结构位置的全角冒号、逗号应被替换为半角。"""
    raw = '{"order"：1，"title"："测试"}'
    result = parse_json_strict(raw)
    assert result["order"] == 1
    assert result["title"] == "测试"


def test_string_internal_fullwidth_punct_preserved():
    """字符串内部的全角标点应保留，避免破坏内容语义。"""
    raw = '{"content":"他说，你好：这是内容。"}'
    result = parse_json_strict(raw)
    assert result["content"] == "他说，你好：这是内容。"


def test_html_entities_decoded():
    """HTML 实体（&quot; &amp; 等）应被解码为普通字符。"""
    raw = '{&quot;volumes&quot;:[{&quot;order&quot;:1,&quot;title&quot;:&quot;测试&quot;}]}'
    result = parse_json_strict(raw)
    assert result["volumes"][0]["title"] == "测试"


def test_double_html_entities_decoded():
    """双重 HTML 转义（&amp;amp;）应被正确解码。"""
    raw = '{"content":"&amp;amp;amp;测试"}'
    result = parse_json_strict(raw)
    assert "测试" in result["content"]
    assert "&amp;" not in result["content"]


# ---- Task 3.5 / 7.4 扩展的鲁棒性用例 ----

def test_empty_response():
    """LLM 返回空字符串时应安全返回默认值，不抛出异常。"""
    result = parse_json_strict("")
    assert result == {}
    result = parse_json_strict("   ")
    assert result == {}


def test_plain_text_response():
    """LLM 返回纯文本说明时应返回默认值。"""
    result = parse_json_strict("这是一个纯文本回答，不是 JSON。")
    assert result == {}


def test_non_json_markdown():
    """非 JSON 的 Markdown 内容不应导致崩溃。"""
    raw = "# 标题\n\n这是一段说明文字。\n\n- 列表项 1\n- 列表项 2"
    result = parse_json_strict(raw)
    assert isinstance(result, dict)
    assert result == {}


def test_truncated_json():
    """截断的 JSON 不应抛异常，应优雅降级。"""
    raw = '{"volumes": [{"title": "第一卷"'
    result = parse_json_strict(raw)
    assert isinstance(result, dict)
    assert "volumes" not in result


def test_control_characters():
    """JSON 字符串中的控制字符应被移除，剩余内容仍可解析。"""
    raw = '{"key": "value\x00with\x07control"}'
    result = parse_json_strict(raw)
    assert result["key"] == "valuewithcontrol"


def test_nested_code_fences():
    """JSON 值内部包含代码围栏时不应崩溃（允许降级为空字典）。"""
    raw = '```json\n{"code": "```python\\nprint(1)\\n```"}\n```'
    result = parse_json_strict(raw)
    assert isinstance(result, dict)


def test_markdown_explanation_with_json():
    """Markdown 说明文字包裹的 JSON 应能正确提取。"""
    raw = '这是前言说明。\n```json\n{"answer": 42}\n```\n这是尾注。'
    result = parse_json_strict(raw)
    assert result.get("answer") == 42


def test_arcs_array_with_fullwidth_punct():
    """细纲接口常见的 arcs 数组，结构位置使用全角标点时应被修复。"""
    raw = (
        '```json\n'
        '{"arcs"：['
        '{"order"：1，"title"："开端"，"summary"："主角登场，遭遇危机。"，"act"："开端"，"strand"："quest"，"key_characters"：["主角"]，"emotional_arc"："紧张→希望"}'
        ']}\n'
        '```'
    )
    result = parse_json_strict(raw)
    assert "arcs" in result
    assert len(result["arcs"]) == 1
    assert result["arcs"][0]["title"] == "开端"
    assert result["arcs"][0]["emotional_arc"] == "紧张→希望"


def test_arcs_repair_from_truncated_response():
    """LLM 返回被截断但只要 arcs 对象完整，就应能提取。"""
    raw = (
        '好的，以下是细纲：\n'
        '{"arcs": [{"order": 1, "title": "第一小节", "summary": "测试内容", "act": "开端", '
        '"strand": "quest", "key_characters": ["A"], "emotional_arc": "紧张"}]}\n'
        '（后续内容被截断）'
    )
    result = parse_json_strict(raw)
    assert "arcs" in result
    assert result["arcs"][0]["title"] == "第一小节"
