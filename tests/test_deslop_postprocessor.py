"""deslop_postprocessor 单元测试。

覆盖：
- 6 项客观指标计算（档位判定）
- AI 味综合分级（轻度/中度/重度）
- Pass 序列选择（轻度=1/中度=2/重度=3）
- 删除比例上限
- run_deslop_postprocess 主入口（跳过/正常/回退）
- should_run_deslop 便捷函数
- get_deslop_summary 格式化
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from novel_agent.audit.deslop_postprocessor import (
    DELETE_RATIO_LIMIT,
    DESLOP_SYSTEM_PROMPT,
    GATE_A_RULES,
    GATE_B_RULES,
    GATE_C_RULES,
    GATE_D_RULES,
    GATE_E_RULES,
    GATE_F_RULES,
    GATE_G_RULES,
    LEVEL_MILD,
    LEVEL_MODERATE,
    LEVEL_SEVERE,
    PASS1_GATES,
    PASS2_GATES,
    PASS3_GATES,
    _BAND_MILD,
    _BAND_MODERATE,
    _BAND_SEVERE,
    _build_pass_prompt,
    _format_metrics_summary,
    _metric_avg_paragraph_sentences,
    _metric_banned_density,
    _metric_dialog_tag_density,
    _metric_parallelism_runs,
    _metric_psychology_ratio,
    _metric_repetition_density,
    _select_passes,
    get_deslop_summary,
    run_deslop_postprocess,
    score_ai_level,
    should_run_deslop,
)


# ════════════════════════════════════════════════════════════════════
# 6 项客观指标测试
# ════════════════════════════════════════════════════════════════════


class TestMetricBannedDensity:
    """指标1：禁用词密度。"""

    def test_clean_text_is_mild(self):
        text = "他走进房间，把书放在桌上。窗外下着雨。"
        result = _metric_banned_density(text, ["仿佛", "犹如"])
        assert result["band"] == _BAND_MILD
        assert result["value"] == 0.0

    def test_moderate_density(self):
        # 1000 字内出现 6-15 次 → 中度
        # 8 次"仿佛"(16字) + 200 次"他走进房间"(1000字) = 8/1016*1000 ≈ 7.9 → moderate
        text = "仿佛" * 8 + "他走进房间" * 200
        result = _metric_banned_density(text, ["仿佛"])
        assert result["band"] == _BAND_MODERATE
        assert result["hits"] == 8

    def test_severe_density(self):
        # 高密度禁用词
        text = "仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛仿佛"
        result = _metric_banned_density(text, ["仿佛"])
        assert result["band"] == _BAND_SEVERE
        assert result["hits"] == 16


class TestMetricParallelismRuns:
    """指标2：连续排比段数。"""

    def test_no_parallelism_is_mild(self):
        text = "他走进房间。\n她坐在窗边。\n雨声响起。\n电话响了。"
        result = _metric_parallelism_runs(text)
        assert result["band"] == _BAND_MILD

    def test_moderate_parallelism(self):
        # 3-4 段连续相同句式
        text = "越来越冷。\n越来越暗。\n越来越累。"
        result = _metric_parallelism_runs(text)
        assert result["band"] == _BAND_MODERATE
        assert result["value"] >= 3

    def test_severe_parallelism(self):
        # 5+ 段连续相同句式
        text = "越来越冷。\n越来越暗。\n越来越累。\n越来越困。\n越来越饿。"
        result = _metric_parallelism_runs(text)
        assert result["band"] == _BAND_SEVERE
        assert result["value"] >= 5


class TestMetricPsychologyRatio:
    """指标3：心理词占比。"""

    def test_low_ratio_is_mild(self):
        text = "他走进房间，把书放在桌上。窗外下着雨。"
        result = _metric_psychology_ratio(text)
        assert result["band"] == _BAND_MILD

    def test_high_ratio_is_severe(self):
        # 大量心理词堆砌
        text = (
            "他感到愤怒。她感到恐惧。他意识到事情不对。她终于明白了。"
            "他心中涌起一股暖流。她心头一震。他心中一动。她心下了然。"
            "他知道一切。她明白所有。他这才意识到。她终于明白了一切。"
        )
        result = _metric_psychology_ratio(text)
        assert result["band"] in (_BAND_MODERATE, _BAND_SEVERE)


class TestMetricDialogTagDensity:
    """指标4：对话标签密度。"""

    def test_no_dialog_is_mild(self):
        text = "他走进房间。窗外下着雨。"
        result = _metric_dialog_tag_density(text)
        assert result["band"] == _BAND_MILD

    def test_low_tag_density_is_mild(self):
        text = '\u201c你来了。\u201d\n他点头。\n\u201c坐吧。\u201d\n她坐下。'
        result = _metric_dialog_tag_density(text)
        assert result["band"] == _BAND_MILD

    def test_high_tag_density_is_severe(self):
        # 每句对话都带"说道"标签
        text = (
            '他\u201c说道\u201d：你来了。\n'
            '她\u201c说道\u201d：嗯。\n'
            '他\u201c说道\u201d：坐吧。\n'
            '她\u201c说道\u201d：好。'
        )
        result = _metric_dialog_tag_density(text)
        # 至少不是 mild
        assert result["band"] in (_BAND_MODERATE, _BAND_SEVERE)


class TestMetricAvgParagraphSentences:
    """指标5：平均段落句数。"""

    def test_short_paragraphs_is_mild(self):
        # 每段 1-2 句
        text = "他走进房间。\n\n她坐在窗边。\n\n雨声响起。\n\n电话响了。\n\n他接起电话。"
        result = _metric_avg_paragraph_sentences(text)
        assert result["band"] == _BAND_MILD

    def test_long_paragraphs_is_severe(self):
        # 每段 6+ 句
        text = "他走进房间。她坐在窗边。雨声响起。电话响了。他接起电话。她没说话。\n\n" \
               "他走进房间。她坐在窗边。雨声响起。电话响了。他接起电话。她没说话。\n\n" \
               "他走进房间。她坐在窗边。雨声响起。电话响了。他接起电话。她没说话。\n\n" \
               "他走进房间。她坐在窗边。雨声响起。电话响了。他接起电话。她没说话。\n\n" \
               "他走进房间。她坐在窗边。雨声响起。电话响了。他接起电话。她没说话。"
        result = _metric_avg_paragraph_sentences(text)
        assert result["band"] == _BAND_SEVERE
        assert result["value"] > 5


class TestMetricRepetitionDensity:
    """指标6：重复描写密度。"""

    def test_no_repetition_is_mild(self):
        text = "他走进房间，把书放在桌上。窗外下着雨。"
        result = _metric_repetition_density(text)
        assert result["band"] == _BAND_MILD

    def test_high_repetition_is_severe(self):
        # 大量重复身体动作描写
        text = (
            "他深吸一口气。她深吸一口气。他深吸一口气。她深吸一口气。"
            "他瞳孔一缩。她瞳孔一缩。他瞳孔一缩。"
            "他嘴角抽动。她嘴角抽动。他嘴角抽动。"
            "他后背发凉。她后背发凉。"
            "他心跳加速。她心跳加速。"
            "他眼中闪过一丝恐惧。她眼中闪过一丝惊讶。他眼中闪过一丝愤怒。"
        )
        result = _metric_repetition_density(text)
        assert result["band"] in (_BAND_MODERATE, _BAND_SEVERE)


# ════════════════════════════════════════════════════════════════════
# AI 味综合分级测试
# ════════════════════════════════════════════════════════════════════


class TestScoreAiLevel:
    """AI 味综合分级。"""

    def test_clean_text_is_mild(self):
        text = "他走进房间，把书放在桌上。窗外下着雨。她抬头看了他一眼。"
        result = score_ai_level(text)
        assert result["level"] == LEVEL_MILD
        assert result["severe_count"] == 0
        assert result["moderate_count"] < 3

    def test_severe_metric_makes_severe(self):
        # 任一指标达重度 → 整体重度
        text = (
            "他感到愤怒。她感到恐惧。他意识到事情不对。她终于明白了。"
            "他心中涌起一股暖流。她心头一震。他心中一动。她心下了然。"
            "他知道一切。她明白所有。他这才意识到。她终于明白了一切。"
            "他心中涌起。她心头一震。他心中一动。"
        )
        result = score_ai_level(text)
        # 心理词占比应达重度
        assert result["severe_count"] >= 1
        assert result["level"] == LEVEL_SEVERE

    def test_three_moderate_makes_moderate(self):
        # 3+ 中度指标但无重度 → 中度
        # 构造文本：中等密度禁用词 + 中等排比 + 中等心理词
        text = (
            "仿佛他走进房间。仿佛她坐在窗边。仿佛雨声响起。仿佛电话响了。"
            "仿佛他接起电话。仿佛她没说话。仿佛他点头。仿佛她转身。"
            "他心中涌起一股暖流。她心头一震。"
            "越来越冷。越来越暗。越来越累。"
        )
        result = score_ai_level(text)
        # 应该是中度或重度（取决于具体指标判定）
        assert result["level"] in (LEVEL_MODERATE, LEVEL_SEVERE)

    def test_returns_six_metrics(self):
        text = "他走进房间。"
        result = score_ai_level(text)
        assert len(result["metrics"]) == 6
        metric_names = [m["metric"] for m in result["metrics"]]
        assert "banned_density" in metric_names
        assert "parallelism_runs" in metric_names
        assert "psychology_ratio" in metric_names
        assert "dialog_tag_density" in metric_names
        assert "avg_paragraph_sentences" in metric_names
        assert "repetition_density" in metric_names


# ════════════════════════════════════════════════════════════════════
# Pass 序列选择测试
# ════════════════════════════════════════════════════════════════════


class TestSelectPasses:
    """按 AI 味等级选择 Pass 序列。"""

    def test_mild_runs_one_pass(self):
        passes = _select_passes(LEVEL_MILD)
        assert len(passes) == 1
        assert passes[0][0] == "Pass1 去泛化"

    def test_moderate_runs_two_passes(self):
        passes = _select_passes(LEVEL_MODERATE)
        assert len(passes) == 2
        assert passes[0][0] == "Pass1 去泛化"
        assert passes[1][0] == "Pass2 去书面化"

    def test_severe_runs_three_passes(self):
        passes = _select_passes(LEVEL_SEVERE)
        assert len(passes) == 3
        assert passes[0][0] == "Pass1 去泛化"
        assert passes[1][0] == "Pass2 去书面化"
        assert passes[2][0] == "Pass3 回自然感"

    def test_delete_ratio_limits(self):
        assert DELETE_RATIO_LIMIT[LEVEL_MILD] == 0.15
        assert DELETE_RATIO_LIMIT[LEVEL_MODERATE] == 0.25
        assert DELETE_RATIO_LIMIT[LEVEL_SEVERE] == 0.35


# ════════════════════════════════════════════════════════════════════
# Gate 规则集完整性测试
# ════════════════════════════════════════════════════════════════════


class TestGateRulesCompleteness:
    """验证 7 Gate 规则集完整。"""

    def test_all_seven_gates_defined(self):
        """7 个 Gate 都必须有内容（非空字符串）。"""
        gates = [
            GATE_A_RULES, GATE_B_RULES, GATE_C_RULES,
            GATE_D_RULES, GATE_E_RULES, GATE_F_RULES, GATE_G_RULES,
        ]
        for gate in gates:
            assert isinstance(gate, str)
            assert len(gate) > 50, f"Gate 规则过短：{gate[:30]}"

    def test_gate_a_contains_key_banned_words(self):
        """Gate A 必须包含核心禁用词规则。"""
        assert "不是A" in GATE_A_RULES or "不是" in GATE_A_RULES
        assert "仿佛" in GATE_A_RULES
        assert "深吸一口气" in GATE_A_RULES
        assert "眼中闪过" in GATE_A_RULES

    def test_gate_b_contains_parallelism_rules(self):
        """Gate B 必须包含排比规则。"""
        assert "排比" in GATE_B_RULES
        assert "越来越" in GATE_B_RULES

    def test_gate_c_contains_externalization_rules(self):
        """Gate C 必须包含心理外化规则。"""
        assert "外化" in GATE_C_RULES or "展示" in GATE_C_RULES
        assert "感到愤怒" in GATE_C_RULES

    def test_gate_d_contains_rhythm_rules(self):
        """Gate D 必须包含节奏规则。"""
        assert "长段落" in GATE_D_RULES or "短段" in GATE_D_RULES
        assert "句号结巴" in GATE_D_RULES

    def test_gate_e_contains_dialog_rules(self):
        """Gate E 必须包含对话规则。"""
        assert "对话标签" in GATE_E_RULES
        assert "说道" in GATE_E_RULES

    def test_gate_f_contains_ending_rules(self):
        """Gate F 必须包含结尾规则。"""
        assert "升华" in GATE_F_RULES
        assert "这一刻" in GATE_F_RULES

    def test_gate_g_contains_explanation_rules(self):
        """Gate G 必须包含解释腔/上帝感规则。"""
        assert "解释腔" in GATE_G_RULES or "上帝感" in GATE_G_RULES
        assert "他不知道的是" in GATE_G_RULES

    def test_three_passes_cover_all_gates(self):
        """三遍 Pass 必须覆盖全部 7 Gate。"""
        # Pass1: A/C/D/E/G
        assert "Gate A" in PASS1_GATES
        assert "Gate C" in PASS1_GATES
        assert "Gate D" in PASS1_GATES
        assert "Gate E" in PASS1_GATES
        assert "Gate G" in PASS1_GATES
        # Pass2: A/B
        assert "Gate A" in PASS2_GATES
        assert "Gate B" in PASS2_GATES
        # Pass3: D/E/F
        assert "Gate D" in PASS3_GATES
        assert "Gate E" in PASS3_GATES
        assert "Gate F" in PASS3_GATES


# ════════════════════════════════════════════════════════════════════
# Prompt 构建测试
# ════════════════════════════════════════════════════════════════════


class TestBuildPassPrompt:
    """Pass prompt 构建。"""

    def test_prompt_contains_pass_name(self):
        prompt = _build_pass_prompt(
            pass_name="Pass1 去泛化",
            gates_rules=GATE_A_RULES,
            text="测试文本",
            delete_ratio_limit=0.15,
            ai_level=LEVEL_MILD,
            metrics_summary="- banned_density: 0.0（mild）",
        )
        assert "Pass1 去泛化" in prompt
        assert "测试文本" in prompt

    def test_prompt_contains_delete_ratio(self):
        prompt = _build_pass_prompt(
            pass_name="Pass2",
            gates_rules=GATE_B_RULES,
            text="测试",
            delete_ratio_limit=0.25,
            ai_level=LEVEL_MODERATE,
            metrics_summary="summary",
        )
        assert "25%" in prompt
        assert "moderate" in prompt

    def test_prompt_contains_iron_laws(self):
        prompt = _build_pass_prompt(
            pass_name="Pass1",
            gates_rules=GATE_A_RULES,
            text="测试",
            delete_ratio_limit=0.15,
            ai_level=LEVEL_MILD,
            metrics_summary="summary",
        )
        assert "不得改变剧情" in prompt
        assert "不得增删角色" in prompt
        assert "只输出改写后的正文" in prompt

    def test_prompt_contains_metrics(self):
        prompt = _build_pass_prompt(
            pass_name="Pass1",
            gates_rules=GATE_A_RULES,
            text="测试",
            delete_ratio_limit=0.15,
            ai_level=LEVEL_MILD,
            metrics_summary="CUSTOM_METRICS_SUMMARY",
        )
        assert "CUSTOM_METRICS_SUMMARY" in prompt


# ════════════════════════════════════════════════════════════════════
# 主入口 run_deslop_postprocess 测试
# ════════════════════════════════════════════════════════════════════


class TestRunDeslopPostprocess:
    """run_deslop_postprocess 主入口。"""

    def test_skipped_when_clean_text(self):
        """干净文本（无 blocking, advisory≤2）跳过 LLM 调用。"""
        text = "他走进房间，把书放在桌上。窗外下着雨。她抬头看了他一眼。"
        llm_client = MagicMock()
        llm_client.generate = AsyncMock()

        result = asyncio.run(run_deslop_postprocess(text, llm_client))

        assert result["skipped"] is True
        assert result["passes_executed"] == []
        # LLM 不应被调用
        llm_client.generate.assert_not_called()
        assert result["processed_text"] == text
        assert result["rolled_back"] is False

    def test_runs_llm_when_blocking_present(self):
        """存在 blocking 级问题时调用 LLM。"""
        # 包含破折号（blocking 级）
        text = "他走进房间——把书放下。"
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="他走进房间，把书放下。")

        result = asyncio.run(run_deslop_postprocess(text, llm_client))

        assert result["skipped"] is False
        assert len(result["passes_executed"]) >= 1
        # LLM 应被调用
        llm_client.generate.assert_called()
        assert result["processed_text"] == "他走进房间，把书放下。"

    def test_force_run_calls_llm_even_when_clean(self):
        """force_run=True 时即使干净文本也调用 LLM。"""
        text = "他走进房间，把书放在桌上。窗外下着雨。"
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="他走进房间，把书放在桌上。")

        result = asyncio.run(run_deslop_postprocess(text, llm_client, force_run=True))

        assert result["skipped"] is False
        llm_client.generate.assert_called()

    def test_rollback_when_blocking_increases(self):
        """改写后 blocking 增多时回退原版本。"""
        # 原文有 1 个 blocking（破折号）
        original = "他走进房间——把书放下。"
        # LLM 返回的改写反而引入 2 个 blocking（破折号 + 占位符）
        bad_rewrite = "他走进——房间。TODO占位符。"

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value=bad_rewrite)

        result = asyncio.run(run_deslop_postprocess(original, llm_client))

        assert result["rolled_back"] is True
        assert result["processed_text"] == original

    def test_max_passes_limits_pass_count(self):
        """max_passes 限制 Pass 数。"""
        # 重度 AI 味文本，正常应跑 3 遍
        text = (
            "他感到愤怒。她感到恐惧。他意识到事情不对。她终于明白了。"
            "他心中涌起一股暖流。她心头一震。他心中一动。她心下了然。"
            "他知道一切。她明白所有。他这才意识到。她终于明白了一切。"
            "——破折号也是blocking。"
        )
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="他走进房间，把书放下。")

        result = asyncio.run(run_deslop_postprocess(text, llm_client, max_passes=1))

        # 只跑 1 遍
        assert len(result["passes_executed"]) <= 1

    def test_pre_check_and_post_check_populated(self):
        """pre_check 和 post_check 应被填充。"""
        text = "他走进房间——把书放下。"
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="他走进房间，把书放下。")

        result = asyncio.run(run_deslop_postprocess(text, llm_client))

        assert result["pre_check"] is not None
        assert "blocking_count" in result["pre_check"]
        assert "advisory_count" in result["pre_check"]
        assert result["post_check"] is not None

    def test_llm_failure_does_not_block(self):
        """LLM 调用失败时不阻塞流程，返回原文本。"""
        text = "他走进房间——把书放下。"
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(side_effect=Exception("LLM error"))

        result = asyncio.run(run_deslop_postprocess(text, llm_client))

        # 不阻塞，passes_executed 为空（因为失败）
        assert result["skipped"] is False
        # processed_text 仍是原文
        assert result["processed_text"] == text


# ════════════════════════════════════════════════════════════════════
# 便捷工具函数测试
# ════════════════════════════════════════════════════════════════════


class TestShouldRunDeslop:
    """should_run_deslop 便捷函数。"""

    def test_returns_false_for_clean_text(self):
        text = "他走进房间，把书放在桌上。窗外下着雨。"
        need_run, reason = should_run_deslop(text)
        assert need_run is False
        assert "通过" in reason

    def test_returns_true_for_blocking(self):
        # 包含破折号（blocking）
        text = "他走进房间——把书放下。"
        need_run, reason = should_run_deslop(text)
        assert need_run is True
        assert "blocking" in reason


class TestGetDeslopSummary:
    """get_deslop_summary 格式化。"""

    def test_skipped_summary(self):
        result = {
            "skipped": True,
            "level": LEVEL_MILD,
            "passes_executed": [],
            "rolled_back": False,
            "pre_check": {"blocking_count": 0, "advisory_count": 1},
            "post_check": {"blocking_count": 0, "advisory_count": 1},
        }
        summary = get_deslop_summary(result)
        assert "跳过" in summary

    def test_normal_summary(self):
        result = {
            "skipped": False,
            "level": LEVEL_MODERATE,
            "passes_executed": ["Pass1 去泛化", "Pass2 去书面化"],
            "rolled_back": False,
            "pre_check": {"blocking_count": 2, "advisory_count": 3},
            "post_check": {"blocking_count": 0, "advisory_count": 1},
        }
        summary = get_deslop_summary(result)
        assert "moderate" in summary
        assert "Pass1" in summary
        assert "Pass2" in summary
        assert "2→0" in summary

    def test_rolled_back_summary(self):
        result = {
            "skipped": False,
            "level": LEVEL_SEVERE,
            "passes_executed": ["Pass1 去泛化"],
            "rolled_back": True,
            "pre_check": {"blocking_count": 1, "advisory_count": 2},
            "post_check": {"blocking_count": 1, "advisory_count": 2},
        }
        summary = get_deslop_summary(result)
        assert "回退" in summary


class TestFormatMetricsSummary:
    """_format_metrics_summary 格式化。"""

    def test_formats_all_metrics(self):
        score = {
            "metrics": [
                {"metric": "banned_density", "value": 5.0, "band": "mild"},
                {"metric": "parallelism_runs", "value": 3, "band": "moderate"},
            ],
            "moderate_count": 1,
            "severe_count": 0,
        }
        summary = _format_metrics_summary(score)
        assert "banned_density" in summary
        assert "parallelism_runs" in summary
        assert "中度指标数" in summary
        assert "重度指标数" in summary


# ════════════════════════════════════════════════════════════════════
# 系统提示词测试
# ════════════════════════════════════════════════════════════════════


class TestDeslopSystemPrompt:
    """DESLOP_SYSTEM_PROMPT 完整性。"""

    def test_system_prompt_mentions_oh_story(self):
        assert "oh-story" in DESLOP_SYSTEM_PROMPT or "7 Gate" in DESLOP_SYSTEM_PROMPT

    def test_system_prompt_mentions_iron_laws(self):
        assert "不改编情" in DESLOP_SYSTEM_PROMPT
        assert "不增删角色" in DESLOP_SYSTEM_PROMPT
        assert "删除比例" in DESLOP_SYSTEM_PROMPT
