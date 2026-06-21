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
        """获取某卷的压缩摘要。无 volume 字段时按章号范围分卷（每30章一卷）。"""
        summaries = self.repo.list_chapter_summaries(limit=1000)
        if not summaries:
            return ""
        # 按 volume 过滤：每30章一卷
        start = (volume - 1) * 30 + 1
        end = volume * 30
        volume_summaries = [s for s in summaries if start <= s.chapter <= end]
        if not volume_summaries:
            return ""
        volume_summaries.sort(key=lambda s: s.chapter)
        # 最多20章，取该卷最后20章
        lines = [
            f"第{s.chapter}章《{s.title}》：{s.core_events[:100]}"
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
            lines = [f"第{s.chapter}章：{s.core_events[:100]}" for s in volume_summaries[-20:]]
            return "【卷摘要】\n" + "\n".join(lines)

    def get_full_summary(self) -> str:
        """获取全量摘要：最近10章详细 + 更早的卷级压缩。"""
        project = self.repo.get_project()
        parts = [f"《{project.title}》"] if project else []
        summaries = self.repo.list_chapter_summaries(limit=1000)
        if not summaries:
            return "\n".join(parts)
        summaries.sort(key=lambda s: s.chapter)
        if len(summaries) <= 10:
            parts.append(
                "\n".join(
                    f"第{s.chapter}章《{s.title}》：{s.core_events}" for s in summaries
                )
            )
            return "\n".join(parts)
        recent = summaries[-10:]
        older = summaries[:-10]
        # 更早的只取 core_events 前100字
        older_text = "\n".join(
            f"第{s.chapter}章《{s.title}》：{s.core_events[:100]}" for s in older
        )
        recent_text = "\n".join(
            f"第{s.chapter}章《{s.title}》：{s.core_events}" for s in recent
        )
        parts.append(
            f"【早期章节摘要】\n{older_text}\n\n【近期章节摘要】\n{recent_text}"
        )
        return "\n".join(parts)
