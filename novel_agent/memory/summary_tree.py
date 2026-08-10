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

    def get_volume_summary(self, volume: int) -> str:
        """获取某卷的压缩摘要。

        B4修复：优先读已存储的LLM卷摘要（存在volume级Outline的summary字段），
        而非从章摘要机械截断100字。
        """
        # 1. 优先读已存储的LLM卷摘要
        from novel_agent.bible.models import Outline
        vol_outline = self.repo.db.query(Outline).filter(
            Outline.project_id == self.repo.project_id,
            Outline.level == "volume",
            Outline.order == volume,
        ).first()
        if vol_outline and vol_outline.summary and len(vol_outline.summary) > 50:
            return vol_outline.summary

        # 2. fallback：从章摘要机械拼接
        summaries = self.repo.list_chapter_summaries(limit=2000)
        if not summaries:
            return ""
        start = (volume - 1) * 30 + 1
        end = volume * 30
        volume_summaries = [s for s in summaries if start <= s.chapter <= end]
        if not volume_summaries:
            return ""
        volume_summaries.sort(key=lambda s: s.chapter)
        lines = [
            f"第{s.chapter}章《{s.title}》：{s.core_events}"
            for s in volume_summaries[-20:]
        ]
        return "【卷摘要】\n" + "\n".join(lines)

    async def generate_volume_summary(self, volume: int, llm_client) -> str:
        """用 LLM 压缩某卷的章摘要为叙事性卷摘要，存库后返回。"""
        summaries = self.repo.list_chapter_summaries(limit=1000)
        if not summaries:
            return ""
        start = (volume - 1) * 30 + 1
        end = volume * 30
        volume_summaries = [s for s in summaries if start <= s.chapter <= end]
        if not volume_summaries:
            return ""
        volume_summaries.sort(key=lambda s: s.chapter)

        # 拼接各章摘要
        chapter_texts = "\n".join(
            f"第{s.chapter}章《{s.title}》：{s.core_events}" for s in volume_summaries
        )

        prompt = (
            f"以下是第{volume}卷（第{start}章到第{end}章）的各章摘要。"
            f"请压缩为一个 300-500 字的叙事性卷摘要，包含：\n"
            f"1. 本卷主线发展\n2. 关键转折\n3. 遗留悬念\n\n"
            f"各章摘要：\n{chapter_texts}\n\n"
            f"只输出摘要正文，不要 JSON 或格式标记。"
        )

        try:
            summary = await llm_client.generate(prompt, system="你是网文摘要助手，擅长压缩叙事。")
            return f"【第{volume}卷摘要】\n{summary}"
        except Exception:
            # fallback 到机械截断
            lines = [f"第{s.chapter}章：{s.core_events}" for s in volume_summaries[-20:]]
            return "【卷摘要】\n" + "\n".join(lines)
