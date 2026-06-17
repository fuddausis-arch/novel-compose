"""测试 ORM 模型能正确建表。"""
from sqlalchemy import inspect

from novel_agent.bible.database import engine
from novel_agent.bible.models import (
    Base, Project, Character, WorldSetting, Outline,
    Foreshadow, ForeshadowImplant, ChapterSummary,
    EmotionArc, SubplotBoard, CharacterMatrix, TruthEvent,
)


def test_all_tables_created():
    """所有 9 库 + 事件流 + project 表应被创建。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "projects", "characters", "world_settings", "outlines",
        "foreshadows", "foreshadow_implants", "chapter_summaries",
        "emotion_arcs", "subplot_board", "character_matrix",
        "truth_events",
    }
    assert expected.issubset(tables), f"缺失表: {expected - tables}"


def test_truth_event_columns():
    """事件流表应有 chapter/type/entity_id/payload/timestamp。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("truth_events")}
    assert {"id", "chapter", "type", "entity_id", "payload", "timestamp"}.issubset(cols)


def test_foreshadow_status_column():
    """伏笔表应有 status 字段。"""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("foreshadows")}
    assert "status" in cols
