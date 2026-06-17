"""编排节点函数：每个节点接收 state + 依赖，返回 state 更新。

节点设计为接受依赖注入（repo/llm_client/recall/applier），
便于测试 mock 和 runner 组装。
"""
from __future__ import annotations

from typing import Any

from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.memory.core import CoreMemoryAssembler
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, SummaryDelta

WRITER_SYSTEM_PROMPT = (
    "你是一位资深网络小说写手。根据给定的设定和上下文，"
    "创作引人入胜的网文章节正文。只输出正文，不要解释。"
)


def assemble_context(state: ChapterGenState, repo: BibleRepository,
                     archival: Any | None = None) -> dict:
    """节点 1：装配章节上下文（core memory + 可选 archival 检索）。"""
    assembler = CoreMemoryAssembler(repo, archival=archival)
    query = f"第{state['chapter']}章 {state.get('title', '')} 的相关前文"
    context = assembler.assemble(chapter=state["chapter"], query=query)
    return {"context": context, "status": "assembled"}


async def write_chapter(state: ChapterGenState,
                        llm_client: LLMClient) -> dict:
    """节点 2：调 LLM 生成章节正文。"""
    prompt = (
        f"请写第{state['chapter']}章《{state.get('title', '')}》。\n\n"
        f"【上下文】\n{state.get('context', '')}\n\n"
        f"要求：只输出正文，目标 2000-3000 字。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT)
        return {"draft": draft, "status": "drafted",
                "word_count": len(draft)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def save_text(state: ChapterGenState, recall: RecallMemory) -> dict:
    """节点 3：把正文存到文件。"""
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=state["draft"],
    )
    return {"status": "saved"}


def save_summary(state: ChapterGenState, applier: DeltaApplier) -> dict:
    """节点 4：抽取摘要并存入圣经（M2 简化：用 draft 前 200 字作摘要）。"""
    draft = state.get("draft", "")
    summary_text = draft[:200] if draft else ""
    delta = Delta(
        target="chapter_summary", action="create", chapter=state["chapter"],
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(draft)),
            core_events=summary_text,
            characters_present="",
        ),
    )
    result = applier.apply(delta)
    if not result.success:
        return {"status": "failed", "error": result.message}
    return {"status": "completed"}
