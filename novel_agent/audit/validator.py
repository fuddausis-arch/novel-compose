"""确定性审计检查器：字数/限频词/伏笔关键词命中，用代码查不交给 LLM。"""
from __future__ import annotations

import re

# AI 常见限频词
FORBIDDEN_WORDS = ["忽然", "竟然", "不禁", "赫然", "蓦然", "陡然", "蓦地"]


def count_chinese_chars(text: str) -> int:
    """统计中文字符数（不含标点空格）。"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def check_word_count(draft: str, min_w: int = 1500, max_w: int = 5000) -> tuple[bool, str]:
    """检查字数是否达标。"""
    count = count_chinese_chars(draft)
    if count < min_w:
        return False, f"字数不足：{count} < {min_w}"
    if count > max_w:
        return False, f"字数超限：{count} > {max_w}"
    return True, f"字数达标：{count}"


def check_forbidden_words(draft: str, max_count: int = 3) -> tuple[bool, list[str]]:
    """检查 AI 限频词出现次数。"""
    hits = []
    for w in FORBIDDEN_WORDS:
        c = draft.count(w)
        if c > 0:
            hits.append(f"{w}({c}次)")
    return len(hits) <= max_count, hits


def check_foreshadows_planted(draft: str, foreshadow_ids: list[str]) -> tuple[bool, list[str]]:
    """检查本章应埋伏笔的关键词是否在正文中出现。"""
    missing = []
    for fid in foreshadow_ids:
        # 检查 ID 本身或其描述关键词
        if fid not in draft:
            missing.append(fid)
    return len(missing) == 0, missing


def run_deterministic_checks(draft: str, foreshadow_to_plant: list[str] = None) -> dict:
    """运行全部确定性检查，返回 {passed, issues}。"""
    foreshadow_to_plant = foreshadow_to_plant or []
    issues = []

    ok, msg = check_word_count(draft)
    if not ok:
        issues.append({"dimension": "字数", "severity": "important", "message": msg})

    ok, hits = check_forbidden_words(draft)
    if not ok:
        issues.append({"dimension": "限频词", "severity": "important",
                       "message": f"AI 限频词过多：{', '.join(hits)}"})

    ok, missing = check_foreshadows_planted(draft, foreshadow_to_plant)
    if not ok:
        issues.append({"dimension": "伏笔", "severity": "critical",
                       "message": f"本章应埋伏笔未出现：{', '.join(missing)}"})

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "word_count": count_chinese_chars(draft),
    }
