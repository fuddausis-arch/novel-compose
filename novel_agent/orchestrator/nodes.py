"""编排节点函数：每个节点接收 state + 依赖，返回 state 更新。

节点设计为接受依赖注入（repo/llm_client/recall/applier/auditor），
便于测试 mock 和 runner 组装。

M3 扩展：写审分离 + 反馈循环节点（audit/polish/rewrite/summarize）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.memory.core import CoreMemoryAssembler
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, SummaryDelta, ForeshadowDelta

logger = logging.getLogger(__name__)

WRITER_SYSTEM_PROMPT = (
    "你是一位资深网络小说写手。根据给定的设定和上下文，"
    "创作引人入胜的网文章节正文。只输出正文，不要解释。"
)


def clean_chapter_text(text: str, chapter: int, title: str = "") -> str:
    """清理 LLM 生成的常见格式垃圾，返回纯净正文。"""
    if not text:
        return ""
    s = text
    # 去掉 markdown 章节标题行（# 第X章 ...）
    s = re.sub(r"^#+\s*第[\d一二三四五六七八九十百千万]+章[：:\s]*.*$", "", s, flags=re.MULTILINE)
    # 去掉 --- 分隔线
    s = re.sub(r"^\s*---+\s*$", "", s, flags=re.MULTILINE)
    # 去掉 markdown 加粗/斜体但保留文字
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<![*])\*([^*]+)\*(?![*])", r"\1", s)
    # 合并连续空行
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _looks_like_json_not_prose(text: str) -> bool:
    """检测 LLM 是否返回了 JSON 结构而非小说正文。"""
    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        return True
    if '"suggestions"' in s or '"payload"' in s:
        return True
    return False


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
        f"要求：只输出正文，目标 2000-3000 字。不要输出 JSON 或任何格式说明。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT)
        draft = clean_chapter_text(draft, state["chapter"], state.get("title", ""))
        if _looks_like_json_not_prose(draft):
            logger.warning("write_chapter 第%d章：LLM 返回 JSON 而非正文", state["chapter"])
            return {"status": "failed", "error": "LLM 返回了 JSON 而非正文，可能模型理解错误"}
        return {"draft": draft, "status": "drafted",
                "draft_version": state.get("draft_version", 0) + 1,
                "word_count": len(draft)}
    except Exception as e:
        logger.warning("write_chapter 第%d章失败：%s", state["chapter"], e)
        return {"status": "failed", "error": str(e)}


async def audit_chapter(state: ChapterGenState, auditor: Auditor,
                        repo: BibleRepository) -> dict:
    """节点：独立审校草稿，返回审计报告。写审分离铁律。"""
    report = await auditor.audit(
        chapter=state["chapter"], title=state.get("title", ""),
        draft=state["draft"], repo=repo,
    )
    iterations = state.get("review_iterations", 0) + 1
    return {
        "audit_report": report.model_dump(),
        "review_iterations": iterations,
        "status": "audited" if report.passed else "needs_rewrite",
    }


def route_after_audit(state: ChapterGenState) -> str:
    """条件边：审计达标→polish；不达标且未超3次→write 回环；超3次→end_failed。"""
    if state.get("status") == "failed":
        logger.warning("route_after_audit 进入 end_failed：status=%s", state.get("status"))
        return "end_failed"
    report = AuditReport(**state.get("audit_report", {}))
    if report.passed:
        return "polish"
    if state.get("review_iterations", 0) >= 3:
        logger.warning("route_after_audit 进入 end_failed：重写超3次")
        return "end_failed"
    return "rewrite"


async def rewrite_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：基于审计建议重写（第2轮起注入历史审阅痕迹）。"""
    report = AuditReport(**state.get("audit_report", {}))
    suggestions = "\n".join(f"- {s}" for s in report.suggestions) or "无具体建议"
    issues = "\n".join(f"- {i.dimension}({i.severity}): {i.message}" for i in report.issues) or "无"
    prompt = (
        f"重写第{state['chapter']}章《{state.get('title', '')}》。\n\n"
        f"【上下文】\n{state.get('context', '')}\n\n"
        f"【上一版草稿】\n{state.get('draft', '')}\n\n"
        f"【审计问题】\n{issues}\n\n"
        f"【修订建议】\n{suggestions}\n\n"
        f"要求：针对问题重写，只输出正文，不要输出 JSON 或任何格式说明。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT)
        draft = clean_chapter_text(draft, state["chapter"], state.get("title", ""))
        if _looks_like_json_not_prose(draft):
            logger.warning("rewrite_chapter 第%d章：LLM 返回 JSON 而非正文", state["chapter"])
            return {"status": "failed", "error": "LLM 返回了 JSON 而非正文，可能模型理解错误"}
        return {"draft": draft,
                "draft_version": state.get("draft_version", 1) + 1,
                "word_count": len(draft), "status": "drafted"}
    except Exception as e:
        logger.warning("rewrite_chapter 第%d章失败：%s", state["chapter"], e)
        return {"status": "failed", "error": str(e)}


async def polish_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：润色优化（文风统一 + AI 痕迹清除）。"""
    POLISH_SYSTEM = (
        "你是网文润色编辑。优化语言表达，清除 AI 痕迹词（忽然/竟然/不禁等限频），"
        "保持原意和情节，增强画面感。只输出润色后正文。"
    )
    prompt = f"润色以下章节正文：\n\n{state.get('draft', '')}"
    try:
        polished = await llm_client.generate(prompt, system=POLISH_SYSTEM)
        polished = clean_chapter_text(polished, state["chapter"], state.get("title", ""))
        return {"polished": polished, "status": "polished",
                "word_count": len(polished)}
    except Exception as e:
        # 润色失败不影响主流程，用原草稿
        draft = clean_chapter_text(state.get("draft", ""), state["chapter"], state.get("title", ""))
        return {"polished": draft, "status": "polished",
                "error": f"润色失败用原稿: {e}"}


def save_text_polished(state: ChapterGenState, recall: RecallMemory) -> dict:
    """节点：保存润色后正文到文件。"""
    content = state.get("polished") or state.get("draft", "")
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=content,
    )
    return {"status": "saved"}


async def summarize_chapter(state: ChapterGenState, llm_client: LLMClient,
                            applier: DeltaApplier,
                            repo: BibleRepository | None = None) -> dict:
    """节点：调 LLM 抽取摘要 + 检测伏笔回收，存入圣经。

    repo 提供时，查本章应回收伏笔让 LLM 判断是否已回收，
    回收的产出 resolve delta 更新伏笔状态。
    """
    content = state.get("polished") or state.get("draft", "")
    chapter = state["chapter"]

    to_resolve = repo.get_foreshadows_to_resolve(chapter) if repo else []
    fs_text = ""
    fs_instruction = ""
    if to_resolve:
        fs_text = "\n\n[本章应回收的伏笔]\n" + "\n".join(
            f"- {f.foreshadow_id}: {f.description}" for f in to_resolve)
        fs_instruction = ',"resolved_foreshadows":[]'

    prompt = (
        f"为以下章节抽取摘要，输出 JSON：\n"
        f'{{"core_events":"","characters_present":"","emotion_changes":"",'
        f'"foreshadow_dynamics":"","chapter_hook":""{fs_instruction}}}\n\n'
        f"{content}{fs_text}\n\n只输出 JSON。"
    )
    SUM_SYSTEM = "你是网文摘要助手。精炼抽取章节核心信息。只输出 JSON。"
    data = {}
    try:
        raw = await llm_client.generate(prompt, system=SUM_SYSTEM)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}

    delta = Delta(
        target="chapter_summary", action="create", chapter=chapter,
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(content)),
            core_events=data.get("core_events", content[:200]),
            characters_present=data.get("characters_present", ""),
            emotion_changes=data.get("emotion_changes", ""),
            foreshadow_dynamics=data.get("foreshadow_dynamics", ""),
            subplot_progress=data.get("subplot_progress", ""),
            chapter_hook=data.get("chapter_hook", ""),
        ),
    )
    result = applier.apply(delta)
    if not result.success:
        return {"status": "failed", "error": result.message}

    resolved_ids = data.get("resolved_foreshadows", []) or []
    for fid in resolved_ids:
        try:
            applier.apply(Delta(
                target="foreshadow", action="resolve", chapter=chapter,
                data=ForeshadowDelta(foreshadow_id=fid),
            ))
        except Exception:
            pass

    return {"status": "completed"}


# ---- M2 保留的兼容节点（旧 graph 测试仍用） ----

def save_text(state: ChapterGenState, recall: RecallMemory) -> dict:
    """M2 兼容：把正文存到文件（不区分 polished）。"""
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=state["draft"],
    )
    return {"status": "saved"}


def save_summary(state: ChapterGenState, applier: DeltaApplier) -> dict:
    """M2 兼容：简化摘要（用 draft 前 200 字）。"""
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
