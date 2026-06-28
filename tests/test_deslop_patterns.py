"""确定性 AI 模式检测器单元测试。

移植 oh-story-claudecode 的 check-ai-patterns.js + check-degeneration.js。
"""
from __future__ import annotations

import pytest

from novel_agent.audit.deslop_patterns import (
    SEVERITY_ADVISORY,
    SEVERITY_BLOCKING,
    SEVERITY_SOFT,
    detect_adjacent_repetition,
    detect_ai_self_reference,
    detect_em_dash,
    detect_engineering_word_leakage,
    detect_generation_refusal,
    detect_long_paragraph,
    detect_long_sentence_repetition,
    detect_not_is_comparison,
    detect_period_stutter,
    detect_placeholder_leakage,
    detect_truncation,
    run_deslop_checks,
)


class TestNotIsComparison:
    """最毒 AI 句式：否定铺垫后肯定翻转（'不是A，而是B'）"""

    def test_basic_pattern(self):
        """基础 '不是A，而是B' 应被检测"""
        text = "他不是害怕，而是愤怒。"
        results = detect_not_is_comparison(text)
        assert len(results) == 1
        assert results[0]["pattern"] == "not-is-comparison"
        assert results[0]["severity"] == SEVERITY_BLOCKING

    def test_variant_with_bing_fei(self):
        """'并非A，而是B' 变体"""
        text = "这并非结束，而是新的开始。"
        results = detect_not_is_comparison(text)
        assert len(results) >= 1

    def test_multiple_in_one_text(self):
        """多 occurrence 应全部检出"""
        text = "他不是在哭，而是在笑。她不是走，而是在跑。"
        results = detect_not_is_comparison(text)
        assert len(results) == 2

    def test_no_false_positive_simple_negation(self):
        """简单否定不应误判"""
        text = "他不去上学。"
        results = detect_not_is_comparison(text)
        assert len(results) == 0

    def test_compact_form_no_comma(self):
        """紧凑写法 '不是A而是B' 也应检出"""
        text = "这不是勇气而是鲁莽。"
        results = detect_not_is_comparison(text)
        assert len(results) == 1


class TestEmDash:
    """破折号检测"""

    def test_chinese_em_dash(self):
        results = detect_em_dash("他走了——回头看了她一眼。")
        assert len(results) >= 1
        assert all(r["pattern"] == "em-dash" for r in results)
        assert all(r["severity"] == SEVERITY_BLOCKING for r in results)

    def test_ascii_double_dash(self):
        results = detect_em_dash("he went -- and came back.")
        assert len(results) >= 1


class TestPeriodStutter:
    """句号结巴检测"""

    def test_four_short_sentences(self):
        text = "他来了。他走了。他哭了。他笑了。"
        results = detect_period_stutter(text)
        assert len(results) >= 1
        assert all(r["severity"] == SEVERITY_ADVISORY for r in results)

    def test_normal_paragraph_no_flag(self):
        text = "他推开门走了进去，发现屋里空无一人。窗户开着，窗帘被风吹得乱飞。"
        results = detect_period_stutter(text)
        assert len(results) == 0


class TestLongParagraph:
    """长段落检测"""

    def test_long_paragraph_flagged(self):
        long_para = "他" + "走" * 250 + "了。"
        results = detect_long_paragraph(long_para, max_chars=200)
        assert len(results) == 1
        assert results[0]["severity"] == SEVERITY_ADVISORY

    def test_short_paragraph_ok(self):
        text = "他走了。\n\n她来了。"
        results = detect_long_paragraph(text, max_chars=200)
        assert len(results) == 0


class TestAdjacentRepetition:
    """紧邻整行复读"""

    def test_identical_adjacent_lines(self):
        text = "他猛地从椅子上站了起来。\n他猛地从椅子上站了起来。\n"
        results = detect_adjacent_repetition(text)
        assert len(results) == 1
        assert results[0]["severity"] == SEVERITY_BLOCKING

    def test_quoted_bullets_exempt(self):
        """引号内复沓台词不判（弹幕刷屏是体裁手法）"""
        text = "「卧槽」\n「卧槽」\n"
        results = detect_adjacent_repetition(text)
        assert len(results) == 0

    def test_short_repetition_exempt(self):
        """可见长度 <8 的短行不判"""
        text = "嗯。\n嗯。\n"
        results = detect_adjacent_repetition(text)
        assert len(results) == 0


