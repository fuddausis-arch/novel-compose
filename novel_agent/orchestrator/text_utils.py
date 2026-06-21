"""文本处理工具：章节正文清洗与 JSON 结构检测。

从 nodes.py 拆出，供编排节点复用。
"""
from __future__ import annotations

import re


def clean_chapter_text(text: str, chapter: int, title: str = "") -> str:
    """清理 LLM 生成的常见格式垃圾，返回纯净正文。"""
    if not text:
        return ""
    s = text
    # 去掉 markdown 章节标题行（# 第X章 ...）
    s = re.sub(r"^#+\s*第[\d一二三四五六七八九十百千万]+章[：:\s]*.*$", "", s, flags=re.MULTILINE)
    # 去掉 --- 分隔线
    s = re.sub(r"^\s*---+\s*$", "", s, flags=re.MULTILINE)
    # 去掉 markdown 加粗/斜体但保留文字
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<![*])\*([^*]+)\*(?![*])", r"\1", s)
    # 合并连续空行
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _looks_like_json_not_prose(text: str) -> bool:
    """检测 LLM 是否返回了 JSON 结构而非小说正文。"""
    s = text.strip()
    # 以 { 开头 } 结尾，大概率是 JSON
    if s.startswith("{") and s.endswith("}"):
        return True
    # 以 [ 开头 ] 结尾，可能是 JSON 数组
    if s.startswith("[") and s.endswith("]"):
        return True
    # 检测常见 JSON 结构关键词
    json_markers = ['"suggestions"', '"payload"', '"chapters"', '"volumes"',
                    '"arcs"', '"error"', '"message"', '"characters"',
                    '"world_settings"', '"foreshadows"']
    for marker in json_markers:
        if marker in s:
            # 但要排除正文中偶然出现的这些词（如对话中说 "error"）
            # 只有当它以 JSON 格式出现时才判定
            # 简单 heuristic：如果文本前 200 字符内出现这些 marker，判定为 JSON
            if marker in s[:200]:
                return True
    return False
