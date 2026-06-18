"""圣经仓储：CRUD 封装。所有写操作经此层，便于后续加校验/事件。"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy.orm import Session

from novel_agent.bible.models import (
    Character, Foreshadow, TruthEvent, ChapterSummary,
    EmotionArc, SubplotBoard, CharacterMatrix, WorldSetting, Outline,
    ForeshadowImplant, Project,
)


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
            self._commit_or_flush()
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

    def update_foreshadow_status(self, foreshadow_id: str, status: str) -> Foreshadow | None:
        f = self.get_foreshadow(foreshadow_id)
        if not f:
            return None
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

    # ---- 大纲 ----
    def create_outline(self, **kwargs) -> Outline:
        o = Outline(project_id=self.project_id, **kwargs)
        self.db.add(o)
        self._commit_or_flush()
        self.db.refresh(o)
        return o

    def list_outlines(self, level: str | None = None) -> list[Outline]:
        q = self.db.query(Outline).filter(Outline.project_id == self.project_id)
        if level:
            q = q.filter(Outline.level == level)
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
