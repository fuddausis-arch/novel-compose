"""审计报告 schema：Auditor 产出的结构化报告。

spec 第 5.2 节：关键维度任一不过直接打回；次要维度通过率 ≥80% 通过。
Fitness 总分 = 字数/重复率/审阅通过率/读者分/大纲偏离 加权。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Issue(BaseModel):
    """单个审计问题。"""
    dimension: str
    severity: Literal["critical", "important", "minor"]
    message: str
    location: str = ""       # 段落/行号引用


class AuditReport(BaseModel):
    """章节审计报告。"""
    passed: bool             # 是否达标（关键维度全过 + 次要通过率≥80%）
    overall_score: int = Field(ge=0, le=100)   # Fitness 总分
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""        # 总评
    suggestions: list[str] = Field(default_factory=list)  # 给 Writer 的修订建议
