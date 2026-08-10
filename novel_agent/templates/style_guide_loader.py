"""写作风格指南加载器。

从 templates/style_guides/ 加载蒸馏后的创作约束：
- core_constraints: 始终注入的核心约束（反AI味/文风/节奏/爽点）
- task-specific guides: 按任务注入（角色/世界观/势力/战斗）
"""
from __future__ import annotations

from pathlib import Path

_STYLE_GUIDES_DIR = Path(__file__).parent / "style_guides"

# 任务到指南文件的映射
_TASK_GUIDE_MAP = {
    "character": "character_guide.txt",
    "combat": "combat_guide.txt",
    "worldview": "worldview_guide.txt",
    "faction": "faction_guide.txt",
}

_cache: dict[str, str] = {}


def _load_file(name: str) -> str:
    if name in _cache:
        return _cache[name]
    path = _STYLE_GUIDES_DIR / name
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    _cache[name] = text
    return text


def get_core_constraints() -> str:
    """获取核心写作约束（始终注入）。"""
    return _load_file("core_constraints.txt")


def get_task_guide(task: str) -> str:
    """获取任务专属指南。

    task 可选: character / combat / worldview / faction
    """
    filename = _TASK_GUIDE_MAP.get(task, "")
    if not filename:
        return ""
    return _load_file(filename)


def get_guides_for_generation(gen_type: str) -> str:
    """根据生成类型返回相关指南。

    gen_type 映射:
    - write_chapter / rewrite_chapter → 核心约束（已包含战斗节奏）
    - generate_characters / suggest_character → 角色指南
    - generate_world → 世界观指南
    - generate_volumes / generate_arcs → 核心约束
    - generate_chapters → 核心约束
    - suggest_faction → 势力指南
    """
    mapping = {
        "write_chapter": "",
        "rewrite_chapter": "",
        "generate_characters": "character",
        "suggest_character": "character",
        "generate_world": "worldview",
        "generate_volumes": "",
        "generate_arcs": "",
        "generate_chapters": "",
        "suggest_faction": "faction",
        "suggest_plot": "",
        "suggest_world": "worldview",
        "suggest_monster": "combat",
        "suggest_relationship": "character",
    }
    task = mapping.get(gen_type, "")
    if not task:
        return ""
    return get_task_guide(task)
