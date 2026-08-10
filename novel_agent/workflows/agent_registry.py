"""bishu-novel 33 个 Agent 定义的注册器。

把 workflows/resources/agents.json 中的 33 个 Agent 定义
播种进 NovelAgent 的 Agent 管理存储（project_data/agents.json），
使前端 Agent 管理页可查看/编辑这些定义，工作流执行器可引用。

字段映射（bishu -> NovelAgent 管理字段）：
- model_params.temperature/top_p/thinking_enabled/reasoning_effort -> 平铺管理字段
- bishu 特有字段（prompt_template/response_format 等）完整保留
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from novel_agent.workflows.loader import RESOURCES_DIR

logger = logging.getLogger(__name__)


def _convert_agent(agent_type: str, definition: dict[str, Any]) -> dict[str, Any]:
    """bishu Agent 定义 -> NovelAgent 管理存储格式。"""
    mp = definition.get("model_params", {}) or {}
    return {
        "agent_type": agent_type,
        "model": "",  # 空 = 继承系统默认模型
        "temperature": mp.get("temperature", 0.8),
        "top_p": mp.get("top_p", 0.92),
        "max_turns": definition.get("max_turns", 10),
        "thinking": bool(mp.get("thinking_enabled", False)),
        "reasoning_effort": mp.get("reasoning_effort") or "medium",
        "tools_whitelist": definition.get("tools") or [],
        "visible": True,
        # ── bishu 扩展字段（完整保留）──
        "source": "bishu-novel",
        "description": definition.get("description", ""),
        "prompt_template": definition.get("prompt_template", agent_type),
        "disallowed_tools": definition.get("disallowed_tools") or [],
        "presence_penalty": mp.get("presence_penalty", 0),
        "thinking_budget": mp.get("thinking_budget"),
        "response_format": mp.get("response_format"),
        "available_for_sub_session": definition.get("available_for_sub_session", True),
        "visible_skill_group_ids": definition.get("visible_skill_group_ids", []),
        "visible_rule_group_ids": definition.get("visible_rule_group_ids", []),
    }


def seed_bishu_agents(agents_store_path: Path, force: bool = False) -> dict[str, Any]:
    """把 33 个 bishu Agent 定义播种进管理存储。

    Args:
        agents_store_path: project_data/agents.json 路径
        force: True 时覆盖已存在的同名定义（用户已改过的会被重置）

    Returns:
        {"seeded": N, "skipped": M, "total": 33}
    """
    with open(RESOURCES_DIR / "agents.json", encoding="utf-8") as f:
        bishu_agents: dict[str, Any] = json.load(f).get("agents", {})

    store: dict[str, Any] = {}
    if agents_store_path.exists():
        try:
            with open(agents_store_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                store = data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取 agents 存储失败，将重建: %s", e)

    seeded = 0
    skipped = 0
    for agent_type, definition in bishu_agents.items():
        if agent_type in store and not force:
            skipped += 1
            continue
        store[agent_type] = _convert_agent(agent_type, definition)
        seeded += 1

    agents_store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(agents_store_path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

    logger.info("bishu Agent 播种完成: 新增 %d，跳过 %d，总计 %d",
                seeded, skipped, len(bishu_agents))
    return {"seeded": seeded, "skipped": skipped, "total": len(bishu_agents)}
