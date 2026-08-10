"""AI 味修复闭环（规则级确定性修复 + LLM 报告驱动重写 + 复检）。

规则级修复：零成本、保守、只做安全替换（不伤语义）；
LLM 级重写：用检测报告作输入，只改表达不改内容，逐段重写后复检；
复检闭环：修复后自动调用 ai_detect.run 对比前后分，达标（AI 率≤20%）放行。
"""
from __future__ import annotations

import re
from typing import Any

# ── 规则级安全替换表（只放绝对安全的；风险项一律留给 LLM 级）──
# 格式: (原串, 替换串)。'' 表示删除；删除后清理残留空格。
_RULE_REPLACEMENTS: list[tuple[str, str]] = [
    ("——", ""),                       # 破折号（典型 AI 符号）
    ("总而言之，", ""), ("总而言之", ""),
    ("综上所述，", ""), ("综上所述", ""),
    ("由此可见，", ""), ("由此可见", ""),
    ("毋庸置疑，", ""), ("毋庸置疑", ""),
    ("值得注意的是，", ""), ("值得注意的是", ""),
    ("与此同时，", ""), ("与此同时", ""),
    ("下意识地", ""), ("不自觉地", ""), ("不由自主地", ""),
    ("不禁", ""),                      # "他不禁笑了" → "他笑了"
]

# 词级命中可选的规则修复（由报告 word_hits 驱动，仅处理明确安全项）
# key: ai_detect 词级命中的 pattern（或其子串）
_WORD_RULE_FIX: dict[str, str] = {
    "总而言之": "",
    "综上所述": "",
    "由此可见": "",
    "毋庸置疑": "",
    "值得注意的是": "",
    "与此同时": "",
    "不禁": "",
    "下意识地": "",
    "不自觉地": "",
    "——": "",
}


def repair_rules(text: str) -> str:
    """规则级确定性修复（零成本，只做安全替换）。"""
    if not text:
        return text
    out = text
    for src, dst in _RULE_REPLACEMENTS:
        out = out.replace(src, dst)
    # 清理删除后可能产生的双空格/逗号粘连（中文通常无碍，仅清理英文空格）
    out = re.sub(r"\s{2,}", " ", out)
    return out


def repair_by_word_hits(text: str, word_hits: list[dict]) -> str:
    """按报告词级命中做安全替换（比全量表更精准，避免误伤不在报告里的词）。"""
    out = text
    for hit in word_hits:
        pattern = hit.get("pattern", "")
        repl = _WORD_RULE_FIX.get(pattern)
        if repl is not None:
            out = out.replace(pattern, repl)
    return out


def repair_and_recheck(text: str, use_word_hits: bool = True) -> dict:
    """规则级修复 + 复检，返回对比报告。

    Returns:
        {
            "repaired_text": 修复后文本,
            "before": {...ai_detect 报告},
            "after": {...ai_detect 报告},
            "score_delta": after.overall_score - before.overall_score,
            "passed": after.passed,
        }
    """
    from .ai_detect import run as ai_run

    before = ai_run(text)
    if use_word_hits and before.get("word_hits"):
        repaired = repair_by_word_hits(text, before["word_hits"])
    else:
        repaired = repair_rules(text)
    # 句子级命中里的总结词/连接词（"总而言之"等）不进 word_hits，
    # 用全量安全表兜底清理（表中均为绝对安全项，不影响语义）
    repaired = repair_rules(repaired)
    after = ai_run(repaired)
    return {
        "repaired_text": repaired,
        "before": before,
        "after": after,
        "score_delta": after["overall_score"] - before["overall_score"],
        "passed": after["passed"],
    }


# ── LLM 报告驱动重写 ────────────────────────────────────

_REPAIR_SYSTEM = """你是资深网文编辑，专长"去 AI 味但绝不伤内容"。你的任务：重写给定的文本片段，让它读起来像人类作者写的，同时严格保留原有情节、设定、信息与情感立场。

【必须做到的】
1. 长短句交替：用 15 字内短句砸点，再用 40 字以上长句展开。
2. 情感用动作和细节说，不用抽象概括（"他掐灭烟，没说话" > "他感到难过"）。
3. 删掉 AI 高频词与套路句（禁词：仿佛、不禁、总而言之、值得注意的是、不是…而是…、下意识地、淡淡地等）。
4. 段落长短不一，对话段短，叙述段长。
5. 保留口语、轻微重复、个人化的表达——这正是人味。
6. 紧张场景做减法：砍形容词、砍外貌堆砌，用短动作短对白。

【绝对禁止】
- 新增/删改情节、人物、设定、信息。
- 改变视角、语气立场。
- 逐句硬限（禁止"每句不得超过X字"这类规定，只允许整体节奏把握）。
- 输出任何解释，只输出重写后的文本。"""


