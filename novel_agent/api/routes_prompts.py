"""Prompt 编排后端：section CRUD + 预览 + token 估算。

借鉴 DeterminFlow prompts/ 模块 + PromptOrchestrator：
- 按 agent_type 管理 section
- section 可开关
- 实时预览拼接结果
- token 估算

复用已有的 novel_agent/prompts/section_manager.py 的 PromptManager。
数据文件：novel_agent/prompts/sections.json（与 PromptManager 共用同一份配置）。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.prompts.section_manager import PromptManager, _DEFAULT_SECTIONS_PATH

router = APIRouter()

# 全局 PromptManager 单例：写操作后调用 reload() 刷新内存
_pm = PromptManager()


# ---- Pydantic 模型 ----


class SectionInput(BaseModel):
    """section 创建/更新时的字段。"""
    name: str
    content: str = ""
    enabled: bool = True
    order: int = 0


class SectionUpdate(BaseModel):
    """section 更新字段（全部可选，name 不可变）。"""
    content: str | None = None
    enabled: bool | None = None
    order: int | None = None


class ToggleInput(BaseModel):
    """section 开关请求体。"""
    enabled: bool


# ---- 文件 I/O 辅助 ----


def _read_sections_json() -> dict:
    """读取 sections.json 原始 JSON。"""
    if not _DEFAULT_SECTIONS_PATH.exists():
        return {"version": "1.0", "description": "Prompt Section 配置", "agents": {}}
    try:
        with open(_DEFAULT_SECTIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"读取 sections.json 失败: {e}")


def _write_sections_json(data: dict) -> None:
    """写入 sections.json 并刷新 PromptManager 内存。"""
    try:
        with open(_DEFAULT_SECTIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存 sections.json 失败: {e}")
    _pm.reload()


def _get_agent_sections_raw(data: dict, agent_type: str) -> list[dict]:
    """从原始 JSON 中获取 agent 的 section 列表（可变引用）。"""
    agents = data.setdefault("agents", {})
    if agent_type not in agents:
        agents[agent_type] = {"description": "", "sections": []}
    return agents[agent_type].setdefault("sections", [])


# ---- 端点 ----


@router.get("/{agent_type}/preview")
def preview_prompt(agent_type: str):
    """预览拼接结果（带 token 估算）。

    路由顺序：放在 /{agent_type}/{section_name} 之前，避免 "preview" 被当作 section_name。
    """
    prompt = _pm.build_prompt(agent_type)
    tokens = PromptManager.estimate_tokens(prompt)
    sections = _pm.get_sections(agent_type)
    return {
        "agent_type": agent_type,
        "prompt": prompt,
        "estimated_tokens": tokens,
        "section_count": len(sections),
        "enabled_count": sum(1 for s in sections if s.enabled),
    }


@router.get("/{agent_type}")
def get_sections(agent_type: str):
    """获取 agent 的所有 section。"""
    sections = _pm.get_sections(agent_type)
    return {
        "agent_type": agent_type,
        "sections": [
            {"name": s.name, "content": s.content, "enabled": s.enabled, "order": s.order}
            for s in sections
        ],
    }


@router.post("/{agent_type}")
def create_section(agent_type: str, section: SectionInput):
    """新增 section。"""
    data = _read_sections_json()
    raw_sections = _get_agent_sections_raw(data, agent_type)
    # 检查重名
    if any(s.get("name") == section.name for s in raw_sections):
        raise HTTPException(409, f"Section 已存在: {section.name}")
    raw_sections.append(section.model_dump())
    _write_sections_json(data)
    return {"created": True, "section": section.model_dump()}


@router.put("/{agent_type}/{section_name}")
def update_section(agent_type: str, section_name: str, updates: SectionUpdate):
    """更新 section。"""
    data = _read_sections_json()
    raw_sections = _get_agent_sections_raw(data, agent_type)
    target = None
    for s in raw_sections:
        if s.get("name") == section_name:
            target = s
            break
    if target is None:
        raise HTTPException(404, f"Section 不存在: {section_name}")
    update_data = updates.model_dump(exclude_unset=True)
    target.update(update_data)
    _write_sections_json(data)
    return {"updated": True, "section": target}


@router.delete("/{agent_type}/{section_name}")
def delete_section(agent_type: str, section_name: str):
    """删除 section。"""
    data = _read_sections_json()
    raw_sections = _get_agent_sections_raw(data, agent_type)
    for i, s in enumerate(raw_sections):
        if s.get("name") == section_name:
            raw_sections.pop(i)
            _write_sections_json(data)
            return {"deleted": True, "section_name": section_name}
    raise HTTPException(404, f"Section 不存在: {section_name}")


@router.put("/{agent_type}/{section_name}/toggle")
def toggle_section(agent_type: str, section_name: str, body: ToggleInput):
    """开关 section。"""
    data = _read_sections_json()
    raw_sections = _get_agent_sections_raw(data, agent_type)
    target = None
    for s in raw_sections:
        if s.get("name") == section_name:
            target = s
            break
    if target is None:
        raise HTTPException(404, f"Section 不存在: {section_name}")
    target["enabled"] = body.enabled
    _write_sections_json(data)
    return {"toggled": True, "section_name": section_name, "enabled": body.enabled}
