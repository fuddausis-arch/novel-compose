"""状态快照：O(1) 读当前世界状态 + 保真度校验。

每章生成后构建快照，CoreMemoryAssembler 优先读快照而非全量查表。
快照包含：角色状态/伏笔状态/支线进度/势力状态的序列化 JSON。
"""
from __future__ import annotations

import logging
from typing import Any

from novel_agent.bible.repository import BibleRepository

logger = logging.getLogger(__name__)


def build_snapshot(repo: BibleRepository, chapter: int) -> dict:
    """构建第 chapter 章的世界状态快照。

    使用 EntityAppearance 查活跃角色（P1-1），替代 last_active_chapter。
    """
    # 角色状态：用 EntityAppearance 查活跃角色 + 主角/反派
    active_result = repo.get_active_entities_for_chapter(chapter)
    active_char_names = set(
        c["name"] if isinstance(c, dict) else c.name
        for c in active_result.get("characters", [])
    )
    all_chars = repo.list_characters()
    chars = [c for c in all_chars
             if c.role in ("主角", "反派") or c.name in active_char_names]
    # 裁剪到最多 15 个角色（快照容量限制）
    if len(chars) > 15:
        chars = chars[:15]

    characters = []
    for c in chars:
        characters.append({
            "name": c.name,
            "role": c.role,
            "location": c.current_location or "",
            "emotion": c.current_emotion or "",
            "personality": (c.personality or ""),
        })

    # 伏笔状态：未回收的伏笔
    foreshadows = []
    for f in repo.list_foreshadows():
        if f.status != "resolved":
            foreshadows.append({
                "id": f.foreshadow_id,
                "description": (f.description or ""),
                "status": f.status,
                "planted_at": f.plant_chapter,
                "resolve_by": f.planned_resolve_chapter,
            })

    # 大纲：当前章约束
    outline = repo.get_outline_by_chapter(chapter)
    outline_info = {}
    if outline:
        outline_info = {
            "title": outline.title,
            "summary": (outline.summary or ""),
            "phase": outline.phase or "regular",
        }

    # 爽点/欠账（阶段3表）
    beats = []
    debts = []
    try:
        for b in repo.list_beats_for_chapter(chapter):
            beats.append({
                "tier": b.tier, "type": b.beat_type,
                "delivered": b.delivered, "intensity": b.intensity,
            })
    except Exception:
        pass
    try:
        for d in repo.list_open_debts():
            debts.append({
                "type": d.debt_type, "desc": (d.description or ""),
                "pressure": d.pressure,
            })
    except Exception:
        pass

    return {
        "chapter": chapter,
        "characters": characters,
        "foreshadows": foreshadows[:20],  # 最多20个
        "outline": outline_info,
        "beats": beats,
        "debts": debts[:10],  # 最多10个
    }


def save_snapshot(repo: BibleRepository, chapter: int,
                  snapshot_data: dict, drift_score: int = 0,
                  is_full_resummary: bool = False) -> None:
    """保存状态快照到数据库。"""
    from novel_agent.bible.models import StateSnapshot
    from sqlalchemy import select

    # 删除同章旧快照
    old = repo.db.query(StateSnapshot).filter(
        StateSnapshot.project_id == repo.project_id,
        StateSnapshot.chapter == chapter,
    ).all()
    for o in old:
        repo.db.delete(o)

    snap = StateSnapshot(
        project_id=repo.project_id,
        chapter=chapter,
        snapshot_data=snapshot_data,
        drift_score=drift_score,
        is_full_resummary=is_full_resummary,
    )
    repo.db.add(snap)
    repo.db.commit()
    logger.info("ch%d 状态快照已保存 (drift=%d, full=%s)",
                chapter, drift_score, is_full_resummary)


def get_latest_snapshot(repo: BibleRepository, chapter: int) -> dict | None:
    """读取最近的状态快照（chapter 或之前最近的）。"""
    from novel_agent.bible.models import StateSnapshot

    snap = repo.db.query(StateSnapshot).filter(
        StateSnapshot.project_id == repo.project_id,
        StateSnapshot.chapter <= chapter,
    ).order_by(StateSnapshot.chapter.desc()).first()
    if not snap:
        return None
    return snap.snapshot_data


def validate_snapshot_fidelity(repo: BibleRepository, chapter: int,
                               draft_text: str) -> dict:
    """校验快照与正文的一致性，返回漂移报告。

    检查项：
    - 角色位置：快照说"基地"，正文是否提到角色在基地
    - 伏笔状态：快照说pending，正文是否已埋设但未更新
    """
    snap = get_latest_snapshot(repo, chapter)
    if not snap:
        return {"valid": True, "reason": "无快照，跳过", "drift_score": 0}

    issues = []

    # 检查角色位置
    for char in snap.get("characters", []):
        name = char.get("name", "")
        location = char.get("location", "")
        if location and name in draft_text and location not in draft_text:
            # 角色出现在正文中但快照位置未提及——可能位置变了
            issues.append(f"角色{name}快照位置={location}但正文未提及该地点")

    # 检查伏笔状态
    for fs in snap.get("foreshadows", []):
        fs_id = fs.get("id", "")
        if fs_id in draft_text and fs.get("status") == "pending":
            issues.append(f"伏笔{fs_id}快照=pending但正文提及，可能已埋设未更新")

    drift_score = len(issues)
    return {
        "valid": drift_score < 5,
        "issues": issues,
        "drift_score": drift_score,
    }


def format_snapshot_for_context(snapshot: dict) -> str:
    """格式化快照为注入上下文的文本。"""
    lines = ["【世界状态快照】"]

    # 角色
    chars = snapshot.get("characters", [])
    if chars:
        lines.append("角色状态：")
        for c in chars:
            info = f"  {c['name']}（{c.get('role', '')}）"
            if c.get("location"):
                info += f" | 位置：{c['location']}"
            if c.get("emotion"):
                info += f" | 情绪：{c['emotion']}"
            lines.append(info)

    # 伏笔
    fores = snapshot.get("foreshadows", [])
    if fores:
        lines.append(f"未回收伏笔（{len(fores)}个）：")
        for f in fores[:5]:
            lines.append(f"  {f['id']}({f.get('status', '')})：{f.get('description', '')}")

    # 欠账
    debts = snapshot.get("debts", [])
    if debts:
        lines.append(f"未还欠账（{len(debts)}个）：")
        for d in debts[:3]:
            lines.append(f"  [{d.get('type', '')}] {d.get('desc', '')} (压力{d.get('pressure', 3)})")

    return "\n".join(lines)
