"""core_constraints.txt oh-story 7 Gate 铁律完整性测试。

验证 Task 6：core_constraints.txt 已追加 oh-story 7 Gate 体系。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def core_constraints_text() -> str:
    """读取 core_constraints.txt 内容。"""
    path = Path(__file__).parent.parent / "novel_agent" / "templates" / "style_guides" / "core_constraints.txt"
    return path.read_text(encoding="utf-8")


class TestCoreConstraintsOhStoryGates:
    """验证 core_constraints.txt 包含完整 oh-story 7 Gate 体系。"""

    def test_contains_oh_story_section(self, core_constraints_text):
        """应包含 oh-story 7 Gate 章节。"""
        assert "oh-story 7 Gate" in core_constraints_text
        assert "三.五" in core_constraints_text

    def test_contains_all_seven_gates(self, core_constraints_text):
        """应包含全部 7 个 Gate。"""
        for gate in ["Gate A", "Gate B", "Gate C", "Gate D", "Gate E", "Gate F", "Gate G"]:
            assert gate in core_constraints_text, f"缺少 {gate}"

    def test_gate_a_contains_most_poisonous_patterns(self, core_constraints_text):
        """Gate A 应包含最毒句式。"""
        gate_a_section = core_constraints_text.split("Gate A")[1].split("Gate B")[0]
        assert "不是A" in gate_a_section or "不是" in gate_a_section
        assert "仿佛" in gate_a_section
        assert "深吸一口气" in gate_a_section
        assert "眼中闪过" in gate_a_section
        assert "嘴角勾起" in gate_a_section

    def test_gate_a_contains_first_level_banned_words(self, core_constraints_text):
        """Gate A 应包含一级禁用词分类。"""
        gate_a_section = core_constraints_text.split("Gate A")[1].split("Gate B")[0]
        assert "情态类" in gate_a_section
        assert "动作类" in gate_a_section
        assert "表情类" in gate_a_section
        assert "心理类" in gate_a_section
        assert "判断类" in gate_a_section
        assert "形容类" in gate_a_section
        assert "过渡类" in gate_a_section

    def test_gate_b_contains_parallelism_rules(self, core_constraints_text):
        """Gate B 应包含排比规则。"""
        gate_b_section = core_constraints_text.split("Gate B")[1].split("Gate C")[0]
        assert "排比" in gate_b_section
        assert "越来越" in gate_b_section

    def test_gate_c_contains_externalization(self, core_constraints_text):
        """Gate C 应包含心理外化规则。"""
        gate_c_section = core_constraints_text.split("Gate C")[1].split("Gate D")[0]
        assert "外化" in gate_c_section or "展示" in gate_c_section
        assert "感到愤怒" in gate_c_section

    def test_gate_d_contains_rhythm_rules(self, core_constraints_text):
        """Gate D 应包含节奏规则。"""
        gate_d_section = core_constraints_text.split("Gate D")[1].split("Gate E")[0]
        assert "长段落" in gate_d_section or "短段" in gate_d_section
        assert "句号结巴" in gate_d_section

    def test_gate_e_contains_dialog_rules(self, core_constraints_text):
        """Gate E 应包含对话规则。"""
        gate_e_section = core_constraints_text.split("Gate E")[1].split("Gate F")[0]
        assert "对话标签" in gate_e_section
        assert "说道" in gate_e_section

    def test_gate_f_contains_ending_rules(self, core_constraints_text):
        """Gate F 应包含结尾规则。"""
        gate_f_section = core_constraints_text.split("Gate F")[1].split("Gate G")[0]
        assert "升华" in gate_f_section
        assert "这一刻" in gate_f_section

    def test_gate_g_contains_explanation_rules(self, core_constraints_text):
        """Gate G 应包含解释腔/上帝感规则。"""
        gate_g_section = core_constraints_text.split("Gate G")[1].split("三遍法")[0]
        assert "解释腔" in gate_g_section or "上帝感" in gate_g_section
        assert "他不知道的是" in gate_g_section

    def test_contains_three_pass_method(self, core_constraints_text):
        """应包含三遍法说明。"""
        assert "三遍法" in core_constraints_text
        assert "Pass1" in core_constraints_text
        assert "Pass2" in core_constraints_text
        assert "Pass3" in core_constraints_text
        assert "去泛化" in core_constraints_text
        assert "去书面化" in core_constraints_text
        assert "回自然感" in core_constraints_text

    def test_contains_six_metrics(self, core_constraints_text):
        """应包含 6 项客观指标。"""
        assert "禁用词密度" in core_constraints_text
        assert "连续排比段数" in core_constraints_text
        assert "心理词占比" in core_constraints_text
        assert "对话标签密度" in core_constraints_text
        assert "平均段落句数" in core_constraints_text
        assert "重复描写密度" in core_constraints_text

    def test_contains_delete_ratio_limits(self, core_constraints_text):
        """应包含删除比例上限。"""
        assert "删除比例上限" in core_constraints_text
        assert "15%" in core_constraints_text
        assert "25%" in core_constraints_text
        assert "35%" in core_constraints_text

    def test_contains_em_dash_ban(self, core_constraints_text):
        """应包含破折号禁令。"""
        assert "破折号" in core_constraints_text
        assert "——" in core_constraints_text

    def test_preserves_original_sections(self, core_constraints_text):
        """应保留原有章节（零/一/二/三/四/五/六）。"""
        assert "零、网文语感铁律" in core_constraints_text
        assert "一、每章必备三要素" in core_constraints_text
        assert "二、节奏与句式" in core_constraints_text
        assert "三、反AI味铁律" in core_constraints_text
        assert "四、开头自查" in core_constraints_text
        assert "五、章节节奏三拍" in core_constraints_text
        assert "六、最重要的原则" in core_constraints_text
