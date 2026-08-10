"""书籍章节检测与拆分。

支持中英文章节标题模式：
  - 第一章 / 第1章 / 第 1 章 / 第1234章
  - 第一回 / 第1回 / 第一節 / 第1节
  - Chapter 1 / CHAPTER I / Chap. 5
  - 卷一 / 卷1 / 序章 / 楔子 / 尾声 / 后记 / 番外

如果无法检测到章节标题，按字数均匀切分（每章 ~3000 字）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chapter:
    """拆分出的一个章节。"""
    index: int          # 0-based 序号
    title: str          # 章节标题（不含换行）
    content: str        # 章节正文
    char_count: int     # 正文字数

    def preview(self, n: int = 200) -> str:
        return self.content[:n] + ("..." if len(self.content) > n else "")


# ── 正则模式 ──────────────────────────────────────────────

# 中文数字 0-99 的正则（一到九十九 / 零 / 〇）
_CN_NUM = r"[零〇一二三四五六七八九十百千万两]"
_CN_NUM_SEQ = rf"{_CN_NUM}+"

# 中文数字章节：第一章 / 第 1 章 / 第十二回 / 第一節
_PAT_CN_CHAPTER = re.compile(
    rf"^\s*第\s*({_CN_NUM_SEQ}|\d+)\s*[章节回節卷篇话話]\s*[^\n]*$",
    re.MULTILINE,
)

# 纯数字章节：1. / 01、 / 001】 等行首数字标记
# 但要避免误匹配正文中的数字，要求行首 + 标题短（<30字）
_PAT_NUM_CHAPTER = re.compile(
    r"^\s*(\d{1,4})\s*[\.、\]】\):：]\s*([^\n]{0,50})$",
    re.MULTILINE,
)

# 英文章节：Chapter 1 / CHAPTER I / Chap. 5
_PAT_EN_CHAPTER = re.compile(
    r"^\s*(?:CHAPTER|Chapter|chap\.?|Ch\.?)\s+([IVXLCDM]+|\d+)\s*[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)

# 特殊章节：序章 / 楔子 / 引子 / 尾声 / 终章 / 后记 / 番外 / 前言 / 引言
_PAT_SPECIAL = re.compile(
    r"^\s*(序章|楔子|引子|前言|引言|序幕|尾声|終章|终章|后记|後記|番外篇?|番外|终章|完结章|尾声|結章|结语|跋)[^\n]*$",
    re.MULTILINE,
)

# 合并所有模式的捕获组名 -> 用于排序
_ALL_PATTERNS = [_PAT_CN_CHAPTER, _PAT_NUM_CHAPTER, _PAT_EN_CHAPTER, _PAT_SPECIAL]

# 无章节标题时的默认切分大小
_DEFAULT_CHUNK_SIZE = 3000


def detect_chapters(text: str) -> list[Chapter]:
    """从全文中检测章节并拆分。

    返回 Chapter 列表。如果检测不到任何章节标题，按 _DEFAULT_CHUNK_SIZE 均匀切分。
    """
    # 收集所有匹配位置
    matches: list[tuple[int, int, str]] = []  # (start, end, title)

    for pat in _ALL_PATTERNS:
        for m in pat.finditer(text):
            title = m.group(0).strip()
            # 去重：同一位置可能被多个模式匹配，保留最长的标题
            pos = m.start()
            existing = next((x for x in matches if abs(x[0] - pos) < 5), None)
            if existing:
                if len(title) > len(existing[2]):
                    matches.remove(existing)
                    matches.append((m.start(), m.end(), title))
            else:
                matches.append((m.start(), m.end(), title))

    if len(matches) < 2:
        # 章节数太少，可能是没有结构化标题，走均匀切分
        return _split_by_size(text)

    # 按位置排序
    matches.sort(key=lambda x: x[0])

    chapters: list[Chapter] = []
    for i, (start, title_end, title) in enumerate(matches):
        # 正文从标题后到下一个标题前
        content_start = title_end
        content_end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        if not content:
            continue
        chapters.append(Chapter(
            index=len(chapters),
            title=title,
            content=content,
            char_count=len(content),
        ))

    if not chapters:
        return _split_by_size(text)

    # 过滤过短的"章节"（< 100 字，可能是误匹配）
    filtered = [c for c in chapters if c.char_count >= 100]
    if len(filtered) < len(chapters) * 0.5:
        # 过滤掉了超过一半，说明可能是误匹配，走均匀切分
        return _split_by_size(text)

    # 重新编号
    for i, c in enumerate(filtered):
        c.index = i
    return filtered


def _split_by_size(text: str, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> list[Chapter]:
    """无章节标题时按字数均匀切分。"""
    text = text.strip()
    if not text:
        return []
    chapters: list[Chapter] = []
    # 尽量在段落边界切分
    paragraphs = text.split("\n")
    current: list[str] = []
    current_len = 0
    idx = 1

    for para in paragraphs:
        current.append(para)
        current_len += len(para)
        if current_len >= chunk_size:
            content = "\n".join(current).strip()
            chapters.append(Chapter(
                index=len(chapters),
                title=f"第{idx}节（自动切分）",
                content=content,
                char_count=len(content),
            ))
            current = []
            current_len = 0
            idx += 1

    # 剩余部分
    if current:
        content = "\n".join(current).strip()
        if len(content) >= 50:
            chapters.append(Chapter(
                index=len(chapters),
                title=f"第{idx}节（自动切分）",
                content=content,
                char_count=len(content),
            ))

    return chapters
