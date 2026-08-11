"""Core memory：每章注入的常驻上下文（~2-4k token）。

包含：项目基础信息 + 当前活跃角色 + 当前卷大纲 + 未回收伏笔子集
     + 前文章节摘要（卷级压缩，防止长篇上下文爆炸）
     + archival 检索回的相关历史切片（spec 2.1，视频启发增强）。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.summary_tree import SummaryTree

logger = logging.getLogger(__name__)


def _fit_full_paras(text: str, budget: int) -> str:
    """预算内保留尽量多的完整段落（不做半截硬切——"看全"原则）。

    段落是语义完整单元；宁可少给、全给，也不把段落从中间切掉。
    """
    if len(text) <= budget:
        return text
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    out: list[str] = []
    used = 0
    for p in paras:
        if used + len(p) + 2 > budget:
            break
        out.append(p)
        used += len(p) + 2
    return "\n\n".join(out)


def format_active_storylines(repo, chapter: int, max_lines: int = 6) -> str:
    """格式化当前故事线：主线必带 + 断线预警 + 最近推进的支线。

    与叙事线系统（storylines 表）联动：写手需要知道主线在哪、
    哪条线正在推进、哪条线快断了。断线阈值默认 5 章。
    独立函数供标准生成（core memory）与交互式创作两条路径共用。
    """
    try:
        from novel_agent.bible.models import Storyline
        lines = repo.db.query(Storyline).filter(
            Storyline.project_id == repo.project_id,
            Storyline.status == "active",
        ).all()
    except Exception:
        return ""
    if not lines:
        return ""

    def _is_main(l) -> bool:
        tags = l.tags or []
        return "主线" in tags or (l.line_type and "主线" in l.line_type)

    mains = [l for l in lines if _is_main(l)]
    stalled = [l for l in lines if chapter - (l.last_active_chapter or 0) >= 5]
    recent = [l for l in lines
              if not _is_main(l) and (l.last_active_chapter or 0) >= chapter - 3]

    picked: list = []
    for l in mains + stalled + recent:
        if l not in picked:
            picked.append(l)
        if len(picked) >= max_lines:
            break

    out = ["【当前故事线】"]
    for l in picked:
        gap = chapter - (l.last_active_chapter or 0)
        flag = "主线" if _is_main(l) else (f"⚠断线{gap}章" if gap >= 5 else "支线")
        line = f"- [{flag}] {l.name}"
        if l.progress:
            line += f"（进度{l.progress}%）"
        if gap > 0 and flag != "主线":
            line += f" 最近推进第{l.last_active_chapter}章"
        if l.summary:
            line += f" | {l.summary}"
        out.append(line)
    return "\n".join(out)


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
        self._cache: dict = {}  # 实例级缓存（同一次生成流程中复用查询结果）

    def _cached(self, key: str, factory):
        """缓存查询结果，避免同一次生成流程中重复查询同一批数据。"""
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    def assemble(self, chapter: int, max_chars: int = 12000,
                 query: str | None = None) -> str:
        """装配上下文，按优先级分配预算，低优先级内容被压缩而非截断高优先级。

        优先级（12000字符预算）：
        1. 本章细纲+约束载荷（不压缩）
        2. 角色状态快照（不压缩）— 阶段2后优先读快照
        3. 前文摘要（5章，可压缩）
        4. 逾期伏笔/欠账（top5，可截断）
        5. archival检索（最低，可全删）— 已从热路径移出

        阶段感知预算：早期重角色，中期重摘要，后期重世界观。
        """
        # 阶段感知：动态调整各段预算权重
        phase = self._get_phase(chapter)
        # prev_budget_ratio: 早期15%、中期30%、后期40%
        # world_budget_ratio: 早期10%、中期15%、后期25%
        if phase == "early":
            prev_budget_ratio, world_budget_ratio = 0.15, 0.10
        elif phase == "mid":
            prev_budget_ratio, world_budget_ratio = 0.30, 0.15
        else:  # late
            prev_budget_ratio, world_budget_ratio = 0.40, 0.25
        # 预先计算各段文本
        # 1. 高优先级（必须完整）：本章细纲
        chapter_outline = self._chapter_outline_summary(chapter)
        # 2. 高优先级：前文摘要（长篇关键）
        prev_summary = ""
        if chapter > 1:
            prev_summary = self._format_previous_summaries(chapter)
        # 3. 中优先级：项目信息
        project = self._cached("project", self.repo.get_project)
        project_text = self._format_project(project) if project else ""
        # 3.5 中优先级：世界观设定（写章节时必须知道的世界规则）
        world_settings = self._cached("world_settings", self.repo.list_world_settings)
        world_text = self._format_world_settings(world_settings) if world_settings else ""
        # 4. 中优先级：角色（可裁剪）- 优先读状态快照
        snapshot_text = self._format_snapshot(chapter)
        if snapshot_text:
            chars_text = snapshot_text
            # 仍需 chars 列表供后续压缩分支使用
            all_chars = self._cached("characters", self.repo.list_characters)
            chars = self._filter_characters_for_chapter(chapter, all_chars)
        else:
            all_chars = self._cached("characters", self.repo.list_characters)
            chars = self._filter_characters_for_chapter(chapter, all_chars)
            chars_text = self._format_characters(chars) if chars else ""
        # 5. 中优先级：伏笔（硬约束，置于角色之前）
        to_plant = self.repo.get_foreshadows_to_plant(chapter)
        plant_text = self._format_to_plant(to_plant) if to_plant else ""
        to_resolve = self.repo.get_foreshadows_to_resolve(chapter)
        resolve_text = self._format_to_resolve(to_resolve) if to_resolve else ""
        # 6. archival — 已从热路径移出（冷路径工具，阶段3 DedupScanner 使用）

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

        # 2. 伏笔（硬约束，不可压缩——必须在prev_summary之前分配预算）
        if plant_text:
            sections.append(plant_text)
            remaining -= len(plant_text) + 2
        if resolve_text:
            sections.append(resolve_text)
            remaining -= len(resolve_text) + 2
        # 2.5 逾期未回收伏笔提示（硬约束）
        overdue = self.repo.get_overdue_foreshadows(chapter)
        if overdue:
            overdue_lines = ["【逾期伏笔提醒】以下伏笔已超过计划回收章节，请在本章或近期回收："]
            for f in overdue[:5]:
                overdue_lines.append(f"- {f.foreshadow_id}：{f.description}（计划第{f.planned_resolve_chapter}章回收）")
            overdue_text = "\n".join(overdue_lines)
            sections.append(overdue_text)
            remaining -= len(overdue_text) + 2

        # 2.7 当前故事线（主线/支线 + 断线预警）— 与叙事线系统联动，硬约束
        storyline_text = self._format_active_storylines(chapter)
        if storyline_text:
            sections.append(storyline_text)
            remaining -= len(storyline_text) + 2

        # 2.8 剧情债（按压力排序，硬约束）— 上一章欠的账本章要还
        debt_text = self._format_open_debts()
        if debt_text:
            sections.append(debt_text)
            remaining -= len(debt_text) + 2

        # 3. 前文摘要（独立子预算：阶段感知，防止长篇后期撑爆）
        prev_budget = int(max_chars * prev_budget_ratio)
        if prev_summary:
            if len(prev_summary) + 2 <= min(remaining, prev_budget):
                sections.append(prev_summary)
                remaining -= len(prev_summary) + 2
            elif min(remaining, prev_budget) > 200:
                # 预算不足：保留尽量多的完整段落（不半截硬切）
                truncated = _fit_full_paras(prev_summary, min(remaining, prev_budget))
                if truncated:
                    sections.append(truncated)
                    remaining -= len(truncated) + 2

        # 4. 项目信息
        if project_text and len(project_text) + 2 <= remaining:
            sections.append(project_text)
            remaining -= len(project_text) + 2

        # 4.5 世界观设定（阶段感知预算：后期权重更大）
        world_budget = int(max_chars * world_budget_ratio)
        if world_text:
            if len(world_text) + 2 <= min(remaining, world_budget):
                sections.append(world_text)
                remaining -= len(world_text) + 2
            elif min(remaining, world_budget) > 200:
                # 预算不足：保留尽量多的完整段落（不半截硬切）
                truncated = _fit_full_paras(world_text, min(remaining, world_budget))
                if truncated:
                    sections.append(truncated)
                    remaining -= len(truncated) + 2

        # 5. 角色（可压缩：保留名字+角色+绝对禁令，丢弃 personality/motivation 等次要字段）
        if chars_text:
            if len(chars_text) + 2 <= remaining:
                sections.append(chars_text)
                remaining -= len(chars_text) + 2
            elif remaining > 200:
                # 压缩：保留名字、角色和绝对禁令（禁令是硬约束，不得丢失）
                compressed_lines = []
                for c in chars[:40]:
                    line = f"- {c.name}（{c.role or '角色'}）"
                    if getattr(c, 'absolute_taboos', ''):
                        line += f" | 绝对禁令：{c.absolute_taboos}"
                    compressed_lines.append(line)
                compressed = "【角色】\n" + "\n".join(compressed_lines)
                if len(compressed) + 2 <= remaining:
                    sections.append(compressed)
                    remaining -= len(compressed) + 2

        # 6. 活跃实体（势力/怪物）—迁移自 MemoryPackBuilder working memory
        if remaining > 200:
            active_entities = self._format_active_entities(chapter)
            if active_entities:
                if len(active_entities) + 2 <= remaining:
                    sections.append(active_entities)
                    remaining -= len(active_entities) + 2
                elif remaining > 150:
                    sections.append(active_entities[:remaining])

        # 7. 近期状态变更—迁移自 MemoryPackBuilder episodic memory
        if remaining > 200:
            recent_changes = self._format_recent_state_changes(chapter)
            if recent_changes:
                if len(recent_changes) + 2 <= remaining:
                    sections.append(recent_changes)
                    remaining -= len(recent_changes) + 2
                elif remaining > 150:
                    sections.append(recent_changes[:remaining])

        # 8. 近期关键事件—迁移自 MemoryPackBuilder episodic memory
        if remaining > 200:
            recent_events = self._format_recent_events(chapter)
            if recent_events:
                if len(recent_events) + 2 <= remaining:
                    sections.append(recent_events)
                    remaining -= len(recent_events) + 2
                elif remaining > 150:
                    sections.append(recent_events[:remaining])

        # 8. archival 语义检索 — 按需回热路径（长篇小说后期一致性关键）：
        # 章节 >= 阈值才开，每章仅检索一次（query=细纲+故事线名，top3+缓存），
        # 预算充足时注入；命中内容是整章，只取头部预览，写手可跳转看全文。
        if remaining > 400:
            try:
                from novel_agent.config import load_config
                cfg = load_config()
                if cfg.memory_semantic_retrieve and chapter >= cfg.memory_semantic_min_chapter:
                    archival_text = self._cached(
                        "archival", lambda: self._retrieve_archival(chapter, query))
                    if archival_text:
                        if len(archival_text) + 2 <= remaining:
                            sections.append(archival_text)
                            remaining -= len(archival_text) + 2
                        elif remaining > 300:
                            sections.append(archival_text[:remaining])
            except Exception as e:
                logger.debug("archival 热路径检索失败: %s", e)

        return "\n\n".join(sections)

    def _get_phase(self, chapter: int) -> str:
        """判断章节所处的叙事阶段。

        早期（1-10章）：世界观建立，需要更多角色信息和当前状态
        中期（11-50章）：故事推进为主，前文摘要最重要
        后期（51+章）：世界观庞大，需要更多世界观设定维持一致性
        """
        if chapter <= 10:
            return "early"
        elif chapter <= 50:
            return "mid"
        else:
            return "late"

    def _filter_characters_for_chapter(self, chapter: int, all_chars: list,
                                       max_chars: int = 40) -> list:
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
        # 全书铁律（绝对不得违反）
        if hasattr(project, 'constitution') and project.constitution:
            parts.append(f"【全书铁律】绝对不得违反\n{project.constitution}")
        # 金手指核心机制（写作时必须遵守其限制与代价）
        if hasattr(project, 'golden_finger') and project.golden_finger:
            try:
                import json as _json
                gf = _json.loads(project.golden_finger) if isinstance(project.golden_finger, str) else project.golden_finger
                gf_text = gf if isinstance(gf, str) else _json.dumps(gf, ensure_ascii=False)
                parts.append(f"【金手指核心机制】写作时必须遵守其限制与代价\n{gf_text}")
            except Exception:
                parts.append(f"【金手指核心机制】写作时必须遵守其限制与代价\n{project.golden_finger}")
        # 目标读者
        if hasattr(project, 'target_audience') and project.target_audience:
            parts.append(f"【目标读者】\n{project.target_audience}")
        # 立意锚点注入Writer context
        if hasattr(project, 'central_concept') and project.central_concept:
            try:
                import json as _json
                concept = _json.loads(project.central_concept) if isinstance(project.central_concept, str) else project.central_concept
                parts.append(f"【全书立意】\n核心爽点：{concept.get('core_hook','')}\n主角长期目标：{concept.get('protagonist_goal','')}")
                taboos = concept.get('taboos', [])
                if taboos:
                    parts.append(f"【立意禁忌】违反则废稿\n{', '.join(taboos) if isinstance(taboos, list) else taboos}")
            except Exception:
                parts.append(f"【全书立意】\n{project.central_concept}")
        return "\n".join(parts)

    def _format_world_settings(self, world_settings) -> str:
        """格式化世界观设定，完整注入不截断。"""
        lines = ["【世界观设定】"]
        for w in world_settings:
            content = (w.content or "")
            lines.append(f"- [{w.category}] {w.title}：{content}")
        return "\n".join(lines)

    def _format_characters(self, chars) -> str:
        lines = ["【当前角色状态】"]
        for c in chars:
            info = f"- {c.name}（{c.role or '角色'}）"
            if c.current_location:
                info += f" | 位置：{c.current_location}"
            if c.current_emotion:
                info += f" | 情绪：{c.current_emotion}"
            # 活人味三件套：承重矛盾+感官瞬间+绝对禁令（优先于personality）
            if hasattr(c, 'core_contradiction') and c.core_contradiction:
                info += f" | 承重矛盾：{c.core_contradiction}"
            if hasattr(c, 'sensory_memories') and c.sensory_memories:
                info += f" | 感官记忆：{c.sensory_memories}"
            if hasattr(c, 'absolute_taboos') and c.absolute_taboos:
                info += f" | 绝对禁令：{c.absolute_taboos}"
            if c.personality and not (hasattr(c, 'core_contradiction') and c.core_contradiction):
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

    def _format_active_storylines(self, chapter: int, max_lines: int = 6) -> str:
        """格式化当前故事线（委托独立函数，与交互式创作路径共用）。"""
        return format_active_storylines(self.repo, chapter, max_lines=max_lines)

    def _format_open_debts(self, max_debts: int = 5) -> str:
        """格式化未还剧情债（按压力降序 top5）— 上一章欠的账本章要还。"""
        try:
            debts = self.repo.list_open_debts()
        except Exception:
            return ""
        if not debts:
            return ""
        out = ["【剧情债】以下欠账请在本章或近期还清："]
        for d in debts[:max_debts]:
            line = f"- [{d.debt_type}] {d.description or ''}（压力{d.pressure or 3}/5）"
            if d.created_chapter:
                line += f"，欠自第{d.created_chapter}章"
            out.append(line)
        return "\n".join(out)

    def _archival_query(self, chapter: int, query: str | None) -> str:
        """构造语义检索 query：本章细纲概要 + 当前故事线名 + 传入 query（截断 500 字）。"""
        parts: list[str] = []
        try:
            outline = self.repo.get_outline_by_chapter(chapter)
            if outline and outline.summary:
                parts.append(outline.summary[:200])
        except Exception:
            pass
        try:
            from novel_agent.bible.models import Storyline
            lines = self.repo.db.query(Storyline).filter(
                Storyline.project_id == self.repo.project_id,
                Storyline.status == "active",
            ).limit(6).all()
            names = [l.name for l in lines if l.name]
            if names:
                parts.append("、".join(names))
        except Exception:
            pass
        if query:
            parts.append(query)
        joined = " ".join(parts).strip()
        return joined[:500] if joined else "相关前文"

    def _retrieve_archival(self, chapter: int, query: str | None) -> str:
        """按需检索相关历史切片并格式化（供写作热路径使用，每章一次）。"""
        if self.archival is None or not self.archival.is_available():
            return ""
        q = self._archival_query(chapter, query)
        try:
            res = self.archival.retrieve(q, top_k=3, chapter_filter=chapter - 1)
        except Exception:
            return ""
        docs = res.get("documents", [[]])[0] or []
        metas = res.get("metadatas", [[]])[0] or []
        if not docs:
            return ""
        slices = []
        for doc, meta in zip(docs, metas):
            m = meta or {}
            slices.append({
                "content": doc,
                "chapter": m.get("chapter"),
                "title": m.get("title", ""),
            })
        return self._format_archival(slices)

    def _format_archival(self, slices: list[dict], preview_chars: int = 250) -> str:
        """格式化 archival 切片（整章只取头部预览，写手可跳转看全文）。"""
        lines = ["【相关历史切片】（语义检索，按相关性召回；整章取预览，可在章节页看全文）"]
        for s in slices:
            chapter = s.get("chapter")
            tag = f"第{chapter}章" if chapter else "设定"
            content = s.get("content") or ""
            content = content.strip()
            # 去掉开头的 "第X章《标题》" 前缀（那是索引时加的文件头）
            import re as _re
            content = _re.sub(r"^第\d+章《[^》]*》\n?", "", content)
            content = _re.sub(r"\s+", "", content)
            if len(content) > preview_chars:
                content = content[:preview_chars] + "…"
            title = s.get("title") or ""
            lines.append(f"- [{tag}] {content}" + (f"（《{title}》预览）" if title and len(content) >= preview_chars else ""))
        return "\n".join(lines)

    def _format_snapshot(self, chapter: int) -> str:
        """读取状态快照（O(1) 读当前世界状态）。

        阶段2实现：从 StateSnapshot 表读取最近快照，
        格式化为注入上下文的文本。无快照时返回空串降级到角色列表。
        """
        try:
            from novel_agent.memory.snapshot import get_latest_snapshot, format_snapshot_for_context
            snap = get_latest_snapshot(self.repo, chapter)
            if snap:
                return format_snapshot_for_context(snap)
        except Exception:
            pass
        return ""

    def _format_previous_summaries(self, chapter: int) -> str:
        """注入前文摘要：最近 5 章详细 + 更早的卷级压缩 + 卷摘要。"""
        recent = self.summary_tree.get_recent_chapter_summaries(count=5)
        if not recent:
            return ""
        lines = ["【前文摘要】"]
        # 最近 5 章详细
        for s in recent:
            if s.chapter < chapter:
                lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events}")
        # 如果超过 5 章历史，加上卷级压缩 + 卷摘要
        all_summaries = self.repo.list_chapter_summaries(limit=1000)
        if len(all_summaries) > 5:
            older = [s for s in all_summaries if s.chapter < chapter - 5]
            if len(older) > 6:
                # 注入已完成卷的卷摘要（阶段4a激活）
                current_volume = (chapter - 1) // 30 + 1
                for vol in range(1, current_volume):
                    vol_summary = self.summary_tree.get_volume_summary(vol)
                    if vol_summary:
                        lines.append(vol_summary)
                # 取最早 3 章 + 最近 3 章，中间省略
                older.sort(key=lambda s: s.chapter)
                for s in older[:3]:
                    lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events}")
                lines.append(f"...（省略 {len(older) - 6} 章）...")
                for s in older[-3:]:
                    lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events}")
            elif older:
                older.sort(key=lambda s: s.chapter)
                for s in older:
                    lines.append(f"第{s.chapter}章《{s.title}》：{s.core_events}")
        return "\n".join(lines)

    def _chapter_outline_summary(self, chapter: int) -> str:
        """读取本章细纲，注入 writer 上下文。O(1) 查询，不遍历全部章纲。"""
        match = self.repo.get_outline_by_chapter(chapter)
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

    def _format_active_entities(self, chapter: int) -> str:
        """格式化本章活跃实体（势力/怪物）—迁移自 MemoryPackBuilder。"""
        try:
            active = self.repo.get_active_entities_for_chapter(chapter, window=3)
        except Exception:
            return ""
        lines = []
        if active.get("factions"):
            lines.append("【近期活跃势力】")
            for f in active["factions"]:
                line = f"- {f['name']}（层级：{f.get('tier','未标')} / 阵营：{f.get('alignment','未标')}）"
                lines.append(line)
        if active.get("monsters"):
            lines.append("【近期活跃怪物/神明】")
            for m in active["monsters"]:
                lines.append(
                    f"- {m['name']}（层级：{m.get('tier','未标')} / 物种：{m.get('species','未标')}）"
                )
        return "\n".join(lines) if lines else ""

    def _format_recent_state_changes(self, chapter: int) -> str:
        """格式化近期状态变更—迁移自 MemoryPackBuilder episodic memory。"""
        try:
            changes = self.repo.list_state_changes(limit=50)  # 只取最近50条，避免全量加载
        except Exception:
            return ""
        # 取最近 15 条本章之前的状态变更
        relevant = [sc for sc in changes if sc.chapter < chapter][-15:]
        if not relevant:
            return ""
        lines = ["【近期状态变更】"]
        for sc in relevant:
            lines.append(
                f"第{sc.chapter}章：{sc.entity_type}「{sc.entity_id}」"
                f"的「{sc.field}」变为「{sc.new_value}」"
            )
        return "\n".join(lines)

    def _format_recent_events(self, chapter: int) -> str:
        """格式化近期关键事件—迁移自 MemoryPackBuilder episodic memory。"""
        try:
            events = self.repo.list_events(limit=30)  # 只取最近30条，避免全量加载
        except Exception:
            return ""
        # 取最近 10 条本章之前的事件
        relevant = [e for e in events if e.chapter < chapter][-10:]
        if not relevant:
            return ""
        lines = ["【近期关键事件】"]
        for e in relevant:
            lines.append(f"第{e.chapter}章 [{e.type}] {e.entity_id}")
        return "\n".join(lines)
