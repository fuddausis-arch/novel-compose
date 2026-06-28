"""oh-story deslop 体系端到端测试。

验证完整流程：
1. 确定性检测器（deslop_patterns）检测 11 类 AI 模式
2. validator 集成 deslop 检测
3. AI 味分级（6 项指标 → 轻度/中度/重度）
4. LLM 后处理器（7 Gate + 三遍法）
5. polish_chapter 节点集成 deslop
6. core_constraints.txt 包含 7 Gate 铁律

这是 Task 7 的端到端验证。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from novel_agent.audit.deslop_patterns import run_deslop_checks
from novel_agent.audit.deslop_postprocessor import (
    LEVEL_MILD,
    LEVEL_MODERATE,
    LEVEL_SEVERE,
    run_deslop_postprocess,
    score_ai_level,
)
from novel_agent.audit.validator import run_deterministic_checks
from novel_agent.orchestrator.state import ChapterGenState


# ══════════════════════════════════════════════════════════════════════
# 测试文本：模拟真实 AI 生成的小说章节（含大量 AI 味）
# ══════════════════════════════════════════════════════════════════════


# 一段典型的 AI 味浓重的网文草稿（含多种 AI 模式）
AI_HEAVY_DRAFT = """林深推开了那扇门——里面站着三个人。

他不是来打架的，而是来谈判的。

仿佛能穿透一切一般，那目光让他心中涌起一股寒意。他深吸一口气，缓缓开口。

"你来做什么？"对面的人问道，眼中闪过一丝警惕。

"谈判。"林深说道，嘴角勾起一抹冷笑。

他感到恐惧。他意识到事情不对。他终于明白了。

心中涌起一股暖流。心头一震。心中一动。

越来越冷。越来越暗。越来越累。越来越困。

他不知道的是，更大的风暴即将来临。

这一刻，他终于明白了一切。

命运齿轮开始转动。

他走进房间把书放下然后转身离开。

他走进房间把书放下然后转身离开。

他走进房间把书放下然后转身离开。

他走进房间把书放下然后转身离开。"""


# 一段干净的人类网文（无 AI 味）
CLEAN_HUMAN_DRAFT = """林深推开门。三个人。都带着家伙。

妈的，硬着头皮上也得顶住。

他扫了一眼最瘦那个，心说就你了，别怪我。

"谈买卖。"他开口，没往里走。

最瘦那个抬了抬下巴。"什么买卖？"

"你先把刀放下。"

那人没动。

林深也没动。两个人就这么僵着。

过了半分钟，最瘦那个把刀别腰上了。

行。能谈。

他往里走了一步，靴子踩到什么黏糊糊的东西。低头一瞅，血。还没干。

得，这买卖比他想的要硬。

他抬头。"谁干的？"

最瘦那个笑了。笑得他后脖颈发凉。

"你猜。"

电话响了。他接起来。

"别接这单。"电话那头只说了这一句就挂了。