class TestLongSentenceRepetition:
    """长句复读"""

    def test_repeated_long_sentence(self):
        text = "他猛地从床上坐起来看了看四周的环境。" * 3
        results = detect_long_sentence_repetition(text)
        assert len(results) >= 1
        assert all(r["severity"] == SEVERITY_BLOCKING for r in results)

    def test_quoted_repeat_exempt(self):
        """引号内复读豁免（弹幕体裁）"""
        text = '「他猛地从床上坐起来看了看四周的环境。」' * 3
        results = detect_long_sentence_repetition(text)
        assert len(results) == 0


class TestTruncation:
    """截断检测"""

    def test_truncated_text(self):
        text = "他推开门，发现"
        results = detect_truncation(text)
        assert len(results) == 1
        assert results[0]["severity"] == SEVERITY_BLOCKING

    def test_complete_text(self):
        text = "他推开门，发现屋里没人。"
        results = detect_truncation(text)
        assert len(results) == 0

    def test_complete_with_quote(self):
        text = '他说:\u201c你来了。\u201d'
        results = detect_truncation(text)
        assert len(results) == 0


class TestAiSelfReference:
    """AI 自指检测"""

    def test_in_prose_blocking(self):
        text = "作为AI，我无法继续创作。"
        results = detect_ai_self_reference(text)
        assert len(results) >= 1
        # 非对话行：soft 仍记录但不豁免
        assert all(r["severity"] == SEVERITY_SOFT for r in results)

    def test_in_dialog_exempt(self):
        """对话行内 AI 自指豁免（系统流题材 AI 角色台词合法）"""
        text = '"作为AI，我会保护你。"'
        results = detect_ai_self_reference(text)
        # 对话行应被豁免（不产生 finding）
        assert len(results) == 0


class TestGenerationRefusal:
    """生成拒绝语检测"""

    def test_refusal_in_prose(self):
        text = "由于内容限制，我无法继续生成。"
        results = detect_generation_refusal(text)
        assert len(results) >= 1
        assert all(r["severity"] == SEVERITY_SOFT for r in results)

    def test_refusal_in_dialog_exempt(self):
        text = '"我无法继续生成内容了，"她说。'
        results = detect_generation_refusal(text)
        assert len(results) == 0  # 对话行豁免


class TestEngineeringWordLeakage:
    """工程词泄漏检测"""

    def test_tier1_in_prose_blocking(self):
        text = "本章的细纲已经写好了。"
        results = detect_engineering_word_leakage(text)
        assert any(r["matched"] == "细纲" and r["severity"] == SEVERITY_BLOCKING for r in results)

    def test_tier1_in_dialog_advisory(self):
        text = '"这个细纲有问题，"她说。'
        results = detect_engineering_word_leakage(text)
        assert any(r["matched"] == "细纲" and r["severity"] == SEVERITY_ADVISORY for r in results)

    def test_tier2_always_advisory(self):
        text = "本章主角做了很多事。"
        results = detect_engineering_word_leakage(text)
        assert any(r["matched"] == "本章" and r["severity"] == SEVERITY_ADVISORY for r in results)


class TestPlaceholderLeakage:
    """占位符泄漏检测"""

    def test_todo_flagged(self):
        results = detect_placeholder_leakage("这里TODO待补充。")
        assert len(results) >= 1
        assert all(r["severity"] == SEVERITY_BLOCKING for r in results)

    def test_placeholder_chinese_flagged(self):
        results = detect_placeholder_leakage("此处省略一万字。")
        assert len(results) >= 1


class TestRunDeslopChecks:
    """主入口测试"""

    def test_clean_text_passes(self):
        text = "他推开门，发现屋里没人。窗外下着雨。他叹了口气，把伞放在门口。"
        result = run_deslop_checks(text)
        assert result["passed"] is True
        assert result["blocking_count"] == 0

    def test_multiple_blocking_fails(self):
        text = "他不是害怕——而是愤怒。"
        result = run_deslop_checks(text)
        assert result["passed"] is False
        assert result["blocking_count"] >= 2  # not-is + em-dash

    def test_return_structure(self):
        result = run_deslop_checks("正常文本。")
        assert "findings" in result
        assert "blocking_count" in result
        assert "advisory_count" in result
        assert "soft_count" in result
        assert "passed" in result
        assert isinstance(result["findings"], list)

    def test_ai_heavy_draft_multiple_blocking(self):
        """AI 味浓重草稿应被检测出多个 blocking"""
        draft = (
            "他深邃的眼眸中神色复杂，缓缓开口道：\u201c你来了。\u201d\n"
            "她不是害怕，而是愤怒——她没想到他会这样对她。\n"
            "他不知道的是，门外站着的正是他失散多年的父亲。\n"
        )
        result = run_deslop_checks(draft)
        assert result["blocking_count"] >= 3
        assert not result["passed"]
