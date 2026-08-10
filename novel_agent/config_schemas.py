"""配置文件 schema 定义和迁移。

借鉴 DeterminFlow config/ 目录的 14 个配置文件：
- agents_config.json, compression_config.json, extensions.json
- llm_pricing.json, mcp_servers.json, models_config.json
- plugin-sources.json, preset_phrases.json, prompts_config.json
- rules_config.json, settings.json, skills_config.json
- tool_groups_config.json, user_injection_config.json

每个配置文件定义 schema（字段名 + 类型 + 默认值），
migrate_configs() 检查并创建缺失的配置文件。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── 14 个配置文件的 schema 定义 ──────────────────────────────
# 每个 schema 是一个 dict：字段名 -> {"type": 类型, "default": 默认值}
CONFIG_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "agents_config.json": {
        "agents": {
            "type": "list",
            "default": [
                {"name": "writer", "model": "", "temperature": 0.8},
                {"name": "auditor", "model": "", "temperature": 0.4},
                {"name": "planner", "model": "", "temperature": 0.9},
            ],
        },
    },
    "compression_config.json": {
        "strategy": {"type": "string", "default": "micro"},
        "max_tokens": {"type": "integer", "default": 32000},
        "keep_recent_msgs": {"type": "integer", "default": 6},
        "micro_keep_recent_tools": {"type": "integer", "default": 5},
    },
    "extensions.json": {
        "enabled": {"type": "boolean", "default": True},
        "extensions": {"type": "list", "default": []},
    },
    "llm_pricing.json": {
        "deepseek-v4-pro": {
            "type": "dict",
            "default": {"input": 0.002, "output": 0.006},
        },
        "deepseek-v4-flash": {
            "type": "dict",
            "default": {"input": 0.0003, "output": 0.001},
        },
        "gpt-4o": {
            "type": "dict",
            "default": {"input": 0.005, "output": 0.015},
        },
        "gpt-4o-mini": {
            "type": "dict",
            "default": {"input": 0.00015, "output": 0.0006},
        },
    },
    "mcp_servers.json": {
        "servers": {"type": "list", "default": []},
    },
    "models_config.json": {
        "default_model": {"type": "string", "default": "deepseek-v4-flash"},
        "models": {
            "type": "list",
            "default": [
                {"name": "deepseek-v4-flash", "context_length": 1000000},
                {"name": "deepseek-v4-pro", "context_length": 1000000},
            ],
        },
    },
    "plugin-sources.json": {
        "sources": {"type": "list", "default": []},
    },
    "preset_phrases.json": {
        "phrases": {"type": "list", "default": []},
    },
    "prompts_config.json": {
        "prompts": {"type": "dict", "default": {}},
    },
    "rules_config.json": {
        "rules": {"type": "list", "default": []},
    },
    "settings.json": {
        "language": {"type": "string", "default": "zh-CN"},
        "theme": {"type": "string", "default": "light"},
        "auto_save": {"type": "boolean", "default": True},
        "max_concurrent_tasks": {"type": "integer", "default": 3},
    },
    "skills_config.json": {
        "enabled_skills": {"type": "list", "default": ["writing_assistant"]},
        "skills": {"type": "dict", "default": {}},
    },
    "tool_groups_config.json": {
        "groups": {
            "type": "dict",
            "default": {
                "query": ["get_character", "list_characters", "get_outline"],
                "write": ["create_character", "create_outline", "create_foreshadow"],
                "action": ["rewrite_chapter", "add_chapter_feedback"],
            },
        },
    },
    "user_injection_config.json": {
        "injections": {"type": "list", "default": []},
    },
}


def _build_default(schema: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """根据 schema 构建默认配置 dict。"""
    result: dict[str, Any] = {}
    for field_name, field_spec in schema.items():
        result[field_name] = field_spec.get("default")
    return result


def migrate_configs(project_data_dir: Path) -> list[str]:
    """检查并创建缺失的配置文件。

    遍历 CONFIG_SCHEMAS，对每个配置文件：
    - 存在则跳过
    - 不存在则用 schema 默认值创建

    Args:
        project_data_dir: 项目数据目录（config/ 子目录存放配置文件）

    Returns:
        已创建的配置文件名列表
    """
    config_dir = project_data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for filename, schema in CONFIG_SCHEMAS.items():
        filepath = config_dir / filename
        if filepath.exists():
            continue
        try:
            default_data = _build_default(schema)
            filepath.write_text(
                json.dumps(default_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            created.append(filename)
            logger.info("migrate_configs: 已创建配置文件 %s", filename)
        except Exception as e:
            logger.warning("migrate_configs: 创建 %s 失败: %s", filename, e)
    return created


def load_config_file(name: str, project_data_dir: Path | None = None) -> dict:
    """加载配置文件。

    Args:
        name: 配置文件名（如 "settings.json"）
        project_data_dir: 项目数据目录（None 时用默认 config 目录）

    Returns:
        配置 dict；文件不存在时返回 schema 默认值
    """
    if project_data_dir is None:
        try:
            from novel_agent.config import load_config
            project_data_dir = load_config().project_data_dir
        except Exception:
            project_data_dir = Path(".")
    filepath = project_data_dir / "config" / name
    if not filepath.exists():
        schema = CONFIG_SCHEMAS.get(name, {})
        return _build_default(schema) if schema else {}
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("load_config_file: 加载 %s 失败: %s，返回默认值", name, e)
        schema = CONFIG_SCHEMAS.get(name, {})
        return _build_default(schema) if schema else {}


def save_config_file(name: str, data: dict, project_data_dir: Path | None = None) -> Path:
    """保存配置文件。

    Args:
        name: 配置文件名
        data: 配置数据
        project_data_dir: 项目数据目录（None 时用默认 config 目录）

    Returns:
        保存的文件路径
    """
    if project_data_dir is None:
        try:
            from novel_agent.config import load_config
            project_data_dir = load_config().project_data_dir
        except Exception:
            project_data_dir = Path(".")
    config_dir = project_data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    filepath = config_dir / name
    filepath.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("save_config_file: 已保存 %s", name)
    return filepath
