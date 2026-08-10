"""Delta schema：agent 产出 → 校验 → apply 的契约。

spec 2.4：模型只输出 JSON delta，pydantic 校验后 immutable apply。
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class ForeshadowDelta(BaseModel):
    foreshadow_id: str
    description: str = ""
    tier: str = ""
    plant_chapter: int = 0
    planned_resolve_chapter: int = 0
    depends_on: str = ""
    implant_method: str = ""


class CharacterDelta(BaseModel):
    name: str
    role: str = ""
    personality: str = ""
    motivation: str = ""
    current_location: str = ""
    current_emotion: str = ""
    known_info: str = ""
    core_contradiction: str = ""
    sensory_memories: str = ""
    absolute_taboos: str = ""


class SummaryDelta(BaseModel):
    title: str = ""
    word_count: int = 0
    time_location: str = ""
    core_events: str = ""
    characters_present: str = ""
    emotion_changes: str = ""
    foreshadow_dynamics: str = ""
    subplot_progress: str = ""
    chapter_hook: str = ""


class OutlineDelta(BaseModel):
    level: Literal["volume", "arc", "chapter"]
    order: int = 0
    act: str = ""
    strand: str = ""
    title: str = ""
    summary: str = ""


# data 字段可接受的具体 delta 类型联合
DeltaData = Union[
    ForeshadowDelta, CharacterDelta, SummaryDelta, OutlineDelta, dict,
]


class Delta(BaseModel):
    """单个 delta 操作。"""
    target: Literal["foreshadow", "character", "chapter_summary",
                    "outline", "world_setting"]
    action: Literal["create", "update", "plant", "develop", "resolve",
                    "state_change", "delete"]
    chapter: int
    data: DeltaData = Field(default_factory=dict)
    notes: str = ""
