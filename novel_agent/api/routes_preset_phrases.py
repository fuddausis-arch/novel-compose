"""预设短语后端：CRUD + 注入。

借鉴 DeterminFlow preset_phrases：
- 预设短语分类管理（如：写作指令/审查指令/通用指令）
- 对话页底部快速选择栏
- 注入到用户消息

数据存储：project_data/preset_phrases.json（单文件列表）。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import load_config

router = APIRouter()


# ---- Pydantic 模型 ----


class PhraseBase(BaseModel):
    """预设短语创建时的完整字段。"""
    category: str = "通用指令"
    text: str
    shortcut: str = ""


class PhraseUpdate(BaseModel):
    """预设短语更新字段（全部可选）。"""
    category: str | None = None
    text: str | None = None
    shortcut: str | None = None


# ---- 文件 I/O 辅助 ----


def _phrases_path() -> Path:
    """获取 preset_phrases.json 路径，自动创建目录。"""
    cfg = load_config()
    cfg.project_data_dir.mkdir(parents=True, exist_ok=True)
    return cfg.project_data_dir / "preset_phrases.json"


def _load_phrases() -> list[dict]:
    """读取所有预设短语，文件不存在时返回空列表。"""
    path = _phrases_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_phrases(phrases: list[dict]) -> None:
    """写入 preset_phrases.json。"""
    path = _phrases_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(phrases, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存预设短语失败: {e}")


def _find_phrase(phrases: list[dict], phrase_id: str) -> dict | None:
    """按 id 查找预设短语。"""
    for p in phrases:
        if p.get("id") == phrase_id:
            return p
    return None


# ---- 端点 ----


@router.get("")
def list_phrases():
    """列出所有预设短语（按分类分组）。"""
    phrases = _load_phrases()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for p in phrases:
        grouped[p.get("category", "通用指令")].append(p)
    return {"phrases": phrases, "grouped": dict(grouped)}


@router.post("")
def create_phrase(phrase: PhraseBase):
    """创建预设短语。"""
    import uuid
    phrases = _load_phrases()
    data = phrase.model_dump()
    data["id"] = uuid.uuid4().hex[:12]
    phrases.append(data)
    _save_phrases(phrases)
    return {"created": True, "phrase": data}


@router.put("/{phrase_id}")
def update_phrase(phrase_id: str, updates: PhraseUpdate):
    """更新预设短语。"""
    phrases = _load_phrases()
    target = _find_phrase(phrases, phrase_id)
    if target is None:
        raise HTTPException(404, f"预设短语不存在: {phrase_id}")
    update_data = updates.model_dump(exclude_unset=True)
    target.update(update_data)
    _save_phrases(phrases)
    return {"updated": True, "phrase": target}


@router.delete("/{phrase_id}")
def delete_phrase(phrase_id: str):
    """删除预设短语。"""
    phrases = _load_phrases()
    target = _find_phrase(phrases, phrase_id)
    if target is None:
        raise HTTPException(404, f"预设短语不存在: {phrase_id}")
    phrases.remove(target)
    _save_phrases(phrases)
    return {"deleted": True, "id": phrase_id}
