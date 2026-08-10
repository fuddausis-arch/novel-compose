"""AI 味检测引擎。

借鉴 bishu-novel ai_detect.py 的设计，但用确定性正则替代 humanize-chinese 引擎：
1. 句级分析：检测 AI 味句子（模板句/排比句/过度解释/标签化描写）
2. 词级分析：检测 AI 味词汇（"仿佛"/"宛如"/"不自觉地"/"嘴角微微"）
3. 段级分析：检测 AI 味段落结构（信息灌输/缺乏博弈/节奏单一）

与 novel_agent.audit.deslop_patterns 的区别：
- deslop_patterns 检测结构性问题（破折号/截断/复读/工程词泄漏），命中即 blocking
- ai_detect 检测"AI 味"风格问题（模糊词/模板句/标签化描写），给出评分和修复建议
- 两者互补：deslop 管"硬伤"，ai_detect 管"味道"

检测使用正则匹配（确定性），不调用 LLM（快速、可控）。
可作为 auditor 的补充工具，也可以独立调用。
"""
from __future__ import annotations

import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)


# ── 句子分割：中文句末标点 ──────────────────────────────────
_SENT_SPLIT_RE = re.compile(r"[。！？!?；;]")
# CJK 字符计数（用于段落长度判断）
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 引号字符（用于判断是否含对话）
_QUOTE_RE = re.compile(r"[「」『』""''\"']")


