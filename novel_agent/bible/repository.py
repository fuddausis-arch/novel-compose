"""圣经仓储：CRUD 封装。所有写操作经此层，便于后续加校验/事件。"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from novel_agent.bible.models import (
    Character, Foreshadow, TruthEvent, ChapterSummary,
    EmotionArc, SubplotBoard, CharacterMatrix, WorldSetting, Outline,
    ForeshadowImplant, Project, StateChange, ChapterCommit,
    Faction, FactionRelationship, CharacterRelationship, Monster, Instance,
    EntityAppearance, AiSuggestion, StateSnapshot, PleasureBeat, PlotDebt,
    RelationshipChange, RedLine, Gag, EntityNameOverride, ImportedChapter,
    ChatSession, ChatMessage, ChapterFeedback,
    WorldState, WorldEvent, Location, LocationRelationship,
    Graph, CustomWorkflow, PostHocResult,
)

logger = logging.getLogger(__name__)


class BibleRepository:
    """单项目的圣经读写入口。"""

    def __init__(self, db: Session, project_id: int):
        self.db = db
        self.project_id = project_id
        self._in_tx = False

    def _commit_or_flush(self):
        """事务上下文内只 flush，否则 commit。失败时回滚避免 session 污染。"""
        try:
            if self._in_tx:
                self.db.flush()
            else:
                self.db.commit()
        except Exception:
            self.db.rollback()
            raise

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

    def update_project(self, **kwargs) -> None:
        """更新项目字段。"""
        project = self.get_project()
        if project:
            for k, v in kwargs.items():
                if hasattr(project, k):
                    setattr(project, k, v)
            self._commit_or_flush()

    def save_generation_checkpoint(self, checkpoint: dict) -> None:
        """保存批量生成 checkpoint（元认知监控）。"""
        project = self.get_project()
        if project:
            project.generation_checkpoint = checkpoint
            self._commit_or_flush()

    def get_generation_checkpoint(self) -> dict:
        """读取批量生成 checkpoint。"""
        project = self.get_project()
        if project and project.generation_checkpoint:
            return dict(project.generation_checkpoint)
        return {}

    # ---- 角色 ----
    def create_character(self, **kwargs) -> Character:
        c = Character(project_id=self.project_id, **kwargs)
        self.db.add(c)
        self._commit_or_flush()
        self.db.refresh(c)
        self.append_event(
            chapter=0, type="character_created",
            entity_id=c.name, payload={"role": c.role},
        )
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

    def get_character_by_id(self, character_id: int) -> Character | None:
        return self.db.query(Character).filter(
            Character.project_id == self.project_id,
            Character.id == character_id,
        ).first()

    def update_character(self, lookup_name: str, **kwargs) -> Character | None:
        c = self.get_character(lookup_name)
        if not c:
            return None
        new_name = kwargs.get("name")
        if new_name and new_name != lookup_name:
            # 级联更新引用角色名的其他表（必须带 project_id 过滤，防止跨项目污染）
            # entity_type 兼容中英文取值（历史数据可能为"角色"或"character"）
            for ea in self.db.query(EntityAppearance).filter(
                EntityAppearance.project_id == self.project_id,
                EntityAppearance.entity_type.in_(["character", "角色"]),
                EntityAppearance.entity_id == lookup_name,
            ).all():
                ea.entity_id = new_name
            for cr in self.db.query(CharacterRelationship).filter(
                CharacterRelationship.project_id == self.project_id,
                (CharacterRelationship.source_character == lookup_name) |
                (CharacterRelationship.target_character == lookup_name)
            ).all():
                if cr.source_character == lookup_name:
                    cr.source_character = new_name
                if cr.target_character == lookup_name:
                    cr.target_character = new_name
            for sc in self.db.query(StateChange).filter(
                StateChange.project_id == self.project_id,
                StateChange.entity_id == lookup_name,
            ).all():
                sc.entity_id = new_name
            for te in self.db.query(TruthEvent).filter(
                TruthEvent.project_id == self.project_id,
                TruthEvent.entity_id == lookup_name,
            ).all():
                te.entity_id = new_name
            # EmotionArc.character_name
            for ea in self.db.query(EmotionArc).filter(
                EmotionArc.project_id == self.project_id,
                EmotionArc.character_name == lookup_name,
            ).all():
                ea.character_name = new_name
            # CharacterMatrix.character_a / character_b
            for cm in self.db.query(CharacterMatrix).filter(
                CharacterMatrix.project_id == self.project_id,
                (CharacterMatrix.character_a == lookup_name) |
                (CharacterMatrix.character_b == lookup_name)
            ).all():
                if cm.character_a == lookup_name:
                    cm.character_a = new_name
                if cm.character_b == lookup_name:
                    cm.character_b = new_name
            # RelationshipChange.source_id / target_id（entity_type='character'）
            for rc in self.db.query(RelationshipChange).filter(
                RelationshipChange.project_id == self.project_id,
                RelationshipChange.entity_type == "character",
                (RelationshipChange.source_id == lookup_name) |
                (RelationshipChange.target_id == lookup_name)
            ).all():
                if rc.source_id == lookup_name:
                    rc.source_id = new_name
                if rc.target_id == lookup_name:
                    rc.target_id = new_name
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
        self.append_event(
            chapter=0, type="foreshadow_created",
            entity_id=f.foreshadow_id, payload={"description": f.description},
        )
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
        "pending": {"planted", "abandoned"},
        "planted": {"developing", "resolved", "abandoned"},
        "developing": {"resolved", "abandoned"},
        "resolved": set(),   # 终态
        "abandoned": set(),  # 终态
    }

    def update_foreshadow_status(self, foreshadow_id: str, status: str) -> Foreshadow | None:
        f = self.get_foreshadow(foreshadow_id)
        if not f:
            return None
        current = f.status or "pending"
        allowed = self._VALID_TRANSITIONS.get(current, set())
        if status not in allowed and current != status:
            logger.warning("伏笔 %s 非法状态跳转: %s -> %s，已拒绝", foreshadow_id, current, status)
            return f
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

    def get_overdue_foreshadows(self, current_chapter: int) -> list[Foreshadow]:
        """获取已逾期未回收的伏笔（planned_resolve_chapter < current_chapter 且 status != resolved）。"""
        return self.db.query(Foreshadow).filter(
            Foreshadow.project_id == self.project_id,
            Foreshadow.status != "resolved",
            Foreshadow.planned_resolve_chapter > 0,
            Foreshadow.planned_resolve_chapter < current_chapter,
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

    def list_events(self, chapter: int | None = None, entity_id: str | None = None,
                    limit: int | None = None) -> list[TruthEvent]:
        q = self.db.query(TruthEvent).filter(TruthEvent.project_id == self.project_id)
        if chapter is not None:
            q = q.filter(TruthEvent.chapter == chapter)
        if entity_id is not None:
            q = q.filter(TruthEvent.entity_id == entity_id)
        q = q.order_by(TruthEvent.timestamp)
        if limit:
            q = q.limit(limit)
        return q.all()

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

    def list_chapter_summaries(self, limit: int = 10, offset: int = 0) -> list[ChapterSummary]:
        return self.db.query(ChapterSummary).filter(
            ChapterSummary.project_id == self.project_id,
        ).order_by(ChapterSummary.chapter.desc()).limit(limit).offset(offset).all()

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
        level = kwargs.get("level")
        parent_id = kwargs.get("parent_id")
        order = kwargs.get("order")
        # 如果 order 缺失或与同级冲突，从 1 开始找第一个未使用的编号
        if order is None or self.db.query(Outline).filter(
            Outline.project_id == self.project_id,
            Outline.level == level,
            Outline.parent_id == parent_id,
            Outline.order == order,
        ).first():
            existing_orders = [
                r[0] for r in self.db.query(Outline.order).filter(
                    Outline.project_id == self.project_id,
                    Outline.level == level,
                    Outline.parent_id == parent_id,
                ).order_by(Outline.order).all()
            ]
            next_order = 1
            for o in existing_orders:
                if o == next_order:
                    next_order += 1
                elif o > next_order:
                    break
            kwargs = {**kwargs, "order": next_order}
        o = Outline(project_id=self.project_id, **kwargs)
        self.db.add(o)
        try:
            self._commit_or_flush()
        except IntegrityError:
            # 并发下同 (project_id, level, parent_id, order) 冲突：rollback 后按 max order + 1 重试一次
            self.db.rollback()
            max_order_row = self.db.query(Outline.order).filter(
                Outline.project_id == self.project_id,
                Outline.level == level,
                Outline.parent_id == parent_id,
            ).order_by(Outline.order.desc()).first()
            new_order = (max_order_row[0] + 1) if max_order_row and max_order_row[0] is not None else 1
            o = Outline(project_id=self.project_id, **{**kwargs, "order": new_order})
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

    def get_outline_by_chapter(self, chapter: int) -> Outline | None:
        """按全局章节号取章级大纲。"""
        return self.db.query(Outline).filter(
            Outline.project_id == self.project_id,
            Outline.level == "chapter",
            Outline.order == chapter,
        ).first()

    # ---- 世界设定 ----
    def create_world_setting(self, **kwargs) -> WorldSetting:
        ws = WorldSetting(project_id=self.project_id, **kwargs)
        self.db.add(ws)
        self._commit_or_flush()
        self.db.refresh(ws)
        self.append_event(
            chapter=0, type="world_setting_created",
            entity_id=ws.title, payload={"category": ws.category},
        )
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
        name = kwargs.get("name")
        if name:
            existing = self.get_faction_by_name(name)
            if existing:
                return existing
        item = Faction(project_id=self.project_id, **kwargs)
        self.db.add(item)
        try:
            self._commit_or_flush()
            self.db.refresh(item)
        except IntegrityError:
            self.db.rollback()
            existing = self.get_faction_by_name(kwargs.get("name"))
            if existing:
                return existing
            raise
        return item

    def update_faction(self, faction_id: int, **kwargs) -> Faction | None:
        """更新势力信息。faction_id 定位。"""
        item = self.get_faction(faction_id)
        if not item:
            return None
        for k, v in kwargs.items():
            if hasattr(item, k) and v is not None:
                setattr(item, k, v)
        try:
            self._commit_or_flush()
            self.db.refresh(item)
        except IntegrityError:
            self.db.rollback()
            raise
        return item

    def delete_faction(self, faction_id: int) -> bool:
        item = self.get_faction(faction_id)
        if not item:
            return False
        self.db.query(FactionRelationship).filter(
            FactionRelationship.project_id == self.project_id,
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
        source = kwargs.get("source_character")
        target = kwargs.get("target_character")
        rel_type = kwargs.get("relation_type")
        if source and target and rel_type:
            existing = self.db.query(CharacterRelationship).filter(
                CharacterRelationship.project_id == self.project_id,
                CharacterRelationship.source_character == source,
                CharacterRelationship.target_character == target,
                CharacterRelationship.relation_type == rel_type,
            ).first()
            if existing:
                return existing
        item = CharacterRelationship(project_id=self.project_id, **kwargs)
        self.db.add(item)
        try:
            self._commit_or_flush()
            self.db.refresh(item)
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(CharacterRelationship).filter(
                CharacterRelationship.project_id == self.project_id,
                CharacterRelationship.source_character == kwargs.get("source_character"),
                CharacterRelationship.target_character == kwargs.get("target_character"),
                CharacterRelationship.relation_type == kwargs.get("relation_type"),
            ).first()
            if existing:
                return existing
            raise
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
        name = kwargs.get("name")
        if name:
            existing = self.get_monster_by_name(name)
            if existing:
                return existing
        item = Monster(project_id=self.project_id, **kwargs)
        self.db.add(item)
        try:
            self._commit_or_flush()
            self.db.refresh(item)
        except IntegrityError:
            self.db.rollback()
            existing = self.get_monster_by_name(kwargs.get("name"))
            if existing:
                return existing
            raise
        return item

    def delete_monster(self, monster_id: int) -> bool:
        item = self.get_monster(monster_id)
        if not item:
            return False
        self.db.delete(item)
        self._commit_or_flush()
        return True

    # ---- 副本/特殊场景 ----
    def list_instances(self) -> list[Instance]:
        return self.db.query(Instance).filter(Instance.project_id == self.project_id).order_by(Instance.order, Instance.id).all()

    def get_instance(self, instance_id: int) -> Instance | None:
        return self.db.query(Instance).filter(
            Instance.project_id == self.project_id, Instance.id == instance_id
        ).first()

    def get_instance_by_name(self, name: str) -> Instance | None:
        return self.db.query(Instance).filter(
            Instance.project_id == self.project_id, Instance.name == name
        ).first()

    def create_instance(self, **kwargs) -> Instance:
        name = kwargs.get("name")
        if name:
            existing = self.get_instance_by_name(name)
            if existing:
                return existing
        item = Instance(project_id=self.project_id, **kwargs)
        self.db.add(item)
        try:
            self._commit_or_flush()
            self.db.refresh(item)
        except IntegrityError:
            self.db.rollback()
            existing = self.get_instance_by_name(kwargs.get("name"))
            if existing:
                return existing
            raise
        return item

    def delete_instance(self, instance_id: int) -> bool:
        item = self.get_instance(instance_id)
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
        deleted = self.db.query(EntityAppearance).filter(
            EntityAppearance.project_id == self.project_id,
            EntityAppearance.chapter == chapter,
        ).delete(synchronize_session=False)
        self._commit_or_flush()
        return deleted

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

        # 预扫描：收集活跃实体，一次性批量预取全部相关数据（消除 N+1 查询）
        char_names: set[str] = set()
        faction_ids: set[int] = set()
        monster_ids: set[int] = set()
        for a in apps:
            etype = (a.entity_type or "").lower()
            if etype in ("character", "characters"):
                char_names.add(a.entity_id)
            elif etype in ("faction", "factions"):
                try:
                    faction_ids.add(int(a.entity_id))
                except (ValueError, TypeError):
                    pass
            elif etype in ("monster", "monsters"):
                try:
                    monster_ids.add(int(a.entity_id))
                except (ValueError, TypeError):
                    pass

        # 主记录一次查出
        chars_by_name: dict[str, Character] = {}
        if char_names:
            chars_by_name = {c.name: c for c in self.db.query(Character).filter(
                Character.project_id == self.project_id,
                Character.name.in_(list(char_names)),
            ).all()}
        factions_by_id: dict[int, Faction] = {}
        if faction_ids:
            factions_by_id = {f.id: f for f in self.db.query(Faction).filter(
                Faction.project_id == self.project_id,
                Faction.id.in_(list(faction_ids)),
            ).all()}
        monsters_by_id: dict[int, Monster] = {}
        if monster_ids:
            monsters_by_id = {m.id: m for m in self.db.query(Monster).filter(
                Monster.project_id == self.project_id,
                Monster.id.in_(list(monster_ids)),
            ).all()}

        # 关系表按 project_id 一次查出后按角色/势力建倒排索引（保持原过滤与去重语义）
        rels_by_character: dict[str, list[str]] = {}
        for r in self.db.query(CharacterRelationship).filter(
            CharacterRelationship.project_id == self.project_id,
        ).all():
            rels_by_character.setdefault(r.source_character, []).append(
                f"{r.target_character}({r.relation_type})")
            if r.target_character != r.source_character:
                rels_by_character.setdefault(r.target_character, []).append(
                    f"{r.source_character}({r.relation_type})")
        rels_by_faction: dict[int, list[str]] = {}
        for r in self.db.query(FactionRelationship).filter(
            FactionRelationship.project_id == self.project_id,
        ).all():
            rels_by_faction.setdefault(r.source_faction_id, []).append(
                f"{r.target_faction_id}({r.relation_type})")
            if r.target_faction_id != r.source_faction_id:
                rels_by_faction.setdefault(r.target_faction_id, []).append(
                    f"{r.source_faction_id}({r.relation_type})")

        # 状态变化一次查出后按角色分组（保持 created_at 排序）
        changes_by_character: dict[str, list[StateChange]] = {}
        if char_names:
            for sc in self.db.query(StateChange).filter(
                StateChange.project_id == self.project_id,
                StateChange.entity_id.in_(list(char_names)),
            ).order_by(StateChange.created_at).all():
                changes_by_character.setdefault(sc.entity_id, []).append(sc)

        # appearances 按 (entity_type, entity_id) 预分组（保持原匹配语义）
        apps_by_entity: dict[tuple[str, str], list[EntityAppearance]] = {}
        for a in apps:
            apps_by_entity.setdefault((a.entity_type, a.entity_id), []).append(a)

        result: dict[str, list[dict]] = {"characters": [], "factions": [], "monsters": []}
        seen = {"character": set(), "faction": set(), "monster": set()}
        for a in apps:
            etype = (a.entity_type or "").lower()
            if etype in ("character", "characters"):
                eid = a.entity_id
                if eid in seen["character"]:
                    continue
                seen["character"].add(eid)
                char = chars_by_name.get(eid)
                if char:
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
                            for app in apps_by_entity.get((a.entity_type, eid), [])
                        ],
                        "relationships": rels_by_character.get(eid, []),
                        "recent_changes": [
                            f"{sc.field}={sc.new_value}"
                            for sc in changes_by_character.get(eid, [])
                            if sc.chapter <= chapter
                        ][-5:],
                    })
            elif etype in ("faction", "factions"):
                try:
                    fid = int(a.entity_id)
                except (ValueError, TypeError):
                    continue
                if fid in seen["faction"]:
                    continue
                seen["faction"].add(fid)
                f = factions_by_id.get(fid)
                if f:
                    result["factions"].append({
                        "name": f.name,
                        "tier": f.tier,
                        "type": f.type,
                        "alignment": f.alignment,
                        "role_in_chapter": a.role_in_chapter,
                        "relationships": rels_by_faction.get(fid, []),
                    })
            elif etype in ("monster", "monsters"):
                try:
                    mid = int(a.entity_id)
                except (ValueError, TypeError):
                    continue
                if mid in seen["monster"]:
                    continue
                seen["monster"].add(mid)
                m = monsters_by_id.get(mid)
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
    def _delete_character_refs(self, name: str) -> None:
        """删除角色时级联清理引用该名字的所有关联数据（与 update_character 的改名级联清单对应）。"""
        for ea in self.db.query(EntityAppearance).filter(
            EntityAppearance.project_id == self.project_id,
            EntityAppearance.entity_type.in_(["character", "角色"]),
            EntityAppearance.entity_id == name,
        ).all():
            self.db.delete(ea)
        for cr in self.db.query(CharacterRelationship).filter(
            CharacterRelationship.project_id == self.project_id,
            (CharacterRelationship.source_character == name) |
            (CharacterRelationship.target_character == name)
        ).all():
            self.db.delete(cr)
        for sc in self.db.query(StateChange).filter(
            StateChange.project_id == self.project_id,
            StateChange.entity_id == name,
        ).all():
            self.db.delete(sc)
        for te in self.db.query(TruthEvent).filter(
            TruthEvent.project_id == self.project_id,
            TruthEvent.entity_id == name,
        ).all():
            self.db.delete(te)
        for ea in self.db.query(EmotionArc).filter(
            EmotionArc.project_id == self.project_id,
            EmotionArc.character_name == name,
        ).all():
            self.db.delete(ea)
        for cm in self.db.query(CharacterMatrix).filter(
            CharacterMatrix.project_id == self.project_id,
            (CharacterMatrix.character_a == name) |
            (CharacterMatrix.character_b == name)
        ).all():
            self.db.delete(cm)
        for rc in self.db.query(RelationshipChange).filter(
            RelationshipChange.project_id == self.project_id,
            RelationshipChange.entity_type == "character",
            (RelationshipChange.source_id == name) |
            (RelationshipChange.target_id == name)
        ).all():
            self.db.delete(rc)
        for no in self.db.query(EntityNameOverride).filter(
            EntityNameOverride.project_id == self.project_id,
            EntityNameOverride.entity_type == "character",
            EntityNameOverride.canonical_name == name,
        ).all():
            self.db.delete(no)

    def delete_character(self, name: str) -> bool:
        c = self.get_character(name)
        if not c: return False
        self._delete_character_refs(name)
        self.db.delete(c); self._commit_or_flush()
        return True

    def delete_character_by_id(self, character_id: int) -> bool:
        c = self.get_character_by_id(character_id)
        if not c: return False
        self._delete_character_refs(c.name)
        self.db.delete(c); self._commit_or_flush()
        return True

    def delete_foreshadow(self, foreshadow_id: str) -> bool:
        f = self.get_foreshadow(foreshadow_id)
        if not f: return False
        # 级联清理出场记录与命名覆盖，避免删除后残留幽灵数据
        for ea in self.db.query(EntityAppearance).filter(
            EntityAppearance.project_id == self.project_id,
            EntityAppearance.entity_type.in_(["foreshadow", "伏笔"]),
            EntityAppearance.entity_id == foreshadow_id,
        ).all():
            self.db.delete(ea)
        for no in self.db.query(EntityNameOverride).filter(
            EntityNameOverride.project_id == self.project_id,
            EntityNameOverride.entity_type == "foreshadow",
            EntityNameOverride.canonical_name == foreshadow_id,
        ).all():
            self.db.delete(no)
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

    def delete_outlines_by_chapter(self, order: int) -> int:
        """删除指定章节号的所有 chapter 级大纲（用于 upsert 去重）。返回删除条数。"""
        deleted = self.db.query(Outline).filter(
            Outline.project_id == self.project_id,
            Outline.level == "chapter",
            Outline.order == order,
        ).delete(synchronize_session=False)
        if deleted:
            self._commit_or_flush()
        return deleted

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
        # ChatMessage 无 project_id 列，需按本项目 ChatSession 的 id 先行删除（先于 ChatSession）
        session_ids = [sid for (sid,) in self.db.query(ChatSession.id).filter(
            ChatSession.project_id == self.project_id).all()]
        if session_ids:
            count += self.db.query(ChatMessage).filter(
                ChatMessage.session_id.in_(session_ids)
            ).delete(synchronize_session=False)
        for model in [Character, CharacterRelationship, Faction, FactionRelationship,
                      Monster, Foreshadow, ForeshadowImplant, ChapterSummary,
                      EmotionArc, SubplotBoard, CharacterMatrix, WorldSetting,
                      Outline, TruthEvent, StateChange, ChapterCommit,
                      EntityAppearance, AiSuggestion, StateSnapshot, PleasureBeat, PlotDebt,
                      RelationshipChange, ChatSession, ChapterFeedback,
                      RedLine, Gag, ImportedChapter, Instance, EntityNameOverride,
                      WorldState, WorldEvent, Location, LocationRelationship,
                      Graph, CustomWorkflow, PostHocResult]:
            count += self.db.query(model).filter(
                model.project_id == self.project_id
            ).delete(synchronize_session=False)
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
                           entity_id: str | None = None,
                           limit: int | None = None) -> list[StateChange]:
        q = self.db.query(StateChange).filter(StateChange.project_id == self.project_id)
        if chapter is not None:
            q = q.filter(StateChange.chapter == chapter)
        if entity_id is not None:
            q = q.filter(StateChange.entity_id == entity_id)
        q = q.order_by(StateChange.created_at)
        if limit:
            q = q.limit(limit)
        return q.all()

    # ---- 关系变化 ----
    def create_relationship_change(self, chapter: int, entity_type: str, source_id: str,
                                   target_id: str, field: str, old_value: str,
                                   new_value: str, reason: str = "") -> RelationshipChange:
        rc = RelationshipChange(
            project_id=self.project_id, chapter=chapter, entity_type=entity_type,
            source_id=source_id, target_id=target_id, field=field,
            old_value=old_value, new_value=new_value, reason=reason,
        )
        self.db.add(rc)
        self._commit_or_flush()
        self.db.refresh(rc)
        return rc

    def list_relationship_changes(self, chapter: int | None = None,
                                  source_id: str | None = None,
                                  target_id: str | None = None) -> list[RelationshipChange]:
        q = self.db.query(RelationshipChange).filter(RelationshipChange.project_id == self.project_id)
        if chapter is not None:
            q = q.filter(RelationshipChange.chapter == chapter)
        if source_id is not None:
            q = q.filter(RelationshipChange.source_id == source_id)
        if target_id is not None:
            q = q.filter(RelationshipChange.target_id == target_id)
        return q.order_by(RelationshipChange.created_at).all()

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

    # ---- 状态快照 ----
    def save_state_snapshot(self, chapter: int, snapshot_data: dict,
                            drift_score: int = 0,
                            is_full_resummary: bool = False) -> StateSnapshot:
        """保存状态快照（删除同章旧快照后新建）。"""
        old = self.db.query(StateSnapshot).filter(
            StateSnapshot.project_id == self.project_id,
            StateSnapshot.chapter == chapter,
        ).all()
        for o in old:
            self.db.delete(o)
        snap = StateSnapshot(
            project_id=self.project_id, chapter=chapter,
            snapshot_data=snapshot_data, drift_score=drift_score,
            is_full_resummary=is_full_resummary,
        )
        self.db.add(snap)
        self._commit_or_flush()
        self.db.refresh(snap)
        return snap

    def get_latest_state_snapshot(self, chapter: int) -> StateSnapshot | None:
        """读取最近的状态快照（chapter 或之前最近的）。"""
        return self.db.query(StateSnapshot).filter(
            StateSnapshot.project_id == self.project_id,
            StateSnapshot.chapter <= chapter,
        ).order_by(StateSnapshot.chapter.desc()).first()

    # ---- 爽点供应链 ----
    def create_pleasure_beat(self, **kwargs) -> PleasureBeat:
        # LLM 返回的 delivered 可能是字符串 "true"/"false"，intensity 可能是字符串数字
        if "delivered" in kwargs:
            v = kwargs["delivered"]
            if isinstance(v, str):
                kwargs["delivered"] = v.lower() in ("true", "1", "yes")
            elif not isinstance(v, bool):
                kwargs["delivered"] = bool(v)
        for k in ("intensity", "delivered_intensity"):
            if k in kwargs:
                try:
                    kwargs[k] = int(kwargs[k])
                except (TypeError, ValueError):
                    kwargs[k] = 0
        b = PleasureBeat(project_id=self.project_id, **kwargs)
        self.db.add(b)
        self._commit_or_flush()
        self.db.refresh(b)
        return b

    def list_beats_for_chapter(self, chapter: int) -> list[PleasureBeat]:
        return self.db.query(PleasureBeat).filter(
            PleasureBeat.project_id == self.project_id,
            PleasureBeat.chapter == chapter,
        ).all()

    def list_beats_since(self, chapter: int) -> list[PleasureBeat]:
        """取 chapter 之后的所有 beat（含 chapter）。"""
        return self.db.query(PleasureBeat).filter(
            PleasureBeat.project_id == self.project_id,
            PleasureBeat.chapter >= chapter,
        ).order_by(PleasureBeat.chapter).all()

    def get_last_delivered_beat_chapter(self, chapter: int) -> int | None:
        """获取最近一次交付 beat 的章节号。"""
        beat = self.db.query(PleasureBeat).filter(
            PleasureBeat.project_id == self.project_id,
            PleasureBeat.chapter < chapter,
            PleasureBeat.delivered == True,
        ).order_by(PleasureBeat.chapter.desc()).first()
        return beat.chapter if beat else None

    def update_beat_delivery(self, beat_id: int, delivered: bool,
                             delivered_intensity: int = 0) -> None:
        b = self.db.query(PleasureBeat).filter(
            PleasureBeat.project_id == self.project_id,
            PleasureBeat.id == beat_id,
        ).first()
        if b:
            b.delivered = delivered
            b.delivered_intensity = delivered_intensity
            self._commit_or_flush()

    def get_pleasure_gap(self, chapter: int) -> int:
        """计算距离上次交付 beat 的章数间隔。"""
        last = self.get_last_delivered_beat_chapter(chapter)
        if last is None:
            return chapter  # 从第1章开始算
        return chapter - last

    # ---- 欠账账本 ----
    def create_plot_debt(self, **kwargs) -> PlotDebt:
        d = PlotDebt(project_id=self.project_id, **kwargs)
        self.db.add(d)
        self._commit_or_flush()
        self.db.refresh(d)
        return d

    def list_open_debts(self) -> list[PlotDebt]:
        return self.db.query(PlotDebt).filter(
            PlotDebt.project_id == self.project_id,
            PlotDebt.status == "open",
        ).order_by(PlotDebt.pressure.desc()).all()

    def resolve_debt(self, debt_id: int, chapter: int) -> None:
        d = self.db.query(PlotDebt).filter(
            PlotDebt.project_id == self.project_id,
            PlotDebt.id == debt_id,
        ).first()
        if d:
            d.status = "resolved"
            d.resolved_chapter = chapter
            self._commit_or_flush()

    # ---- 红线（RedLine）----
    def list_red_lines(self, scope: str | None = None,
                       chapter_num: int | None = None) -> list[RedLine]:
        """列出红线，可按 scope/chapter_num 过滤。

        - scope="project" 仅项目级（chapter_num IS NULL）
        - scope="chapter"  仅章级（chapter_num IS NOT NULL）
        - chapter_num=N    指定章级红线
        """
        q = self.db.query(RedLine).filter(RedLine.project_id == self.project_id)
        if scope == "project":
            q = q.filter(RedLine.chapter_num.is_(None))
        elif scope == "chapter":
            q = q.filter(RedLine.chapter_num.is_not(None))
        if chapter_num is not None:
            q = q.filter(RedLine.chapter_num == chapter_num)
        return q.order_by(RedLine.id).all()

    def get_red_line(self, red_line_id: int) -> RedLine | None:
        return self.db.query(RedLine).filter(
            RedLine.project_id == self.project_id,
            RedLine.id == red_line_id,
        ).first()

    def create_red_line(self, **kwargs) -> RedLine:
        r = RedLine(project_id=self.project_id, **kwargs)
        self.db.add(r)
        self._commit_or_flush()
        self.db.refresh(r)
        return r

    def update_red_line(self, red_line_id: int, **kwargs) -> RedLine | None:
        r = self.get_red_line(red_line_id)
        if not r:
            return None
        for k, v in kwargs.items():
            if hasattr(r, k):
                setattr(r, k, v)
        self._commit_or_flush()
        self.db.refresh(r)
        return r

    def delete_red_line(self, red_line_id: int) -> bool:
        r = self.get_red_line(red_line_id)
        if not r:
            return False
        self.db.delete(r)
        self._commit_or_flush()
        return True

    def list_active_red_lines_for_chapter(self, chapter_num: int) -> list[RedLine]:
        """取本章生效的红线：项目级 + 本章级，且 enabled=True。"""
        return self.db.query(RedLine).filter(
            RedLine.project_id == self.project_id,
            RedLine.enabled == True,  # noqa: E712
            (RedLine.chapter_num.is_(None)) | (RedLine.chapter_num == chapter_num),
        ).order_by(RedLine.id).all()

    # ---- 梗（Gag）----
    def list_gags(self, category: str | None = None,
                  status: str | None = None) -> list[Gag]:
        q = self.db.query(Gag).filter(Gag.project_id == self.project_id)
        if category:
            q = q.filter(Gag.category == category)
        if status:
            q = q.filter(Gag.status == status)
        return q.order_by(Gag.id).all()

    def get_gag(self, gag_id: int) -> Gag | None:
        return self.db.query(Gag).filter(
            Gag.project_id == self.project_id,
            Gag.id == gag_id,
        ).first()

    def create_gag(self, **kwargs) -> Gag:
        g = Gag(project_id=self.project_id, **kwargs)
        self.db.add(g)
        self._commit_or_flush()
        self.db.refresh(g)
        return g

    def update_gag(self, gag_id: int, **kwargs) -> Gag | None:
        g = self.get_gag(gag_id)
        if not g:
            return None
        for k, v in kwargs.items():
            if hasattr(g, k):
                setattr(g, k, v)
        self._commit_or_flush()
        self.db.refresh(g)
        return g

    def delete_gag(self, gag_id: int) -> bool:
        g = self.get_gag(gag_id)
        if not g:
            return False
        self.db.delete(g)
        self._commit_or_flush()
        return True

    # ---- 命名权威别名修正（EntityNameOverride）----
    def list_name_overrides(self, entity_type: str | None = None,
                            canonical_name: str | None = None) -> list[EntityNameOverride]:
        """列出"我的修正"（别名合并记录），可按实体类型/规范名过滤。"""
        q = self.db.query(EntityNameOverride).filter(
            EntityNameOverride.project_id == self.project_id)
        if entity_type:
            q = q.filter(EntityNameOverride.entity_type == entity_type)
        if canonical_name:
            q = q.filter(EntityNameOverride.canonical_name == canonical_name)
        return q.order_by(EntityNameOverride.id).all()

    def get_name_override(self, override_id: int) -> EntityNameOverride | None:
        return self.db.query(EntityNameOverride).filter(
            EntityNameOverride.project_id == self.project_id,
            EntityNameOverride.id == override_id,
        ).first()

    def create_name_override(self, entity_type: str, canonical_name: str,
                             alias: str, note: str = "") -> EntityNameOverride:
        o = EntityNameOverride(
            project_id=self.project_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            alias=alias,
            note=note,
        )
        self.db.add(o)
        self._commit_or_flush()
        self.db.refresh(o)
        return o

    def delete_name_override(self, override_id: int) -> bool:
        """删除记录即回滚该别名合并。"""
        o = self.get_name_override(override_id)
        if not o:
            return False
        self.db.delete(o)
        self._commit_or_flush()
        return True

    # ---- 导入章节（ImportedChapter）----
    def list_imported_chapters(self) -> list[ImportedChapter]:
        return self.db.query(ImportedChapter).filter(
            ImportedChapter.project_id == self.project_id,
        ).order_by(ImportedChapter.chapter_order, ImportedChapter.id).all()

    def get_imported_chapter(self, imported_id: int) -> ImportedChapter | None:
        return self.db.query(ImportedChapter).filter(
            ImportedChapter.project_id == self.project_id,
            ImportedChapter.id == imported_id,
        ).first()

    def get_imported_chapter_by_chapter(self, chapter_num: int) -> ImportedChapter | None:
        return self.db.query(ImportedChapter).filter(
            ImportedChapter.project_id == self.project_id,
            ImportedChapter.chapter_order == chapter_num,
        ).first()

    def create_imported_chapter(self, **kwargs) -> ImportedChapter:
        ic = ImportedChapter(project_id=self.project_id, **kwargs)
        self.db.add(ic)
        self._commit_or_flush()
        self.db.refresh(ic)
        return ic

    def delete_imported_chapter(self, imported_id: int) -> bool:
        ic = self.get_imported_chapter(imported_id)
        if not ic:
            return False
        self.db.delete(ic)
        self._commit_or_flush()
        return True

    def delete_imported_chapters_for_project(self) -> int:
        """删除项目所有导入章节，返回删除条数。"""
        items = self.db.query(ImportedChapter).filter(
            ImportedChapter.project_id == self.project_id,
        ).all()
        for it in items:
            self.db.delete(it)
        if items:
            self._commit_or_flush()
        return len(items)
