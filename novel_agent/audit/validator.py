"""确定性审计检查器：字数/限频词/伏笔关键词命中/句长分布/对话占比/禁用表达。

能用代码确定性检查的，不交给 LLM 判断。
阈值从 references/csv/节奏阈值.csv 读取（单一真源）。
"""
from __future__ import annotations

import csv
import json
import logging
import re
import statistics
from pathlib import Path

from novel_agent.audit.deslop_patterns import run_deslop_checks
from novel_agent.audit.name_authority import classify_name, is_non_person_name

logger = logging.getLogger(__name__)

# ---- AI 限频词/标记短语加载（单一真源：references/csv/AI限频词.csv） ----

# 硬编码兜底（CSV 读取失败时使用），与 prompt 黑名单保持一致
_FORBIDDEN_FALLBACK = [
    {"word": "忽然", "type": "副词", "limit": 2},
    {"word": "竟然", "type": "副词", "limit": 2},
    {"word": "不禁", "type": "副词", "limit": 2},
    {"word": "赫然", "type": "副词", "limit": 2},
    {"word": "蓦然", "type": "副词", "limit": 2},
    {"word": "陡然", "type": "副词", "limit": 2},
    {"word": "蓦地", "type": "副词", "limit": 2},
    {"word": "深吸一口气", "type": "动作", "limit": 1},
    {"word": "嘴角微微上扬", "type": "动作", "limit": 1},
    {"word": "嘴角勾起一抹弧度", "type": "动作", "limit": 1},
    {"word": "瞳孔一缩", "type": "动作", "limit": 1},
    {"word": "后背发凉", "type": "动作", "limit": 1},
    {"word": "像被定格的照片", "type": "明喻", "limit": 1},
    {"word": "系统提示音", "type": "套路", "limit": 0},
]

_FORBIDDEN_WORDS_CACHE: list[dict] | None = None


def _load_forbidden_words() -> list[dict]:
    """从 references/csv/AI限频词.csv 加载限频词清单。

    返回 [{"word": "忽然", "type": "副词", "limit": 2, "note": "..."}]。
    CSV 缺失时回退到硬编码 _FORBIDDEN_FALLBACK。
    """
    global _FORBIDDEN_WORDS_CACHE
    if _FORBIDDEN_WORDS_CACHE is not None:
        return _FORBIDDEN_WORDS_CACHE
    csv_path = Path(__file__).parent.parent / "references" / "csv" / "AI限频词.csv"
    rows: list[dict] = []
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                word = (row.get("词") or "").strip()
                if not word:
                    continue
                try:
                    limit = int((row.get("上限") or "2").strip())
                except ValueError:
                    limit = 2
                rows.append({
                    "word": word,
                    "type": (row.get("类型") or "副词").strip(),
                    "limit": limit,
                    "note": (row.get("说明") or "").strip(),
                })
    except Exception as e:
        logger.warning("读取AI限频词.csv失败(%s)，使用硬编码兜底", e)
        rows = list(_FORBIDDEN_FALLBACK)
    _FORBIDDEN_WORDS_CACHE = rows
    return rows


# 兼容旧代码：导出 FORBIDDEN_WORDS（副词类）
FORBIDDEN_WORDS = [r["word"] for r in _FORBIDDEN_FALLBACK if r["type"] == "副词"]

# ---- 阈值加载（单一真源，避免三处漂移） ----

_THRESHOLDS: dict | None = None


