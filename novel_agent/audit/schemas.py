"""审计报告 schema：Auditor 产出的结构化报告。

spec 第 5.2 节：关键维度任一不过直接打回；次要维度通过率 ≥80% 通过。
Fitness 总分 = 字数/重复率/审阅通过率/读者分/大纲偏离 加权。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Issue(BaseModel):
    """单个审计问题。"""
    dimension: str = ""
    severity: str = "minor"
    message: str = ""
    location: str = ""       # 段落/行号引用


class AuditReport(BaseModel):
    """章节审计报告。"""
    passed: bool = False             # 是否达标（关键维度全过 + 次要通过率≥80%）
    overall_score: int = Field(default=0, ge=0, le=100)   # Fitness 总分
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""        # 总评
    suggestions: list[str] = Field(default_factory=list)  # 给 Writer 的修订建议

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
