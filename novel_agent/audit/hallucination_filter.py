"""幻觉过滤：过滤"正文从未出现的实体"，防图谱污染（可视化融合 P5）。

原理：EntityAppearance 表是"实体曾在正文出场的记录"（由章节提交/正文落盘时写入）。
若某实体（角色/势力/怪物）在正文中从未出场，则自动生成的图谱不应把它的
节点和边画出来——那些只是"设定纸面存在"的实体，画进去会污染图谱语义。

保护机制：若某一类实体完全没有出场记录（新项目刚建角色、还没写正文），
则不过滤（返回全部），避免自动图谱变成空图。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from novel_agent.bible.models import EntityAppearance


def appeared_entity_ids(db: Session, project_id: int, entity_type: str) -> set[str]:
    """返回某类实体在正文中出现过的 entity_id 集合。

    entity_type: character / faction / monster
    注意：EntityAppearance.entity_id 对 character 存角色名，
    对 faction/monster 存字符串化的 id。
    """
    rows = db.query(EntityAppearance.entity_id).filter(
        EntityAppearance.project_id == project_id,
        EntityAppearance.entity_type == entity_type,
    ).distinct().all()
    return {r[0] for r in rows}


def filter_appeared(db: Session, project_id: int, entity_type: str,
                    entities: list, id_fn=None) -> list:
    """从实体列表中过滤出"正文出现过"的实体。

    Args:
        entity_type: character / faction / monster
        entities: ORM 实体列表（Character / Faction / Monster）
        id_fn: 取实体匹配键的函数，默认按 name；faction/monster 传
               lambda e: str(e.id)（appearance 表按字符串 id 匹配）

    Returns:
        过滤后的实体列表；若该类实体无任何出场记录（新项目）则返回全部。
    """
    if not entities:
        return entities
    appeared = appeared_entity_ids(db, project_id, entity_type)
    if not appeared:
        # 保护：正文还没写，所有实体都"未出场"，不过滤，避免空图
        return entities
    id_fn = id_fn or (lambda e: e.name)
    return [e for e in entities if id_fn(e) in appeared]


def count_entities_hidden(original: int, filtered: int) -> int:
    """返回被幻觉过滤隐藏的实体数量（供日志/提示用）。"""
    return max(0, original - filtered)
