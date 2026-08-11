"""主 Agent 上下文注入：按对象类型或全局项目状态构造文本。"""
from __future__ import annotations

import json
import logging
import re

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.memory.recall import RecallMemory

logger = logging.getLogger(__name__)


def _truncate_reference_text(ref_text: str, total_limit: int = 4000) -> str:
    """参考文件文本过大时按总量控制：每文件注入开篇完整段落块（段落完整，不硬截断句子），
    总量不超 total_limit，并引导需要完整内容时通过指令读取。

    参考文件可能达几 MB，global 会话每轮全量注入会撑爆上下文；
    但"拿着半截就跑"（2000 字硬切）会丢失语义，改为完整段落块采样。
    """
    if len(ref_text) <= total_limit:
        return ref_text
    logger.warning(
        "参考文件总文本 %d 字超过 %d 字上限，改为完整段落块采样注入", len(ref_text), total_limit
    )
    # get_all_reference_text 以 “【参考文件：...】” 分块，按块取开篇完整段落
    parts = []
    used = 0
    per_file_blocks = 1
    for block in re.split(r"(?=【参考文件：)", ref_text):
        block = block.strip()
        if not block:
            continue
        # 分离块头（文件名）与正文
        header, body = "", block
        if block.startswith("【参考文件："):
            first_nl = block.find("\n")
            if first_nl != -1:
                header, body = block[:first_nl], block[first_nl + 1:]
        # 按段落切完整块（段落完整，不硬切）
        paras = [p.strip() for p in re.split(r"\n+", body) if p.strip()]
        blocks: list[str] = []
        cur = ""
        for p in paras:
            if cur and len(cur) + len(p) > 800:
                blocks.append(cur)
                cur = p
            else:
                cur = f"{cur}\n{p}" if cur else p
        if cur:
            blocks.append(cur)
        if not blocks:
            continue
        sample = "\n\n".join(blocks[:per_file_blocks])
        text_block = f"{header}\n{sample}" if header else sample
        text_block += (
            "\n（参考文件较长，此处为开篇完整段落样例；如需完整内容请通过指令读取。）"
        )
        if used + len(text_block) > total_limit:
            break
        parts.append(text_block)
        used += len(text_block)
    return "\n\n".join(parts)


