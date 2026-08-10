"""文本后处理器：检测并修复LLM生成文本中的AI味格式问题。

基于网上调研的工程化方案，实现4项后处理：
1. 无标点长句检测（连续50字+无逗号句号）→ 标记问题段
2. 排比过载检测（连续4+相同前缀句式）→ 标记问题段
3. 感叹号轰炸检测（单段3+感叹号）→ 自动降级
4. 重复递进检测（越来越X连续3+）→ 自动截断

检测到的问题返回给polish prompt做LLM修复；
感叹号和重复递进可直接规则修复（不需LLM）。
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# 句末/停顿标点集合（中英文）
# C12：\n 加入停顿字符集，防止长句检测跨行误报（连续多行行尾无标点被判为单句）
_PAUSE_CHARS = r'，,。！？；：!?,;:…—\n'

# 感叹号（中英文）
_EXCLAIM = '！!'


def detect_long_unpunctuated(text: str, threshold: int = 50) -> list[dict]:
    """检测连续 threshold 字以上无标点的片段。

    Returns:
        问题列表，每项含 segment/cn_len/pos/suggestion
    """
    pattern = re.compile(rf'[^{_PAUSE_CHARS}]+')
    issues = []
    for m in pattern.finditer(text):
        seg = m.group()
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', seg))
        if cn_count >= threshold:
            issues.append({
                'type': 'long_unpunctuated',
                'segment': seg[:80] + '...' if len(seg) > 80 else seg,
                'cn_len': cn_count,
                'pos': m.start(),
                'suggestion': f'连续{cn_count}字无标点，需断句'
            })
    return issues


def detect_parallelism_overload(text: str, min_repeat: int = 4, prefix_len: int = 3) -> list[dict]:
    """检测连续 min_repeat 个以上、前 prefix_len 字高度相似的句式。

    Returns:
        问题列表
    """
    # 切分句/分句
    clauses = re.split(r'[。！？，；!?;,]', text)
    clauses = [c.strip() for c in clauses if c.strip()]

    issues = []
    i = 0
    while i < len(clauses):
        prefix = clauses[i][:prefix_len]
        if len(prefix) < prefix_len:
            i += 1
            continue
        # 向后看连续多少个分句以相同前缀开头
        run = 1
        j = i + 1
        while j < len(clauses) and clauses[j][:prefix_len] == prefix:
            run += 1
            j += 1
        if run >= min_repeat:
            issues.append({
                'type': 'parallelism_overload',
                'prefix': prefix,
                'count': run,
                'clauses': clauses[i:min(i + run, i + 6)],
                'suggestion': f'连续{run}个分句以"{prefix}"开头，排比过载'
            })
        i = j
    return issues


def fix_exclamation_bombing(text: str, max_per_para: int = 2) -> tuple[str, list[dict]]:
    """检测并修复单段感叹号超过 max_per_para 的段落。

    策略：保留前 max_per_para 个感叹号，多余的改为句号。
    """
    paragraphs = re.split(r'(\n\s*\n)', text)  # 保留分隔符
    issues = []
    fixed_parts = []
    para_idx = 0

    for part in paragraphs:
        if re.match(r'^\n\s*\n$', part):
            fixed_parts.append(part)
            continue

        excl_count = part.count('！') + part.count('!')
        if excl_count > max_per_para:
            issues.append({
                'type': 'exclamation_bombing',
                'para_index': para_idx,
                'count': excl_count,
                'preview': part[:40] + '...',
                'suggestion': f'该段感叹号{excl_count}个，已降级为{max_per_para}个'
            })
            # 把连续感叹号组视为1个，保留前max_per_para组，多余的整组改为句号
            count = 0
            result = []
            i = 0
            while i < len(part):
                if part[i] in _EXCLAIM:
                    # 收集连续的感叹号
                    j = i
                    while j < len(part) and part[j] in _EXCLAIM:
                        j += 1
                    count += 1
                    if count <= max_per_para:
                        result.append('！')  # 统一为单个全角感叹号
                    else:
                        result.append('。')
                    i = j
                else:
                    result.append(part[i])
                    i += 1
            fixed_parts.append(''.join(result))
        else:
            fixed_parts.append(part)
        para_idx += 1

    return ''.join(fixed_parts), issues


def fix_repetitive_escalation(text: str, max_repeat: int = 2) -> tuple[str, list[dict]]:
    """检测并修复重复递进（越来越X/放弃X/碾成X 连续3+个）。

    策略：保留前 max_repeat 个，多余的删除。
    """
    issues = []
    min_count = max_repeat + 1

    # 匹配连续重复模式
    patterns = [
        # 越来越X 连续（无标点分隔）— 排除"越"避免吃掉下一个匹配
        ('越来越', re.compile(r'(越来越[^越，,。！？；：!?,;:\s…—、]+)'),
         re.compile(r'(越来越[^越，,。！？；：!?,;:\s…—、]+(?:越来越[^越，,。！？；：!?,;:\s…—、]+){' + str(min_count - 1) + ',})')),
        # 放弃X 连续（感叹号分隔）
        ('放弃', re.compile(r'(放弃[^，,。！？；：!?,;:\s…—、]+)'),
         re.compile(r'((?:放弃[^，,。！？；：!?,;:\s…—、]+[！!？?]?\s*){' + str(min_count) + ',})')),
        # 碾成X 连续（顿号/逗号分隔）
        ('碾成', re.compile(r'(碾成[^，,。！？；：!?,;:\s…—、]+)'),
         re.compile(r'((?:碾成[^，,。！？；：!?,;:\s…—、]+[、，,]?\s*){' + str(min_count) + ',})')),
        # 冲进X 连续
        ('冲进', re.compile(r'(冲进[^，,。！？；：!?,;:\s…—、]+)'),
         re.compile(r'((?:冲进[^，,。！？；：!?,;:\s…—、]+[，,]?\s*){' + str(min_count) + ',})')),
    ]

    for label, single_pat, multi_pat in patterns:
        # 先收集所有匹配，再倒序替换避免位置错乱
        replacements = []
        for m in multi_pat.finditer(text):
            match = m.group()
            sub_count = len(single_pat.findall(match))
            if sub_count > max_repeat:
                issues.append({
                    'type': 'repetitive_escalation',
                    'pattern': label,
                    'count': sub_count,
                    'preview': match[:60] + '...',
                    'suggestion': f'"{label}"连续{sub_count}次，已截断为{max_repeat}次'
                })
                # 截断：保留前 max_repeat 个匹配
                all_matches = single_pat.findall(match)
                kept = ''.join(all_matches[:max_repeat])
                # 清理截断尾部的多余标点
                kept = re.sub(r'[！!？?…—、，,\s]+$', '。', kept)
                replacements.append((m.start(), m.end(), match, kept))
        # 倒序替换，避免位置偏移
        for start, end, match, kept in reversed(replacements):
            text = text[:start] + kept + text[end:]

    return text, issues


def post_process_text(text: str) -> tuple[str, list[dict]]:
    """主入口：对polish后的文本做后处理。

    流程：
    1. 规则修复：感叹号轰炸 + 重复递进（可直接改）
    2. 检测报告：无标点长句 + 排比过载（返回给调用方决定是否LLM修复）

    Returns:
        (修复后文本, 问题列表)
    """
    all_issues = []

    # 1. 感叹号轰炸修复
    text, issues = fix_exclamation_bombing(text, max_per_para=2)
    all_issues.extend(issues)

    # 2. 重复递进修复
    text, issues = fix_repetitive_escalation(text, max_repeat=2)
    all_issues.extend(issues)

    # 3. 检测无标点长句（报告，不自动修复——需要LLM断句）
    issues = detect_long_unpunctuated(text, threshold=50)
    all_issues.extend(issues)

    # 4. 检测排比过载（报告，不自动修复——需要LLM改写）
    issues = detect_parallelism_overload(text, min_repeat=4, prefix_len=3)
    all_issues.extend(issues)

    if all_issues:
        logger.info("post_process_text: 发现 %d 个问题", len(all_issues))

    return text, all_issues
