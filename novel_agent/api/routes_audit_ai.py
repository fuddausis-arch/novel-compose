"""AI 味检测与去味闭环 API（P0）。

对应计划书《AI味检测与去味闭环计划书-20260810》的 6 个接口中的核心 4 个：
- POST /ai-style/check          检测文本 AI 率（规则层 60% + 统计层 40%）
- POST /ai-style/repair-rule    规则级确定性修复 + 复检（零成本，不调 LLM）
- POST /ai-style/repair         LLM 报告驱动重写 + 复检闭环（最多 2 轮，达标放行）
- POST /ai-style/check-chapter  按章节号读取正文并检测（配合前端"选章节→看报告"）

达标线：AI 率 ≤20%（80% 人工率），由 ai_detect.run 的 passed 字段判定。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from novel_agent.audit.ai_detect import run as ai_detect_run
from novel_agent.config import load_config

logger = logging.getLogger(__name__)
router = APIRouter()


class CheckRequest(BaseModel):
    text: str
    project_id: int | None = None  # 可选：用于自动加载角色名白名单（避免主角名被误报）


class RepairRuleRequest(BaseModel):
    text: str
    project_id: int | None = None


class RepairRequest(BaseModel):
    text: str
    project_id: int | None = None


class CheckChapterRequest(BaseModel):
    project_id: int
    chapter: int


def _role_ignore_words(project_id: int | None) -> set[str] | None:
    """从项目角色库加载角色名 + 用户标记的误判白名单。

    角色名高频出现≠AI 味；用户手动标记"误判"的词也要跳过。
    """
    words: set[str] = set()
    if project_id:
        try:
            from novel_agent.bible.models import Character
            from novel_agent.bible.database import SessionLocal, set_config
            from novel_agent.config import load_config
            cfg = load_config()
            set_config(cfg)
            session = SessionLocal()
            try:
                names = {
                    c.name for c in session.query(Character)
                    .filter(Character.project_id == project_id).all()
                }
            finally:
                session.close()
            words |= {n for n in names if n and 1 <= len(n) <= 4}
        except Exception:
            pass
        # 用户手动标记的误判词
        words |= _load_ignore_words(project_id)
    return words or None


# ── 误判白名单持久化（project_data/ai_ignore_words.json）──
_IGNORE_FILE = "ai_ignore_words.json"
_ignore_lock = __import__("threading").Lock()


def _ignore_words_path() -> str:
    return str(load_config().project_data_dir / _IGNORE_FILE)


def _load_ignore_words(project_id: int) -> set[str]:
    """读取某项目的误判白名单词。"""
    import json as _json
    import os
    path = _ignore_words_path()
    try:
        if not os.path.exists(path):
            return set()
        with open(path, encoding="utf-8") as f:
            data = _json.load(f)
        return set(data.get(str(project_id), {}).keys())
    except Exception:
        return set()


class IgnoreWordRequest(BaseModel):
    project_id: int
    word: str
    reason: str = ""


@router.get("/ai-style/ignore-words")
def list_ignore_words(project_id: int):
    """列出某项目已标记为误判的词。"""
    import json as _json
    import os
    path = _ignore_words_path()
    try:
        if not os.path.exists(path):
            return {"words": {}}
        with open(path, encoding="utf-8") as f:
            data = _json.load(f)
        return {"words": data.get(str(project_id), {})}
    except Exception:
        return {"words": {}}


@router.post("/ai-style/ignore-words")
def add_ignore_word(req: IgnoreWordRequest):
    """把某个命中词标记为误判（加入项目白名单，后续检测不再报）。"""
    word = (req.word or "").strip()
    if not word:
        raise HTTPException(400, "词不能为空")
    import json as _json
    import os
    path = _ignore_words_path()
    data: dict = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            data = {}
    project_map = data.setdefault(str(req.project_id), {})
    project_map[word] = req.reason or ""
    with _ignore_lock:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    return {"added": True, "word": word}


@router.delete("/ai-style/ignore-words/{project_id}/{word}")
def remove_ignore_word(project_id: int, word: str):
    """撤销误判标记。"""
    import json as _json
    import os
    path = _ignore_words_path()
    removed = False
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = _json.load(f)
            project_map = data.get(str(project_id), {})
            if word in project_map:
                del project_map[word]
                removed = True
            with _ignore_lock:
                with open(path, "w", encoding="utf-8") as f:
                    _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    if not removed:
        raise HTTPException(404, "白名单词不存在")
    return {"removed": True, "word": word}


@router.post("/ai-style/check")
def check_ai_style(req: CheckRequest):
    """检测一段文本的 AI 率，返回结构化报告（词/句/段/统计四类命中）。

    传入 project_id 时自动加载该项目的角色名作为白名单，
    避免主角名反复出现被误报为"重复词"。
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "文本为空")
    if len(text) < 30:
        raise HTTPException(400, "文本过短（<30 字），无法有效检测")
    ignore = _role_ignore_words(req.project_id)
    return ai_detect_run(text, ignore_words=ignore)


