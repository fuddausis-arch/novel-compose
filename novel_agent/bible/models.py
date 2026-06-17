"""圣经 ORM 模型：9 库 + 事件流表。

对应 spec 第 2.2 节。所有时间戳用 UTC。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON,
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(50), default="")          # 主角/配角/反派
    age = Column(String(50), default="")
    gender = Column(String(20), default="")
    appearance = Column(Text, default="")
    background = Column(Text, default="")
    personality = Column(Text, default="")
    motivation = Column(Text, default="")
    # 动态状态（每章 diff 更新）
    current_location = Column(String(200), default="")
    current_emotion = Column(String(100), default="")
    known_info = Column(Text, default="")          # 角色已知信息（信息边界）
    arc = Column(Text, default="")
    relationships = Column(Text, default="")
    secrets = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorldSetting(Base):
    """世界设定（对应「核心设定」）。"""
    __tablename__ = "world_settings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    level = Column(String(20), nullable=False)     # volume / arc / chapter
    parent_id = Column(Integer, ForeignKey("outlines.id"), nullable=True)
    order = Column(Integer, default=0)
    act = Column(String(50), default="")           # 开端/发展/高潮/结局 或 卷名
    title = Column(String(200), default="")
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Foreshadow(Base):
    """伏笔台账（对应「伏笔与道具追踪」）。"""
    __tablename__ = "foreshadows"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    foreshadow_id = Column(String(20), nullable=False, index=True)
    chapter = Column(Integer, default=0)
    implant_method = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ChapterSummary(Base):
    """章节摘要历史。"""
    __tablename__ = "chapter_summaries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    chapter = Column(Integer, nullable=False, index=True)
    type = Column(String(50), nullable=False)      # foreshadow_planted/foreshadow_resolved/
                                                   # character_state_change/resource_change/
                                                   # relationship_change/timeline_event
    entity_id = Column(String(100), default="")    # 伏笔id/角色名/物品名
    payload = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
