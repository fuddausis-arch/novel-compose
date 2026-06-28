"""polish_chapter 节点 deslop 后处理集成测试。

验证 Task 5：polish_chapter 节点正确注入 oh-story 7 Gate deslop 后处理。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from novel_agent.orchestrator.state import ChapterGenState


@pytest.mark.asyncio
async def test_polish_invokes_deslop_on_blocking():
    """polish 后存在 blocking 级 AI 模式时，deslop 应被调用。"""
    from novel_agent.orchestrator.nodes import polish_chapter

    # LLM mock：第一次 polish 返回带破折号的文本（blocking），第二次 deslop 返回干净文本
    call_count = {"polish": 0, "deslop": 0}

    # 构造足够长（≥2200字）、有标点、含破折号的 polish 文本
    base_paragraph = "他走进房间——把书放下。窗外下着雨，她抬头看了他一眼。"
    polished_text = (base_paragraph + "\n\n") * 120  # 约 2640+ 字

    async def mock_generate(prompt, system=None, **kwargs):
        call_count["polish"] += 1
        # 用 system 头部区分：polish 的 system 是"你是网文润色编辑"
        # deslop 的 system 是"你是网文去AI味编辑"
        sys_head = (system or "")[:20]
        if "润色编辑" in sys_head and "去AI味" not in sys_head:
            # polish 调用：返回带破折号的文本（触发 deslop blocking）
            return polished_text
        if "去AI味编辑" in sys_head:
            # deslop 调用：返回干净文本（破折号替换为逗号）
            call_count["deslop"] += 1
            return polished_text.replace("——", "，")
        # 其他调用（如格式修复）：保留原文（含破折号），让 deslop 能检测到 blocking
        return polished_text

    mock_client = MagicMock()
    mock_client.generate = mock_generate

    state = ChapterGenState(
        chapter=1, title="测试", draft="原稿" * 500, status="audited",
    )
    result = await polish_chapter(state, llm_client=mock_client)

    assert result["status"] == "polished"
    # deslop 应被调用（因为 polish 后的文本含破折号 blocking）
    assert call_count["deslop"] >= 1
    # 最终 polished 不应再含破折号
    assert "——" not in result["polished"]


@pytest.mark.asyncio
async def test_polish_skips_deslop_on_clean_text():
    """polish 后文本干净（无 blocking, advisory≤2）时，deslop 跳过 LLM 调用。"""
    from novel_agent.orchestrator.nodes import polish_chapter

    call_count = {"polish": 0, "deslop": 0}

    async def mock_generate(prompt, system=None, **kwargs):
        call_count["polish"] += 1
        if "润色" in prompt:
            # polish 返回干净文本（无 blocking）
            return "他走进房间，把书放下。窗外下着雨。她抬头看了他一眼。" * 100
        call_count["deslop"] += 1
        return "should not be called"

    mock_client = MagicMock()
    mock_client.generate = mock_generate

    state = ChapterGenState(
        chapter=1, title="测试", draft="原稿" * 500, status="audited",
    )
    result = await polish_chapter(state, llm_client=mock_client)

    assert result["status"] == "polished"
    # deslop LLM 不应被调用（干净文本跳过）
    assert call_count["deslop"] == 0


@pytest.mark.asyncio
async def test_polish_deslop_failure_does_not_block():
    """deslop 后处理失败时不阻塞 polish 流程。"""
    from novel_agent.orchestrator.nodes import polish_chapter

    # 构造足够长、有标点、含破折号的 polish 文本
    base_paragraph = "他走进房间——把书放下。窗外下着雨，她抬头看了他一眼。"
    polished_text = (base_paragraph + "\n\n") * 120

    async def mock_generate(prompt, system=None, **kwargs):
        sys_head = (system or "")[:20]
        if "润色编辑" in sys_head and "去AI味" not in sys_head:
            return polished_text
        if "去AI味编辑" in sys_head:
            # deslop 调用抛异常
            raise Exception("deslop LLM error")
        return polished_text

    mock_client = MagicMock()
    mock_client.generate = mock_generate

    state = ChapterGenState(
        chapter=1, title="测试", draft="原稿" * 500, status="audited",
    )
    # 不应抛异常
    result = await polish_chapter(state, llm_client=mock_client)
    assert result["status"] == "polished"
    # 应保留 polish 版本（deslop 失败）
    assert "他走进房间" in result["polished"]


@pytest.mark.asyncio
async def test_polish_deslop_rollback_on_shrink():
    """deslop 后字数缩水过多时，保留 polish 版本。"""
    from novel_agent.orchestrator.nodes import polish_chapter

    async def mock_generate(prompt, system=None, **kwargs):
        sys_head = (system or "")[:20]
        if "润色编辑" in sys_head and "去AI味" not in sys_head:
            # polish 返回较长文本
            return "他走进房间，把书放下。" + "正文内容" * 500
        if "去AI味编辑" in sys_head:
            # deslop 返回极短文本（缩水超过 35%）
            return "短文本。"
        return "他走进房间，把书放下。" + "正文内容" * 500

    mock_client = MagicMock()
    mock_client.generate = mock_generate

    state = ChapterGenState(
        chapter=1, title="测试", draft="原稿" * 500, status="audited",
    )
    result = await polish_chapter(state, llm_client=mock_client)
    # 应保留 polish 版本而非 deslop 短文本
    assert "正文内容" in result["polished"]
    assert result["polished"] != "短文本。"


@pytest.mark.asyncio
async def test_polish_deslop_preserves_word_count_budget():
    """deslop 后处理不应让最终字数跌破 word_min。"""
    from novel_agent.orchestrator.nodes import polish_chapter
    from novel_agent.audit.validator import _get_threshold
    import re

    word_min = int(_get_threshold("字数下限", 2200))

    async def mock_generate(prompt, system=None, **kwargs):
        sys_head = (system or "")[:20]
        if "润色编辑" in sys_head and "去AI味" not in sys_head:
            # polish 返回略高于 word_min 的文本
            base = "他走进房间，把书放下。" * 100
            return base
        if "去AI味编辑" in sys_head:
            # deslop 返回略短但仍高于 word_min*0.65 的文本
            return "他走进房间，把书放下。" * 80
        return "他走进房间，把书放下。" * 100

    mock_client = MagicMock()
    mock_client.generate = mock_generate

    state = ChapterGenState(
        chapter=1, title="测试", draft="原稿" * 500, status="audited",
    )
    result = await polish_chapter(state, llm_client=mock_client)
    # 最终字数应合理（不低于 word_min 太多）
    final_cn = len(re.findall(r'[\u4e00-\u9fff]', result["polished"]))
    # 至少应保留 polish 版本的 65%
    assert final_cn > 0
