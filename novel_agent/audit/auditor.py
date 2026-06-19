"""Auditor agent：独立审校，产出结构化审计报告。

写审分离铁律（spec 第 0.3 节）：Auditor 与 Writer 是独立 LLM 调用，
Auditor 只看成稿 + 圣经，不知生成过程，防自我背书。
"""
from __future__ import annotations

import json
import re

from novel_agent.audit.dimensions import DIMENSIONS, CRITICAL_DIMENSIONS
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient

AUDITOR_SYSTEM_PROMPT = (
    "你是一位严苛的网文审校编辑。独立审阅章节草稿，对照圣经设定检查一致性。"
    "只看成稿和设定，不知生成过程。按维度产出结构化 JSON 审计报告。"
)


def _build_dimensions_text() -> str:
    """把审计维度格式化为 prompt 文本。"""
    lines = []
    for d in DIMENSIONS:
        tag = "【关键】" if d.critical else ""
        lines.append(f"- {tag}{d.name}（{d.category.value}）：{d.check}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON（容忍 markdown 代码块包裹）。"""
    # 先尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # 尝试找第一个 { 到最后一个 }
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


class Auditor:
    """独立审校 agent。"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def audit(self, chapter: int, title: str, draft: str,
                    repo: BibleRepository) -> AuditReport:
        """审阅章节草稿，返回结构化审计报告。"""
        # 装配审校上下文：角色状态 + 伏笔 + 审计维度
        chars = repo.list_characters()
        char_text = "\n".join(
            f"- {c.name}（{c.role}）：{c.personality}，位置={c.current_location}"
            for c in chars
        ) or "无角色记录"
        to_plant = repo.get_foreshadows_to_plant(chapter)
        to_resolve = repo.get_foreshadows_to_resolve(chapter)
        foreshadow_text = ""
        if to_plant:
            foreshadow_text += "应埋：" + "；".join(f"{f.foreshadow_id}:{f.description}" for f in to_plant)
        if to_resolve:
            foreshadow_text += "应回收：" + "；".join(f"{f.foreshadow_id}:{f.description}" for f in to_resolve)

        prompt = (
            f"审阅第{chapter}章《{title}》草稿。\n\n"
            f"【角色状态】\n{char_text}\n\n"
            f"【伏笔要求】\n{foreshadow_text or '无'}\n\n"
            f"【审计维度】\n{_build_dimensions_text()}\n\n"
            f"【草稿正文】\n{draft}\n\n"
            f"要求：按上述维度审阅，输出 JSON：\n"
            f'{{"passed": bool, "overall_score": 0-100, '
            f'"issues": [{{"dimension":"","severity":"critical|important|minor",'
            f'"message":"","location":""}}], "summary": "", "suggestions": []}}\n'
            f"关键维度任一不过则 passed=false。只输出 JSON。"
        )
        try:
            raw = await self.llm_client.generate(prompt, system=AUDITOR_SYSTEM_PROMPT)
        except Exception as e:
            return AuditReport(passed=False, overall_score=0,
                               summary=f"LLM 调用失败: {e}")

        data = _extract_json(raw)
        if data is None:
            return AuditReport(passed=False, overall_score=0,
                               summary="审计报告解析失败：LLM 未返回有效 JSON")

        # 字段补全
        if "passed" not in data:
            issues = data.get("issues", [])
            has_critical = any(
                str(i.get("severity", "")).lower() == "critical"
                for i in issues if isinstance(i, dict)
            )
            data["passed"] = not has_critical
        if "overall_score" not in data:
            data["overall_score"] = 60

        try:
            return AuditReport.model_validate(data)
        except Exception as e:
            return AuditReport(passed=False, overall_score=0,
                               summary=f"审计报告字段校验失败: {e}")