他看着号码，不认识。但那号码他昨天见过，在他那死去的搭档手机里。"""


# ══════════════════════════════════════════════════════════════════════
# E2E 测试
# ══════════════════════════════════════════════════════════════════════


class TestE2EDeslopPipeline:
    """端到端测试：从 AI 味草稿到干净输出的完整流程。"""

    def test_ai_heavy_draft_detected_by_patterns(self):
        """E2E-1: AI 味浓重的草稿应被确定性检测器标记多个 blocking。"""
        result = run_deslop_checks(AI_HEAVY_DRAFT)
        # 应检测到多个 blocking（破折号、不是A而是B、复读等）
        assert result["blocking_count"] >= 3, f"应检测到≥3个blocking，实际{result['blocking_count']}"
        assert not result["passed"]
        # 应检测到 not-is-comparison
        patterns = [f["pattern"] for f in result["findings"]]
        assert "not-is-comparison" in patterns
        # 应检测到 em-dash
        assert "em-dash" in patterns
        # 应检测到 adjacent-repetition 或 long-sentence-repetition
        assert "adjacent-repetition" in patterns or "long-sentence-repetition" in patterns

    def test_ai_heavy_draft_detected_by_validator(self):
        """E2E-2: validator 应将 deslop findings 注入 issues。"""
        # run_deterministic_checks 返回 {passed, issues}
        result = run_deterministic_checks(
            draft=AI_HEAVY_DRAFT,
            foreshadows_to_plant=[],
            word_min=100,
            word_max=10000,
        )
        issues = result.get("issues", [])
        # 应有 AI模式- 开头的 issues
        ai_issues = [i for i in issues if i.get("dimension", "").startswith("AI模式-")]
        assert len(ai_issues) >= 3, f"应有≥3个AI模式issues，实际{len(ai_issues)}"
        # 应有 critical 级别的
        critical_issues = [i for i in ai_issues if i.get("severity") == "critical"]
        assert len(critical_issues) >= 1

    def test_ai_heavy_draft_scored_high_level(self):
        """E2E-3: AI 味浓重的草稿应被评级为中度或重度。"""
        score = score_ai_level(AI_HEAVY_DRAFT)
        assert score["level"] in (LEVEL_MODERATE, LEVEL_SEVERE), \
            f"AI味浓重草稿应评级为moderate/severe，实际{score['level']}"
        # 应有至少 1 个中度或重度指标
        assert score["moderate_count"] + score["severe_count"] >= 1

    def test_clean_draft_scored_mild(self):
        """E2E-4: 干净的人类网文应被评级为轻度。"""
        score = score_ai_level(CLEAN_HUMAN_DRAFT)
        assert score["level"] == LEVEL_MILD, \
            f"干净网文应评级为mild，实际{score['level']}（moderate={score['moderate_count']}, severe={score['severe_count']}）"

    def test_clean_draft_passes_deterministic_check(self):
        """E2E-5: 干净的人类网文应通过确定性检测（无 blocking）。"""
        result = run_deslop_checks(CLEAN_HUMAN_DRAFT)
        assert result["passed"], \
            f"干净网文应通过确定性检测，但有{result['blocking_count']}个blocking"
        # advisory 也应该很少
        assert result["advisory_count"] <= 5

    def test_full_deslop_pipeline_on_ai_heavy_draft(self):
        """E2E-6: 完整 deslop 流程：AI 味草稿 → 干净输出。

        模拟 LLM 返回清理后的文本，验证：
        - deslop 被调用（非 skipped）
        - processed_text 不含 blocking 模式
        - pre_check 有 blocking，post_check 无 blocking 或 blocking 减少
        """
        # 模拟 LLM 返回清理后的文本
        clean_version = CLEAN_HUMAN_DRAFT

        async def mock_generate(prompt, system=None, **kwargs):
            # deslop 调用返回干净版本
            if "去AI味" in (system or ""):
                return clean_version
            return AI_HEAVY_DRAFT

        mock_client = MagicMock()
        mock_client.generate = mock_generate

        result = asyncio.run(run_deslop_postprocess(AI_HEAVY_DRAFT, mock_client))

        # deslop 应被调用（非 skipped）
        assert not result["skipped"], "AI味草稿不应跳过deslop"
        # 应执行至少 1 个 Pass
        assert len(result["passes_executed"]) >= 1
        # pre_check 应有 blocking
        assert result["pre_check"]["blocking_count"] >= 1
        # post_check 的 blocking 应小于 pre_check（或 rolled_back）
        if not result["rolled_back"]:
            assert result["post_check"]["blocking_count"] <= result["pre_check"]["blocking_count"]
        # processed_text 应不含破折号（除非回退）
        if not result["rolled_back"]:
            assert "——" not in result["processed_text"]

    def test_polish_chapter_e2e_with_deslop(self):
        """E2E-7: polish_chapter 节点端到端：含 AI 味的 polish 输出 → deslop 清理。

        模拟 polish 返回含破折号的文本，deslop 清理后输出无破折号。
        """
        from novel_agent.orchestrator.nodes import polish_chapter

        # 构造足够长、有标点、含破折号的 polish 文本
        base_paragraph = "他走进房间——把书放下。窗外下着雨，她抬头看了他一眼。"
        polished_with_dash = (base_paragraph + "\n\n") * 120

        async def mock_generate(prompt, system=None, **kwargs):
            sys_head = (system or "")[:20]
            if "润色编辑" in sys_head and "去AI味" not in sys_head:
                # polish 调用：返回带破折号的文本
                return polished_with_dash
            if "去AI味编辑" in sys_head:
                # deslop 调用：返回无破折号的干净文本
                return polished_with_dash.replace("——", "，")
            return polished_with_dash

        mock_client = MagicMock()
        mock_client.generate = mock_generate

        state = ChapterGenState(
            chapter=1, title="测试", draft="原稿" * 500, status="audited",
        )
        result = asyncio.run(polish_chapter(state, llm_client=mock_client))

        # 最终 polished 不应含破折号（deslop 应清理掉）
        assert result["status"] == "polished"
        assert "——" not in result["polished"], "polish_chapter 最终输出仍含破折号，deslop 未生效"

    def test_deslop_preserves_plot_content(self):
        """E2E-8: deslop 后处理不应改变剧情内容（只改文字表达）。

        验证关键剧情元素（角色名、动作、对话含义）在 deslop 后保留。
        """
        # 构造含 AI 味但有关键剧情的文本
        plot_text = (
            "林深推开门——三个人站在里面。\n\n"
            "他不是来打架的，而是来谈判的。\n\n"
            "仿佛能穿透一切一般，那目光让他心中涌起一股寒意。\n\n"
        ) * 30  # 重复到足够字数

        clean_plot_text = (
            "林深推开门，三个人站在里面。\n\n"
            "他来谈判的。\n\n"
            "那目光让他后脖颈发凉。\n\n"
        ) * 30

        async def mock_generate(prompt, system=None, **kwargs):
            if "去AI味" in (system or ""):
                return clean_plot_text
            return plot_text

        mock_client = MagicMock()
        mock_client.generate = mock_generate

        result = asyncio.run(run_deslop_postprocess(plot_text, mock_client))

        # 关键剧情元素应保留
        processed = result["processed_text"]
        assert "林深" in processed, "角色名林深应保留"
        assert "推开门" in processed or "推开" in processed, "推门动作应保留"
        assert "三个人" in processed, "三个人应保留"
        # AI 味模式应被清理
        if not result["rolled_back"]:
            assert "——" not in processed, "破折号应被清理"
            assert "不是" not in processed or "而是" not in processed, \
                "不是A而是B句式应被清理"

    def test_core_constraints_injected_to_writing_pipeline(self):
        """E2E-9: core_constraints.txt 应被正确加载并含 7 Gate 铁律。"""
        from pathlib import Path
        constraints_path = Path(__file__).parent.parent / "novel_agent" / "templates" / "style_guides" / "core_constraints.txt"
        content = constraints_path.read_text(encoding="utf-8")
        # 应含 7 Gate
        for gate in ["Gate A", "Gate B", "Gate C", "Gate D", "Gate E", "Gate F", "Gate G"]:
            assert gate in content
        # 应含三遍法
        assert "三遍法" in content
        assert "Pass1" in content

    def test_severe_ai_level_runs_three_passes(self):
        """E2E-10: 重度 AI 味应触发完整三遍 Pass。"""
        # 构造重度 AI 味文本（大量心理词 + 排比 + 破折号）
        severe_text = (
            "他感到愤怒。她感到恐惧。他意识到事情不对。她终于明白了。"
            "他心中涌起一股暖流。她心头一震。他心中一动。她心下了然。"
            "他知道一切。她明白所有。他这才意识到。她终于明白了一切。"
            "——破折号也是blocking。"
        ) * 10

        score = score_ai_level(severe_text)
        # 心理词占比应达重度
        assert score["level"] == LEVEL_SEVERE, \
            f"应评级为severe，实际{score['level']}"

        call_count = {"passes": 0}

        async def mock_generate(prompt, system=None, **kwargs):
            call_count["passes"] += 1
            # 每遍返回略清理的文本
            return severe_text.replace("——", "，").replace("他感到", "他")

        mock_client = MagicMock()
        mock_client.generate = mock_generate

        result = asyncio.run(run_deslop_postprocess(severe_text, mock_client))

        # 重度应执行 3 遍 Pass
        assert len(result["passes_executed"]) == 3, \
            f"重度应执行3遍Pass，实际{len(result['passes_executed'])}"
        assert "Pass1 去泛化" in result["passes_executed"]
        assert "Pass2 去书面化" in result["passes_executed"]
        assert "Pass3 回自然感" in result["passes_executed"]

    def test_mild_ai_level_runs_one_pass(self):
        """E2E-11: 轻度 AI 味应只执行 1 遍 Pass。"""
        # 构造轻度 AI 味文本（仅少量 blocking）
        mild_text = "他走进房间——把书放下。" + "窗外下着雨，她抬头看了他一眼。" * 100

        async def mock_generate(prompt, system=None, **kwargs):
            return mild_text.replace("——", "，")

        mock_client = MagicMock()
        mock_client.generate = mock_generate

        result = asyncio.run(run_deslop_postprocess(mild_text, mock_client, force_run=True))

        # 轻度应执行 1 遍 Pass
        assert len(result["passes_executed"]) == 1, \
            f"轻度应执行1遍Pass，实际{len(result['passes_executed'])}"
        assert result["passes_executed"][0] == "Pass1 去泛化"

    def test_deslop_summary_format(self):
        """E2E-12: deslop 结果摘要应可读。"""
        from novel_agent.audit.deslop_postprocessor import get_deslop_summary

        result = {
            "skipped": False,
            "level": LEVEL_SEVERE,
            "passes_executed": ["Pass1 去泛化", "Pass2 去书面化", "Pass3 回自然感"],
            "rolled_back": False,
            "pre_check": {"blocking_count": 5, "advisory_count": 2},
            "post_check": {"blocking_count": 0, "advisory_count": 1},
        }
        summary = get_deslop_summary(result)
        assert "severe" in summary
        assert "Pass1" in summary
        assert "5→0" in summary
        assert "2→1" in summary