@router.post("/ai-style/check-deep")
def check_ai_style_deep(req: CheckRequest):
    """深度检测：roberta 中文模型判别 AI 概率（最准，CPU 推理较慢）。

    与 /ai-style/check 的关系：
    - check       规则 + 统计信号（秒级，抓显式 AI 味词）
    - check-deep  专门训练的分类模型（更准，但需下载模型、推理较慢）
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "文本为空")
    if len(text) < 30:
        raise HTTPException(400, "文本过短（<30 字），无法有效检测")
    from novel_agent.audit.roberta_signal import detect_deep
    return detect_deep(text)


@router.post("/ai-style/repair-rule")
def repair_rule(req: RepairRuleRequest):
    """规则级确定性修复 + 复检（零 LLM 调用）。"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "文本为空")
    from novel_agent.audit.ai_repair import repair_and_recheck
    result = repair_and_recheck(text, use_word_hits=True)
    return {
        "repaired_text": result["repaired_text"],
        "before": result["before"],
        "after": result["after"],
        "score_delta": result["score_delta"],
        "passed": result["passed"],
        "method": "rule",
    }


@router.post("/ai-style/repair")
async def repair_llm(req: RepairRequest):
    """LLM 报告驱动重写 + 复检闭环（SSE 流式，最多 2 轮，达标放行）。

    事件：round_start / chunk（文本增量）/ round_done / done / error。
    前端 fetch + ReadableStream 消费，可中断（断开即停止生成）。
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "文本为空")
    cfg = load_config()
    if not cfg.llm.api_key:
        raise HTTPException(400, "未配置 LLM API Key，无法使用 LLM 修复（可用 /ai-style/repair-rule）")
    from novel_agent.llm.client import LLMClient
    from novel_agent.audit.ai_repair import stream_llm_repair_and_recheck
    client = LLMClient(cfg.get_agent_llm("auditor"))

    async def event_gen():
        try:
            async for ev in stream_llm_repair_and_recheck(text, client):
                yield {
                    "event": ev["type"],
                    "data": json.dumps(
                        {k: v for k, v in ev.items() if k != "type"},
                        ensure_ascii=False,
                    ),
                }
        except Exception as e:  # noqa: BLE001 - 流式中断/超时统一转为 error 事件
            logger.warning("ai-style/repair 流式失败: %s", e)
            yield {
                "event": "error",
                "data": json.dumps({"message": f"润色失败：{e}"}, ensure_ascii=False),
            }

    return EventSourceResponse(event_gen())


@router.post("/ai-style/check-chapter")
def check_chapter(req: CheckChapterRequest):
    """按章节号读取正文并检测（配合前端'选章节→看报告'）。

    自动加载该项目角色名作为白名单，主角名不误报。
    """
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=req.project_id)
    text = recall.read_chapter_text(req.chapter)
    text = (text or "").strip()
    if not text:
        raise HTTPException(404, f"章节 {req.chapter} 无正文")
    ignore = _role_ignore_words(req.project_id)
    return ai_detect_run(text, ignore_words=ignore)
