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


def check_foreshadows_planted(draft: str, foreshadows: list[dict]) -> tuple[bool, list[str]]:
    """检查本章应埋伏笔的描述关键词是否在正文中出现。

    注意：检查的是伏笔描述的关键词，不是伏笔 ID（ID 是元数据，不应出现在正文中）。
    foreshadows 参数是 [{"id": "S-001", "description": "神秘文物箱"}, ...] 格式。
    """
    missing = []
    for f in foreshadows:
        desc = f.get("description", "").strip()
        fid = f.get("id", "")
        if not desc:
            # 没有描述则跳过（无法检查）
            continue
        # 取描述中前 4-6 个字作为关键词检查
        keywords = desc.split("，")[0].split("。")[0].split("、")[0][:6]
        if keywords and keywords not in draft:
            missing.append(f"{fid}({desc[:20]})")
    return len(missing) == 0, missing


def run_deterministic_checks(draft: str, foreshadows_to_plant: list[dict] = None,
                             word_min: int = 1500, word_max: int = 5000) -> dict:
    """运行全部确定性检查，返回 {passed, issues}。

    foreshadows_to_plant: [{"id":"S-001","description":"神秘文物箱"}, ...]
    字数阈值可通过参数覆盖，默认与 writer prompt 目标对齐。
    """
    foreshadows_to_plant = foreshadows_to_plant or []
    issues = []

    ok, msg = check_word_count(draft, min_w=word_min, max_w=word_max)
    if not ok:
        issues.append({"dimension": "字数", "severity": "important", "message": msg})

    ok, hits = check_forbidden_words(draft)
    if not ok:
        issues.append({"dimension": "限频词", "severity": "important",
                       "message": f"AI 限频词过多：{', '.join(hits)}"})

    ok, missing = check_foreshadows_planted(draft, foreshadows_to_plant)
    if not ok:
        # 降级为 important：伏笔检查是启发式的，不应阻断生成
        issues.append({"dimension": "伏笔", "severity": "important",
                       "message": f"本章应埋伏笔关键词未出现：{', '.join(missing)}"})

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "word_count": count_chinese_chars(draft),
    }