class ContextBuilder:
    """构建主 Agent 所需的上下文文本。"""

    def __init__(self, repo: BibleRepository, cfg: Config):
        self.repo = repo
        self.cfg = cfg

    def build(self, session_type: str, object_type: str, object_id: str) -> str:
        if session_type == "global":
            return self._build_global_context()
        return self._build_object_context(object_type, object_id)

    def _build_object_context(self, object_type: str, object_id: str) -> str:
        project = self.repo.get_project()
        base = f"当前项目：《{project.title if project else '未知'}》\n"
        if object_type == "chapter":
            return base + self._chapter_context(int(object_id or 0))
        if object_type == "outline":
            return base + self._outline_context(int(object_id or 0))
        if object_type == "character":
            return base + self._character_context(object_id)
        if object_type == "monster":
            return base + self._monster_context(object_id)
        if object_type == "world":
            return base + self._world_context()
        if object_type == "faction":
            return base + self._faction_context(object_id)
        if object_type == "relationship":
            return base + self._relationship_context(object_id)
        return base + "（无特定对象上下文）"

    def _chapter_context(self, chapter: int) -> str:
        parts = [f"对象：第{chapter}章"]
        recall = RecallMemory(self.cfg, project_id=self.repo.project_id)
        text = recall.read_chapter_text(chapter)
        if text:
            parts.append(f"【正文】\n{text}")
        outline = self.repo.get_outline_by_chapter(chapter)
        if outline:
            parts.append(f"【章纲】{outline.title}：{outline.summary}")
            beats = self._safe_json(outline.required_beats)
            if beats:
                parts.append(f"【required_beats】{json.dumps(beats, ensure_ascii=False)}")
        return "\n\n".join(parts)

    def _outline_context(self, outline_id: int) -> str:
        o = self.repo.get_outline(outline_id)
        if not o:
            return f"对象：大纲ID {outline_id}（不存在）"
        parts = [f"对象：{o.level} 大纲《{o.title}》"]
        parts.append(f"摘要：{o.summary}")
        if o.required_beats:
            parts.append(f"爽点计划：{o.required_beats}")
        return "\n".join(parts)

    def _character_context(self, name: str) -> str:
        c = self.repo.get_character(name)
        if not c:
            return f"对象：角色 {name}（不存在）"
        return (
            f"对象：角色 {c.name}（{c.role}）\n"
            f"性格：{c.personality}\n动机：{c.motivation}\n"
            f"背景：{c.background}\n当前位置：{c.current_location}\n情绪：{c.current_emotion}\n"
            f"绝对禁令：{getattr(c, 'absolute_taboos', '') or '无'}"
        )

    def _monster_context(self, monster_id: str) -> str:
        m = self.repo.get_monster(int(monster_id)) if monster_id.isdigit() else None
        if not m:
            return f"对象：怪物ID {monster_id}（不存在）"
        return (
            f"对象：怪物 {m.name}（{m.species}/{m.rank}）\n"
            f"行为：{m.behavior}\n弱点：{m.weaknesses}\n栖息地：{m.habitats}"
        )

    def _world_context(self) -> str:
        items = self.repo.list_world_settings()
        if not items:
            return "对象：世界设定（暂无）"
        return "对象：世界设定\n" + "\n".join(
            f"- [{w.category}] {w.title}：{w.content}" for w in items
        )

    def _faction_context(self, faction_id: str) -> str:
        f = self.repo.get_faction(int(faction_id)) if faction_id.isdigit() else None
        if not f:
            return f"对象：势力ID {faction_id}（不存在）"
        return (
            f"对象：势力 {f.name}（{f.type}/{f.alignment}）\n"
            f"目标：{f.goals}\n层级：{f.hierarchy}\n领土：{f.territories}"
        )

    def _relationship_context(self, relationship_id: str) -> str:
        rel = self.repo.get_character_relationship(int(relationship_id)) if relationship_id.isdigit() else None
        if rel:
            return (
                f"对象：人物关系 {rel.source_character} → {rel.target_character}\n"
                f"类型：{rel.relation_type}（{rel.relation_subtype}）\n"
                f"描述：{rel.description}"
            )
        fr = self.repo.get_faction_relationship(int(relationship_id)) if relationship_id.isdigit() else None
        if fr:
            from novel_agent.bible.repository import BibleRepository
            src = self.repo.get_faction(fr.source_faction_id)
            tgt = self.repo.get_faction(fr.target_faction_id)
            return (
                f"对象：势力关系 {src.name if src else '?'} → {tgt.name if tgt else '?'}\n"
                f"类型：{fr.relation_type}\n描述：{fr.description}"
            )
        return f"对象：关系ID {relationship_id}（不存在）"

    def _build_global_context(self) -> str:
        project = self.repo.get_project()
        parts = ["当前为全局对话模式。"]
        if project:
            parts.append(f"项目：《{project.title}》 {project.genre}\n简介：{project.summary}")
            # 注入禁令上下文（constitution/golden_finger/central_concept）
            if getattr(project, 'constitution', ''):
                parts.append(f"【全书铁律（绝对不得违反）】\n{project.constitution}")
            if getattr(project, 'golden_finger', ''):
                try:
                    gf = json.loads(project.golden_finger) if isinstance(project.golden_finger, str) else project.golden_finger
                    gf_text = gf if isinstance(gf, str) else json.dumps(gf, ensure_ascii=False)
                    parts.append(f"【金手指设定（必须遵守其机制/限制/代价）】\n{gf_text}")
                except Exception:
                    parts.append(f"【金手指设定（必须遵守其机制/限制/代价）】\n{project.golden_finger}")
            if getattr(project, 'central_concept', ''):
                try:
                    concept = json.loads(project.central_concept) if isinstance(project.central_concept, str) else project.central_concept
                    taboos = concept.get('taboos', []) if isinstance(concept, dict) else []
                    taboos_list = taboos if isinstance(taboos, list) else ([taboos] if taboos else [])
                    taboos_text = ', '.join(str(t) for t in taboos_list) if taboos_list else '无'
                    parts.append(f"【立意禁忌（违反则废稿）】\n{taboos_text}")
                except Exception:
                    parts.append(f"【立意】\n{project.central_concept}")
        chapters = self.repo.list_chapter_summaries(limit=5)
        if chapters:
            parts.append("【最近章节摘要】")
            for s in sorted(chapters, key=lambda x: x.chapter):
                parts.append(f"- 第{s.chapter}章《{s.title}》：{s.core_events}")
        fores = self.repo.list_foreshadows()
        if fores:
            unresolved = [f for f in fores if f.status not in ("resolved", "abandoned")]
            parts.append(f"【伏笔】未回收 {len(unresolved)} 条")
        debts = self.repo.list_open_debts()
        if debts:
            parts.append(f"【欠账】未偿还 {len(debts)} 条")
        # 注入项目参考文件内容（超长时截断，防止每轮全量携带几 MB 文本）
        try:
            from novel_agent.api.routes_references import get_all_reference_text
            ref_text = get_all_reference_text(self.repo.project_id)
            if ref_text.strip():
                parts.append(_truncate_reference_text(ref_text))
        except Exception:
            pass
        return "\n\n".join(parts)

    @staticmethod
    def _safe_json(text: str | None) -> dict | list | None:
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None
