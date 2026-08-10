"""审计报告 schema：Auditor 产出的结构化报告。

多维度审查：用户视角 + 专业视角 + 编辑视角。
审查不通过时触发对抗性讨论，Writer 和 Auditor 多轮辩论后优化。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Issue(BaseModel):
    """单个审计问题。"""
    dimension: str = ""
    severity: Literal["critical", "important", "minor"] = "minor"
    message: str = ""
    location: str = ""       # 段落/行号引用

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, v):
        if isinstance(v, str):
            low = v.strip().lower()
            if low in ("critical", "important", "minor"):
                return low
        return "minor"


class PerspectiveScore(BaseModel):
    """单视角评分。"""
    score: int = Field(default=0, ge=0, le=100)
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    summary: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_score(cls, v):
        if v is None:
            return 0
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    @field_validator("passed", mode="before")
    @classmethod
    def _coerce_passed(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "通过", "pass", "passed")
        if isinstance(v, (int, float)):
            return bool(v)
        return bool(v)


class AuditReport(BaseModel):
    """章节审计报告（多维度）。"""
    passed: bool = False             # 三视角全部 passed 才算通过
    overall_score: int = Field(default=0, ge=0, le=100)   # 综合分
    # 三视角评分
    user_perspective: PerspectiveScore = Field(default_factory=PerspectiveScore)
    expert_perspective: PerspectiveScore = Field(default_factory=PerspectiveScore)
    editor_perspective: PerspectiveScore = Field(default_factory=PerspectiveScore)
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""
    suggestions: list[str] = Field(default_factory=list)
    # 对抗性讨论记录
    debate_rounds: list[dict] = Field(default_factory=list)

    @field_validator("overall_score", mode="before")
    @classmethod
    def _coerce_score(cls, v):
        if v is None:
            return 0
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    @field_validator("passed", mode="before")
    @classmethod
    def _coerce_passed(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "通过", "pass", "passed")
        if isinstance(v, (int, float)):
            return bool(v)
        return bool(v)

    @field_validator("suggestions", mode="before")
    @classmethod
    def _coerce_suggestions(cls, v):
        if v is None:
            return []
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(item.get("text") or item.get("message") or item.get("suggestion") or str(item))
            else:
                result.append(str(item))
        return result
