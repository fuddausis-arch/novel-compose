"""卷级规划状态 schema。"""
from __future__ import annotations
from typing import TypedDict


class VolumePlanState(TypedDict, total=False):
    project_id: int
    volume: str               # 卷名（保留兼容，全书规划不再依赖）
    chapter_count: int        # 本卷章节数（保留兼容，全书规划不再依赖）
    target_volumes: int       # 全书目标卷数（0=由 AI 自决）
    custom_prompt: str        # 用户对全书的规划要求（金手指/世界观/角色性格/卷次要求等）
    golden_finger: str        # 金手指设定（JSON 字符串）
    protagonist: str          # 主角设定（JSON 字符串）
    constitution: str         # 设定纲领/硬约束
    volume_plan: dict         # Planner 产出的卷规划（含 central_concept + volumes）
    settings: dict            # Architect 产出的设定
    outline: dict             # Outliner 产出的章节细纲（已从规划 pipeline 移除，保留字段兼容）
    review_decision: dict     # 人审①的决策（approved/edits）
    status: str               # PlanningStatus: pending/planned/designed/reviewing/approved/rejected/failed
    error: str
    errors: list[str]         # 写入圣经时的去重/失败警告列表