def _load_thresholds() -> dict:
    """从 references/csv/节奏阈值.csv 读取数值。

    支持用户目录覆盖：打包后 exe 内的 CSV 只读，
    用户可在 %APPDATA%/NovelCompose/节奏阈值.csv 放同名文件覆盖任意阈值。
    """
    global _THRESHOLDS
    if _THRESHOLDS is not None:
        return _THRESHOLDS
    _THRESHOLDS = {}
    csv_path = Path(__file__).parent.parent / "references" / "csv" / "节奏阈值.csv"
    try:
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("参数名", "").strip()
                val_str = row.get("数值", "").strip()
                if key and val_str:
                    try:
                        _THRESHOLDS[key] = float(val_str)
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning("读取节奏阈值.csv失败(%s)，使用硬编码默认值", e)
    # 用户目录覆盖（打包后可调字数上限等，不被 exe 内 CSV 锁死）
    try:
        import os, sys
        if getattr(sys, "frozen", False):
            app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            user_csv = app_data / "NovelCompose" / "节奏阈值.csv"
            if user_csv.exists():
                with open(user_csv, encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        key = row.get("参数名", "").strip()
                        val_str = row.get("数值", "").strip()
                        if key and val_str:
                            try:
                                _THRESHOLDS[key] = float(val_str)
                            except ValueError:
                                pass
                logger.info("已加载用户目录覆盖阈值: %s", user_csv)
    except Exception:
        pass
    return _THRESHOLDS


def _get_threshold(key: str, default: float) -> float:
    """安全取阈值，缺失时回退默认值。"""
    return _load_thresholds().get(key, default)


# ---- 基础检查 ----

def count_chinese_chars(text: str) -> int:
    """统计中文字符数（不含标点空格）。"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def check_word_count(draft: str, min_w: int = 800, max_w: int = 8000) -> tuple[bool, str]:
    """检查字数是否达标。方向性检查，阈值宽松。"""
    count = count_chinese_chars(draft)
    if count < min_w:
        return False, f"字数不足：{count} < {min_w}"
    if count > max_w:
        return False, f"字数超限：{count} > {max_w}"
    return True, f"字数达标：{count}"


def check_forbidden_words(draft: str, max_per_word: int | None = None) -> tuple[bool, list[str]]:
    """检查 AI 限频词/标记短语出现次数。

    单一真源：references/csv/AI限频词.csv。
    - 副词类：单词单章出现次数不得超过 limit（默认2）。
    - 动作/明喻/套路类：出现即报警，limit=1 表示>1次即超限，limit=0 表示完全禁止。
    max_per_word 参数仅作兼容兜底（CSV 缺失时使用），正常情况从 CSV 读 per-word limit。
    """
    rules = _load_forbidden_words()
    hits = []
    over_limit = []
    for r in rules:
        word = r["word"]
        limit = r["limit"] if max_per_word is None else max_per_word
        c = draft.count(word)
        if c > 0:
            hits.append(f"{word}({c}次)")
            if c > limit:
                over_limit.append(f"{word}({c}次,上限{limit})")
    return len(over_limit) == 0, over_limit if over_limit else hits


def check_foreshadows_planted(draft: str, foreshadows: list[dict]) -> tuple[bool, list[str]]:
    """检查本章应埋伏笔的描述关键词是否在正文中出现。

    改进：取描述中所有有意义的词（按标点分割），只要任一关键词命中即视为埋设。
    避免只取前6字导致通用词误判。
    """
    missing = []
    for f in foreshadows:
        desc = f.get("description", "").strip()
        fid = f.get("id", "")
        if not desc:
            continue
        # 取所有分词，至少2字的才算关键词
        import re
        segments = re.split(r'[，。、；：！？（）\s]+', desc)
        keywords = [s for s in segments if len(s) >= 2]
        if not keywords:
            keywords = [desc[:4]]
        # 任一关键词命中即视为已埋设
        if not any(kw in draft for kw in keywords):
            missing.append(f"{fid}({desc[:20]})")
    return len(missing) == 0, missing


def check_foreshadows_resolved(draft: str, to_resolve: list[dict]) -> list[dict]:
    """检查本章应回收伏笔是否在正文中出现回收迹象。

    B6修复：to_resolve 伏笔无任何确定性校验 → 永远卡在 planted/developing。
    现在检查应回收伏笔的关键词是否在正文中出现（至少出现才算有回收迹象）。
    """
    issues = []
    for f in to_resolve:
        desc = f.get("description", "").strip()
        fid = f.get("id", f.get("foreshadow_id", ""))
        if not desc:
            continue
        import re
        segments = re.split(r'[，。、；：！？（）\s]+', desc)
        keywords = [s for s in segments if len(s) >= 2]
        if not keywords:
            continue
        # 应回收伏笔的关键词完全不在正文中出现 → 可能漏回收
        if not any(kw in draft for kw in keywords):
            issues.append({"dimension": "伏笔跟踪", "severity": "important",
                "message": f"应回收伏笔{fid}({desc[:20]})在正文中未出现，可能漏回收"})
    return issues


# ---- 文风确定性检查（来自4.1文风指南的量化标准） ----

_SENT_SPLIT = re.compile(r'[。！？…]+')


def check_sentence_length(draft: str) -> list[dict]:
    """句长分布检测（4.1文风指南）。

    方向性检查：只在严重偏离时才报错。
    CV极低=过于均匀(AI味)，均值极端偏离=节奏单调。
    阈值从 节奏阈值.csv 读取：sentence_mean_min/max, sentence_cv_min, sentence_short_ratio_min。
    """
    sentences = [s for s in _SENT_SPLIT.split(draft) if s.strip()]
    lens = [len(re.findall(r'[\u4e00-\u9fff]', s)) for s in sentences]
    if len(lens) < 10:
        return []
    mean = statistics.mean(lens)
    short_ratio = sum(1 for n in lens if n <= 10) / len(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0

    mean_min = _get_threshold("sentence_mean_min", 18)
    mean_max = _get_threshold("sentence_mean_max", 45)
    cv_min = _get_threshold("sentence_cv_min", 0.4)
    short_ratio_min = _get_threshold("sentence_short_ratio_min", 0.15)

    issues = []
    # 只在严重偏离时报告（均值超出阈值范围的两倍）
    if mean < mean_min * 0.5 or mean > mean_max * 1.5:
        issues.append({"dimension": "句式", "severity": "minor",
            "message": f"平均句长{mean:.1f}字，节奏可能偏{'碎' if mean < mean_min else '拖'}"})
    # CV极低才报（低于阈值的一半），降为 minor
    if cv < cv_min * 0.5:
        issues.append({"dimension": "句式", "severity": "minor",
            "message": f"句长变异系数{cv:.2f}，长短句缺乏交错(AI味)"})
    # 短句占比过低=缺乏短句轰炸（网文语感铁律）
    if short_ratio < short_ratio_min * 0.5:
        issues.append({"dimension": "句式", "severity": "minor",
            "message": f"短句占比{short_ratio:.0%}<{short_ratio_min:.0%}，缺乏短句轰炸(AI味)"})
    return issues


_DIAL = re.compile(r'\u201c([^\u201d]*)\u201d')
_TAG_WORDS = ("说道", "问道", "答道", "道：", "说：")


def check_dialog_ratio(draft: str) -> list[dict]:
    """对话占比检测（4.1文风指南）。

    方向性检查：只在极端偏离时报告。
    对话标签率过高才报（反AI味核心）。
    阈值从 节奏阈值.csv 读取：dialog_ratio_min/max, dialog_tag_ratio_max。
    """
    total = count_chinese_chars(draft) or 1
    dial_chars = sum(len(re.findall(r'[\u4e00-\u9fff]', m))
                     for m in _DIAL.findall(draft))
    ratio = dial_chars / total
    dial_sents = re.findall(r'[^。！？]*\u201c[^\u201d]*\u201d[^。！？]*[。！？]?', draft)
    tagged = sum(1 for ds in dial_sents if any(t in ds for t in _TAG_WORDS))
    tag_ratio = tagged / len(dial_sents) if dial_sents else 0

    tag_max = _get_threshold("dialog_tag_ratio_max", 0.5)
    ratio_min = _get_threshold("dialog_ratio_min", 0.15)
    ratio_max = _get_threshold("dialog_ratio_max", 0.50)

    issues = []
    # 对话占比过低=缺乏对话捅刀（网文语感铁律），只在严重偏低时报告
    if ratio < ratio_min * 0.3:
        issues.append({"dimension": "对话", "severity": "minor",
            "message": f"对话占比{ratio:.0%}<{ratio_min:.0%}，缺乏对话(AI味)"})
    # 对话占比过高=几乎全对话
    elif ratio > ratio_max * 1.6:
        issues.append({"dimension": "对话", "severity": "minor",
            "message": f"对话占比{ratio:.0%}>{ratio_max:.0%}，过多对话缺乏叙述"})
    # 标签率过高才报，保持 important
    if tag_ratio > tag_max:
        issues.append({"dimension": "对话", "severity": "important",
            "message": f"对话标签率{tag_ratio:.0%}>{tag_max:.0%}，应用动作替代'说道'(反AI味)"})
    return issues


FORBIDDEN_PATTERNS = [
    # 只保留需要正则匹配的模式；字面短语（深吸一口气/嘴角勾起一抹/缓缓开口/眼中闪过一丝等）
    # 已统一到 references/csv/AI限频词.csv，由 check_forbidden_words 检查
    (re.compile(r"好消息[，,].*?坏消息"), "好消息/坏消息三连(AI味)"),
    (re.compile(r"他不知道的是"), "全知视角'他不知道的是'(AI味)"),
]


def check_forbidden_patterns(draft: str) -> list[dict]:
    """禁用表达检测（4.1禁用句式 + 4.7高频套话）。

    注意：不做全局 str.replace 替换——"深吸一口气"在溺水场景是正确写法。
    只检测+报告，由 LLM 在 rewrite 时判断是否需要修改。
    """
    issues = []
    for pat, label in FORBIDDEN_PATTERNS:
        matches = pat.findall(draft)
        if matches:
            issues.append({"dimension": "禁用表达", "severity": "minor",
                "message": f"{label}：出现{len(matches)}次"})
    return issues


# ---- 内容完整性检查（方向性，severity=minor） ----

# AI 高频情绪词（出现2次以上就该换表达）
_EMOTION_WORDS = [
    "后背发凉", "心里发毛", "心跳加速", "心跳得厉害", "深吸一口气",
    "屏住呼吸", "屏住呼吸", "松了口气", "捂住嘴", "不敢出声",
    "头皮发麻", "浑身一震", "瞳孔一缩", "倒吸一口凉气",
]


def check_emotion_repetition(draft: str) -> list[dict]:
    """检查 AI 高频情绪词是否反复使用。"""
    issues = []
    for w in _EMOTION_WORDS:
        count = draft.count(w)
        if count >= 2:
            issues.append({"dimension": "情绪词复读", "severity": "minor",
                "message": f"'{w}'出现{count}次，应换用不同身体动作展示情绪"})
    return issues


def check_chapter_ending(draft: str) -> list[dict]:
    """检查章末是否有钩子（方向性检查）。

    好钩子特征：问号、省略号、突然中断、具体悬念。
    差钩子特征：空泛警告（"小心XX"）、总结升华、情绪感慨。
    """
    lines = [l.strip() for l in draft.strip().split("\n") if l.strip()]
    if len(lines) < 3:
        return []
    ending = lines[-1]
    issues = []

    # 检查是否以空泛警告结尾
    if re.search(r'(小心|注意|当心).{1,6}[结的了]$', ending) and len(ending) < 20:
        issues.append({"dimension": "章末钩子", "severity": "minor",
            "message": f"章末可能是空泛警告（'{ending[:15]}'），应改为具体悬念"})

    # 检查是否以总结/感慨结尾
    if re.search(r'(就这样|这就是|或许|也许|大概).*[了罢]$', ending):
        issues.append({"dimension": "章末钩子", "severity": "minor",
            "message": "章末像总结/感慨，应用动作或悬念收尾"})

    return issues


def check_content_diversity(draft: str) -> list[dict]:
    """检查内容多样性：是否有对话、是否纯叙述。"""
    issues = []
    total = count_chinese_chars(draft) or 1
    dial_chars = sum(len(re.findall(r'[\u4e00-\u9fff]', m))
                     for m in _DIAL.findall(draft))
    dial_ratio = dial_chars / total

    # 完全无对话
    if dial_ratio < 0.02 and total > 500:
        issues.append({"dimension": "内容多样性", "severity": "minor",
            "message": "本章几乎无对话，全是叙述——读者会觉得枯燥"})

    return issues


def check_paragraph_fragmentation(draft: str) -> list[dict]:
    """段落碎片化检测：反"每句一段"机械感。

    检测指标：
    1. 独句段占比（>60%则严重碎片化）
    2. 连续独句段最大长度（≥5段则判定为机械碎片化）
    3. 段落平均句数（<1.5则过于碎片化）
    """
    issues = []
    paras = [p.strip() for p in draft.split("\n\n") if p.strip()]
    if len(paras) < 5:
        return issues  # 太短，不检测

    # 每段句数
    para_sentence_counts = []
    for p in paras:
        sents = [s for s in _SENT_SPLIT.split(p) if s.strip()]
        para_sentence_counts.append(len(sents))

    if not para_sentence_counts:
        return issues

    # 独句段占比
    single_para_count = sum(1 for c in para_sentence_counts if c == 1)
    single_ratio = single_para_count / len(para_sentence_counts)

    # 连续独句段最大长度
    max_consecutive = 0
    current = 0
    for c in para_sentence_counts:
        if c == 1:
            current += 1
            max_consecutive = max(max_consecutive, current)
        else:
            current = 0

    # 段落平均句数
    avg_sentences = sum(para_sentence_counts) / len(para_sentence_counts)

    if max_consecutive >= 5:
        issues.append({"dimension": "段落节奏", "severity": "important",
            "message": f"连续{max_consecutive}段都是独句段——每句一段的机械碎片化写法，请合并相关句子"})
    elif single_ratio > 0.6:
        issues.append({"dimension": "段落节奏", "severity": "minor",
            "message": f"独句段占比{single_ratio:.0%}——段落过于碎片化，建议将相关句子合并为3-6句的正常叙事段落"})
    elif avg_sentences < 1.5 and len(para_sentence_counts) >= 10:
        issues.append({"dimension": "段落节奏", "severity": "minor",
            "message": f"段落平均仅{avg_sentences:.1f}句——节奏偏碎，缺乏段落呼吸感"})

    return issues


# ---- 主入口 ----

def run_deterministic_checks(draft: str, foreshadows_to_plant: list[dict] = None,
                             word_min: int = 800, word_max: int = 8000) -> dict:
    """运行全部确定性检查，返回 {passed, issues}。

    foreshadows_to_plant: [{"id":"S-001","description":"神秘文物箱"}, ...]
    字数阈值可通过参数覆盖，默认与 writer prompt 目标对齐。
    """
    foreshadows_to_plant = foreshadows_to_plant or []
    issues = []

    ok, msg = check_word_count(draft, min_w=word_min, max_w=word_max)
    if not ok:
        cn_count = count_chinese_chars(draft)
        # 低于60%或超过上限均为critical（强制rewrite收敛）
        if cn_count < word_min * 0.6 or cn_count > word_max:
            severity = "critical"
        else:
            severity = "important"
        issues.append({"dimension": "字数", "severity": severity, "message": msg})

    ok, hits = check_forbidden_words(draft)
    if not ok:
        # 限频词命中数≥阈值2倍为critical，否则important
        over_count = len(hits)
        severity = "critical" if over_count >= 4 else "important"
        issues.append({"dimension": "限频词", "severity": severity,
                       "message": f"AI 限频词过多：{', '.join(hits)}"})

    ok, missing = check_foreshadows_planted(draft, foreshadows_to_plant)
    if not ok:
        # 伏笔是硬约束，缺失即逻辑断裂，直接critical
        issues.append({"dimension": "伏笔", "severity": "critical",
                       "message": f"本章应埋伏笔关键词未出现：{', '.join(missing)}"})

    # 文风确定性检查
    issues.extend(check_sentence_length(draft))
    issues.extend(check_dialog_ratio(draft))
    issues.extend(check_forbidden_patterns(draft))

    # 内容完整性检查
    issues.extend(check_emotion_repetition(draft))
    issues.extend(check_chapter_ending(draft))
    issues.extend(check_content_diversity(draft))

    # 段落碎片化检查（反"每句一段"机械感）
    issues.extend(check_paragraph_fragmentation(draft))

    # ── oh-story AI 模式检测（11 类确定性检测）──
    # blocking→critical / advisory→minor / soft→minor
    deslop_result = run_deslop_checks(draft)
    severity_map = {
        "blocking": "critical",
        "advisory": "minor",
        "soft": "minor",
    }
    for finding in deslop_result["findings"]:
        issues.append({
            "dimension": f"AI模式-{finding['pattern']}",
            "severity": severity_map.get(finding["severity"], "minor"),
            "message": finding["message"],
        })

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "word_count": count_chinese_chars(draft),
    }


# ---- 爽点供应链检查（需要 repo） ----

def check_pleasure_gap(repo, chapter: int) -> list[dict]:
    """爽点断层检测（4.4节奏情绪）。

    压抑章不累加gap（P2-2）：本章无beat计划=压抑章，不报断层。
    数据源：outline.required_beats（计划），而非 PleasureBeat 表（交付记录，audit时还不存在）。
    """
    thresholds = _load_thresholds()
    small_gap = int(thresholds.get("small_gap_max", 5))
    medium_gap = int(thresholds.get("medium_gap_max", 12))
    large_gap = int(thresholds.get("large_gap_max", 30))

    # 查本章是否有beat计划——从大纲读取，而非PleasureBeat交付表
    try:
        outline = repo.get_outline_by_chapter(chapter)
    except Exception:
        return []
    if not outline or not outline.required_beats:
        return []  # 无大纲或无beat计划=压抑章，不报断层

    # 解析 required_beats JSON
    try:
        import json
        planned_beats = json.loads(outline.required_beats) if outline.required_beats else []
    except Exception:
        planned_beats = []
    if not planned_beats:
        return []
    # 防护：LLM 可能把 required_beats 生成成字符串数组（如 ["small"]）而非对象数组，
    # 此时 b.get() 崩溃会使爽点断层检测静默失效。只保留 dict 元素。
    if isinstance(planned_beats, list):
        planned_beats = [b for b in planned_beats if isinstance(b, dict)]
    else:
        planned_beats = []
    if not planned_beats:
        return []

    # 有beat计划 → 检查gap
    try:
        gap = repo.get_pleasure_gap(chapter)
    except Exception:
        return []

    issues = []
    has_small = any(b.get("tier") == "small" for b in planned_beats)
    has_medium = any(b.get("tier") == "medium" for b in planned_beats)
    has_large = any(b.get("tier") == "large" for b in planned_beats)

    if has_small and gap > small_gap:
        issues.append({"dimension": "爽点分布", "severity": "important",
            "message": f"小爽点断层：距上次交付{gap}章(上限{small_gap})"})
    if has_medium and gap > medium_gap:
        issues.append({"dimension": "爽点分布", "severity": "important",
            "message": f"中爽点断层：距上次交付{gap}章(上限{medium_gap})"})
    if has_large and gap > large_gap:
        issues.append({"dimension": "爽点分布", "severity": "critical",
            "message": f"大爽点断层：距上次交付{gap}章(上限{large_gap})"})
    return issues


def check_golden_three(repo, chapter: int) -> list[dict]:
    """黄金三章检查：前3章必须有爽点计划。

    前3章是黄金三章，每章至少1个small beat。
    数据源：outline.required_beats + outline.phase，而非 PleasureBeat 表。
    """
    opening_chapters = int(_get_threshold("opening_chapters", 3))
    if chapter > opening_chapters:
        return []

    issues = []
    try:
        outline = repo.get_outline_by_chapter(chapter)
        if not outline:
            issues.append({"dimension": "爽点分布", "severity": "important",
                "message": f"第{chapter}章是黄金三章但无大纲"})
            return issues
        # 从大纲读取beat计划
        import json
        planned_beats = json.loads(outline.required_beats) if outline.required_beats else []
        # 防护：字符串数组元素会导致 b.get() 崩溃（爽点检查静默失效），只保留 dict 元素
        if isinstance(planned_beats, list):
            planned_beats = [b for b in planned_beats if isinstance(b, dict)]
        else:
            planned_beats = []
        if not planned_beats:
            issues.append({"dimension": "爽点分布", "severity": "critical",
                "message": f"第{chapter}章是黄金三章但无爽点计划"})
        elif not any(b.get("tier") == "small" for b in planned_beats):
            issues.append({"dimension": "爽点分布", "severity": "important",
                "message": f"第{chapter}章黄金三章但无small级爽点"})
        # phase检查
        if outline.phase and outline.phase != "opening":
            issues.append({"dimension": "爽点分布", "severity": "important",
                "message": f"第{chapter}章黄金三章但phase={outline.phase}（应为opening）"})
    except Exception:
        pass
    return issues


def check_suppression_streak(repo, chapter: int) -> list[dict]:
    """连续压抑章数检查（4.4节奏情绪）。

    规则：连续 suppression_max 章无爽点交付 → critical（读者疲劳）。
    数据源：repo.get_pleasure_gap（距上次交付章数）。
    阈值：suppression_max（默认3）。
    """
    suppression_max = int(_get_threshold("suppression_max", 3))
    try:
        outline = repo.get_outline_by_chapter(chapter)
        if not outline or not outline.required_beats:
            # 无beat计划=压抑章，检查连续压抑长度
            gap = repo.get_pleasure_gap(chapter)
            if gap > suppression_max:
                return [{"dimension": "爽点分布", "severity": "critical",
                    "message": f"连续{gap}章无爽点交付(上限{suppression_max})，读者疲劳风险"}]
    except Exception:
        pass
    return []


def check_hook_repetition(repo, chapter: int) -> list[dict]:
    """章末钩子连续重复检查（4.4节奏情绪）。

    规则：连续 hook_no_repeat+1 章使用同种钩子类型 → important。
    数据源：outline.required_hooks。
    阈值：hook_no_repeat（默认2，即连续2章同种钩子报警）。
    """
    hook_no_repeat = int(_get_threshold("hook_no_repeat", 2))
    issues = []
    try:
        hook_types = []
        for ch in range(max(1, chapter - hook_no_repeat), chapter + 1):
            o = repo.get_outline_by_chapter(ch)
            if not o or not o.required_hooks:
                hook_types.append(None)
                continue
            hooks = _safe_json_loads(o.required_hooks)
            htype = hooks.get("type", "") if isinstance(hooks, dict) else ""
            hook_types.append(htype)
        # 检查最近 hook_no_repeat+1 章是否同种钩子
        if len(hook_types) >= hook_no_repeat + 1:
            recent = hook_types[-(hook_no_repeat + 1):]
            if recent[0] and all(h == recent[0] for h in recent):
                issues.append({"dimension": "章末钩子", "severity": "important",
                    "message": f"连续{hook_no_repeat + 1}章使用同种钩子「{recent[0]}」，缺乏变化"})
    except Exception:
        pass
    return issues


# ---- 拆书分布形状校准：反模式检测（P0） ----

# 剧情功能分类体系（来源：拆书20种标签，精简为生成需要的16种）
NARRATIVE_FUNCTIONS = {
    "开篇钩子", "揭示", "铺垫", "转折", "过渡", "冲突", "高潮", "收束",
    "伏笔", "人物塑造", "世界观铺陈", "关系建立", "悬念设置",
    "挫折", "战斗", "智斗",
}

# 高潮赌注等级（来源：拆书8卷递进规律）
STAKES_LEVELS = ["个人突破", "团队突破", "体系突破", "区域突破", "世界存亡"]


def _safe_json_loads(text: str):
    """安全 JSON 解析，失败返回 None。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def check_narrative_pattern(repo, chapter: int) -> list[dict]:
    """检测连续章节的剧情功能反模式。

    规则来源：拆书第1卷63章逐章标注，未发现连续两章相同功能。
    - 连续3章同种功能 → critical
    - 连续5章无"高潮"或"转折" → important
    - 连续2章"日常" → warning
    """
    issues = []
    try:
        outlines = []
        for ch in range(max(1, chapter - 4), chapter + 1):
            o = repo.get_outline_by_chapter(ch)
            if o:
                cc = _safe_json_loads(o.character_constraints)
                if cc:
                    outlines.append((ch, cc.get("narrative_function", "")))
        if len(outlines) >= 3:
            last3 = [nf for _, nf in outlines[-3:]]
            if last3[0] and last3[0] == last3[1] == last3[2]:
                issues.append({
                    "dimension": "剧情功能", "severity": "critical",
                    "message": f"连续3章均为「{last3[0]}」，违反功能交替原则",
                })
        if len(outlines) >= 5:
            last5_text = " ".join(nf for _, nf in outlines[-5:])
            # C7：narrative_function 字段缺失（数据源不生产）时 last5_text 全空，
            # 跳过避免必报"连续5章无高潮或转折"；字段存在时保持原检查行为
            if last5_text.strip() and not any(k in last5_text for k in ("高潮", "转折")):
                issues.append({
                    "dimension": "剧情功能", "severity": "important",
                    "message": "连续5章无高潮或转折，节奏可能拖沓",
                })
        if len(outlines) >= 2:
            last2 = [nf for _, nf in outlines[-2:]]
            if last2[0] == last2[1] == "日常":
                issues.append({
                    "dimension": "剧情功能", "severity": "warning",
                    "message": "连续2章日常，缺乏冲突推进",
                })
    except Exception:
        pass
    return issues


def check_outline_quality(repo, chapter: int) -> list[dict]:
    """检查章纲是否包含必要字段。

    规则来源：拆书每章标注10个字段，生成需要其中3个核心字段。
    - 所有章必须有 narrative_function
    - 前期章(前10章)必须有 info_focus
    - 非过渡章必须有 character_decisions
    """
    issues = []
    try:
        o = repo.get_outline_by_chapter(chapter)
        if not o:
            return issues
        cc = _safe_json_loads(o.character_constraints)
        if not cc:
            issues.append({
                "dimension": "章纲质量", "severity": "important",
                "message": f"第{chapter}章缺少约束载荷（narrative_function/info_focus/character_decisions）",
            })
            return issues
        nf = cc.get("narrative_function", "")
        if not nf:
            # C7：章纲生成端不生产 narrative_function 字段，缺失时降级跳过，
            # 避免每章必报假问题导致正常章节被迫人审
            logger.debug("check_outline_quality 第%d章：narrative_function 缺失，跳过章纲字段检查", chapter)
            return issues
        if chapter <= 10 and not cc.get("info_focus"):
            issues.append({
                "dimension": "章纲质量", "severity": "important",
                "message": f"第{chapter}章处于开篇期，缺少 info_focus（本章重点揭示哪类设定）",
            })
        if nf != "过渡" and not cc.get("character_decisions"):
            issues.append({
                "dimension": "章纲质量", "severity": "warning",
                "message": f"第{chapter}章非过渡章，缺少 character_decisions",
            })
    except Exception:
        pass
    return issues


def check_subplot_lifecycle(repo, chapter: int,
                             chapters_per_volume: int = 30) -> list[dict]:
    """检测支线遗忘和拖延。

    规则来源：拆书支线正常范围 1-5卷，埋设到展开 0-2卷间隔。
    - 埋设后超过3卷未展开 → 遗忘支线
    - 展开后超过3卷未收束 → 拖延支线
    - 计划回收章已过 → 逾期未收
    """
    issues = []
    try:
        foreshadows = repo.list_foreshadows()
        current_volume = (chapter - 1) // chapters_per_volume + 1
        for f in foreshadows:
            if f.status in ("pending", "planted"):
                plant_vol = max(1, (f.plant_chapter - 1) // chapters_per_volume + 1)
                gap_volumes = current_volume - plant_vol
                if gap_volumes > 3 and f.status == "pending":
                    issues.append({
                        "dimension": "支线生命周期", "severity": "important",
                        "message": f"伏笔[{f.foreshadow_id}]埋设于第{f.plant_chapter}章，"
                                   f"已过{gap_volumes}卷未展开",
                    })
                elif f.status == "planted" and f.planned_resolve_chapter > 0:
                    if f.planned_resolve_chapter < chapter:
                        issues.append({
                            "dimension": "支线生命周期", "severity": "critical",
                            "message": f"伏笔[{f.foreshadow_id}]计划第{f.planned_resolve_chapter}章回收，"
                                       f"已逾期至第{chapter}章",
                        })
    except Exception:
        pass
    return issues


def check_info_density_anomaly(repo, chapter: int) -> list[dict]:
    """检测信息密度偏离阶段预期。

    规则来源：拆书密度波浪型曲线，不同阶段预期不同。
    - 开篇奠基期(前10章)：预期高密度 3-10 条
    - 段前期(每卷前10章)：预期中高密度 3-8 条
    - 段中期(每卷11-20章)：预期中低密度 1-6 条
    - 段后期(每卷21-30章)：预期中高密度 2-8 条
    """
    issues = []
    try:
        pos_in_vol = (chapter - 1) % 30 + 1
        if chapter <= 10:
            stage, expected_min = "开篇奠基期", 3
        elif pos_in_vol <= 10:
            stage, expected_min = "段前期", 3
        elif pos_in_vol <= 20:
            stage, expected_min = "段中期", 1
        else:
            stage, expected_min = "段后期", 2

        o = repo.get_outline_by_chapter(chapter)
        if not o:
            return issues
        cc = _safe_json_loads(o.character_constraints)
        if not cc:
            return issues
        info_focus = cc.get("info_focus", "")
        if not info_focus:
            # C7：章纲生成端不生产 info_focus 字段，缺失时降级为 debug 不报，
            # 避免前10章必报 warning 导致正常章节被迫人审。
            # （字段存在时保持原检查行为：原逻辑仅当 info_focus 为空且 expected_min>=3 时才报，
            #   非空时本检查不产生任何 issue。）
            logger.debug("check_info_density_anomaly 第%d章：info_focus 缺失，跳过信息密度检查", chapter)
            return issues
    except Exception:
        pass
    return issues


def check_stakes_progression(prev_stakes: str, curr_stakes: str) -> list[dict]:
    """检查高潮赌注递进是否合理。

    规则来源：拆书8卷赌注每两卷升一级，跳级不超过1级。
    - 跳级超过1级 → critical
    - 赌注倒退 → warning
    """
    issues = []
    if prev_stakes not in STAKES_LEVELS or curr_stakes not in STAKES_LEVELS:
        return issues
    prev_idx = STAKES_LEVELS.index(prev_stakes)
    curr_idx = STAKES_LEVELS.index(curr_stakes)
    if curr_idx > prev_idx + 1:
        issues.append({
            "severity": "critical",
            "message": f"赌注跳级过大：{prev_stakes}→{curr_stakes}，中间缺一级",
        })
    if curr_idx < prev_idx:
        issues.append({
            "severity": "warning",
            "message": f"赌注倒退：{prev_stakes}→{curr_stakes}",
        })
    return issues


def effective_pressure(debt, chapter: int, suppression_chapters: int = 0) -> int:
    """计算欠账有效压力（P2-3 pressure非线性）。

    基础 pressure 随时间和连续压抑章节数加速增长：
    - 每拖 5 章 +1
    - 每连续压抑 1 章 +0.5
    - 上限 5
    """
    base = getattr(debt, "pressure", 3) or 3
    age = max(0, chapter - getattr(debt, "created_chapter", chapter))
    age_bonus = age // 5
    suppression_bonus = suppression_chapters // 2
    return min(5, int(base + age_bonus + suppression_bonus))


def check_volume_climax(repo, chapter: int,
                        chapters_per_volume: int = 30) -> list[dict]:
    """卷高潮检查（P2-4）：卷末只强制偿还本卷短线欠账，长线不判 critical。

    卷末定义为每卷最后 3 章。
    """
    position_in_volume = (chapter - 1) % chapters_per_volume + 1
    if position_in_volume < chapters_per_volume - 2:
        return []

    volume_start = chapter - position_in_volume + 1
    issues = []
    try:
        open_debts = repo.list_open_debts()
        # 计算连续压抑章数（距上次交付爽点的间隔）
        suppression = repo.get_pleasure_gap(chapter)
        for d in open_debts:
            # 只检查本卷产生的短线欠账
            created = getattr(d, "created_chapter", 0) or 0
            term = getattr(d, "term", "short")
            if volume_start <= created <= chapter and term == "short":
                eff = effective_pressure(d, chapter, suppression_chapters=suppression)
                if eff >= 4:
                    issues.append({
                        "dimension": "欠账偿还", "severity": "critical",
                        "message": f"卷末将至，本卷短线欠账[{d.debt_type}]未还，有效压力{eff}",
                    })
                else:
                    issues.append({
                        "dimension": "欠账偿还", "severity": "important",
                        "message": f"卷末将至，本卷短线欠账[{d.debt_type}]待还",
                    })
    except Exception:
        pass
    return issues


# ---- L0 角色一致性检查（零 token 消耗） ----

# 常见中文姓氏，用于识别草稿中的疑似角色名
_COMMON_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟黄穆"
    "萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮"
    "蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万"
    "支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇"
    "邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗"
    "山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸"
    "司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双闻昕"
    "党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别"
    "庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国"
    "文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋"
    "沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)


def check_character_name_consistency(draft: str, repo) -> list[dict]:
    """L0 角色名一致性检查：草稿中出现的角色名是否都在 Bible 中。

    用简单的模式匹配：中文姓名 = 姓氏 + 1-2字名。
    如果草稿中出现了疑似角色名但不在 Bible 角色列表中，标记为 important。
    """
    issues = []
    try:
        characters = repo.list_characters()
        known_names = {c.name for c in characters}
        # 构建已知角色名的别名集（角色可能有多个称呼）
        for c in characters:
            if c.name:
                known_names.add(c.name)
                # 名（去掉姓）
                if len(c.name) >= 2:
                    known_names.add(c.name[1:])
    except Exception:
        return issues

    if not known_names:
        return issues

    # 在草稿中查找疑似角色名：姓氏 + 1-2个中文字
    # 只匹配明确的对话提示语（"X说："、"X道："），且后面必须跟冒号
    # 避免把"知道""感到""看来"等动词短语误识为角色名
    # 注意：贪婪匹配会把"林晚笑道："中的"笑"并入名字，须在匹配后剥离尾部情绪/语气字
    name_pattern = re.compile(r'([\u4e00-\u9fff]{2,4})(?:说|道|问|答|喊|骂|叹|笑|怒|惊)(?=[：:])')
    # 说话词中的情绪/语气字与说话助词：贪婪匹配会把"林晚笑道"中的"笑"、"张无忌说道"中的"说"
    # 并入名字，匹配后须逐一剥离。这些字在名字结尾只可能属于"笑道/叹道/说道"等结构。
    _NAME_SUFFIX = set("说问道答喊骂叹笑怒惊")

    suspected_names = set()
    for match in name_pattern.finditer(draft):
        name = match.group(1)
        # 剥离尾部情绪/语气/说话助词："林晚笑"→"林晚"；"陈默叹"→"陈默"；"张无忌说"→"张无忌"
        while name and name[-1] in _NAME_SUFFIX:
            name = name[:-1]
        if not name:
            continue
        # 剥离后至少保留"姓+名"两字，只剩单姓不构成角色名
        if len(name) < 2:
            continue
        # 命名权威过滤：亲属称呼（母亲/大哥/王兄/李大人）与通用人物别名（老者/黑衣人/掌柜）
        # 不是具体人名，不应报"疑似未知角色"
        if is_non_person_name(name):
            continue
        if name and name[0] in _COMMON_SURNAMES:
            if name not in known_names and name[1:] not in known_names:
                suspected_names.add(name)

    for name in suspected_names:
        issues.append({
            "dimension": "角色一致性",
            "severity": "important",
            "message": f"草稿中出现疑似未知角色名「{name}」，不在 Bible 角色列表中",
        })

    return issues


def check_character_location(draft: str, repo) -> list[dict]:
    """L0 角色位置矛盾检查：角色在 Bible 中的位置 vs 草稿中提到的位置。

    简单字符串匹配：如果角色 current_location 是 A，但草稿中说角色在 B，标记为 important。
    """
    issues = []
    try:
        characters = repo.list_characters()
    except Exception:
        return issues

    for c in characters:
        if not c.name or not c.current_location:
            continue
        bible_loc = c.current_location.strip()
        if not bible_loc or bible_loc == "未知":
            continue

        # 在草稿中搜索 "角色名 + 在/到了/抵达/身处 + 位置"
        # 如果出现了与 Bible 不同的位置词，可能是矛盾
        # 这里只做简单的关键词检测，不做完整的 NER
        # 检查草稿中是否提到了角色在不同位置
        loc_pattern = re.compile(
            rf'{re.escape(c.name)}.*?(?:在|到了|抵达|身处|来到|出现在|位于)\s*([\u4e00-\u9fff]{{2,8}})'
        )
        for match in loc_pattern.finditer(draft):
            draft_loc = match.group(1).strip()
            # 如果草稿中的位置与 Bible 中的位置不同
            if draft_loc and bible_loc and draft_loc != bible_loc:
                # 只在两个位置词完全不相同时才报告
                if draft_loc not in bible_loc and bible_loc not in draft_loc:
                    issues.append({
                        "dimension": "角色位置",
                        "severity": "minor",
                        "message": f"角色「{c.name}」Bible 位置为「{bible_loc}」，但草稿提到在「{draft_loc}」",
                    })
                    break  # 每个角色只报一次

    return issues


def check_character_state_consistency(draft: str, repo) -> list[dict]:
    """L0 角色状态一致性检查：检查草稿中角色状态是否与 Bible 矛盾。

    检查角色是否在草稿中"死亡"但 Bible 中状态为"存活"等。
    """
    issues = []
    try:
        characters = repo.list_characters()
    except Exception:
        return issues

    # 明确死亡词（去掉"死"单字，避免"怕死""打死"误匹配）
    death_keywords = ["死亡", "死去", "陨落", "身亡", "毙命", "断气", "咽气", "丧命"]
    # 否定/非死亡语境词：片段内含这些词时跳过
    negate_keywords = ["没死", "不死", "怕死", "要死", "打死", "弄死", "杀死", "死死",
                       "死里逃生", "死而后已", "视死如归", "死不瞑目", "死皮赖脸", "死心塌地"]
    for c in characters:
        if not c.name:
            continue
        # 遍历角色名的每个出现位置，取其后15字片段检查
        for m in re.finditer(re.escape(c.name), draft):
            segment = draft[m.start(): m.start() + len(c.name) + 15]
            # 片段含否定词则跳过这个位置
            if any(neg in segment for neg in negate_keywords):
                continue
            # 片段含明确死亡词则报 issue
            hit_kw = next((kw for kw in death_keywords if kw in segment), None)
            if hit_kw:
                issues.append({
                    "dimension": "角色状态",
                    "severity": "important",
                    "message": f"角色「{c.name}」在草稿中疑似死亡（{hit_kw}），需确认 Bible 状态更新",
                })
                break

    return issues
