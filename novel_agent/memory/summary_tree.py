"""Summary tree：章→弧→卷→全书分层摘要。

M1：只实现章摘要查询与拼接；弧/卷摘要由 M3 的 Summarizer agent 生成后存库。
"""
from __future__ import annotations

from novel_agent.bible.repository import BibleRepository


class SummaryTree:
    """分层摘要树读取。"""

    def __init__(self, repo: BibleRepository):
        self.repo = repo

    def get_recent_chapter_summaries(self, count: int = 5):
        """最近 N 章摘要，按章节升序。"""
        recent = self.repo.list_chapter_summaries(limit=count)
        return sorted(recent, key=lambda s: s.chapter)

    def get_arc_summary(self, arc_chapters: list[int]) -> str:
        """某弧的摘要。M1：拼接该弧内各章摘要。"""
        parts = []
        for ch in arc_chapters:
            s = self.repo.get_chapter_summary(ch)
            if s:
                parts.append(f"第{ch}章《{s.title}》：{s.core_events}")
        return "\n".join(parts)

    def get_volume_summary(self, volume: int) -> str:
        """某卷摘要。M3 由 Summarizer 生成。M1 返回空串。"""
        return ""

    def get_full_summary(self) -> str:
        """全书摘要：项目标题 + 所有章摘要拼接（M1 简化）。"""
        project = self.repo.get_project()
        parts = [f"《{project.title}》"] if project else []
        summaries = self.repo.list_chapter_summaries(limit=1000)
        for s in sorted(summaries, key=lambda x: x.chapter):
            parts.append(f"第{s.chapter}章《{s.title}》：{s.core_events}")
        return "\n".join(parts)
