"""Delta applier：校验 → immutable apply → 追加事件流。

spec 2.4 铁律：模型绝不直接写真相源，只产 delta；代码层 apply + 校验。
"""
from __future__ import annotations

from dataclasses import dataclass

from novel_agent.bible.repository import BibleRepository
from novel_agent.protocol.schemas import (
    Delta, ForeshadowDelta, CharacterDelta, SummaryDelta, OutlineDelta,
)


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
