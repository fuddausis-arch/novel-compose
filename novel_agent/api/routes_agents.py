"""Agent 定义管理后端：CRUD + 可见性控制。

借鉴 DeterminFlow agent/ 模块：
- Agent 定义：agent_type, model, temperature, top_p, max_turns, thinking, tools_whitelist, visible
- 参数编辑
- 可见性控制（对前端隐藏/显示）

数据存储：project_data/agents.json（单文件 dict）。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import load_config

router = APIRouter()


# ---- Pydantic 模型 ----


class AgentDef(BaseModel):
    """Agent 创建时的完整定义。"""
    agent_type: str
    model: str = ""
    temperature: float = 0.8
    top_p: float = 0.92
    max_turns: int = 10
    thinking: bool = False
    reasoning_effort: str = "medium"
    tools_whitelist: list[str] = []
    visible: bool = True


class AgentUpdate(BaseModel):
    """Agent 更新字段（全部可选，agent_type 不可变）。"""
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_turns: int | None = None
    thinking: bool | None = None
    reasoning_effort: str | None = None
    tools_whitelist: list[str] | None = None
    visible: bool | None = None


# ---- 文件 I/O 辅助 ----


def _agents_path() -> Path:
    """获取 agents.json 路径，自动创建目录。"""
    cfg = load_config()
    cfg.project_data_dir.mkdir(parents=True, exist_ok=True)
    return cfg.project_data_dir / "agents.json"


def _load_agents() -> dict:
    """读取所有 agent 定义，文件不存在时返回空字典。"""
    path = _agents_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_agents(agents: dict) -> None:
    """写入 agents.json。"""
    path = _agents_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(agents, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存 agents 失败: {e}")


# ---- 端点 ----


@router.get("")
def list_agents():
    """列出所有 agent 定义。"""
    return {"agents": _load_agents()}


@router.get("/{agent_type}")
def get_agent(agent_type: str):
    """获取单个 agent 定义。"""
    agents = _load_agents()
    if agent_type not in agents:
        raise HTTPException(404, f"Agent 不存在: {agent_type}")
    return agents[agent_type]


@router.post("")
def create_agent(agent: AgentDef):
    """创建新 agent。"""
    agents = _load_agents()
    if agent.agent_type in agents:
        raise HTTPException(409, f"Agent 已存在: {agent.agent_type}")
    data = agent.model_dump()
    agents[agent.agent_type] = data
    _save_agents(agents)
    return {"created": True, "agent": data}


@router.put("/{agent_type}")
def update_agent(agent_type: str, updates: AgentUpdate):
    """更新 agent 参数。"""
    agents = _load_agents()
    if agent_type not in agents:
        raise HTTPException(404, f"Agent 不存在: {agent_type}")
    update_data = updates.model_dump(exclude_unset=True)
    agents[agent_type].update(update_data)
    _save_agents(agents)
    return {"updated": True, "agent": agents[agent_type]}


@router.delete("/{agent_type}")
def delete_agent(agent_type: str):
    """删除 agent 定义。"""
    agents = _load_agents()
    if agent_type not in agents:
        raise HTTPException(404, f"Agent 不存在: {agent_type}")
    deleted = agents.pop(agent_type)
    _save_agents(agents)
    return {"deleted": True, "agent_type": agent_type, "agent": deleted}


@router.post("/seed-bishu")
def seed_bishu(force: bool = False):
    """播种 bishu-novel 33 个 Agent 定义到管理存储。

    force=True 时覆盖同名定义（用户改过的会被重置）。
    """
    from novel_agent.workflows.agent_registry import seed_bishu_agents

    result = seed_bishu_agents(_agents_path(), force=force)
    return result
