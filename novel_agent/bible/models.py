"""圣经 ORM 模型：9 库 + 事件流表。

对应 spec 第 2.2 节。所有时间戳用 UTC。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Project(Base):
    """小说项目元信息。"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    genre = Column(String(100), default="")
    summary = Column(Text, default="")
    style = Column(Text, default="")
    constitution = Column(Text, default="")
    target_audience = Column(String(200), default="")
    word_count_target = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Character(Base):
    """角色卡（对应「主要人物卡」）。"""
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), default="")          # 主角/配角/反派
    age = Column(String(50), default="")
    gender = Column(String(20), default="")
    appearance = Column(Text, default="")
    background = Column(Text, default="")
    personality = Column(Text, default="")
    motivation = Column(Text, default="")
    importance = Column(String(50), default="")    # 主角/配角/关键人物/小人物/NPC
    # 动态状态（每章 diff 更新）
    current_location = Column(String(200), default="")
    current_emotion = Column(String(100), default="")
    known_info = Column(Text, default="")          # 角色已知信息（信息边界）
    arc = Column(Text, default="")
    relationships = Column(Text, default="")
    secrets = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Faction(Base):
    __tablename__ = "factions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    alias = Column(String, default="")
    type = Column(String, default="")
    tier = Column(String(50), default="")           # 顶级势力/一流势力/二流势力/三流势力/隐世势力
    alignment = Column(String, default="")
    description = Column(Text, default="")
    history = Column(Text, default="")
    goals = Column(Text, default="")
    hierarchy = Column(Text, default="")
    territories = Column(Text, default="")
    resources = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_faction_name"),)


class FactionRelationship(Base):
    __tablename__ = "faction_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_faction_id = Column(Integer, ForeignKey("factions.id", ondelete="CASCADE"), nullable=False)
    target_faction_id = Column(Integer, ForeignKey("factions.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String, default="neutral")
    strength = Column(Integer, default=0)
    description = Column(Text, default="")
    since_chapter = Column(Integer, default=0)
    status = Column(String, default="active")
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_character = Column(String, nullable=False)
    target_character = Column(String, nullable=False)
    relation_type = Column(String, default="other")
    relation_subtype = Column(String, default="")
    strength = Column(Integer, default=0)
    description = Column(Text, default="")
    since_chapter = Column(Integer, default=0)
    status = Column(String, default="active")
    is_bidirectional = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "source_character", "target_character", "relation_type", name="uix_project_char_rel"),)


class Monster(Base):
    __tablename__ = "monsters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    alias = Column(String, default="")
    species = Column(String, default="")
    rank = Column(String, default="")
    tier = Column(String(50), default="")           # BOSS/精英/首领/小怪/普通
    attributes = Column(Text, default="")
    skills = Column(Text, default="")
    drops = Column(Text, default="")
    habitats = Column(Text, default="")
    behavior = Column(Text, default="")
    weaknesses = Column(Text, default="")
    lore = Column(Text, default="")
    first_appearance = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "name", name="uix_project_monster_name"),)


class EntityAppearance(Base):
    __tablename__ = "entity_appearances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String, nullable=False)  # character / faction / monster
    entity_id = Column(String, nullable=False)    # name for character, id for faction/monster (store as string)
    chapter = Column(Integer, nullable=False)
    role_in_chapter = Column(String, default="mention")  # lead / participant / mention / background
    context_snippet = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().isoformat())
    updated_at = Column(String, default=lambda: datetime.now().isoformat(), onupdate=lambda: datetime.now().isoformat())

    __table_args__ = (UniqueConstraint("project_id", "entity_type", "entity_id", "chapter", name="uix_entity_appearance"),)


