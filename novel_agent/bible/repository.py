"""圣经仓储：CRUD 封装。所有写操作经此层，便于后续加校验/事件。"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from sqlalchemy.orm import Session
from novel_agent.bible.models import (
    Character, Foreshadow, TruthEvent, ChapterSummary,
    EmotionArc, SubplotBoard, CharacterMatrix, WorldSetting, Outline,
    ForeshadowImplant, Project, StateChange, ChapterCommit,
    Faction, FactionRelationship, CharacterRelationship, Monster,
    EntityAppearance, AiSuggestion,
)

logger = logging.getLogger(__name__)


class BibleRepository:
    """单项目的圣经读写入口。"""

    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id
        self._in_tx = False

    def _commit_or_flush(self):
        """事务上下文内只 flush，否则 commit。"""
        if self._in_tx:
            self.db.flush()
        else:
            self.db.commit()

    @contextmanager
    def unit_of_work(self):
        """事务上下文：内部写操作只 flush 不 commit，退出统一 commit/rollback。

        用于 applier 保证「apply 快照 + 追加事件流」原子性。
        """
        self._in_tx = True
        try:
            yield
            self._in_tx = False  # 先复位标志
            self.db.commit()     # 直接 commit，不走 _commit_or_flush
        except Exception:
            self.db.rollback()
            raise
        finally:
            self._in_tx = False

    # ---- 项目 ----
    def get_project(self) -> Project | None:
        return self.db.query(Project).filter(Project.id == self.project_id).first()

    # ---- 角色 ----
    def create_character(self, **kwargs) -> Character:
        c = Character(project_id=self.project_id, **kwargs)
        self.db.add(c)
        self._commit_or_flush()
        self.db.refresh(c)
        return c

    def list_characters(self) -> list[Character]:
        return self.db.query(Character).filter(
            Character.project_id == self.project_id
        ).all()

    def get_character(self, name: str) -> Character | None:
        return self.db.query(Character).filter(
            Character.project_id == self.project_id,
            Character.name == name,
        ).first()

    def update_character(self, name: str, **kwargs) -> Character | None:
        c = self.get_character(name)
        if not c:
            return None
        new_name = kwargs.get("name")
        if new_name and new_name != name:
            # 级联更新引用角色名的其他表
            for ea in self.db.query(EntityAppearance).filter(
                EntityAppearance.entity_type == "角色",
                EntityAppearance.entity_id == name,
            ).all():
                ea.entity_id = new_name
            for cr in self.db.query(CharacterRelationship).filter(
                (CharacterRelationship.source_character == name) |
                (CharacterRelationship.target_character == name)
            ).all():
                if cr.source_character == name:
                    cr.source_character = new_name
                if cr.target_character == name:
                    cr.target_character = new_name
            for sc in self.db.query(StateChange).filter(
                StateChange.entity_id == name,
            ).all():
                sc.entity_id = new_name
            for te in self.db.query(TruthEvent).filter(
                TruthEvent.entity_id == name,
            ).all():
                te.entity_id = new_name
        for k, v in kwargs.items():
            if hasattr(c, k):
                setattr(c, k, v)
        self._commit_or_flush()
        self.db.refresh(c)
        return c

    # ---- 伏笔 ----
    def create_foreshadow(self, **kwargs) -> Foreshadow:
        f = Foreshadow(project_id=self.project_id, **kwargs)
        self.db.add(f)
        self._commit_or_flush()
        self.db.refresh(f)
        return f

    def get_foreshadow(self, foreshadow_id: str) -> Foreshadow | None:
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.foreshadow_id == foreshadow_id,
        ).first()

    def list_foreshadows(self) -> list[Foreshadow]:
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
        ).all()

    _VALID_TRANSITIONS = {
        "pending": {"planted"},
        "planted": {"developing", "resolved"},
        "developing": {"resolved"},
        "resolved": set(),  # 终态
    }

    def update_foreshadow_status(self, foreshadow_id: str, status: str) -> Foreshadow | None:
        f = self.get_foreshadow(foreshadow_id)
        if not f:
            return None
        current = f.status or "pending"
        allowed = self._VALID_TRANSITIONS.get(current, set())
        if status not in allowed and current != status:
            logger.warning("伏笔 %s 非法状态跳转: %s → %s", foreshadow_id, current, status)
        f.status = status
        self._commit_or_flush()
        self.db.refresh(f)
        return f

    def get_foreshadows_by_status(self, status: str) -> list[Foreshadow]:
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.status == status,
        ).all()

    def get_foreshadows_to_plant(self, chapter: int) -> list[Foreshadow]:
        """取本章相关的伏笔（plant_chapter 匹配，pending 待埋或 planted 待复检）。"""
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.plant_chapter == chapter,
            Foreshadow.status.in_(["pending", "planted"]),
        ).all()

    def get_foreshadows_to_resolve(self, chapter: int) -> list[Foreshadow]:
        """取本章应回收的伏笔。"""
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.planned_resolve_chapter == chapter,
            Foreshadow.status.in_(["planted", "developing"]),
        ).all()

    # ---- 事件流 ----
    def append_event(self, chapter: int, type: str, entity_id: str = "",
                     payload: dict | None = None) -> TruthEvent:
        ev = TruthEvent(
            project_id=self.project_id, chapter=chapter, type=type,
            entity_id=entity_id, payload=payload or {},
        )
        self.db.add(ev)
        self._commit_or_flush()
        self.db.refresh(ev)
        return ev

    def list_events(self, chapter: int | None = None, entity_id: str | None = None) -> list[TruthEvent]:
        q = self.db.query(TruthEvent).filter(TruthEvent.project_id == self.project_id)
        if chapter is not None:
            q = q.filter(TruthEvent.chapter == chapter)
        if entity_id is not None:
            q = q.filter(TruthEvent.entity_id == entity_id)
        return q.order_by(TruthEvent.timestamp).all()

    # ---- 章节摘要 ----
    def create_chapter_summary(self, **kwargs) -> ChapterSummary:
        s = ChapterSummary(project_id=self.project_id, **kwargs)
        self.db.add(s)
        self._commit_or_flush()
        self.db.refresh(s)
        return s

    def get_chapter_summary(self, chapter: int) -> ChapterSummary | None:
        return self.db.query(ChapterSummary).filter(
            ChapterSummary.project_id == self.project_id,
            ChapterSummary.chapter == chapter,
        ).first()

    def list_chapter_summaries(self, limit: int = 10) -> list[ChapterSummary]:
        return self.db.query(ChapterSummary).filter(
            ChapterSummary.project_id == self.project_id,
        ).order_by(ChapterSummary.chapter.desc()).limit(limit).all()

    def update_chapter_summary(self, chapter: int, **kwargs) -> ChapterSummary | None:
        """更新已存在的章节摘要（支持重新生成）。"""
        s = self.get_chapter_summary(chapter)
        if not s:
            return None
        for k, v in kwargs.items():
            if hasattr(s, k):
                setattr(s, k, v)
        self._commit_or_flush()
        self.db.refresh(s)
        return s

    def create_or_update_chapter_summary(self, chapter: int, **kwargs) -> ChapterSummary:
        """不存在则创建，存在则更新章节摘要。"""
        s = self.get_chapter_summary(chapter)
        if not s:
            s = ChapterSummary(project_id=self.project_id, chapter=chapter, **kwargs)
            self.db.add(s)
        else:
            for k, v in kwargs.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        self._commit_or_flush()
        self.db.refresh(s)
        return s

    # ---- 大纲 ----
    def create_outline(self, **kwargs) -> Outline:
        o = Outline(project_id=self.project_id, **kwargs)
        self.db.add(o)
        self._commit_or_flush()
        self.db.refresh(o)
        return o

    def list_outlines(self, level: str | None = None,
                      parent_id: int | None = None) -> list[Outline]:
        q = self.db.query(Outline).filter(Outline.project_id == self.project_id)
        if level:
            q = q.filter(Outline.level == level)
        if parent_id is not None:
            q = q.filter(Outline.parent_id == parent_id)
        return q.order_by(Outline.order).all()

    # ---- 世界设定 ----
    def create_world_setting(self, **kwargs) -> WorldSetting:
        ws = WorldSetting(project_id=self.project_id, **kwargs)
        self.db.add(ws)
        self._commit_or_flush()
        self.db.refresh(ws)
        return ws

    def list_world_settings(self) -> list[WorldSetting]:
        return self.db.query(WorldSetting).filter(
            WorldSetting.project_id == self.project_id
        ).order_by(WorldSetting.order).all()

    # ---- 势力 ----
    def list_factions(self) -> list[Faction]:
        return self.db.query(Faction).filter(Faction.project_id == self.project_id).all()

    def get_faction(self, faction_id: int) -> Faction | None:
        return self.db.query(Faction).filter(
            Faction.project_id == self.project_id, Faction.id == faction_id
        ).first()

    def get_faction_by_name(self, name: str) -> Faction | None:
        return self.db.query(Faction).filter(
            Faction.project_id == self.project_id, Faction.name == name
        ).first()

    def create_faction(self, **kwargs) -> Faction:
        item = Faction(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self._commit_or_flush()
        self.db.refresh(item)
        return item

    def delete_faction(self, faction_id: int) -> bool:
        item = self.get_faction(faction_id)
        if not item:
            return False
        self.db.query(FactionRelationship).filter(
            (FactionRelationship.source_faction_id == faction_id) | (FactionRelationship.target_faction_id == faction_id)
        ).delete(synchronize_session=False)
        self.db.delete(item)
        self._commit_or_flush()
        return True

    # ---- 势力关系 ----
    def list_faction_relationships(self) -> list[FactionRelationship]:
        return self.db.query(FactionRelationship).filter(
            FactionRelationship.project_id == self.project_id
        ).all()

    def get_faction_relationship(self, rel_id: int) -> FactionRelationship | None:
        return self.db.query(FactionRelationship).filter(
            FactionRelationship.project_id == self.project_id, FactionRelationship.id == rel_id
        ).first()

    def create_faction_relationship(self, **kwargs) -> FactionRelationship:
        item = FactionRelationship(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self._commit_or_flush()
        self.db.refresh(item)
        return item

    def delete_faction_relationship(self, rel_id: int) -> bool:
        item = self.get_faction_relationship(rel_id)
        if not item:
            return False
        self.db.delete(item)
        self._commit_or_flush()
        return True

    # ---- 人物关系 ----
    def list_character_relationships(self) -> list[CharacterRelationship]:
        return self.db.query(CharacterRelationship).filter(
            CharacterRelationship.project_id == self.project_id
        ).all()

    def get_character_relationship(self, rel_id: int) -> CharacterRelationship | None:
        return self.db.query(CharacterRelationship).filter(
            CharacterRelationship.project_id == self.project_id, CharacterRelationship.id == rel_id
        ).first()

    def create_character_relationship(self, **kwargs) -> CharacterRelationship:
        item = CharacterRelationship(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self._commit_or_flush()
        self.db.refresh(item)
        return item

    def delete_character_relationship(self, rel_id: int) -> bool:
        item = self.get_character_relationship(rel_id)
        if not item:
            return False
        self.db.delete(item)
        self._commit_or_flush()
        return True

    # ---- 怪物 ----
    def list_monsters(self) -> list[Monster]:
        return self.db.query(Monster).filter(Monster.project_id == self.project_id).all()

    def get_monster(self, monster_id: int) -> Monster | None:
        return self.db.query(Monster).filter(
            Monster.project_id == self.project_id, Monster.id == monster_id
        ).first()

    def get_monster_by_name(self, name: str) -> Monster | None:
        return self.db.query(Monster).filter(
            Monster.project_id == self.project_id, Monster.name == name
        ).first()

    def create_monster(self, **kwargs) -> Monster:
        item = Monster(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self._commit_or_flush()
        self.db.refresh(item)
        return item

    def delete_monster(self, monster_id: int) -> bool:
        item = self.get_monster(monster_id)
        if not item:
            return False
        self.db.delete(item)
        self._commit_or_flush()
        return True

    # ---- 实体出场 ----
    def list_entity_appearances(self, entity_type=None, entity_id=None, chapter=None) -> list[EntityAppearance]:
        q = self.db.query(EntityAppearance).filter(EntityAppearance.project_id == self.project_id)
        if entity_type is not None:
            q = q.filter(EntityAppearance.entity_type == entity_type)
        if entity_id is not None:
            q = q.filter(EntityAppearance.entity_id == str(entity_id))
        if chapter is not None:
            q = q.filter(EntityAppearance.chapter == chapter)
        return q.order_by(EntityAppearance.chapter.desc(), EntityAppearance.id.desc()).all()

    def get_entity_appearance(self, id: int) -> EntityAppearance | None:
        return self.db.query(EntityAppearance).filter(
            EntityAppearance.project_id == self.project_id, EntityAppearance.id == id
        ).first()

    def create_entity_appearance(self, **kwargs) -> EntityAppearance:
        item = EntityAppearance(project_id=self.project_id, **kwargs)
        self.db.add(item)
        self._commit_or_flush()
        self.db.refresh(item)
        return item

    def delete_entity_appearance(self, id: int) -> bool:
        item = self.get_entity_appearance(id)
        if not item:
            return False
        self.db.delete(item)
        self._commit_or_flush()
        return True

    def delete_entity_appearances_for_chapter(self, chapter: int) -> int:
        items = self.db.query(EntityAppearance).filter(
            EntityAppearance.project_id == self.project_id,
            EntityAppearance.chapter == chapter,
        ).all()
        for it in items:
            self.db.delete(it)
        self._commit_or_flush()
        return len(items)

    def record_appearances(self, chapter: int, appearance_list: list[dict]) -> list[EntityAppearance]:
        self.delete_entity_appearances_for_chapter(chapter)
        created = []
        for app in appearance_list:
            a = {k: v for k, v in app.items() if k in {"entity_type", "entity_id", "role_in_chapter", "context_snippet"}}
            created.append(self.create_entity_appearance(chapter=chapter, **a))
        return created

    def get_appearances_for_entity(self, entity_type: str, entity_id) -> list[EntityAppearance]:
        return self.list_entity_appearances(entity_type=entity_type, entity_id=str(entity_id))

    def get_active_entities_for_chapter(self, chapter: int, window: int = 3) -> dict:
        """获取最近 window 章内活跃的实体，按类型聚合关键信息。"""
        start = max(1, chapter - window + 1)
        apps = self.db.query(EntityAppearance).filter(
            EntityAppearance.project_id == self.project_id,
            EntityAppearance.chapter >= start,
            EntityAppearance.chapter <= chapter,
        ).order_by(EntityAppearance.chapter.desc()).all()

        result: dict[str, list[dict]] = {"characters": [], "factions": [], "monsters": []}
        seen = {"character": set(), "faction": set(), "monster": set()}
        for a in apps:
            etype = (a.entity_type or "").lower()
            if etype in ("character", "characters"):
                eid = a.entity_id
                if eid in seen["character"]:
                    continue
                seen["character"].add(eid)
                char = self.get_character(eid)
                if char:
                    rels = [
                        f"{r.target_character}({r.relation_type})"
                        for r in self.list_character_relationships()
                        if r.source_character == eid or r.target_character == eid
                    ]
                    recent_changes = [
                        f"{sc.field}={sc.new_value}"
                        for sc in self.list_state_changes(entity_id=eid)
                        if sc.chapter <= chapter
                    ][-5:]
                    result["characters"].append({
                        "name": char.name,
                        "importance": char.importance,
                        "role": char.role,
                        "current_location": char.current_location,
                        "current_emotion": char.current_emotion,
                        "known_info": char.known_info,
                        "role_in_chapter": a.role_in_chapter,
                        "appearances": [
                            {"chapter": app.chapter, "role": app.role_in_chapter}
                            for app in apps if app.entity_type == a.entity_type and app.entity_id == eid
                        ],
                        "relationships": rels,
                        "recent_changes": recent_changes,
                    })
            elif etype in ("faction", "factions"):
                try:
                    fid = int(a.entity_id)
                except (ValueError, TypeError):
                    continue
                if fid in seen["faction"]:
                    continue
                seen["faction"].add(fid)
                f = self.get_faction(fid)
                if f:
                    rels = [
                        f"{r.target_faction_id}({r.relation_type})"
                        for r in self.list_faction_relationships()
                        if r.source_faction_id == fid or r.target_faction_id == fid
                    ]
                    result["factions"].append({
                        "name": f.name,
                        "tier": f.tier,
                        "type": f.type,
                        "alignment": f.alignment,
                        "role_in_chapter": a.role_in_chapter,
                        "relationships": rels,
                    })
            elif etype in ("monster", "monsters"):
                try:
                    mid = int(a.entity_id)
                except (ValueError, TypeError):
                    continue
                if mid in seen["monster"]:
                    continue
                seen["monster"].add(mid)
                m = self.get_monster(mid)
                if m:
                    result["monsters"].append({
                        "name": m.name,
                        "tier": m.tier,
                        "species": m.species,
                        "rank": m.rank,
                        "role_in_chapter": a.role_in_chapter,
                    })
        return result

    # ---- 删除操作 ----
    def delete_character(self, name: str) -> bool:
        c = self.get_character(name)
        if not c: return False
        self.db.delete(c); self._commit_or_flush()
        return True

    def delete_foreshadow(self, foreshadow_id: str) -> bool:
        f = self.get_foreshadow(foreshadow_id)
        if not f: return False
        self.db.delete(f); self._commit_or_flush()
        return True

    def delete_outline(self, outline_id: int) -> bool:
        o = self.db.query(Outline).filter(
            Outline.project_id == self.project_id, Outline.id == outline_id).first()
        if not o: return False
        # 级联删除子级
        self._delete_outline_children(outline_id)
        self.db.delete(o); self._commit_or_flush()
        return True

    def _delete_outline_children(self, outline_id: int) -> None:
        children = self.db.query(Outline).filter(
            Outline.project_id == self.project_id,
            Outline.parent_id == outline_id,
        ).all()
        for child in children:
            self._delete_outline_children(child.id)
            self.db.delete(child)

    def delete_chapter_summary(self, chapter: int) -> bool:
        s = self.get_chapter_summary(chapter)
        if not s: return False
        self.db.delete(s); self._commit_or_flush()
        return True

    def delete_all_project_data(self) -> int:
        """删除项目的所有圣经数据（不删项目本身），返回删除条数。"""
        count = 0
        for model in [Character, CharacterRelationship, Faction, FactionRelationship,
                      Foreshadow, ForeshadowImplant, ChapterSummary,
                      EmotionArc, SubplotBoard, CharacterMatrix, WorldSetting,
                      Outline, TruthEvent, StateChange, ChapterCommit,
                      EntityAppearance]:
            items = self.db.query(model).filter(model.project_id == self.project_id).all()
            for it in items:
                self.db.delete(it); count += 1
        self._commit_or_flush()
        return count

    # ---- 更新操作（全字段） ----
    def update_foreshadow(self, foreshadow_id: str, **kwargs) -> Foreshadow | None:
        f = self.get_foreshadow(foreshadow_id)
        if not f: return None
        for k, v in kwargs.items():
            if hasattr(f, k): setattr(f, k, v)
        self._commit_or_flush(); self.db.refresh(f)
        return f

    def update_outline(self, outline_id: int, **kwargs) -> Outline | None:
        o = self.get_outline(outline_id)
        if not o: return None
        for k, v in kwargs.items():
            if hasattr(o, k): setattr(o, k, v)
        self._commit_or_flush(); self.db.refresh(o)
        return o

    def get_outline(self, outline_id: int) -> Outline | None:
        return self.db.query(Outline).filter(
            Outline.project_id == self.project_id, Outline.id == outline_id).first()

    # ---- 状态变化 ----
    def create_state_change(self, chapter: int, entity_type: str, entity_id: str,
                            field: str, old_value: str, new_value: str) -> StateChange:
        sc = StateChange(
            project_id=self.project_id, chapter=chapter, entity_type=entity_type,
            entity_id=entity_id, field=field, old_value=old_value, new_value=new_value,
        )
        self.db.add(sc)
        self._commit_or_flush()
        self.db.refresh(sc)
        return sc

    def list_state_changes(self, chapter: int | None = None,
                           entity_id: str | None = None) -> list[StateChange]:
        q = self.db.query(StateChange).filter(StateChange.project_id == self.project_id)
        if chapter is not None:
            q = q.filter(StateChange.chapter == chapter)
        if entity_id is not None:
            q = q.filter(StateChange.entity_id == entity_id)
        return q.order_by(StateChange.created_at).all()

    # ---- 章节提交 ----
    def get_chapter_commit(self, chapter: int) -> ChapterCommit | None:
        return self.db.query(ChapterCommit).filter(
            ChapterCommit.project_id == self.project_id,
            ChapterCommit.chapter == chapter,
        ).first()

    def create_or_update_chapter_commit(self, chapter: int, **kwargs) -> ChapterCommit:
        c = self.get_chapter_commit(chapter)
        if not c:
            c = ChapterCommit(project_id=self.project_id, chapter=chapter, **kwargs)
            self.db.add(c)
        else:
            for k, v in kwargs.items():
                if hasattr(c, k):
                    setattr(c, k, v)
        self._commit_or_flush()
        self.db.refresh(c)
        return c

    # ---- AI 建议历史 ----
    def create_ai_suggestion(self, **kwargs) -> AiSuggestion:
        s = AiSuggestion(project_id=self.project_id, **kwargs)
        self.db.add(s)
        self._commit_or_flush()
        self.db.refresh(s)
        return s
