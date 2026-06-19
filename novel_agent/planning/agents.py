"""规划三 agent：Planner（卷规划）/Architect（设定）/Outliner（章节细纲+伏笔）。

每个 agent 调 LLM 产出结构化 JSON，经 DeltaApplier 写入圣经。
"""
from __future__ import annotations

import json
import re

from novel_agent.bible.models import Project
from novel_agent.llm.client import LLMClient


def _extract_json(text: str) -> dict:
    """从 LLM 输出提取 JSON（容忍代码块包裹）。"""
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


PLANNER_SYSTEM = "你是网文总编。规划全书卷次结构、节奏曲线、爽点分布。只输出 JSON。"
ARCHITECT_SYSTEM = "你是网文设定师。设计世界观、角色、力量体系。只输出 JSON。"
OUTLINER_SYSTEM = "你是网文大纲师。规划本卷章节细纲和伏笔布局。只输出 JSON。"


class Planner:
    """总编：全书→卷→弧三级规划。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def plan(self, project: Project, target_chapters: int = 30) -> dict:
        prompt = (
            f"为以下小说规划卷次结构，目标 {target_chapters} 章。\n\n"
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n\n"
            f"输出 JSON：{{\"volumes\":[{{\"name\":\"\",\"theme\":\"\","
            f"\"chapters\":0,\"summary\":\"\"}}]}}\n只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=PLANNER_SYSTEM)
        return _extract_json(raw)


class Architect:
    """设定组：世界观/角色/力量体系。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def design(self, project: Project, volume_plan: dict) -> dict:
        prompt = (
            f"为以下小说设计核心设定。\n\n"
            f"标题：{project.title}\n类型：{project.genre}\n简介：{project.summary}\n"
            f"卷规划：{json.dumps(volume_plan, ensure_ascii=False)}\n\n"
            f"输出 JSON：{{\"characters\":[{{\"name\":\"\",\"role\":\"\","
            f"\"personality\":\"\",\"motivation\":\"\"}}],"
            f"\"world_settings\":[{{\"category\":\"\",\"title\":\"\",\"content\":\"\"}}]}}\n"
            f"只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=ARCHITECT_SYSTEM)
        return _extract_json(raw)


class Outliner:
    """大纲师：本卷章节细纲 + 伏笔布局。"""
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def outline(self, project: Project, volume: str,
                      chapter_count: int) -> dict:
        prompt = (
            f"为《{project.title}》的{volume}规划 {chapter_count} 章细纲。\n\n"
            f"类型：{project.genre}\n简介：{project.summary}\n\n"
            f"输出 JSON：{{\"chapters\":[{{\"chapter\":1,\"title\":\"\","
            f"\"summary\":\"\",\"foreshadows\":[{{\"id\":\"F-XXX\","
            f"\"description\":\"\",\"plant_chapter\":1,\"resolve_chapter\":3}}]}}]}}\n"
            f"伏笔 ID 需项目内唯一（格式 F-001/F-002...），不要照抄示例值 F-XXX。\n"
            f"只输出 JSON。"
        )
        raw = await self.llm_client.generate(prompt, system=OUTLINER_SYSTEM)
        return _extract_json(raw)
