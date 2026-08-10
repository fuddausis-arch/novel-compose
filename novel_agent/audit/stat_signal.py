"""AI 味检测 · 统计层信号（纯 Python，零 LLM 调用）。

对齐主流检测器（朱雀 / GPTZero / Turnitin）的统计信号，全部确定性计算：
- burstiness:        句长突发性（全文级变异系数 + 滑窗节奏均匀度）
- adj_density:       常见 AI 描写形容词密度
- dash_density:      破折号密度
- connector_density: AI 高频连接词密度
- para_cv:           段落长短分布均匀度
- repetition:        高频重复词密度
- dialog_ratio:      对话占比

每个信号返回 score(0-100，越高越像人) + hits(定位) + suggestion。
与 novel_agent.audit.ai_detect 的规则命中互补：规则管"命中模式"，统计管"整体分布"。
"""
from __future__ import annotations

import re
from collections import Counter

# ── 基础工具（与 ai_detect 独立实现，避免循环导入）────────────

_SENT_SPLIT_RE = re.compile(r"[。！？!?；;]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_QUOTE_RE = re.compile(r"[「」『』“”\"']")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


def _cjk_len(text: str) -> int:
    return len(_CJK_RE.findall(text))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cv(xs: list[float]) -> float:
    """变异系数 = 标准差/均值（衡量波动）。"""
    if len(xs) < 3:
        return 0.0
    m = _mean(xs)
    if m <= 0:
        return 0.0
    variance = sum((x - m) ** 2 for x in xs) / len(xs)
    return (variance ** 0.5) / m


def _score_from_cv(cv: float, good: float = 0.55, bad: float = 0.25) -> int:
    """把变异系数映射到 0-100 分（越高越像人）。cv >= good → 100，<= bad → 0，中间线性。"""
    if cv >= good:
        return 100
    if cv <= bad:
        return 0
    return int(round((cv - bad) / (good - bad) * 100))


# ── 信号词表 ─────────────────────────────────────────────

# 常见 AI 描写形容词/副词（模糊化、标签化描写高频词）
_AI_ADJ_WORDS: list[str] = [
    "冷峻", "深邃", "清冷", "凌厉", "柔和", "疲惫", "坚定", "复杂", "微妙",
    "莫名", "淡淡", "微微", "缓缓", "轻轻", "深深", "静静", "隐隐", "隐隐约约",
    "若有所思", "深邃如", "波澜不惊", "嘴角勾起", "眼底闪过", "眸中", "瞳孔中",
    "空气仿佛凝固", "气氛瞬间", "时间仿佛", "空间仿佛", "仿佛置身", "仿佛看到",
]

# AI 高频连接词/套路词
_AI_CONNECTORS: list[str] = [
    "总而言之", "综上所述", "换言之", "由此可见", "值得注意的是", "显而易见",
    "与此同时", "另一方面", "首先", "其次", "最后", "不仅如此", "更为重要的是",
    "不得不说", "不得不承认", "事实上", "实际上", "显然", "无疑", "然而",
    "不禁", "不由", "下意识", "不自觉地", "仿佛", "宛如", "犹如", "刹那间",
    "一时间", "突然", "瞬间", "这一刻", "那一刻",
]

# 常见单字/短词停用（重复词统计时排除）
_STOP_WORDS = {"的", "了", "是", "在", "和", "他", "她", "它", "我", "你",
               "也", "就", "都", "而", "及", "与", "这", "那", "把", "被",
               "有", "又", "着", "过", "不", "上", "下", "个", "人"}


def _ai_adj_count(text: str) -> int:
    return sum(text.count(w) for w in _AI_ADJ_WORDS)


def _ai_connector_count(text: str) -> int:
    return sum(text.count(w) for w in _AI_CONNECTORS)


# ── 各信号实现 ──────────────────────────────────────────

def signal_burstiness(text: str) -> dict:
    """句长突发性：全文句长变异系数 + 相邻句长差（局部节奏）。

    AI 文本句长均匀（CV 低、相邻句几乎等长）；人类长短交替。
    """
    sent_lens = [_cjk_len(s) for s in _split_sentences(text) if _cjk_len(s) > 0]
    if len(sent_lens) < 4:
        return {"score": 100, "hits": [], "suggestion": "句子太少，无法评估节奏"}
    cv = _cv(sent_lens)
    # 相邻句长差：人类相邻句差异大
    diffs = [abs(sent_lens[i] - sent_lens[i + 1]) for i in range(len(sent_lens) - 1)]
    adj_diff = _mean(diffs)
    score = _score_from_cv(cv)
    # 相邻句几乎等长（差 < 5 字）占比过高 → 叠加扣分
    flat_ratio = sum(1 for d in diffs if d < 5) / len(diffs)
    if flat_ratio > 0.5:
        score = max(0, score - 20)
    hits: list[dict] = []
    if score < 60:
        # 定位一个节奏最均匀的滑窗（连续 5 句 CV 最低）
        best_i, best_cv = 0, 1.0
        for i in range(len(sent_lens) - 4):
            w = sent_lens[i:i + 5]
            c = _cv(w)
            if c < best_cv:
                best_cv, best_i = c, i
        sentences = [s for s in _split_sentences(text) if _cjk_len(s) > 0]
        hits.append({
            "snippet": "".join(sentences[best_i:best_i + 5])[:120],
            "issue": "句长节奏过于均匀（AI 节拍器感）",
            "fix": "长短句交替：加入 15 字内短句冲击，再用 40 字长句展开",
        })
    return {
        "score": score,
        "hits": hits,
        "suggestion": "句长忽长忽短（短句砸下接长句）是降低 AI 味最有效的手段之一",
    }


def signal_adj_density(text: str) -> dict:
    """AI 描写形容词密度：千字命中数。"""
    cn = _cjk_len(text)
    if cn < 50:
        return {"score": 100, "hits": [], "suggestion": "文本过短，跳过"}
    cnt = _ai_adj_count(text)
    density = cnt / cn * 1000
    if density <= 2:
        score = 100
    elif density >= 8:
        score = 30
    else:
        score = int(round(100 - (density - 2) / 6 * 70))
    hits: list[dict] = []
    if score < 60:
        for w in _AI_ADJ_WORDS:
            n = text.count(w)
            if n:
                hits.append({
                    "snippet": w,
                    "issue": f"AI 描写词「{w}」出现 {n} 次",
                    "fix": "用具体动作/感官细节替代模糊形容词",
                })
                if len(hits) >= 5:
                    break
    return {
        "score": score,
        "hits": hits,
        "suggestion": "一句话形容词超 3 个基本可判 AI 文；用动作和细节代替形容词",
    }


def signal_dash_density(text: str) -> dict:
    """破折号密度：千字命中数。

    注意：中文破折号是「——」（两个 U+2014），count("——") 即完整破折号个数，
    不要叠加 count("—")，否则每个破折号会被数 3 次（双计数）。
    """
    cn = _cjk_len(text)
    if cn < 50:
        return {"score": 100, "hits": [], "suggestion": "文本过短，跳过"}
    cnt = text.count("——")
    density = cnt / cn * 1000
    if density <= 1:
        score = 100
    elif density >= 6:
        score = 20
    else:
        score = int(round(100 - (density - 1) / 5 * 80))
    hits: list[dict] = []
    if score < 60:
        hits.append({
            "snippet": f"全文破折号 {cnt} 个（{density:.1f}/千字）",
            "issue": "破折号过度使用是典型 AI 符号",
            "fix": "删掉不必要的破折号，用逗号、句号或直接切断代替",
        })
    return {"score": score, "hits": hits, "suggestion": "破折号只在真正插入说明时用，通常 1 章 ≤2 个"}


def signal_connector_density(text: str) -> dict:
    """AI 高频连接词密度。"""
    cn = _cjk_len(text)
    if cn < 100:
        return {"score": 100, "hits": [], "suggestion": "文本过短，跳过"}
    cnt = _ai_connector_count(text)
    density = cnt / cn * 1000
    if density <= 4:
        score = 100
    elif density >= 15:
        score = 20
    else:
        score = int(round(100 - (density - 4) / 11 * 80))
    hits: list[dict] = []
    if score < 60:
        for w in ["总而言之", "综上所述", "由此可见", "此外", "与此同时", "不得不", "不禁", "仿佛"]:
            n = text.count(w)
            if n:
                hits.append({
                    "snippet": w,
                    "issue": f"AI 连接/套路词「{w}」{n} 次",
                    "fix": "删除或改为口语化表达",
                })
                if len(hits) >= 6:
                    break
    return {"score": score, "hits": hits, "suggestion": "人类写作连接词密度低，且常用口语连接（可、其实、但）"}


def signal_para_cv(text: str) -> dict:
    """段落长短分布：过均匀 → AI 味。"""
    paras = [_cjk_len(p) for p in _split_paragraphs(text) if _cjk_len(p) > 0]
    if len(paras) < 4:
        return {"score": 100, "hits": [], "suggestion": "段落太少，跳过"}
    cv = _cv(paras)
    score = _score_from_cv(cv, good=0.65, bad=0.3)
    hits: list[dict] = []
    if score < 60:
        hits.append({
            "snippet": f"段落长度变异系数 {cv:.2f}（过均匀）",
            "issue": "段落长短过于整齐（AI 习惯每段相近长度）",
            "fix": "对话段 1-2 行，场景段 4-6 行，长短交替",
        })
    return {"score": score, "hits": hits, "suggestion": "人类段落长短不一，对话/动作段短，叙述段长"}


# 说话者位置的人名：出现在「说/道/问」等动词前的 2-3 字词视为人名（角色名反复出现是
# 小说的正常现象，不是 AI 味）。repetition 信号统计高频词时跳过这些人名，避免把主角
# 名当"复读词"误报。
_SPEAKER_NAME_RE = re.compile(r"([\u4e00-\u9fff]{2,3})(?=[说问道答喊骂叹笑怒惊])")


def _collect_speaker_names(text: str) -> set[str]:
    return set(_SPEAKER_NAME_RE.findall(text))


def signal_repetition(text: str, ignore_words: set[str] | None = None) -> dict:
    """高频重复词：千字密度（跳过说话者人名与调用方白名单词）。

    小说里主角/配角名天然高频，若把「苏城」出现 22 次报为 AI 味就是误判；
    这里的重复只针对"非人名"的词（如「三千年」这类设定词复读）。
    """
    cn = _cjk_len(text)
    if cn < 200:
        return {"score": 100, "hits": [], "suggestion": "文本过短，跳过"}
    speaker_names = _collect_speaker_names(text)
    skip = set(ignore_words or set()) | speaker_names
    words = re.findall(r"[\u4e00-\u9fff]{2}", text)  # 2 字词片段近似
    counter = Counter(
        w for w in words
        if w not in _STOP_WORDS
        and w not in skip
        and not all(c in _STOP_WORDS for c in w)
    )
    hits: list[dict] = []
    score = 100
    for w, n in counter.most_common(8):
        if n < 3:
            break
        density = n / cn * 1000
        if density >= 2.5:  # 每千字 2.5 次以上
            score = max(0, score - 10)
            hits.append({
                "snippet": w,
                "issue": f"「{w}」重复 {n} 次（{density:.1f}/千字）",
                "fix": f"换同义表达，避免反复使用「{w}」",
            })
    return {"score": score, "hits": hits, "suggestion": "同一词频繁出现是 AI 的复读习惯（如'三千年'出现 18 次）"}


def signal_dialog_ratio(text: str) -> dict:
    """对话占比：引号内字数 / 总字数。过低 → 无博弈。"""
    cn = _cjk_len(text)
    if cn < 200:
        return {"score": 100, "hits": [], "suggestion": "文本过短，跳过"}
    quoted = sum(len(_CJK_RE.findall(seg)) for seg in _QUOTE_RE.split(text)[1::2])
    ratio = quoted / cn if cn else 0
    if ratio >= 0.15:
        score = 100
    elif ratio <= 0.03:
        score = 25
    else:
        score = int(round(100 - (0.15 - ratio) / 0.12 * 75))
    hits: list[dict] = []
    if score < 60:
        hits.append({
            "snippet": f"对话占比 {ratio:.0%}（偏低）",
            "issue": "长时间无对话，叙事缺少人物博弈",
            "fix": "插入对话冲突或人物互动，用台词推进信息与情绪",
        })
    return {"score": score, "hits": hits, "suggestion": "对话是网文的灵魂；纯叙述段建议对话占比 15% 以上"}


# ── 聚合入口 ─────────────────────────────────────────────

_SIGNAL_FUNCS = {
    "burstiness": signal_burstiness,
    "adj_density": signal_adj_density,
    "dash_density": signal_dash_density,
    "connector_density": signal_connector_density,
    "para_cv": signal_para_cv,
    "repetition": signal_repetition,
    "dialog_ratio": signal_dialog_ratio,
}


def stat_signal_report(text: str, ignore_words: set[str] | None = None) -> dict:
    """统计层检测入口。

    Args:
        text: 待检测文本
        ignore_words: 白名单词集合（如项目角色名/设定词），重复统计时跳过

    Returns:
        {
            "dimensions": {信号名: score 0-100},
            "stat_score": 0-100（各信号加权，越高越像人）,
            "hits": [{"snippet", "issue", "fix"}, ...]（去重合并）
        }
    """
    if not text or not text.strip():
        return {"dimensions": {}, "stat_score": 100, "hits": []}

    dims: dict[str, int] = {}
    hits: list[dict] = []
    for name, fn in _SIGNAL_FUNCS.items():
        if name == "repetition":
            res = fn(text, ignore_words)
        else:
            res = fn(text)
        dims[name] = res["score"]
        hits.extend(res["hits"])

    # 综合分：核心信号加权（burstiness 权重最高——主流检测器第一信号）
    weights = {
        "burstiness": 0.30, "adj_density": 0.15, "dash_density": 0.10,
        "connector_density": 0.15, "para_cv": 0.10, "repetition": 0.10,
        "dialog_ratio": 0.10,
    }
    total = sum(w * dims.get(name, 100) for name, w in weights.items())
    stat_score = int(round(total))

    # 去重 hits（按 snippet 去重）
    seen: set[str] = set()
    unique_hits: list[dict] = []
    for h in hits:
        key = h["snippet"]
        if key in seen:
            continue
        seen.add(key)
        unique_hits.append(h)

    return {"dimensions": dims, "stat_score": stat_score, "hits": unique_hits}
