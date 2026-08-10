"""确定性 AI 模式检测器。

移植 oh-story-claudecode 的 check-ai-patterns.js + check-degeneration.js。
只检测不改写，由 LLM 在 rewrite/polish 时根据报告修改。

检测项（11 类）：
- not-is-comparison：否定铺垫后肯定翻转（最毒 AI 句式，blocking）
- em-dash：破折号 ——/—/--（blocking）
- period-stutter：句号结巴（连续短句，advisory）
- long-paragraph：长段落 >200 字（advisory）
- adjacent-repetition：紧邻整行复读（blocking）
- long-sentence-repetition：长句复读 ≥3 次（blocking）
- truncation：末字不在终止标点集（blocking）
- ai-self-reference：作为 AI/人工智能（soft，对话行豁免）
- generation-refusal：我无法继续/生成（soft，对话行豁免）
- engineering-word-leakage：细纲/情节点/他不知道的是等工程词与全知剧透（tier1 blocking/tier2 advisory）
- placeholder-leakage：TODO/占位符/未完待续（blocking）

严重度分级：
- blocking：命中即必须重写
- advisory：只提示不阻塞
- soft：对话行豁免（系统流题材 AI 角色台词合法）

辅助算法：
- _strip_quoted：去掉引号内片段（弹幕刷屏/复沓台词是体裁手法，不判复读）
- _visible_length：只数 CJK + 字母数字，不数标点空格
- _is_dialogue_line：判定是否为对话行（含任何引号字符）
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 严重度分级
SEVERITY_BLOCKING = "blocking"  # 命中即必须重写
SEVERITY_ADVISORY = "advisory"  # 只提示不阻塞
SEVERITY_SOFT = "soft"  # 对话行豁免

# 引号字符集（用于对话行判定）—— 含中英文引号
_QUOTE_CHARS = set('""\'\'「」『』【】“”‘’')


def _is_dialogue_line(line: str) -> bool:
    """判定是否为对话行（含任何引号字符）。"""
    return any(c in _QUOTE_CHARS for c in line)


def _visible_length(text: str) -> int:
    """可见长度：只数 CJK + 字母数字，不数标点空格。

    避免"！！！"被算成长句。
    """
    return len(re.findall(r'[\u4e00-\u9fff a-zA-Z0-9]', text))


def _strip_quoted(text: str) -> str:
    """去掉引号内片段（弹幕刷屏/复沓台词是体裁手法，不判复读）。

    去掉 「」『』【】""''""'' 成对引号内内容。
    """
    patterns = [
        r'「[^」]*」',
        r'『[^』]*』',
        r'【[^】]*】',
        r'"[^"]*"',
        r"'[^']*'",
        r'\u201c[^\u201d]*\u201d',  # 中文双引号 ""
        r'\u2018[^\u2019]*\u2019',  # 中文单引号 ''
    ]
    result = text
    for pat in patterns:
        result = re.sub(pat, '', result)
    return result


# ── 1. not-is-comparison（最毒 AI 句式）──

# 匹配模式：
# - "不是X，而是Y" / "并非X，而是Y" / "不仅X，更是Y" / "不只X，更是Y"
# - 紧凑写法 "不是X而是Y"（无逗号，中间 ≤5 字）
# - "既不X，也不Y" 双重否定排比
_NOT_IS_PATTERNS = [
    re.compile(r'不是[^，。；！？\n]{1,30}[，,]\s*而是[^，。；！？\n]{1,30}'),
    re.compile(r'并非[^，。；！？\n]{1,30}[，,]\s*而是[^，。；！？\n]{1,30}'),
    re.compile(r'不是[^，。；！？\n]{1,5}而是[^，。；！？\n]{1,30}'),  # 紧凑写法
    re.compile(r'不仅[^，。；！？\n]{1,30}[，,]\s*更是[^，。；！？\n]{1,30}'),
    re.compile(r'不只[^，。；！？\n]{1,30}[，,]\s*更是[^，。；！？\n]{1,30}'),
    re.compile(r'既不[^，。；！？\n]{1,30}[，,]\s*也不[^，。；！？\n]{1,30}'),  # 双重否定排比
]


def detect_not_is_comparison(text: str) -> list[dict]:
    """检测否定铺垫后肯定翻转（'不是A，而是B' 最毒 AI 句式）。

    blocking 级：正文里几乎永不合法，命中即触发重写。
    """
    results: list[dict] = []
    seen_spans: set[tuple[int, int]] = set()
    for pat in _NOT_IS_PATTERNS:
        for match in pat.finditer(text):
            span = (match.start(), match.end())
            # 去重：不同模式可能匹配同一段文本
            if any(s <= span[0] < e or s < span[1] <= e for s, e in seen_spans):
                continue
            seen_spans.add(span)
            results.append({
                "pattern": "not-is-comparison",
                "severity": SEVERITY_BLOCKING,
                "matched": match.group(),
                "position": match.start(),
                "message": f"否定铺垫后肯定翻转（最毒AI句式）：'{match.group()[:30]}'",
            })
    return results


# ── 2. em-dash（破折号）──

_EM_DASH_PATTERNS = [
    re.compile(r'——'),  # 中文双破折号
    re.compile(r'(?<![\d—])—(?![\d—])'),  # 单个 em dash（非数字范围）
    re.compile(r'--+'),  # ASCII 连字符（2 个及以上，对齐 oh-story check-ai-patterns.js:165）
]


def detect_em_dash(text: str) -> list[dict]:
    """检测破折号（——/—/--）。

    blocking 级：正文产物不保留破折号，用动作/短句/换行/逗号/句号替代。
    """
    results: list[dict] = []
    seen_positions: set[int] = set()
    for pat in _EM_DASH_PATTERNS:
        for match in pat.finditer(text):
            # 去重：—— 模式可能被 —— 和 — 同时匹配
            if any(p in seen_positions for p in range(match.start(), match.end())):
                continue
            for p in range(match.start(), match.end()):
                seen_positions.add(p)
            results.append({
                "pattern": "em-dash",
                "severity": SEVERITY_BLOCKING,
                "matched": match.group(),
                "position": match.start(),
                "message": f"破折号'{match.group()}'：用动作/短句/换行/逗号/句号替代",
            })
    return results


# ── 3. period-stutter（句号结巴）──

def detect_period_stutter(text: str, min_consecutive: int = 4, max_sent_len: int = 6) -> list[dict]:
    """检测句号结巴（连续 ≥4 个短句，每句 ≤6 字）。

    advisory 级：碎句号是 AI 节奏标记，但偶尔使用是合法的。
    """
    results: list[dict] = []
    sentences = re.split(r'[。！？]', text)
    consecutive_count = 0
    start_idx = 0

    def _flush(count: int, start: int) -> None:
        if count >= min_consecutive:
            stutter_sents = sentences[start:start + count]
            stutter_text = '。'.join(s.strip() for s in stutter_sents if s.strip())
            results.append({
                "pattern": "period-stutter",
                "severity": SEVERITY_ADVISORY,
                "matched": stutter_text[:50],
                "position": -1,
                "message": f"句号结巴：连续{count}个短句（≤{max_sent_len}字），节奏过碎",
            })

    for i, sent in enumerate(sentences):
        sent = sent.strip()
        if not sent:
            continue
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', sent))
        if 0 < cn_count <= max_sent_len:
            if consecutive_count == 0:
                start_idx = i
            consecutive_count += 1
        else:
            _flush(consecutive_count, start_idx)
            consecutive_count = 0

    _flush(consecutive_count, start_idx)
    return results


# ── 4. long-paragraph（长段落）──

def detect_long_paragraph(text: str, max_chars: int = 200) -> list[dict]:
    """检测长段落（>200 字）。

    advisory 级：网文段落以 1-3 句为主，长段落是 AI 工整感来源。
    """
    results: list[dict] = []
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    for para in paragraphs:
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', para))
        if cn_count > max_chars:
            results.append({
                "pattern": "long-paragraph",
                "severity": SEVERITY_ADVISORY,
                "matched": para[:50],
                "position": -1,
                "message": f"长段落（{cn_count}字>{max_chars}）：拆成 1-3 句的短段",
            })
    return results


# ── 5. adjacent-repetition（紧邻整行复读）──

_ADJACENT_MIN_LEN = 8  # 可见长度阈值


def detect_adjacent_repetition(text: str) -> list[dict]:
    """检测紧邻整行复读（模型打转的硬信号）。

    blocking 级：去引号后可见长度 ≥8 的相邻行完全相同。
    引号内复沓台词不判（弹幕刷屏是体裁手法）。
    """
    results: list[dict] = []
    lines = [l.rstrip() for l in text.split('\n')]
    for i in range(1, len(lines)):
        prev = lines[i - 1].strip()
        curr = lines[i].strip()
        if not prev or not curr:
            continue
        if prev == curr:
            stripped = _strip_quoted(prev)
            if _visible_length(stripped) >= _ADJACENT_MIN_LEN:
                results.append({
                    "pattern": "adjacent-repetition",
                    "severity": SEVERITY_BLOCKING,
                    "matched": curr[:50],
                    "position": -1,
                    "message": f"紧邻整行复读：'{curr[:30]}'",
                })
    return results


# ── 6. long-sentence-repetition（长句复读）──

_REPEAT_MIN_COUNT = 3
_REPEAT_MIN_LEN = 12


def detect_long_sentence_repetition(text: str) -> list[dict]:
    """检测长句复读（去引号后同句出现 ≥3 次，可见长度 ≥12）。

    blocking 级：模型打转的硬信号。
    引号内复读豁免（弹幕体裁）。
    """
    results: list[dict] = []
    stripped = _strip_quoted(text)
    sentences = re.split(r'[。！？!?]', stripped)
    counts: dict[str, int] = {}
    for sent in sentences:
        s = sent.strip()
        if not s:
            continue
        if _visible_length(s) >= _REPEAT_MIN_LEN:
            counts[s] = counts.get(s, 0) + 1

    for sent, count in counts.items():
        if count >= _REPEAT_MIN_COUNT:
            results.append({
                "pattern": "long-sentence-repetition",
                "severity": SEVERITY_BLOCKING,
                "matched": sent[:50],
                "position": -1,
                "message": f"长句复读：'{sent[:30]}' 出现 {count} 次",
            })
    return results


# ── 7. truncation（截断）──

# 终止标点集：句末合法收尾字符（含中英文引号/括号/句末标点/省略号）
# 对齐 oh-story check-degeneration.js:233-247（含 … 省略号收尾）
_TERMINAL_PUNCT = set([
    '。', '！', '？', '!', '?', '…', '…',
    '"', "'",  # ASCII 引号
    '\u201c', '\u201d',  # 中文双引号 “”
    '\u2018', '\u2019',  # 中文单引号 ‘’
    '』', '」', '）', '】',
])


def detect_truncation(text: str) -> list[dict]:
    """检测截断（最后内容行末字不在终止标点集内）。

    blocking 级：生成截断的硬信号。
    """
    results: list[dict] = []
    lines = [l.rstrip() for l in text.split('\n')]
    # 跳过空行、frontmatter、代码块、标题、分隔线
    content_lines = [
        l for l in lines
        if l.strip()
        and not l.startswith('---')
        and not l.startswith('#')
        and not l.startswith('```')
    ]
    if not content_lines:
        return results
    last_line = content_lines[-1].strip()
    if last_line and last_line[-1] not in _TERMINAL_PUNCT:
        results.append({
            "pattern": "truncation",
            "severity": SEVERITY_BLOCKING,
            "matched": last_line[-30:],
            "position": -1,
            "message": f"截断：末字'{last_line[-1]}'不在终止标点集内",
        })
    return results


# ── 8. ai-self-reference（AI 自指）──

_AI_SELF_PATTERNS = [
    re.compile(r'作为(?:一个)?(?:AI|人工智能|语言模型|大模型)'),
    re.compile(r'我是(?:一个)?(?:AI|人工智能|语言模型|大模型)'),
    # 对齐 oh-story check-degeneration.js:37（补 Here's / am unable / apologize）
    re.compile(r'As an AI', re.IGNORECASE),
    re.compile(r'I am an AI', re.IGNORECASE),
    re.compile(r"I (?:cannot|can't|am unable|apologize)", re.IGNORECASE),
    re.compile(r"Here'?s", re.IGNORECASE),
    re.compile(r'I cannot (?:continue|generate|create)', re.IGNORECASE),
    re.compile(r'\bSure,', re.IGNORECASE),
    re.compile(r'\bCertainly,', re.IGNORECASE),
]


def detect_ai_self_reference(text: str) -> list[dict]:
    """检测 AI 自指（'作为AI' / 'As an AI' / 'Sure,' 等）。

    soft 级：对话行豁免（系统流题材 AI 角色台词合法）。
    """
    results: list[dict] = []
    lines = text.split('\n')
    for line in lines:
        is_dialog = _is_dialogue_line(line)
        for pat in _AI_SELF_PATTERNS:
            for match in pat.finditer(line):
                if is_dialog:
                    # 对话行豁免：系统流题材 AI 角色台词合法
                    continue
                results.append({
                    "pattern": "ai-self-reference",
                    "severity": SEVERITY_SOFT,
                    "matched": match.group(),
                    "position": -1,
                    "message": f"AI 自指'{match.group()}'：正文不得出现",
                })
    return results


# ── 9. generation-refusal（生成拒绝语）──

_REFUSAL_PATTERNS = [
    re.compile(r'我(?:无法|不能)(?:继续|生成|创作|完成|提供)'),
    re.compile(r'超出(?:了)?(?:我|模型)(?:的)?(?:能力|范围|权限)'),
    re.compile(r'由于(?:内容|政策|安全)限制'),
]


def detect_generation_refusal(text: str) -> list[dict]:
    """检测生成拒绝语。

    soft 级：对话行豁免。
    """
    results: list[dict] = []
    lines = text.split('\n')
    for line in lines:
        is_dialog = _is_dialogue_line(line)
        for pat in _REFUSAL_PATTERNS:
            for match in pat.finditer(line):
                if is_dialog:
                    continue  # 对话行豁免
                results.append({
                    "pattern": "generation-refusal",
                    "severity": SEVERITY_SOFT,
                    "matched": match.group(),
                    "position": -1,
                    "message": f"生成拒绝语'{match.group()}'：正文不得出现",
                })
    return results


# ── 10. engineering-word-leakage（工程词泄漏 + 全知剧透）──

# tier1：纯写作流水线术语 + 全知视角剧透句，正文里几乎永不合法
# - 工程词：写作流水线字段名，正文不应出现
# - 全知剧透：「他不知道的是」类句式，限知视角写作禁止
_TIER1_WORDS = [
    "细纲", "情节点", "卷纲", "功能标签", "目标情绪", "字数目标",
    "章首钩子", "章尾钩子", "narrative_function", "beat_type",
    "required_beats", "character_constraints", "info_focus",
    # 全知视角剧透句（限知视角铁律）
    "他不知道的是", "她不知道的是", "他们不知道的是",
]

# tier2：章节结构/歧义词，恒 advisory（正文里应是具体人名/场景，不是元叙述）
# 对齐 oh-story check-degeneration.js:48（补 第X章/这一章/上章/下章/前一章/后一章/前文/后文）
# C11：移除"主角/反派/配角/读者"等普通叙事词——正文高频正常使用，advisory 超阈值会触发整章 LLM 改写
_TIER2_WORDS = [
    "本章", "这一章", "上一章", "上章", "下一章", "下章",
    "前一章", "后一章", "前文", "后文",
    "伏笔", "任务描述",
]

# 首行章节标题豁免：oh-story check-degeneration.js:281 对首行 "第N章" 标题降级豁免
_CHAPTER_TITLE_RE = re.compile(r'^\s*第[一二三四五六七八九十百千零0-9]+[章节回卷]')


def detect_engineering_word_leakage(text: str) -> list[dict]:
    """检测工程词泄漏 + 全知视角剧透。

    tier1：非对话行 blocking，对话行 advisory
    tier2：恒 advisory

    首行章节标题（第N章）豁免 tier2 的"本章/这一章"类误报——
    对齐 oh-story check-degeneration.js:281。
    """
    results: list[dict] = []
    lines = text.split('\n')
    first_content_line = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        is_chapter_title = first_content_line and bool(_CHAPTER_TITLE_RE.match(stripped))
        is_dialog = _is_dialogue_line(line)
        # tier1
        for word in _TIER1_WORDS:
            if word in line:
                results.append({
                    "pattern": "engineering-word-leakage",
                    "severity": SEVERITY_ADVISORY if is_dialog else SEVERITY_BLOCKING,
                    "matched": word,
                    "position": -1,
                    "message": f"工程词/剧透泄漏'{word}'：{'对话行advisory' if is_dialog else '正文blocking'}",
                })
        # tier2（首行章节标题豁免）
        if not is_chapter_title:
            for word in _TIER2_WORDS:
                if word in line:
                    results.append({
                        "pattern": "engineering-word-leakage",
                        "severity": SEVERITY_ADVISORY,
                        "matched": word,
                        "position": -1,
                        "message": f"工程词'{word}'：advisory（检查是否应替换为具体表述）",
                    })
        first_content_line = False
    return results


# ── 11. placeholder-leakage（占位符泄漏）──

_PLACEHOLDER_PATTERNS = [
    re.compile(r'TODO', re.IGNORECASE),
    re.compile(r'占位符'),
    re.compile(r'未完待续'),
    re.compile(r'placeholder', re.IGNORECASE),
    re.compile(r'此处省略'),
    re.compile(r'以下省略'),
    # 括号省略精确正则：对齐 oh-story check-degeneration.js:38
    # 覆盖 "（此处省略）"/"(这里略)"/"（下文略过）" 等所有变体
    re.compile(r'[（(](?:此处|以下|这里|下文|后续)?\s*(?:省略|略)(?:去|过)?[^）)]{0,10}[）)]'),
    # 乱码替换字符 U+FFFD：对齐 oh-story check-degeneration.js:36
    re.compile(r'\uFFFD'),
    re.compile(r'[？?]{2,}'),  # 多个问号（疑似替换字符）
]


def detect_placeholder_leakage(text: str) -> list[dict]:
    """检测占位符泄漏。

    blocking 级：正文里永不合法。
    """
    results: list[dict] = []
    for pat in _PLACEHOLDER_PATTERNS:
        for match in pat.finditer(text):
            results.append({
                "pattern": "placeholder-leakage",
                "severity": SEVERITY_BLOCKING,
                "matched": match.group(),
                "position": match.start(),
                "message": f"占位符'{match.group()}'：正文不得出现",
            })
    return results


# ── 主入口 ──

def run_deslop_checks(text: str) -> dict:
    """运行全部 AI 模式检测，返回 {findings, blocking_count, advisory_count, soft_count, passed}。

    finding 结构：{pattern, severity, matched, position, message}
    - passed：blocking_count == 0 时为 True
    """
    findings: list[dict] = []
    findings.extend(detect_not_is_comparison(text))
    findings.extend(detect_em_dash(text))
    findings.extend(detect_period_stutter(text))
    findings.extend(detect_long_paragraph(text))
    findings.extend(detect_adjacent_repetition(text))
    findings.extend(detect_long_sentence_repetition(text))
    findings.extend(detect_truncation(text))
    findings.extend(detect_ai_self_reference(text))
    findings.extend(detect_generation_refusal(text))
    findings.extend(detect_engineering_word_leakage(text))
    findings.extend(detect_placeholder_leakage(text))

    blocking = [f for f in findings if f["severity"] == SEVERITY_BLOCKING]
    advisory = [f for f in findings if f["severity"] == SEVERITY_ADVISORY]
    soft = [f for f in findings if f["severity"] == SEVERITY_SOFT]

    return {
        "findings": findings,
        "blocking_count": len(blocking),
        "advisory_count": len(advisory),
        "soft_count": len(soft),
        "passed": len(blocking) == 0,
    }
