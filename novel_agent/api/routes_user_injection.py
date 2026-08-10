"""用户注入配置后端：CRUD + 会话启动注入。

借鉴 DeterminFlow user_injection：
- 用户自定义内容注入到每次会话启动时的 system prompt
- 支持按项目/全局配置

数据存储：project_data/user_injection.json。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import load_config

router = APIRouter()


# ---- 默认配置 ----

_DEFAULT_CONFIG = {
    "global_prompt": "",
    "project_prompts": {},
    "inject_position": "system",  # "system" | "user"
}


# ---- Pydantic 模型 ----


class InjectionUpdate(BaseModel):
    """用户注入配置更新字段（全部可选）。"""
    global_prompt: str | None = None
    project_prompts: dict[str, str] | None = None
    inject_position: str | None = None


# ---- 文件 I/O 辅助 ----


def _config_path() -> Path:
    """获取 user_injection.json 路径，自动创建目录。"""
    cfg = load_config()
    cfg.project_data_dir.mkdir(parents=True, exist_ok=True)
    return cfg.project_data_dir / "user_injection.json"


def _load_config() -> dict:
    """读取注入配置，文件不存在时返回默认配置。"""
    path = _config_path()
    if not path.exists():
        return dict(_DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # 合并默认值，确保字段完整
        result = dict(_DEFAULT_CONFIG)
        result.update(data if isinstance(data, dict) else {})
        return result
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_CONFIG)


def _save_config(config: dict) -> None:
    """写入 user_injection.json。"""
    path = _config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存注入配置失败: {e}")


# ---- 端点 ----


@router.get("")
def get_injection():
    """获取注入配置。"""
    return _load_config()


@router.put("")
def update_injection(updates: InjectionUpdate):
    """更新注入配置。"""
    config = _load_config()
    update_data = updates.model_dump(exclude_unset=True)
    # 校验 inject_position 取值
    if "inject_position" in update_data:
        if update_data["inject_position"] not in ("system", "user"):
            raise HTTPException(400, "inject_position 必须为 'system' 或 'user'")
    config.update(update_data)
    _save_config(config)
    return {"updated": True, "config": config}