class WorldSetting(Base):
    """世界设定（对应「核心设定」）。"""
    __tablename__ = "world_settings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), default="")      # 世界观/力量体系/势力/地点/规则
    title = Column(String(200), default="")
    content = Column(Text, default="")
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Outline(Base):
    """大纲：卷→弧→章三级（对应「细纲」）。"""
    __tablename__ = "outlines"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(20), nullable=False)     # volume / arc / chapter
    parent_id = Column(Integer, ForeignKey("outlines.id", ondelete="CASCADE"), nullable=True)
    order = Column(Integer, default=0)
    act = Column(String(50), default="")           # 开端/发展/高潮/结局 或 卷名
    strand = Column(String(20), default="")        # quest / fire / constellation
    title = Column(String(200), default="")
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Foreshadow(Base):
    """伏笔台账（对应「伏笔与道具追踪」）。"""
    __tablename__ = "foreshadows"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)  # S-001 / M-001 / L-001
    tier = Column(String(10), default="")          # short / medium / long
    plant_chapter = Column(Integer, default=0)
    description = Column(Text, default="")
    depends_on = Column(Text, default="")          # 依赖的其他伏笔 id
    status = Column(String(20), default="pending")  # pending/planted/developing/resolved/abandoned
    planned_resolve_chapter = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ForeshadowImplant(Base):
    """伏笔植入方案（对应「核心伏笔早期植入方案」）。"""
    __tablename__ = "foreshadow_implants"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)
    chapter = Column(Integer, default=0)
    implant_method = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterSummary(Base):
    """章节摘要历史。"""
    __tablename__ = "chapter_summaries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    title = Column(String(200), default="")
    time_location = Column(String(500), default="")
    core_events = Column(Text, default="")
    characters_present = Column(Text, default="")
    emotion_changes = Column(Text, default="")
    foreshadow_dynamics = Column(Text, default="")
    subplot_progress = Column(Text, default="")
    chapter_hook = Column(Text, default="")
    word_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmotionArc(Base):
    """情感弧线追踪。"""
    __tablename__ = "emotion_arcs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    character_name = Column(String(100), nullable=False, index=True)
    chapter = Column(Integer, nullable=False)
    event = Column(Text, default="")
    emotion_before = Column(String(100), default="")
    emotion_after = Column(String(100), default="")
    growth = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SubplotBoard(Base):
    """支线进度板。"""
    __tablename__ = "subplot_board"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    is_main = Column(Integer, default=0)           # 1=主线 0=支线
    status = Column(String(50), default="active")  # active/paused/resolved
    progress = Column(Integer, default=0)          # 0-100
    related_characters = Column(Text, default="")
    next_goal = Column(Text, default="")
    planned_resolve_chapter = Column(Integer, default=0)
    updated_chapter = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CharacterMatrix(Base):
    """角色交互矩阵：相遇记录/知识边界/信息传播。"""
    __tablename__ = "character_matrix"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False)
    character_a = Column(String(100), nullable=False)
    character_b = Column(String(100), default="")
    interaction_type = Column(String(50), default="")  # meeting/conflict/cooperation/info_share
    info_exchanged = Column(Text, default="")
    relationship_change = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class TruthEvent(Base):
    """事件流：不可变追加，支持 time-travel 查询（spec 2.3）。"""
    __tablename__ = "truth_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    type = Column(String(50), nullable=False)      # foreshadow_planted/foreshadow_resolved/
                                                   # character_state_change/resource_change/
                                                   # relationship_change/timeline_event
    entity_id = Column(String(100), default="")    # 伏笔id/角色名/物品名
    payload = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class StateChange(Base):
    """实体状态增量：记录角色/物品/势力等字段变化。"""
    __tablename__ = "state_changes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    entity_type = Column(String(50), default="")   # 角色/地点/物品/势力/招式
    entity_id = Column(String(100), default="")
    field = Column(String(100), default="")        # 字段路径，如 realm / location.current
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterCommit(Base):
    """章节提交记录：标记本章已提取事实并落库。"""
    __tablename__ = "chapter_commits"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    status = Column(String(20), default="draft")   # draft / committed
    summary = Column(Text, default="")
    word_count = Column(Integer, default=0)
    committed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AiSuggestion(Base):
    """AI 一键串联建议历史。"""
    __tablename__ = "ai_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    context_type = Column(String(50), nullable=False)   # outline / chapter / monster / faction / relationship
    context_id = Column(String(100), default="")        # outline.id / chapter number / asset id
    suggest_type = Column(String(50), nullable=False)   # plot / monster / faction / relationship
    prompt = Column(Text, default="")
    raw_response = Column(Text, default="")
    adopted_items = Column(JSON, default=list)
    status = Column(String(20), default="adopted")      # adopted / partial / rejected
    created_at = Column(DateTime, default=datetime.utcnow)


def migrate_db(engine) -> None:
    """SQLite 轻量迁移：创建缺失表、为已存在表补上新列。"""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            try:
                table.create(bind=engine)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"migrate_db create table {table.name}: {exc}")
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing or col.primary_key:
                continue
            try:
                type_sql = col.type.compile(dialect=engine.dialect)
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {type_sql}"))
                    conn.commit()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"migrate_db skip {table.name}.{col.name}: {exc}")
