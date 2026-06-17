"""圣经仓储：CRUD 封装。所有写操作经此层，便于后续加校验/事件。"""
from __future__ import annotations

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

    # ---- 项目 ----
    def get_project(self) -> Project | None:
        return self.db.query(Project).filter(Project.id == self.project_id).first()

    # ---- 角色 ----
    def create_character(self, **kwargs) -> Character:
        c = Character(project_id=self.project_id, **kwargs)
        self.db.add(c)
        self.db.commit()
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
        self.db.commit()
        self.db.refresh(c)
        return c

    # ---- 伏笔 ----
    def create_foreshadow(self, **kwargs) -> Foreshadow:
        f = Foreshadow(project_id=self.project_id, **kwargs)
        self.db.add(f)
        self.db.commit()
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
        self.db.commit()
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
        self.db.commit()
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
        self.db.commit()
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

    # ---- 大纲 ----
    def create_outline(self, **kwargs) -> Outline:
        o = Outline(project_id=self.project_id, **kwargs)
        self.db.add(o)
        self.db.commit()
        self.db.refresh(o)
        return o

    def list_outlines(self, level: str | None = None) -> list[Outline]:
        q = self.db.query(Outline).filter(Outline.project_id == self.project_id)
        if level:
            q = q.filter(Outline.level == level)
        return q.order_by(Outline.order).all()
