"""卷级规划状态 schema。"""
from __future__ import annotations
from typing import TypedDict


class VolumePlanState(TypedDict, total=False):
    project_id: int
    volume: str               # 卷名
    chapter_count: int        # 本卷章节数
    volume_plan: dict         # Planner 产出的卷规划
    settings: dict            # Architect 产出的设定
    outline: dict             # Outliner 产出的章节细纲
    review_decision: dict     # 人审①的决策（approved/edits）
    status: str               # pending/planned/designed/outlined/reviewing/approved/rejected/failed
    error: str
