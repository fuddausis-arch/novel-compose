"""集成测试：验证 deslop_patterns 已集成到 validator.run_deterministic_checks。"""
from __future__ import annotations

import pytest

from novel_agent.audit.validator import run_deterministic_checks


class TestDeslopIntegration:
    """验证 deslop_patterns 已集成到 validator"""

    def test_not_is_comparison_detected_in_validator(self):
        """'不是A，而是B' 应被 validator 检测为 critical"""
        draft = "他不是害怕，而是愤怒。这不是结束，而是开始。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        ai_pattern_issues = [i for i in result["issues"] if "AI模式" in i.get("dimension", "")]
        assert len(ai_pattern_issues) >= 1
        assert any(i["severity"] == "critical" for i in ai_pattern_issues)

    def test_em_dash_detected_in_validator(self):
        """破折号应被 validator 检测"""
        draft = "他走了——回头看了她一眼。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        em_dash_issues = [i for i in result["issues"] if "em-dash" in i.get("dimension", "")]
        assert len(em_dash_issues) >= 1
        assert any(i["severity"] == "critical" for i in em_dash_issues)

    def test_engineering_word_leakage_detected(self):
        """工程词泄漏应被 validator 检测"""
        draft = "本章的细纲已经写好了。主角做了很多事。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        eng_issues = [i for i in result["issues"] if "engineering-word" in i.get("dimension", "")]
        assert len(eng_issues) >= 1
        # 细纲 in non-dialog → blocking → critical
        assert any(i["severity"] == "critical" for i in eng_issues)

    def test_omniscient_disclosure_detected(self):
        """全知视角剧透 '他不知道的是' 应被检测"""
        draft = "他不知道的是，门外站着的正是他失散多年的父亲。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        disclosure_issues = [
            i for i in result["issues"]
            if "engineering-word" in i.get("dimension", "") and "他不知道的是" in i.get("message", "")
        ]
        assert len(disclosure_issues) >= 1
        assert any(i["severity"] == "critical" for i in disclosure_issues)

    def test_clean_text_no_critical(self):
        """干净文本应无 critical 级 AI 模式问题"""
        draft = "他推开门，发现屋里没人。窗外下着雨，雨点打在玻璃上。他叹了口气，把伞放在门口。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        critical_issues = [i for i in result["issues"] if i["severity"] == "critical"]
        assert len(critical_issues) == 0

    def test_deslop_findings_included_in_issues(self):
        """deslop 检测结果应包含在 issues 列表中"""
        draft = "他不是害怕——而是愤怒。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        # 应同时检测到 not-is-comparison 和 em-dash
        dimensions = [i.get("dimension", "") for i in result["issues"]]
        assert any("not-is-comparison" in d for d in dimensions)
        assert any("em-dash" in d for d in dimensions)

    def test_word_count_still_returned(self):
        """字数统计应仍正常返回"""
        draft = "他推开门，发现屋里没人。"
        result = run_deterministic_checks(draft, word_min=10, word_max=1000)
        assert "word_count" in result
        assert result["word_count"] > 0
