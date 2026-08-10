"""编排层工具函数：标签匹配、题材判断、温度调整等纯逻辑。

这些函数不依赖 LangGraph state，可独立测试和复用。
"""
from __future__ import annotations

from novel_agent.orchestrator.constants import (
    BOOK_TAGS, BEAT_TAG_MAP, GENRE_TAG_AFFINITY, TEMP_MAP,
)


def books_for_beat(beat_type: str) -> list[str] | None:
    """根据 beat_type 推断应该优先查哪些书。返回 None 表示不过滤（查全部）。"""
    if not beat_type:
        return None
    text = beat_type.lower()
    matched_tags: set[str] = set()
    for tag, keywords in BEAT_TAG_MAP.items():
        if any(kw in text for kw in keywords):
            matched_tags.add(tag)
    if not matched_tags:
        return None
    relevant_books = [
        book for book, tags in BOOK_TAGS.items()
        if matched_tags & set(tags)
    ]
    return relevant_books if relevant_books else None


def genre_matches_corpus(genre: str) -> list[str] | None:
    """判断项目题材是否与现有语感库（末日/克苏鲁系）匹配。

    返回匹配的标签列表；返回 None 表示题材不匹配，应跳过语感注入。
    """
    if not genre:
        return None
    text = genre.strip().lower()
    for g, tags in GENRE_TAG_AFFINITY.items():
        if g in text:
            return tags
    return None


def get_temperature_for_narrative(narrative_function: str, base_temp: float = 0.8) -> float:
    """根据章节叙事功能动态调整 temperature。

    高创意任务（情感/高潮/人物）→ 高温度
    高逻辑任务（推理/揭示/收束）→ 低温度
    匹配不到时用 base_temp。
    """
    if not narrative_function:
        return base_temp
    for key, temp in TEMP_MAP.items():
        if key in narrative_function:
            return temp
    return base_temp