def _split_sentences(text: str) -> list[str]:
    """按中文句末标点分割句子，保留非空句子。"""
    parts = _SENT_SPLIT_RE.split(text)
    return [s.strip() for s in parts if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """按换行分割段落，保留非空段落。"""
    return [p.strip() for p in text.split("\n") if p.strip()]


def _cjk_len(text: str) -> int:
    """统计 CJK 字符数。"""
    return len(_CJK_RE.findall(text))


# ── AI_PATTERNS：预定义 AI 味模式（正则 + 修复建议）──────────
# 每个模式包含：
#   regex: 编译后的正则
#   level: "word" | "sentence"
#   issue: 问题描述
#   fix: 修复建议
#   penalty: 每次命中的扣分（overall_score 从 100 起扣）
AI_PATTERNS: dict[str, dict] = {
    # ── 词级：AI 味高频词 ──
    "仿佛": {
        "regex": re.compile(r"仿佛"),
        "level": "word",
        "issue": "滥用比喻词",
        "fix": "用具体动作或感官细节替代比喻",
        "penalty": 3,
    },
    "宛如": {
        "regex": re.compile(r"宛如"),
        "level": "word",
        "issue": "滥用比喻词",
        "fix": "用具体画面替代文言化比喻",
        "penalty": 3,
    },
    "犹如": {
        "regex": re.compile(r"犹如"),
        "level": "word",
        "issue": "滥用比喻词",
        "fix": "用直接描写替代比喻",
        "penalty": 3,
    },
    "不自觉地": {
        "regex": re.compile(r"不自觉地"),
        "level": "word",
        "issue": "AI 常用副词",
        "fix": "删除或改写为具体动作",
        "penalty": 4,
    },
    "下意识地": {
        "regex": re.compile(r"下意识地"),
        "level": "word",
        "issue": "AI 常用副词",
        "fix": "删除或改写为具体动作",
        "penalty": 4,
    },
    "嘴角微微": {
        "regex": re.compile(r"嘴角微微"),
        "level": "word",
        "issue": "标签化表情描写",
        "fix": "用具体表情动作替代（如'咧嘴'/'抿唇'）",
        "penalty": 4,
    },
    "微微一笑": {
        "regex": re.compile(r"微微一笑"),
        "level": "word",
        "issue": "标签化表情描写",
        "fix": "用具体笑容细节替代",
        "penalty": 4,
    },
    "不禁": {
        "regex": re.compile(r"不禁"),
        "level": "word",
        "issue": "AI 凑字副词",
        "fix": "删除，直接写动作",
        "penalty": 2,
    },
    "莫名地": {
        "regex": re.compile(r"莫名地"),
        "level": "word",
        "issue": "模糊化描写",
        "fix": "给出具体原因或用行动展示情绪",
        "penalty": 4,
    },
    "淡淡地": {
        "regex": re.compile(r"淡淡地"),
        "level": "word",
        "issue": "AI 模糊语气",
        "fix": "用具体语气/动作替代",
        "penalty": 3,
    },
    "深吸一口气": {
        "regex": re.compile(r"深吸[了一]?口气"),
        "level": "word",
        "issue": "AI 套路生理反应",
        "fix": "用更具体的身体反应替代",
        "penalty": 4,
    },
    "心跳如擂鼓": {
        "regex": re.compile(r"心跳如擂鼓"),
        "level": "word",
        "issue": "AI 套路比喻",
        "fix": "用具体的心跳感受替代",
        "penalty": 5,
    },
    "瞳孔一缩": {
        "regex": re.compile(r"瞳孔[一]?缩"),
        "level": "word",
        "issue": "AI 标签化反应",
        "fix": "用具体的眼神变化替代",
        "penalty": 5,
    },
    "后背发凉": {
        "regex": re.compile(r"后背发凉"),
        "level": "word",
        "issue": "AI 套路生理反应",
        "fix": "用具体的恐惧表现替代",
        "penalty": 4,
    },
    # ── 句级：AI 味句式 ──
    "不是X而是Y": {
        "regex": re.compile(r"不是[^，。；！？\n]{1,20}[，,]\s*而是[^，。；！？\n]{1,20}"),
        "level": "sentence",
        "issue": "否定翻转句式（最毒 AI 句式）",
        "fix": "直接陈述，去掉'不是…而是'的翻转结构",
        "penalty": 6,
    },
    "不仅X而且Y": {
        "regex": re.compile(r"不仅[^，。；！？\n]{1,20}[，,]?\s*(?:而且|更是|还)"),
        "level": "sentence",
        "issue": "递进套话",
        "fix": "拆成两个独立短句，去掉递进连接词",
        "penalty": 5,
    },
    "换句话说": {
        "regex": re.compile(r"换句话说"),
        "level": "sentence",
        "issue": "过度解释",
        "fix": "删除，前面已说清楚就不必重复",
        "penalty": 5,
    },
    "也就是说": {
        "regex": re.compile(r"也就是说"),
        "level": "sentence",
        "issue": "过度解释",
        "fix": "删除，避免啰嗦重复",
        "penalty": 5,
    },
    "仿佛X一般": {
        "regex": re.compile(r"仿佛[^，。；！？\n]{1,20}一般"),
        "level": "sentence",
        "issue": "滥用比喻句式",
        "fix": "去掉'仿佛…一般'，直接描写",
        "penalty": 4,
    },
    "如同X一样": {
        "regex": re.compile(r"如同[^，。；！？\n]{1,20}一样"),
        "level": "sentence",
        "issue": "滥用比喻句式",
        "fix": "去掉'如同…一样'，直接描写",
        "penalty": 4,
    },
    "一时间": {
        "regex": re.compile(r"一时间[，,]"),
        "level": "sentence",
        "issue": "AI 凑时间词",
        "fix": "删除或用具体时间节奏替代",
        "penalty": 3,
    },
    "刹那间": {
        "regex": re.compile(r"刹那间[，,]"),
        "level": "sentence",
        "issue": "AI 凑时间词",
        "fix": "删除或用具体动作节奏替代",
        "penalty": 3,
    },
    "与此同时": {
        "regex": re.compile(r"与此同时[，,]"),
        "level": "sentence",
        "issue": "AI 连接词",
        "fix": "用具体场景切换替代",
        "penalty": 3,
    },
    "总而言之": {
        "regex": re.compile(r"总而言之"),
        "level": "sentence",
        "issue": "AI 总结词",
        "fix": "删除，网文不需要总结",
        "penalty": 5,
    },
    "这是一个X的人": {
        "regex": re.compile(r"这是一个[^，。；！？\n]{1,15}的人"),
        "level": "sentence",
        "issue": "标签化人物描写",
        "fix": "用行动和对话展示性格，不要贴标签",
        "penalty": 5,
    },
}


# ── 段级检测阈值 ──
_INFO_DUMP_MIN_CHARS = 150  # 信息灌输：纯说明段落超过此字数
_UNIFORM_SENT_LEN_THRESHOLD = 0.15  # 节奏单一：句长变异系数低于此值
_NO_DIALOGUE_MIN_CHARS = 300  # 缺乏博弈：连续无对话文本超过此字数


def _detect_word_issues(text: str) -> list[dict]:
    """词级分析：检测 AI 味词汇。"""
    issues: list[dict] = []
    for name, pattern in AI_PATTERNS.items():
        if pattern["level"] != "word":
            continue
        matches = pattern["regex"].findall(text)
        if matches:
            issues.append({
                "word": name,
                "count": len(matches),
                "issue": pattern["issue"],
                "fix": pattern["fix"],
            })
    # 按出现次数降序
    issues.sort(key=lambda x: x["count"], reverse=True)
    return issues


def _detect_sentence_issues(text: str) -> list[dict]:
    """句级分析：检测 AI 味句子。"""
    issues: list[dict] = []
    sentences = _split_sentences(text)
    seen_sentences: set[str] = set()  # 去重：同一句被多个模式命中只记一次

    for sentence in sentences:
        for name, pattern in AI_PATTERNS.items():
            if pattern["level"] != "sentence":
                continue
            match = pattern["regex"].search(sentence)
            if match:
                # 截取匹配片段附近的上下文
                snippet = sentence[:80] if len(sentence) > 80 else sentence
                issue_key = f"{snippet}:{name}"
                if issue_key in seen_sentences:
                    continue
                seen_sentences.add(issue_key)
                issues.append({
                    "sentence": snippet,
                    "matched": match.group()[:50],
                    "issue": pattern["issue"],
                    "fix": pattern["fix"],
                })
    return issues


def _detect_paragraph_issues(text: str) -> list[dict]:
    """段级分析：检测 AI 味段落结构。

    三类问题：
    1. 信息灌输：纯说明长段落（无对话、无动作，超过阈值字数）
    2. 节奏单一：段落内句长过于均匀（变异系数过低）
    3. 缺乏博弈：连续大段文本无任何对话标记
    """
    issues: list[dict] = []
    paragraphs = _split_paragraphs(text)

    for i, para in enumerate(paragraphs):
        cn_len = _cjk_len(para)
        if cn_len < 20:
            continue  # 太短不分析

        # 1. 信息灌输：纯说明长段落（无引号 = 无对话）
        has_dialogue = bool(_QUOTE_RE.search(para))
        if not has_dialogue and cn_len > _INFO_DUMP_MIN_CHARS:
            issues.append({
                "paragraph": para[:80],
                "issue": "信息灌输",
                "fix": "拆短段落，插入对话或动作，避免纯说明堆砌",
            })

        # 2. 节奏单一：句长变异系数过低
        sent_lens = [_cjk_len(s) for s in _split_sentences(para) if _cjk_len(s) > 0]
        if len(sent_lens) >= 3:
            mean_len = sum(sent_lens) / len(sent_lens)
            if mean_len > 0:
                variance = sum((x - mean_len) ** 2 for x in sent_lens) / len(sent_lens)
                cv = (variance ** 0.5) / mean_len
                if cv < _UNIFORM_SENT_LEN_THRESHOLD:
                    issues.append({
                        "paragraph": para[:80],
                        "issue": "节奏单一",
                        "fix": "长短句交替，打破均匀节奏，增加短句冲击",
                    })

    # 3. 缺乏博弈：全文连续无对话
    no_dialogue_streak = 0
    for para in paragraphs:
        cn_len = _cjk_len(para)
        has_dialogue = bool(_QUOTE_RE.search(para))
        if has_dialogue:
            no_dialogue_streak = 0
        else:
            no_dialogue_streak += cn_len
        if no_dialogue_streak >= _NO_DIALOGUE_MIN_CHARS:
            issues.append({
                "paragraph": f"（连续{no_dialogue_streak}字无对话）",
                "issue": "缺乏博弈",
                "fix": "插入对话冲突或人物互动，避免长时间独白式叙述",
            })
            break  # 只报一次

    return issues


def _calc_overall_score(
    word_issues: list[dict],
    sentence_issues: list[dict],
    paragraph_issues: list[dict],
) -> int:
    """计算整体 AI 味评分。

    100 = 纯人类，0 = 纯 AI 味。
    从 100 起扣，每个问题按对应 penalty 扣分，最低 0。
    """
    score = 100

    # 词级：按 penalty * count 扣，但单词最多扣 penalty * 3（避免一个词刷爆分数）
    for issue in word_issues:
        name = issue["word"]
        pattern = AI_PATTERNS.get(name)
        if pattern:
            count = issue["count"]
            deduction = pattern["penalty"] * min(count, 3)
            score -= deduction

    # 句级：每个命中扣对应 penalty
    for issue in sentence_issues:
        # 反查 penalty：通过 issue 内容匹配模式
        for name, pattern in AI_PATTERNS.items():
            if pattern["level"] == "sentence" and pattern["issue"] == issue["issue"]:
                score -= pattern["penalty"]
                break

    # 段级：每个问题扣 6 分
    score -= len(paragraph_issues) * 6

    return max(0, score)


def _build_summary(
    word_issues: list[dict],
    sentence_issues: list[dict],
    paragraph_issues: list[dict],
    score: int,
) -> str:
    """生成检测摘要文本。"""
    parts: list[str] = []
    if word_issues:
        top_words = ", ".join(
            f"{w['word']}({w['count']}次)" for w in word_issues[:3]
        )
        parts.append(f"词级问题{len(word_issues)}类（{top_words}）")
    if sentence_issues:
        parts.append(f"句级问题{len(sentence_issues)}处")
    if paragraph_issues:
        parts.append(f"段级问题{len(paragraph_issues)}处")

    if not parts:
        return f"AI 味评分 {score}/100，未检测到明显 AI 味问题"

    level = "轻微" if score >= 70 else ("中等" if score >= 40 else "严重")
    return f"AI 味评分 {score}/100（{level}），" + "；".join(parts)


# ── 主接口 ─────────────────────────────────────────────────


def detect_ai_style(text: str) -> dict:
    """检测文本的 AI 味，返回结构化报告。

    Args:
        text: 待检测的正文文本

    Returns:
        {
            "sentence_issues": [{"sentence": "...", "issue": "...", "fix": "..."}],
            "word_issues": [{"word": "仿佛", "count": 3, "fix": "..."}],
            "paragraph_issues": [{"paragraph": "...", "issue": "...", "fix": "..."}],
            "overall_score": 0-100,  # 0=纯AI味, 100=纯人类
            "summary": "检测摘要"
        }
    """
    if not text or not text.strip():
        return {
            "sentence_issues": [],
            "word_issues": [],
            "paragraph_issues": [],
            "overall_score": 100,
            "summary": "文本为空，无法检测",
        }

    word_issues = _detect_word_issues(text)
    sentence_issues = _detect_sentence_issues(text)
    paragraph_issues = _detect_paragraph_issues(text)
    overall_score = _calc_overall_score(word_issues, sentence_issues, paragraph_issues)
    summary = _build_summary(word_issues, sentence_issues, paragraph_issues, overall_score)

    logger.debug(
        "detect_ai_style: score=%d, word=%d, sentence=%d, paragraph=%d",
        overall_score, len(word_issues), len(sentence_issues), len(paragraph_issues),
    )

    return {
        "sentence_issues": sentence_issues,
        "word_issues": word_issues,
        "paragraph_issues": paragraph_issues,
        "overall_score": overall_score,
        "summary": summary,
    }


# ── run()：工作流/脚本可调用的统一入口 ─────────────────────────

def _ai_level(score: int) -> str:
    """把 0-100 评分映射到可读的 AI 味等级。"""
    if score >= 90:
        return "自然"
    if score >= 70:
        return "轻度AI味"
    return "明显AI味"


def _collect_suggestions(
    word_issues: list[dict],
    sentence_issues: list[dict],
    paragraph_issues: list[dict],
) -> list[str]:
    """汇总所有修复建议，去重、去空，按出现频率排序。"""
    counter: Counter = Counter()
    for issue in word_issues:
        if issue.get("fix"):
            counter[issue["fix"]] += 1
    for issue in sentence_issues:
        if issue.get("fix"):
            counter[issue["fix"]] += 1
    for issue in paragraph_issues:
        if issue.get("fix"):
            counter[issue["fix"]] += 1
    # 频率高的修复建议排前面（说明问题越普遍、越该优先处理）
    return [fix for fix, _ in counter.most_common()]


def run(text: str, ignore_words: set[str] | None = None) -> dict:
    """AI 率检测统一入口（规则 + 统计 + 深度模型三层融合）。

    对正文做词/句/段三级 AI 味分析，返回结构化报告，供工作流脚本
    与外部调用方直接消费。深度模型（AIGC_detector_zhv3）就绪时占综合分
    50%；未就绪自动降级为规则+统计两层，不阻塞调用。

    Args:
        text: 待检测的正文文本
        ignore_words: 白名单词集合（如项目角色名/设定关键词），
            重复词统计时跳过，避免主角名反复出现被误报为 AI 味

    Returns:
        {
            "overall_score": 0-100,      # 越高越自然（100=纯人类）
            "ai_level": "自然"|"轻度AI味"|"明显AI味",
            "deep_available": bool,      # 深度模型是否参与评分
            "deep_ai_probability": 0-1,  # 深度模型 AI 概率（未就绪为 None）
            "deep_verdict": "AI"|"Mixed"|"Human"|"unavailable",
            "word_hits": [{"pattern":"仿佛","count":N,"level":"word","issue":"...","fix":"..."}],
            "sentence_hits": [{"sentence":"...","matched":"...","level":"sentence","issue":"...","fix":"..."}],
            "paragraph_hits": [{"paragraph":"...","level":"paragraph","issue":"...","fix":"..."}],
            "total_hits": N,             # 所有命中条数合计
            "suggestions": [...],        # 去重后的修复建议（按频率排序）
            "chars": N,                  # CJK 字符数
            "summary": "检测摘要"
        }
    """
    report = detect_ai_style(text)

    word_issues = report.get("word_issues", [])
    sentence_issues = report.get("sentence_issues", [])
    paragraph_issues = report.get("paragraph_issues", [])
    rule_score = report.get("overall_score", 100)

    # 统计层信号（零成本，与规则层互补）
    from .stat_signal import stat_signal_report
    stat = stat_signal_report(text, ignore_words=ignore_words)
    stat_score = stat["stat_score"]
    stat_hits = stat["hits"]

    # 深度层信号（AIGC_detector_zhv3 分类模型，判官级；模型未就绪时优雅降级）
    deep_available = False
    deep_ai_probability: float | None = None
    deep_verdict = "unavailable"
    deep_ai_level = "模型未就绪"
    try:
        from .roberta_signal import detect_deep
        deep = detect_deep(text)
        if deep.get("available"):
            deep_available = True
            deep_ai_probability = deep.get("ai_probability")
            deep_verdict = deep.get("verdict", "")
            deep_ai_level = deep.get("ai_level", "")
    except Exception:
        logger.warning("深度检测不可用，降级为规则+统计两层", exc_info=True)

    # 综合分：深度模型就绪时 规则30% + 统计20% + 深度50%（深度层为准绳）；
    # 未就绪时回退 规则60% + 统计40%（与旧行为一致）
    if deep_available and deep_ai_probability is not None:
        deep_human_score = (1.0 - deep_ai_probability) * 100.0
        score = int(round(rule_score * 0.3 + stat_score * 0.2 + deep_human_score * 0.5))
    else:
        score = int(round(rule_score * 0.6 + stat_score * 0.4))

    # 词级命中：直接透出 pattern/count/issue/fix，补 level 标记
    word_hits = [
        {
            "pattern": w["word"],
            "count": w.get("count", 1),
            "level": "word",
            "issue": w.get("issue", ""),
            "fix": w.get("fix", ""),
        }
        for w in word_issues
    ]
    # 句级命中
    sentence_hits = [
        {
            "sentence": s.get("sentence", ""),
            "matched": s.get("matched", ""),
            "level": "sentence",
            "issue": s.get("issue", ""),
            "fix": s.get("fix", ""),
        }
        for s in sentence_issues
    ]
    # 段级命中
    paragraph_hits = [
        {
            "paragraph": p.get("paragraph", ""),
            "level": "paragraph",
            "issue": p.get("issue", ""),
            "fix": p.get("fix", ""),
        }
        for p in paragraph_issues
    ]

    total_hits = (
        sum(w.get("count", 1) for w in word_issues)
        + len(sentence_issues)
        + len(paragraph_issues)
        + len(stat_hits)
    )

    # 达标线：从配置读取（默认 AI 率 ≤30%），保证与前端展示一致
    pass_line = 30
    try:
        from novel_agent.config import load_config
        pass_line = int(load_config().ai_pass_ai_rate)
    except Exception:
        pass

    ai_rate = 100 - score
    passed = ai_rate <= pass_line

    # 判定提示：分数落在达标线附近的"轻度AI味"多数是段落级误报，提示人工判断
    if passed:
        verdict_hint = "通过"
    elif score >= 100 - pass_line - 10:
        verdict_hint = (
            f"接近达标线（AI率 {ai_rate}% ≤ {pass_line}% 即通过），"
            f"可能是个别段落的风格误报，建议查看可疑段落后再判断"
        )
    else:
        verdict_hint = (
            f"AI率 {ai_rate}% 明显高于达标线 {pass_line}%，"
            f"建议对照可疑段落修改后再复检"
        )

    return {
        "overall_score": score,
        "rule_score": rule_score,          # 规则层分（0-100）
        "stat_score": stat_score,          # 统计层分（0-100）
        "deep_available": deep_available,  # 深度模型是否就绪
        "deep_ai_probability": deep_ai_probability,  # 深度模型 AI 概率（0-1）
        "deep_verdict": deep_verdict,      # AI / Mixed / Human / unavailable
        "deep_ai_level": deep_ai_level,
        "ai_rate": ai_rate,                # AI 率
        "pass_line": pass_line,            # 达标线（百分数）
        "passed": passed,                  # AI 率 ≤ 达标线 视为通过
        "verdict_hint": verdict_hint,      # 给作者看的判定提示（含人工判断建议）
        "dimensions": stat.get("dimensions", {}),
        "ai_level": _ai_level(score),
        "word_hits": word_hits,
        "sentence_hits": sentence_hits,
        "paragraph_hits": paragraph_hits,
        "stat_hits": stat_hits,
        "total_hits": total_hits,
        "suggestions": _collect_suggestions(word_issues, sentence_issues, paragraph_issues),
        "chars": _cjk_len(text),
        "summary": report.get("summary", ""),
    }
