"""Memory Pack：按 webnovel-writer 思路分三层控制上下文预算。

- working memory：本章必须知道的真源（项目、章纲、活跃伏笔、当前实体状态快照）
- episodic memory：近期发生的事实（状态变更、人物关系变更、近期章摘要）
- semantic memory：长期知识（世界观、角色卡、题材模板、参考资料）

每层按字符预算截断，避免长文上下文爆炸。
"""
from __future__ import annotations

from dataclasses import dataclass

from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.recall import RecallMemory
from novel_agent.references.search import ReferenceSearch, canonical_genre
from novel_agent.templates.loader import GenreLoader


@dataclass
class MemoryBudget:
    """字符预算（近似 token，中文字符按 1:1.5 token 估算）。"""
    total: int = 12000
    working_ratio: float = 0.30
    episodic_ratio: float = 0.40
    semantic_ratio: float = 0.30

    def working(self) -> int:
        return int(self.total * self.working_ratio)

    def episodic(self) -> int:
        return int(self.total * self.episodic_ratio)

    def semantic(self) -> int:
        return int(self.total * self.semantic_ratio)


class MemoryPackBuilder:
    """为指定章节组装带预算控制的记忆包。"""

    def __init__(self, repo: BibleRepository, chapter: int, recall: RecallMemory):
        self.repo = repo
        self.chapter = chapter
        self.recall = recall

    def build(self, budget: MemoryBudget | None = None) -> dict[str, str]:
        budget = budget or MemoryBudget()
        return {
            "working": self._working_memory(budget.working()),
            "episodic": self._episodic_memory(budget.episodic()),
            "semantic": self._semantic_memory(budget.semantic()),
        }

    def _working_memory(self, limit: int) -> str:
        sections = []
        project = self.repo.get_project()
        if project:
            sections.append(f"【项目】{project.title}（{project.genre}）\n简介：{project.summary}\n文风：{project.style}")

        outline = next((o for o in self.repo.list_outlines() if o.order == self.chapter), None)
        if outline:
            sections.append(f"【本章大纲】第{outline.order}章 {outline.title}\n{outline.summary}\nstrand={outline.strand}")

        to_plant = self.repo.get_foreshadows_to_plant(self.chapter)
        if to_plant:
            sections.append("【本章需埋伏笔】\n" + "\n".join(
                f"- {f.foreshadow_id}（{f.tier}）：{f.description}（计划{f.planned_resolve_chapter}章回收）"
                for f in to_plant
            ))

        to_resolve = self.repo.get_foreshadows_to_resolve(self.chapter)
        if to_resolve:
            sections.append("【本章需回收伏笔】\n" + "\n".join(
                f"- {f.foreshadow_id}：{f.description}" for f in to_resolve
            ))

        active = self.repo.get_foreshadows_by_status("planted") + self.repo.get_foreshadows_by_status("developing")
        if active:
            sections.append("【当前活跃伏笔】\n" + "\n".join(
                f"- {f.foreshadow_id}（{f.status}）：{f.description}" for f in active
            ))

        # 当前实体状态快照（按最近状态变更聚合）
        changes = self.repo.list_state_changes()
        latest = {}
        for sc in changes:
            key = f"{sc.entity_type}:{sc.entity_id}:{sc.field}"
            latest[key] = sc.new_value
        if latest:
            sections.append("【当前实体状态快照】\n" + "\n".join(f"- {k} = {v}" for k, v in list(latest.items())[:30]))

        # 活跃设定：最近章节出场的角色/势力/怪物及其关键信息
        active = self.repo.get_active_entities_for_chapter(self.chapter, window=3)
        active_lines = ["【活跃设定】"]
        if active.get("characters"):
            active_lines.append("近期出场角色：")
            for c in active["characters"]:
                parts = [f"- {c['name']}（重要度：{c['importance'] or '未标'} / 身份：{c['role'] or '未标'}）"]
                if c.get("current_location"):
                    parts.append(f"  位置：{c['current_location']}")
                if c.get("current_emotion"):
                    parts.append(f"  情绪：{c['current_emotion']}")
                if c.get("known_info"):
                    parts.append(f"  已知信息：{c['known_info']}")
                if c.get("relationships"):
                    parts.append(f"  关系：{', '.join(c['relationships'])}")
                if c.get("recent_changes"):
                    parts.append(f"  近期状态变更：{', '.join(c['recent_changes'])}")
                parts.append(f"  本章角色：{c['role_in_chapter']}")
                active_lines.extend(parts)
        if active.get("factions"):
            active_lines.append("近期出场势力：")
            for f in active["factions"]:
                line = f"- {f['name']}（层级：{f['tier'] or '未标'} / 类型：{f['type'] or '未标'} / 阵营：{f['alignment'] or '未标'} / 本章角色：{f['role_in_chapter']}）"
                active_lines.append(line)
                if f.get("relationships"):
                    active_lines.append(f"  关系：{', '.join(f['relationships'])}")
        if active.get("monsters"):
            active_lines.append("近期出场怪物：")
            for m in active["monsters"]:
                active_lines.append(
                    f"- {m['name']}（层级：{m['tier'] or '未标'} / 物种：{m['species'] or '未标'} / 等级：{m['rank'] or '未标'} / 本章角色：{m['role_in_chapter']}）"
                )
        if len(active_lines) > 1:
            sections.append("\n".join(active_lines))

        return self._truncate("\n\n".join(sections), limit)

    def _episodic_memory(self, limit: int) -> str:
        sections = []

        # 近期章节摘要（优先于全文）
        summaries = [s for s in self.repo.list_chapter_summaries(limit=5) if s.chapter < self.chapter]
        if summaries:
            sections.append("【近期章摘要】\n" + "\n".join(
                f"第{s.chapter}章《{s.title}》：{s.core_events or '无摘要'}"
                for s in sorted(summaries, key=lambda x: x.chapter)
            ))
        else:
            # fallback 读最近1章正文末尾
            prev_chapters = sorted([c for c in self.recall.list_chapters() if c < self.chapter], reverse=True)[:1]
            if prev_chapters:
                tail = self.recall.read_chapter_text(prev_chapters[0])[-1200:]
                sections.append(f"【上章结尾】\n{tail}")

        # 近期状态变更（取最新 20 条）
        recent_changes = self.repo.list_state_changes()[-20:]
        if recent_changes:
            sections.append("【近期状态变更】\n" + "\n".join(
                f"第{sc.chapter}章：{sc.entity_type}「{sc.entity_id}」的「{sc.field}」变为「{sc.new_value}」"
                for sc in recent_changes
            ))

        # 近期事件（排除状态变更，保留关系/世界规则等）
        events = [e for e in self.repo.list_events() if e.chapter < self.chapter][-15:]
        if events:
            sections.append("【近期关键事件】\n" + "\n".join(
                f"第{e.chapter}章 [{e.type}] {e.entity_id}: {e.payload}"
                for e in events
            ))

        return self._truncate("\n\n".join(sections), limit)

    def _semantic_memory(self, limit: int) -> str:
        sections = []

        project = self.repo.get_project()
        if project:
            cg = canonical_genre(project.genre)
            template = GenreLoader().load(cg)
            if template:
                sections.append(f"【题材模板：{cg}】\n{template}")

            refs = ReferenceSearch().for_skill("webnovel-write", canonical_genre=cg, limit=6)
            if refs:
                sections.append("【题材参考资料】\n" + "\n".join(
                    f"- {r.get('关键词', '')}: {r.get('核心摘要', '')}"
                    for r in refs
                ))

        world = self.repo.list_world_settings()
        if world:
            sections.append("【世界观设定】\n" + "\n".join(
                f"【{w.category}】{w.title}：{w.content[:300]}" for w in world
            ))

        chars = self.repo.list_characters()
        if chars:
            sections.append("【角色卡】\n" + "\n".join(
                f"- {c.name}（{c.role}）：{c.personality or '无'}；动机：{c.motivation or '无'}；"
                f"位置={c.current_location} 情绪={c.current_emotion}"
                for c in chars
            ))

        return self._truncate("\n\n".join(sections), limit)

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        # 尽量在段落边界截断
        cut = text[:limit]
        last_break = max(cut.rfind("\n\n"), cut.rfind("\n"))
        if last_break > limit * 0.8:
            cut = cut[:last_break]
        return cut.strip() + "\n[...记忆截断...]"
