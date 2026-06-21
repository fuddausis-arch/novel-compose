"""Core memory：每章注入的常驻上下文（~2-4k token）。

包含：项目基础信息 + 当前活跃角色 + 当前卷大纲 + 未回收伏笔子集
     + 前文章节摘要（卷级压缩，防止长篇上下文爆炸）
     + archival 检索回的相关历史切片（spec 2.1，视频启发增强）。
"""
from __future__ import annotations

from typing import Any

from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.summary_tree import SummaryTree


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
        self.summary_tree = SummaryTree(repo)

    def assemble(self, chapter: int, max_chars: int = 8000,
                 query: str | None = None) -> str:
        """装配上下文，按优先级分配预算，低优先级内容被压缩而非截断高优先级。"""
        # 预先计算各段文本
        # 1. 高优先级（必须完整）：本章细纲
        chapter_outline = self._chapter_outline_summary(chapter)
        # 2. 高优先级：前文摘要（长篇关键）
        prev_summary = ""
        if chapter > 1:
            prev_summary = self._format_previous_summaries(chapter)
        # 3. 中优先级：项目信息
        project = self.repo.get_project()
        project_text = self._format_project(project) if project else ""
        # 4. 中优先级：角色（可裁剪）
        all_chars = self.repo.list_characters()
        chars = self._filter_characters_for_chapter(chapter, all_chars)
        chars_text = self._format_characters(chars) if chars else ""
        # 5. 中优先级：伏笔（硬约束，置于角色之前）
        to_plant = self.repo.get_foreshadows_to_plant(chapter)
        plant_text = self._format_to_plant(to_plant) if to_plant else ""
        to_resolve = self.repo.get_foreshadows_to_resolve(chapter)
        resolve_text = self._format_to_resolve(to_resolve) if to_resolve else ""
        # 6. 低优先级：archival
        archival_text = ""
        if self.archival and query:
            slices = self.archival.retrieve(query=query, top_k=4)
            if slices:
                archival_text = self._format_archival(slices)

        # 按优先级分配预算
        sections: list[str] = []
        remaining = max_chars

        # 1. 细纲（最高优先级，不压缩）
        if chapter_outline:
            sections.append(chapter_outline)
            remaining -= len(chapter_outline) + 2  # +2 for \n\n
        else:
            fallback = "【本章细纲】\n当前暂无本章细纲，请基于项目整体规划自由发挥。"
            sections.append(fallback)
            remaining -= len(fallback) + 2

        # 2. 前文摘要
        if prev_summary:
            if len(prev_summary) + 2 <= remaining:
                sections.append(prev_summary)
                remaining -= len(prev_summary) + 2
            elif remaining > 200:
                sections.append(prev_summary[:remaining])
                remaining = 0

        # 3. 项目信息
        if project_text and len(project_text) + 2 <= remaining:
            sections.append(project_text)
            remaining -= len(project_text) + 2

        # 4. 伏笔（在角色之前，因为伏笔是硬约束）
        if plant_text and len(plant_text) + 2 <= remaining:
            sections.append(plant_text)
            remaining -= len(plant_text) + 2
        if resolve_text and len(resolve_text) + 2 <= remaining:
            sections.append(resolve_text)
            remaining -= len(resolve_text) + 2
        # 4.5 逾期未回收伏笔提示（硬约束，紧随伏笔部分）
        overdue = self.repo.get_overdue_foreshadows(chapter)
        if overdue:
            overdue_lines = ["【逾期伏笔提醒】以下伏笔已超过计划回收章节，请在本章或近期回收："]
            for f in overdue[:5]:  # 最多提示5个
                overdue_lines.append(f"- {f.foreshadow_id}：{f.description[:60]}（计划第{f.planned_resolve_chapter}章回收）")
            overdue_text = "\n".join(overdue_lines)
            if len(overdue_text) + 2 <= remaining:
                sections.append(overdue_text)
                remaining -= len(overdue_text) + 2
            elif remaining > 200:
                sections.append(overdue_text[:remaining])
                remaining = 0

        # 5. 角色（可压缩：只保留名字+角色类型）
        if chars_text:
            if len(chars_text) + 2 <= remaining:
                sections.append(chars_text)
                remaining -= len(chars_text) + 2
            elif remaining > 200:
                # 压缩：只保留名字和角色
                compressed = "【角色】\n" + "\n".join(
                    f"- {c.name}（{c.role or '角色'}）" for c in chars[:20]
                )
                if len(compressed) + 2 <= remaining:
                    sections.append(compressed)

        # 6. archival（最低优先级）
        if archival_text and len(archival_text) + 2 <= remaining:
            sections.append(archival_text)

        return "\n\n".join(sections)

    def _filter_characters_for_chapter(self, chapter: int, all_chars: list,
                                       max_chars: int = 20) -> list:
        """筛选本章相关角色：本章大纲中提到的 + 最近出现的 + 主角/重要角色。

        长篇小说角色可能上百，全量注入会撑爆 core memory 的 max_chars 上限，
        故按相关性裁剪到 max_chars 个。
        """
        if len(all_chars) <= max_chars:
            return all_chars

        selected: list = []
        # 1. 主角/反派优先（占一半配额）
        role_quota = max_chars // 2
        for c in all_chars:
            if c.role in ("主角", "反派") and len(selected) < role_quota:
                selected.append(c)

        # 2. 本章大纲中提到的角色
        outline = self._chapter_outline_summary(chapter)
        if outline:
            for c in all_chars:
                if c not in selected and c.name and c.name in outline:
                    selected.append(c)
                    if len(selected) >= max_chars:
                        break

        # 3. 最近3章摘要中出现的角色
        if len(selected) < max_chars:
            try:
                summaries = self.repo.list_chapter_summaries()
                recent = [s for s in summaries
                          if s.chapter >= chapter - 3 and s.chapter < chapter]
                recent_text = " ".join(s.characters_present or "" for s in recent)
                for c in all_chars:
                    if c not in selected and c.name and c.name in recent_text:
                        selected.append(c)
                        if len(selected) >= max_chars:
                            break
            except Exception:
                pass

        # 4. 如果还不够，补满到 max_chars
        for c in all_chars:
            if c not in selected and len(selected) < max_chars:
                selected.append(c)

        return selected

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

    def _format_previous_summaries(self, chapter: int) -> str:
        """注入前文摘要：最近 5 章详细 + 更早的卷级压缩。"""
        recent = self.summary_tree.get_recent_chapter_summaries(count=5)
        if not recent:
            return ""
        lines = ["【前文摘要】"]
        # 最近 5 章详细
        for s in recent:
            if s.chapter < chapter:
                lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events[:200]}")
        # 如果超过 5 章历史，加上一卷的摘要（取首尾各3章，避免噪声）
        all_summaries = self.repo.list_chapter_summaries(limit=1000)
        if len(all_summaries) > 5:
            older = [s for s in all_summaries if s.chapter < chapter - 5]
            if len(older) > 6:
                # 取最早 3 章 + 最近 3 章，中间省略
                older.sort(key=lambda s: s.chapter)
                for s in older[:3]:
                    lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events[:80]}")
                lines.append(f"...（省略 {len(older) - 6} 章）...")
                for s in older[-3:]:
                    lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events[:80]}")
            elif older:
                older.sort(key=lambda s: s.chapter)
                for s in older:
                    lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events[:80]}")
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