def _build_repair_user(original: str, report: dict[str, Any]) -> str:
    """把检测报告里的高风险命中转成重写指令。"""
    lines: list[str] = []
    hits = report.get("word_hits", [])[:12]
    for h in hits:
        lines.append(f"- 词「{h.get('pattern')}」出现 {h.get('count', 1)} 次（{h.get('issue', '')}）")
    sent = report.get("sentence_hits", [])[:10]
    for s in sent:
        snippet = s.get("sentence", "")[:60]
        lines.append(f"- 句式问题句：{snippet}…（{s.get('issue', '')}）")
    para = report.get("paragraph_hits", [])[:5]
    for p in para:
        snippet = p.get("paragraph", "")[:50]
        lines.append(f"- 段落问题：{snippet}…（{p.get('issue', '')}）")
    stat = report.get("stat_hits", [])[:8]
    for s in stat:
        lines.append(f"- 统计信号：{s.get('snippet', '')}（{s.get('issue', '')}）")
    hit_text = "\n".join(lines) if lines else "（无明显命中，按人味总原则通读润色）"
    return (
        "以下是检测报告发现的问题：\n"
        f"{hit_text}\n\n"
        "请根据上述问题重写下面这段文本，只改表达方式，不改任何情节/设定/信息，"
        "保持篇幅大致相当（±20%）。\n\n"
        "【原文】\n"
        f"{original}"
    )


async def repair_llm(original: str, report: dict[str, Any], client: Any) -> str:
    """LLM 报告驱动重写（基础版：全章重写 + 内容锁定）。"""
    user = _build_repair_user(original, report)
    result = await client.generate(
        user,
        system=_REPAIR_SYSTEM,
        temperature=0.7,
    )
    return result.strip() if result else original


async def llm_repair_and_recheck(
    text: str, client: Any, report: dict[str, Any] | None = None,
) -> dict:
    """LLM 修复 + 复检闭环，最多 2 轮。"""
    from .ai_detect import run as ai_run

    before_report = report or ai_run(text)
    repaired = await repair_llm(text, before_report, client)
    after = ai_run(repaired)
    rounds = 1

    # 第二轮：仍未达标且第一轮有提升 → 再来一轮
    if not after["passed"] and after["overall_score"] > before_report["overall_score"]:
        second = await repair_llm(repaired, after, client)
        after = ai_run(second)
        repaired = second
        rounds = 2

    return {
        "repaired_text": repaired,
        "before": before_report,
        "after": after,
        "score_delta": after["overall_score"] - before_report["overall_score"],
        "passed": after["passed"],
        "rounds": rounds,
    }


async def stream_llm_repair_and_recheck(
    text: str, client: Any,
) -> Any:
    """流式 LLM 修复 + 复检闭环（SSE 事件源）。

    逐 token 流式重写（前端可实时显示 + 中断），完成后复检；
    最多 2 轮，每轮必须提升，达标（AI 率≤20%）提前放行。

    Yields（事件 dict，type 即 SSE event 名）:
        {"type": "round_start", "round": n}
        {"type": "chunk", "text": delta}          # 流式文本增量
        {"type": "round_done", "round": n, "after": {...报告}}
        {"type": "done", "before": {...}, "after": {...}, "score_delta": n,
         "passed": bool, "rounds": n, "repaired_text": str}
    """
    from .ai_detect import run as ai_run

    before = ai_run(text)
    current = text
    current_report = before
    rounds = 1
    for round_no in range(1, 3):
        yield {"type": "round_start", "round": round_no}
        user = _build_repair_user(current, current_report)
        parts: list[str] = []
        async for delta in client.stream_generate(
            user, system=_REPAIR_SYSTEM, temperature=0.7,
        ):
            parts.append(delta)
            yield {"type": "chunk", "text": delta}
        repaired = "".join(parts).strip() or current
        after = ai_run(repaired)
        yield {"type": "round_done", "round": round_no, "after": after}
        rounds = round_no
        current = repaired
        current_report = after
        # 达标或未提升 → 停止（避免死循环）
        if after["passed"] or after["overall_score"] <= before["overall_score"]:
            break
    yield {
        "type": "done",
        "before": before,
        "after": current_report,
        "score_delta": current_report["overall_score"] - before["overall_score"],
        "passed": current_report["passed"],
        "rounds": rounds,
        "repaired_text": current,
    }
