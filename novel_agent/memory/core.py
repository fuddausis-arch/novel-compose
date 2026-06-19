"""Core memory：每章注入的常驻上下文（~2-4k token）。

包含：项目基础信息 + 当前活跃角色 + 当前卷大纲 + 未回收伏笔子集
     + archival 检索回的相关历史切片（spec 2.1，视频启发增强）。
"""
from __future__ import annotations

from typing import Any

from novel_agent.bible.repository import BibleRepository


class CoreMemoryAssembler:
    """装配某章生成时的常驻上下文。"""

    def __init__(self, repo: BibleRepository, archival: Any | None = None):
        """
        Args:
            repo: 圣经仓储
            archival: 可选的 ArchivalMemory，提供则按 query 检索历史切片注入
        """
        self.repo = repo
        self.archival = archival

    def assemble(self, chapter: int, max_chars: int = 8000,
                 query: str | None = None) -> str:
        sections: list[str] = []

        # 本章细纲：生成层必须围绕的剧情约束
        chapter_outline = self._chapter_outline_summary(chapter)
        if chapter_outline:
            sections.append(chapter_outline)
        else:
            sections.append("【本章细纲】\n当前暂无本章细纲，请基于项目整体规划自由发挥。")

        project = self.repo.get_project()
        if project:
            sections.append(self._format_project(project))
        # 当前活跃角色（M1 简化：全部角色；M3 优化为按本章出场筛选）
        chars = self.repo.list_characters()
        if chars:
            sections.append(self._format_characters(chars))
        # 本章应埋伏笔
        to_plant = self.repo.get_foreshadows_to_plant(chapter)
        if to_plant:
            sections.append(self._format_to_plant(to_plant))
        # 本章应回收伏笔
        to_resolve = self.repo.get_foreshadows_to_resolve(chapter)
        if to_resolve:
            sections.append(self._format_to_resolve(to_resolve))
        # archival 检索：注入与本章相关的历史切片
        if self.archival and query:
            slices = self.archival.retrieve(query=query, top_k=4)
            if slices:
                sections.append(self._format_archival(slices))

        ctx = "\n\n".join(sections)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars] + "\n[...截断...]"
        return ctx

    def _format_project(self, project) -> str:
        parts = [f"【小说标题】\n{project.title}"]
        if project.genre:
            parts.append(f"【类型】\n{project.genre}")
        if project.summary:
            parts.append(f"【简介】\n{project.summary}")
        if project.style:
            parts.append(f"【风格规范】\n{project.style}")
        return "\n".join(parts)

    def _format_characters(self, chars) -> str:
        lines = ["【当前角色状态】"]
        for c in chars:
            info = f"- {c.name}（{c.role or '角色'}）"
            if c.current_location:
                info += f" | 位置：{c.current_location}"
            if c.current_emotion:
                info += f" | 情绪：{c.current_emotion}"
            if c.personality:
                info += f" | 性格：{c.personality}"
            lines.append(info)
        return "\n".join(lines)

    def _format_to_plant(self, foreshadows) -> str:
        lines = ["【本章应埋伏笔】"]
        for f in foreshadows:
            lines.append(f"- {f.foreshadow_id}：{f.description}（计划第 {f.planned_resolve_chapter} 章回收）")
        return "\n".join(lines)

    def _format_to_resolve(self, foreshadows) -> str:
        lines = ["【本章应回收伏笔】"]
        for f in foreshadows:
            lines.append(f"- {f.foreshadow_id}：{f.description}")
        return "\n".join(lines)

    def _format_archival(self, slices: list[dict]) -> str:
        lines = ["【相关历史切片】（按语义相关性召回）"]
        for s in slices:
            chapter = s.get("chapter")
            tag = f"第{chapter}章" if chapter else "设定"
            lines.append(f"- [{tag}] {s['content']}")
        return "\n".join(lines)

    def _chapter_outline_summary(self, chapter: int) -> str:
        """读取本章细纲，注入 writer 上下文。"""
        outlines = self.repo.list_outlines(level="chapter")
        match = next((o for o in outlines if o.order == chapter), None)
        if not match:
            return ""
        lines = ["【本章细纲】"]
        lines.append(f"标题：{match.title}")
        lines.append(f"概要：{match.summary}")
        if match.act:
            lines.append(f"节奏：{match.act}")
        if match.strand:
            lines.append(f"故事线：{match.strand}")
        return "\n".join(lines)
