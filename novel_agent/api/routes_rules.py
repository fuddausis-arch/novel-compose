"""Rules 管理后端：CRUD + 冲突检测 + reminder 注入。

借鉴 DeterminFlow rules/ 模块：
- Rule 定义：name, description, rule_text, group, enabled, priority
- <rules> 标签注入到 system prompt
- 冲突检测：同 group 内 priority 重复时 warning

数据存储：project_data/rules/rules.json（单文件列表）。
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


class RuleBase(BaseModel):
    """Rule 创建时的完整字段。"""
    name: str
    description: str = ""
    rule_text: str
    group: str = "default"
    enabled: bool = True
    priority: int = 0


class RuleUpdate(BaseModel):
    """Rule 更新字段（全部可选）。"""
    name: str | None = None
    description: str | None = None
    rule_text: str | None = None
    group: str | None = None
    enabled: bool | None = None
    priority: int | None = None


# ---- 文件 I/O 辅助 ----


def _rules_path() -> Path:
    """获取 rules.json 路径，自动创建目录。"""
    cfg = load_config()
    d = cfg.project_data_dir / "rules"
    d.mkdir(parents=True, exist_ok=True)
    return d / "rules.json"


def _load_rules() -> list[dict]:
    """读取所有 rules，文件不存在时返回空列表。"""
    path = _rules_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_rules(rules: list[dict]) -> None:
    """写入 rules.json。"""
    path = _rules_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存 rules 失败: {e}")


def _find_rule(rules: list[dict], rule_id: str) -> dict | None:
    """按 id 查找 rule。"""
    for r in rules:
        if r.get("id") == rule_id:
            return r
    return None


# ---- 端点 ----


@router.get("")
def list_rules():
    """列出所有 rules。"""
    return {"rules": _load_rules()}


@router.post("")
def create_rule(rule: RuleBase):
    """创建 rule。"""
    import uuid
    rules = _load_rules()
    data = rule.model_dump()
    data["id"] = uuid.uuid4().hex[:12]
    rules.append(data)
    _save_rules(rules)
    return {"created": True, "rule": data}


@router.put("/{rule_id}")
def update_rule(rule_id: str, updates: RuleUpdate):
    """更新 rule。"""
    rules = _load_rules()
    target = _find_rule(rules, rule_id)
    if target is None:
        raise HTTPException(404, f"Rule 不存在: {rule_id}")
    update_data = updates.model_dump(exclude_unset=True)
    target.update(update_data)
    _save_rules(rules)
    return {"updated": True, "rule": target}


@router.delete("/{rule_id}")
def delete_rule(rule_id: str):
    """删除 rule。"""
    rules = _load_rules()
    target = _find_rule(rules, rule_id)
    if target is None:
        raise HTTPException(404, f"Rule 不存在: {rule_id}")
    rules.remove(target)
    _save_rules(rules)
    return {"deleted": True, "id": rule_id}


@router.get("/conflicts")
def detect_conflicts():
    """检测冲突：同 group 内 priority 重复时返回 warning。

    返回格式：
    {
        "conflicts": [
            {"group": "...", "priority": 1, "rules": ["id1", "id2"]}
        ]
    }
    """
    rules = _load_rules()
    # 按 (group, priority) 分组，只统计已启用的 rule
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for r in rules:
        if not r.get("enabled", True):
            continue
        key = (r.get("group", "default"), r.get("priority", 0))
        groups[key].append(r.get("id", ""))

    conflicts = []
    for (group, priority), ids in groups.items():
        if len(ids) > 1:
            conflicts.append({
                "group": group,
                "priority": priority,
                "rules": ids,
                "message": f"分组 '{group}' 内 priority={priority} 有 {len(ids)} 条规则重复",
            })
    return {"conflicts": conflicts, "total": len(conflicts)}
