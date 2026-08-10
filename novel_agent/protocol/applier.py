"""Delta applier：校验 → immutable apply → 追加事件流。

spec 2.4 铁律：模型绝不直接写真相源，只产 delta；代码层 apply + 校验。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from novel_agent.bible.repository import BibleRepository
from novel_agent.protocol.schemas import (
    Delta, ForeshadowDelta, CharacterDelta, SummaryDelta, OutlineDelta,
)

logger = logging.getLogger(__name__)


class ApplyError(Exception):
    """delta 校验或 apply 失败。"""


@dataclass
class ApplyResult:
    success: bool
    message: str = ""


def _coerce(data, cls):
    """把 data（dict 或该类型实例）统一成指定 delta 类型。"""
    if isinstance(data, cls):
        return data
    return cls(**data)


class DeltaApplier:
    """把 Delta 应用到圣经。"""

    def __init__(self, repo: BibleRepository, archival=None):
        self.repo = repo
        self.archival = archival

    def apply(self, delta: Delta) -> ApplyResult:
        handler = {
            ("foreshadow", "plant"): self._plant_foreshadow,
            ("foreshadow", "develop"): self._develop_foreshadow,
            ("foreshadow", "resolve"): self._resolve_foreshadow,
            ("character", "state_change"): self._character_state_change,
            ("character", "create"): self._create_character,
            ("chapter_summary", "create"): self._create_summary,
            ("outline", "create"): self._create_outline,
            ("world_setting", "create"): self._create_world_setting,
        }.get((delta.target, delta.action))

        if not handler:
            raise ApplyError(
                f"不支持的 delta: target={delta.target} action={delta.action}"
            )
        # 事务原子性：handler 内多步写要么全成要么全回滚（spec 2.4）
        try:
            with self.repo.unit_of_work():
                result = handler(delta)
            # 兜底：async 上下文里同步 session 的 commit 可能不立即落盘
            self.repo.db.commit()
            return result
        except ApplyError:
            raise
        except Exception as e:
            raise ApplyError(f"apply 失败已回滚: {e}") from e

    def _plant_foreshadow(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, ForeshadowDelta)
        existing = self.repo.get_foreshadow(d.foreshadow_id)
        if existing and existing.status == "planted":
            return ApplyResult(False, f"伏笔 {d.foreshadow_id} 已埋设")
        if existing:
            self.repo.update_foreshadow_status(d.foreshadow_id, "planted")
        else:
            self.repo.create_foreshadow(
                foreshadow_id=d.foreshadow_id, tier=d.tier,
                plant_chapter=d.plant_chapter or delta.chapter,
                description=d.description, depends_on=d.depends_on,
                planned_resolve_chapter=d.planned_resolve_chapter,
                status="planted",
            )
        self.repo.append_event(
            chapter=delta.chapter, type="foreshadow_planted",
            entity_id=d.foreshadow_id,
            payload={"description": d.description, "method": d.implant_method},
        )
        return ApplyResult(True)

    def _develop_foreshadow(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, ForeshadowDelta)
        f = self.repo.get_foreshadow(d.foreshadow_id)
        if not f:
            raise ApplyError(f"伏笔 {d.foreshadow_id} 不存在，无法发展")
        self.repo.update_foreshadow_status(d.foreshadow_id, "developing")
        self.repo.append_event(
            chapter=delta.chapter, type="foreshadow_developed",
            entity_id=d.foreshadow_id, payload={"description": d.description},
        )
        return ApplyResult(True)

    def _resolve_foreshadow(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, ForeshadowDelta)
        f = self.repo.get_foreshadow(d.foreshadow_id)
        if not f:
            raise ApplyError(f"伏笔 {d.foreshadow_id} 不存在，无法回收")
        if f.status == "resolved":
            return ApplyResult(False, f"伏笔 {d.foreshadow_id} 已回收")
        self.repo.update_foreshadow_status(d.foreshadow_id, "resolved")
        self.repo.append_event(
            chapter=delta.chapter, type="foreshadow_resolved",
            entity_id=d.foreshadow_id, payload={"description": d.description},
        )
        return ApplyResult(True)

    def _character_state_change(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, CharacterDelta)
        c = self.repo.get_character(d.name)
        if not c:
            raise ApplyError(f"角色 {d.name} 不存在")
        updates = {}
        if d.current_location:
            updates["current_location"] = d.current_location
        if d.current_emotion:
            updates["current_emotion"] = d.current_emotion
        if d.known_info:
            updates["known_info"] = d.known_info
        if updates:
            self.repo.update_character(d.name, **updates)
        self.repo.append_event(
            chapter=delta.chapter, type="character_state_change",
            entity_id=d.name, payload=updates,
        )
        return ApplyResult(True)

    def _create_character(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, CharacterDelta)
        if self.repo.get_character(d.name):
            return ApplyResult(False, f"角色 {d.name} 已存在")
        self.repo.create_character(
            name=d.name, role=d.role, personality=d.personality,
            motivation=d.motivation, current_location=d.current_location,
            current_emotion=d.current_emotion, known_info=d.known_info,
            core_contradiction=d.core_contradiction,
            sensory_memories=d.sensory_memories,
            absolute_taboos=d.absolute_taboos,
        )
        self.repo.append_event(
            chapter=delta.chapter, type="character_introduced",
            entity_id=d.name, payload={"role": d.role},
        )
        return ApplyResult(True)

    def _create_summary(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, SummaryDelta)
        existing = self.repo.get_chapter_summary(delta.chapter)
        if existing:
            # 已存在则更新（支持重新生成）
            self.repo.update_chapter_summary(
                delta.chapter, title=d.title, word_count=d.word_count,
                core_events=d.core_events, characters_present=d.characters_present,
                emotion_changes=d.emotion_changes, foreshadow_dynamics=d.foreshadow_dynamics,
                subplot_progress=d.subplot_progress, chapter_hook=d.chapter_hook,
            )
        else:
            self.repo.create_chapter_summary(
                chapter=delta.chapter, title=d.title, word_count=d.word_count,
                time_location=d.time_location, core_events=d.core_events,
                characters_present=d.characters_present, emotion_changes=d.emotion_changes,
                foreshadow_dynamics=d.foreshadow_dynamics,
                subplot_progress=d.subplot_progress, chapter_hook=d.chapter_hook,
            )
        self.repo.append_event(
            chapter=delta.chapter, type="chapter_summary_created",
            entity_id=str(delta.chapter),
            payload={"title": d.title, "word_count": d.word_count},
        )
        if self.archival:
            self.archival.index_chapter(
                chapter=delta.chapter, title=d.title,
                content=f"{d.core_events} {d.chapter_hook}".strip(),
            )
        return ApplyResult(True)

    def _create_outline(self, delta: Delta) -> ApplyResult:
        d = _coerce(delta.data, OutlineDelta)
        self.repo.create_outline(
            level=d.level, order=d.order, act=d.act,
            title=d.title, summary=d.summary,
        )
        self.repo.append_event(
            chapter=delta.chapter, type="outline_created",
            entity_id=f"{d.level}:{d.order}",
            payload={"level": d.level, "act": d.act, "title": d.title},
        )
        return ApplyResult(True)

    def _create_world_setting(self, delta: Delta) -> ApplyResult:
        """应用世界观设定 delta。"""
        d = delta.data
        data = d if isinstance(d, dict) else (d.model_dump() if hasattr(d, "model_dump") else {})
        category = data.get("category", "其他")
        title = data.get("title", "")
        content = data.get("content", "")
        self.repo.create_world_setting(
            category=category, title=title, content=content,
        )
        self.repo.append_event(
            chapter=delta.chapter, type="world_setting_created",
            entity_id=title, payload={"category": category},
        )
        return ApplyResult(True)

    def apply_deltas(self, deltas: list[dict], chapter: int | None = None) -> ApplyResult:
        """批量应用统一格式的 dict deltas（commit_chapter 数据流闭环）。"""
        warnings: list[str] = []
        try:
            for d in deltas:
                t = d.get("type")
                if t == "state_change":
                    warning = self._apply_state_change(d, chapter=chapter)
                    if warning:
                        warnings.append(warning)
                elif t == "relationship_update":
                    self._apply_relationship_update(d, chapter=chapter)
                elif t == "event":
                    self._apply_event(d, chapter=chapter)
                elif t == "foreshadow_update":
                    self._apply_foreshadow_update(d, chapter=chapter)
                elif t == "chapter_commit":
                    self._apply_chapter_commit(d)
                elif t == "character_create":
                    self._apply_character_create(d, chapter=chapter)
                elif t == "faction_create":
                    self._apply_faction_create(d, chapter=chapter)
                elif t == "monster_create":
                    self._apply_monster_create(d, chapter=chapter)
                elif t == "world_setting_create":
                    self._apply_world_setting_create(d, chapter=chapter)
                else:
                    raise ApplyError(f"不支持的 delta 类型: {t}")
            message = "\n".join(warnings) if warnings else ""
            return ApplyResult(True, message)
        except ApplyError:
            raise
        except Exception as e:
            raise ApplyError(f"apply_deltas 失败: {e}") from e

    def _apply_state_change(self, d: dict, chapter: int | None = None) -> str | None:
        entity_type = d.get("entity") or d.get("entity_type", "")
        entity_id = d.get("entity_id", "")
        field = d.get("field", "")
        old_value = str(d.get("old_value") if "old_value" in d else d.get("old", ""))
        new_value = str(d.get("new_value") if "new_value" in d else d.get("new", ""))
        ch = (d.get("chapter") if d.get("chapter") is not None else chapter) or 0

        warning: str | None = None
        # 角色状态变更：比对 Data Agent 提取的 old_value 与圣经当前值
        if entity_type in {"角色", "character"} and field in {"current_location", "current_emotion", "known_info"}:
            char = self.repo.get_character(entity_id)
            if char:
                current_value = str(getattr(char, field, "") or "")
                # 互为子串视为一致；否则提示用户人工审核
                if old_value and current_value and not (
                    old_value in current_value or current_value in old_value
                ):
                    warning = (
                        f"【重要警告】角色 '{entity_id}' 的 {field} 当前值为 "
                        f"'{current_value}'，但 Data Agent 认为旧值是 '{old_value}'，"
                        f"两者不一致。已按新值 '{new_value}' 更新，请人工核对。"
                    )
                self.repo.update_character(entity_id, **{field: new_value})

        self.repo.create_state_change(
            chapter=ch, entity_type=entity_type, entity_id=entity_id,
            field=field, old_value=old_value, new_value=new_value,
        )
        self.repo.append_event(
            chapter=ch, type="state_change", entity_id=entity_id,
            payload={"field": field, "new": new_value},
        )
        return warning

    def _apply_relationship_update(self, d: dict, chapter: int | None = None) -> None:
        ch = d.get("chapter") if d.get("chapter") is not None else chapter
        a = str(d.get("character_a") or "").strip()
        b = str(d.get("character_b") or "").strip()
        rel = str(d.get("relation") or d.get("relationship") or d.get("relation_type") or "").strip()
        try:
            strength = int(d.get("strength") or 0)
        except (TypeError, ValueError):
            strength = 0
        entity_id = f"{a}-{b}" if (a or b) else f"{d.get('source', '')}-{d.get('target', '')}"

        # P0#2：关系不只写事件流——同时落角色关系表 + 关系变更表
        if a and b and a != b:
            try:
                self.repo.create_character_relationship(
                    source_character=a, target_character=b,
                    relation_type=rel or "other",
                    strength=strength,
                    description=str(d.get("description") or ""),
                    since_chapter=ch or 0,
                )
            except Exception as e:
                logger.warning("角色关系落库失败 %s-%s: %s", a, b, e)
            # P0#5：角色交互矩阵（相遇/交互记录）
            try:
                self.repo.create_character_matrix(
                    chapter=ch or 0, character_a=a, character_b=b,
                    interaction_type="meeting",
                    relationship_change=rel,
                )
            except Exception as e:
                logger.warning("角色交互矩阵落库失败 %s-%s: %s", a, b, e)
            try:
                self.repo.create_relationship_change(
                    chapter=ch or 0, entity_type="角色", source_id=a, target_id=b,
                    field="relationship",
                    old_value=str(d.get("old_relation") or d.get("old") or ""),
                    new_value=rel,
                    reason=str(d.get("description") or ""),
                )
            except Exception as e:
                logger.warning("关系变更落库失败 %s-%s: %s", a, b, e)

        self.repo.append_event(
            chapter=ch, type="relationship_change", entity_id=entity_id, payload=d,
        )

    def _apply_event(self, d: dict, chapter: int | None = None) -> None:
        ch = d.get("chapter") if d.get("chapter") is not None else chapter
        self.repo.append_event(
            chapter=ch,
            type=d.get("event_type", "剧情"),
            entity_id=d.get("subject") or d.get("entity_id", ""),
            payload=d.get("payload") or {"description": d.get("description", "")},
        )

    def _apply_foreshadow_update(self, d: dict, chapter: int | None = None) -> None:
        foreshadow_id = str(d.get("foreshadow_id", "")).strip()
        status = d.get("status", "planted")
        ch = d.get("chapter") if d.get("chapter") is not None else chapter
        if not foreshadow_id:
            return
        existing = self.repo.get_foreshadow(foreshadow_id)
        if not existing:
            if status == "planted":
                # P0#3：正文/大纲埋设的伏笔自动创建（不再静默失败）
                try:
                    self.repo.create_foreshadow(
                        foreshadow_id=foreshadow_id,
                        tier=str(d.get("tier") or "c"),
                        plant_chapter=int(ch or d.get("plant_chapter") or 0),
                        description=str(d.get("description") or ""),
                        planned_resolve_chapter=int(d.get("planned_resolve_chapter") or 0),
                        status="planted",
                    )
                except Exception as e:
                    logger.warning("伏笔 %s 自动埋设失败: %s", foreshadow_id, e)
                    return
            else:
                # developing/resolved 但不存在：记录警告，不静默（可能命名不一致）
                logger.warning("伏笔 %s 不存在但状态为 %s，跳过更新（可能命名不一致）", foreshadow_id, status)
                return
        else:
            self.repo.update_foreshadow_status(foreshadow_id, status)
        self.repo.append_event(
            chapter=ch, type="foreshadow_update", entity_id=foreshadow_id,
            payload={"status": status},
        )

    def _apply_chapter_commit(self, d: dict) -> None:
        self.repo.create_or_update_chapter_commit(
            chapter=d.get("chapter"),
            status="committed",
            summary=d.get("summary", ""),
            word_count=d.get("word_count", 0),
            committed_at=datetime.utcnow(),
        )

    def _apply_character_create(self, d: dict, chapter: int | None = None) -> None:
        """从正文提取的新角色，若已存在则跳过。"""
        name = d.get("name", "").strip()
        if not name:
            return
        if self.repo.get_character(name):
            return  # 已存在，跳过
        self.repo.create_character(
            name=name,
            role=d.get("role", "配角"),
            age=d.get("age", ""),
            gender=d.get("gender", ""),
            appearance=d.get("appearance", ""),
            personality=d.get("personality", ""),
            motivation=d.get("motivation", ""),
            background=d.get("background", ""),
            current_location=d.get("current_location", ""),
            current_emotion=d.get("current_emotion", ""),
            known_info=d.get("known_info", ""),
        )
        ch = d.get("chapter") if d.get("chapter") is not None else chapter
        self.repo.append_event(
            chapter=ch, type="character_introduced",
            entity_id=name, payload={"role": d.get("role", "配角")},
        )

    def _apply_faction_create(self, d: dict, chapter: int | None = None) -> None:
        """从正文提取的新组织/势力。"""
        name = d.get("name", "").strip()
        if not name:
            return
        existing = self.repo.get_faction_by_name(name)
        if existing:
            return
        self.repo.create_faction(
            name=name,
            alias=d.get("alias", ""),
            # 势力类型优先取 faction_type（_build_create_delta 保留的业务字段），
            # 兼容旧数据里直接放 type 的情况（此时 delta.type 不是动作类型）
            type=d.get("faction_type") or (d.get("type", "其他") if d.get("type") != "faction_create" else "其他"),
            tier=d.get("tier", ""),
            alignment=d.get("alignment", "中立"),
            description=d.get("description", ""),
            goals=d.get("goals", ""),
        )
        ch = d.get("chapter") if d.get("chapter") is not None else chapter
        self.repo.append_event(
            chapter=ch, type="faction_introduced",
            entity_id=name, payload={"type": d.get("faction_type") or d.get("type", "")},
        )

    def _apply_monster_create(self, d: dict, chapter: int | None = None) -> None:
        """从正文提取的新怪物/异兽。"""
        name = d.get("name", "").strip()
        if not name:
            return
        existing = self.repo.get_monster_by_name(name)
        if existing:
            return
        self.repo.create_monster(
            name=name,
            alias=d.get("alias", ""),
            species=d.get("species", ""),
            rank=d.get("rank", "普通"),
            tier=d.get("tier", ""),
            attributes=d.get("attributes", ""),
            skills=d.get("skills", ""),
            drops=d.get("drops", ""),
            habitats=d.get("habitats", ""),
            behavior=d.get("behavior", ""),
            weaknesses=d.get("weaknesses", ""),
            lore=d.get("lore", ""),
            first_appearance=d.get("first_appearance") or (d.get("chapter") if d.get("chapter") is not None else chapter) or 0,
        )
        ch = (d.get("chapter") if d.get("chapter") is not None else chapter) or 0
        self.repo.append_event(
            chapter=ch, type="monster_introduced",
            entity_id=name, payload={"species": d.get("species", "")},
        )

    def _apply_world_setting_create(self, d: dict, chapter: int | None = None) -> None:
        """从正文提取的新世界观设定（同名去重，postprocess 可能多次调用）。"""
        title = d.get("title", "").strip()
        if not title:
            return
        from novel_agent.bible.models import WorldSetting

        existing = self.repo.db.query(WorldSetting).filter(
            WorldSetting.project_id == self.repo.project_id,
            WorldSetting.title == title,
        ).first()
        if existing:
            ch = d.get("chapter") if d.get("chapter") is not None else chapter
            self.repo.append_event(
                chapter=ch, type="world_setting_added",
                entity_id=title, payload={"category": d.get("category", ""), "skipped": True},
            )
            return
        self.repo.create_world_setting(
            category=d.get("category", "其他"),
            title=title,
            content=d.get("content", ""),
        )
        ch = d.get("chapter") if d.get("chapter") is not None else chapter
        self.repo.append_event(
            chapter=ch, type="world_setting_added",
            entity_id=title, payload={"category": d.get("category", "")},
        )
