"""叙事线系统 API：CRUD + 枚举 meta + AI 扫描(SSE) + 线规划(SSE) + 大纲联动。

对应《叙事线系统计划书-20260810.md》第五节接口设计。
标签/状态/交汇类型枚举唯一来源是 /meta（前端不硬编码）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Storyline, StorylineNode, StorylineRelation
from novel_agent.config import load_config

logger = logging.getLogger(__name__)
router = APIRouter()


# 固定枚举（前后端共用唯一来源 → /meta 下发，前端不硬编码）
TAGS = ["主线", "支线", "明线", "暗线"]
STATUSES = ["active", "paused", "resolved", "abandoned"]
RELATION_TYPES = ["merge", "intersect", "parallel", "conflict"]
NODE_TYPES = ["foreshadow", "event", "milestone"]


def get_story_db():
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── 输入模型 ──
class StorylineInput(BaseModel):
    name: str
    line_type: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = "active"
    progress: int = 0
    summary: str = ""
    notes: str = ""
    planned_resolve_chapter: int = 0
    volume: str = ""


class StorylineUpdate(BaseModel):
    name: str | None = None
    line_type: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    progress: int | None = None
    summary: str | None = None
    notes: str | None = None
    planned_resolve_chapter: int | None = None
    volume: str | None = None


class NodeInput(BaseModel):
    node_type: str = "event"
    foreshadow_id: str = ""
    chapter: int = 0
    title: str = ""
    description: str = ""
    order_index: int = 0


class NodeUpdate(BaseModel):
    node_type: str | None = None
    foreshadow_id: str | None = None
    chapter: int | None = None
    title: str | None = None
    description: str | None = None
    order_index: int | None = None


class RelationInput(BaseModel):
    source_storyline_id: int
    target_storyline_id: int
    relation_type: str = "merge"
    chapter: int = 0
    description: str = ""


class ScanRequest(BaseModel):
    chapter: int | None = None       # None = 扫描全书
    start_chapter: int = 0
    end_chapter: int = 0


class PlanRequest(BaseModel):
    prompt: str = ""                 # 卷纲/大纲文本


# ── 序列化 ──
def _line_dict(l: Storyline, db: Session) -> dict:
    nodes = db.query(StorylineNode).filter_by(storyline_id=l.id).order_by(
        StorylineNode.order_index, StorylineNode.chapter).all()
    rels = db.query(StorylineRelation).filter(
        (StorylineRelation.source_storyline_id == l.id)
        | (StorylineRelation.target_storyline_id == l.id)).all()
    return {
        "id": l.id, "project_id": l.project_id, "name": l.name,
        "line_type": l.line_type, "tags": l.tags or [], "status": l.status,
        "progress": l.progress, "summary": l.summary, "notes": l.notes,
        "planned_resolve_chapter": l.planned_resolve_chapter, "volume": l.volume,
        "last_active_chapter": l.last_active_chapter,
        "node_count": len(nodes),
        "relation_count": len(rels),
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }


def _node_dict(n: StorylineNode) -> dict:
    return {"id": n.id, "storyline_id": n.storyline_id, "node_type": n.node_type,
            "foreshadow_id": n.foreshadow_id or "", "chapter": n.chapter,
            "title": n.title, "description": n.description, "order_index": n.order_index}


def _rel_dict(r: StorylineRelation) -> dict:
    return {"id": r.id, "project_id": r.project_id, "source_storyline_id": r.source_storyline_id,
            "target_storyline_id": r.target_storyline_id, "relation_type": r.relation_type,
            "chapter": r.chapter, "description": r.description}


def _get_line(db: Session, project_id: int, line_id: int) -> Storyline:
    l = db.query(Storyline).filter(Storyline.project_id == project_id,
                                   Storyline.id == line_id).first()
    if not l:
        raise HTTPException(404, "线不存在")
    return l


# ── meta：前端枚举唯一来源 ──
@router.get("/meta")
def storylines_meta():
    return {"tags": TAGS, "statuses": STATUSES,
            "relation_types": RELATION_TYPES, "node_types": NODE_TYPES}


# ── 线 CRUD ──
@router.get("/{project_id}/storylines")
def list_storylines(project_id: int, tag: str = "", status: str = "",
                    volume: str = "", search: str = "",
                    db: Session = Depends(get_story_db)):
    q = db.query(Storyline).filter(Storyline.project_id == project_id)
    if status:
        q = q.filter(Storyline.status == status)
    if volume:
        q = q.filter(Storyline.volume == volume)
    items = q.order_by(Storyline.volume, Storyline.id).all()
    # tag/search 在 Python 层过滤（SQLite JSON 列中文 contains 有转义问题，线量级小无性能顾虑）
    if tag:
        items = [l for l in items if tag in (l.tags or [])]
    if search:
        s = search.lower()
        items = [l for l in items
                 if s in l.name.lower() or s in (l.line_type or "").lower()
                 or s in (l.summary or "").lower()]
    return {"items": [_line_dict(l, db) for l in items]}


@router.post("/{project_id}/storylines")
def create_storyline(project_id: int, data: StorylineInput,
                     db: Session = Depends(get_story_db)):
    if not data.name.strip():
        raise HTTPException(400, "线名不能为空")
    l = Storyline(project_id=project_id, name=data.name.strip(), line_type=data.line_type,
                  tags=data.tags, status=data.status, progress=max(0, min(100, data.progress)),
                  summary=data.summary, notes=data.notes,
                  planned_resolve_chapter=data.planned_resolve_chapter, volume=data.volume)
    db.add(l)
    db.commit()
    db.refresh(l)
    return _line_dict(l, db)


@router.put("/{project_id}/storylines/{line_id}")
def update_storyline(project_id: int, line_id: int, data: StorylineUpdate,
                     db: Session = Depends(get_story_db)):
    l = _get_line(db, project_id, line_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if k == "progress" and v is not None:
            v = max(0, min(100, v))
        setattr(l, k, v)
    db.commit()
    db.refresh(l)
    return _line_dict(l, db)


@router.delete("/{project_id}/storylines/{line_id}")
def delete_storyline(project_id: int, line_id: int, db: Session = Depends(get_story_db)):
    l = _get_line(db, project_id, line_id)
    db.delete(l)  # ORM cascade 删节点
    db.query(StorylineRelation).filter(
        (StorylineRelation.source_storyline_id == line_id)
        | (StorylineRelation.target_storyline_id == line_id)).delete()
    db.commit()
    return {"deleted": True}


# ── 节点 CRUD ──
@router.post("/{project_id}/storylines/{line_id}/nodes")
def create_node(project_id: int, line_id: int, data: NodeInput,
                db: Session = Depends(get_story_db)):
    _get_line(db, project_id, line_id)
    n = StorylineNode(storyline_id=line_id, node_type=data.node_type,
                      foreshadow_id=data.foreshadow_id, chapter=data.chapter,
                      title=data.title, description=data.description,
                      order_index=data.order_index)
    db.add(n)
    db.commit()
    db.refresh(n)
    return _node_dict(n)


@router.put("/storyline-nodes/{node_id}")
def update_node(node_id: int, data: NodeUpdate, db: Session = Depends(get_story_db)):
    n = db.query(StorylineNode).filter_by(id=node_id).first()
    if not n:
        raise HTTPException(404, "节点不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(n, k, v)
    db.commit()
    db.refresh(n)
    return _node_dict(n)


@router.delete("/storyline-nodes/{node_id}")
def delete_node(node_id: int, db: Session = Depends(get_story_db)):
    n = db.query(StorylineNode).filter_by(id=node_id).first()
    if not n:
        raise HTTPException(404, "节点不存在")
    db.delete(n)
    db.commit()
    return {"deleted": True}


# ── 交汇 CRUD ──
@router.post("/{project_id}/storylines/relations")
def create_relation(project_id: int, data: RelationInput,
                    db: Session = Depends(get_story_db)):
    if data.source_storyline_id == data.target_storyline_id:
        raise HTTPException(400, "线不能与自己交汇")
    r = StorylineRelation(project_id=project_id, source_storyline_id=data.source_storyline_id,
                          target_storyline_id=data.target_storyline_id,
                          relation_type=data.relation_type, chapter=data.chapter,
                          description=data.description)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _rel_dict(r)


@router.put("/storyline-relations/{rel_id}")
def update_relation(rel_id: int, data: RelationInput,
                    db: Session = Depends(get_story_db)):
    r = db.query(StorylineRelation).filter_by(id=rel_id).first()
    if not r:
        raise HTTPException(404, "交汇关系不存在")
    r.source_storyline_id = data.source_storyline_id
    r.target_storyline_id = data.target_storyline_id
    r.relation_type = data.relation_type
    r.chapter = data.chapter
    r.description = data.description
    db.commit()
    db.refresh(r)
    return _rel_dict(r)


@router.delete("/storyline-relations/{rel_id}")
def delete_relation(rel_id: int, db: Session = Depends(get_story_db)):
    r = db.query(StorylineRelation).filter_by(id=rel_id).first()
    if not r:
        raise HTTPException(404, "交汇关系不存在")
    db.delete(r)
    db.commit()
    return {"deleted": True}


# ── 单线详情（节点链 + 交汇）供网络视图 ──
@router.get("/{project_id}/storylines/{line_id}/detail")
def line_detail(project_id: int, line_id: int, db: Session = Depends(get_story_db)):
    l = _get_line(db, project_id, line_id)
    nodes = db.query(StorylineNode).filter_by(storyline_id=line_id).order_by(
        StorylineNode.order_index, StorylineNode.chapter).all()
    rels = db.query(StorylineRelation).filter(
        (StorylineRelation.source_storyline_id == line_id)
        | (StorylineRelation.target_storyline_id == line_id)).all()
    return {
        "line": _line_dict(l, db),
        "nodes": [_node_dict(n) for n in nodes],
        "relations": [_rel_dict(r) for r in rels],
    }


# ── AI 健康度扫描（SSE，双通道交叉验证） ──
@router.post("/{project_id}/storylines/scan")
async def scan_storylines(project_id: int, req: ScanRequest,
                          db: Session = Depends(get_story_db)):
    """AI 健康度扫描（SSE）：规则+LLM 双通道交叉验证。req.chapter=None 扫描全书。

    事件：scan_start / rule_result / line_result / chapter_error / alerts / done / error。
    前端 fetch + ReadableStream 消费，可中断（断开即停止）。
    """
    cfg = load_config()
    if not cfg.llm.api_key:
        raise HTTPException(400, "未配置 LLM API Key，扫描需要 LLM 通道")
    from novel_agent.llm.client import LLMClient
    from novel_agent.storyline.scanner import (
        DEFAULT_BREAK_THRESHOLD, cross_validate, llm_scan_chapter, rule_scan_chapter,
    )
    from novel_agent.memory.recall import RecallMemory
    client = LLMClient(cfg.get_agent_llm("summarizer"))

    recall = RecallMemory(cfg, project_id=project_id)
    lines = db.query(Storyline).filter_by(project_id=project_id).all()

    chapters = [req.chapter] if req.chapter else list(
        range(max(1, req.start_chapter or 1), (req.end_chapter or 1) + 1))

    async def event_gen():
        yield {"event": "scan_start", "data": json.dumps(
            {"project_id": project_id, "chapters": chapters, "lines": len(lines)})}
        adopted = pending = 0
        all_alerts: list[dict] = []
        for ch in chapters:
            text = recall.read_chapter_text(ch) or ""
            try:
                rule_res = rule_scan_chapter(db, project_id, ch, text, lines,
                                             break_threshold=DEFAULT_BREAK_THRESHOLD)
                all_alerts.extend(rule_res["alerts"])
                yield {"event": "rule_result", "data": json.dumps(
                    {"chapter": ch, "alerts": rule_res["alerts"]}, ensure_ascii=False)}
                if text.strip():
                    llm_res = await llm_scan_chapter(client, ch, text, lines)
                    # 逐线交叉验证（每条线独立 try，单条失败不影响其他）
                    for ll in llm_res.get("line_results", []):
                        try:
                            rule_line = next(
                                (r for r in rule_res["line_results"]
                                 if r["storyline_id"] == ll.get("storyline_id")), {})
                            cv = cross_validate(rule_line, ll)
                            if cv["verdict"] == "adopt":
                                adopted += 1
                                if cv["adopted_progressed"]:
                                    line = next((x for x in lines
                                                 if x.id == ll.get("storyline_id")), None)
                                    if line:
                                        line.last_active_chapter = ch
                                        line.progress = max(0, min(100, line.progress
                                                                   + int(ll.get("progress_delta") or 0)))
                            else:
                                pending += 1
                            yield {"event": "line_result", "data": json.dumps(
                                {"chapter": ch, "verdict": cv["verdict"], **cv},
                                ensure_ascii=False)}
                        except Exception as e:  # 单条失败不中断（风险 #2）
                            logger.warning("线 %s 交叉验证失败: %s", ll.get("storyline_id"), e)
                    for a in llm_res.get("alerts", []):
                        all_alerts.append({"chapter": ch, **a})
                db.commit()
            except Exception as e:
                logger.warning("第%d章扫描失败: %s", ch, e)
                yield {"event": "chapter_error", "data": json.dumps(
                    {"chapter": ch, "message": str(e)}, ensure_ascii=False)}
        yield {"event": "alerts", "data": json.dumps(
            {"items": all_alerts, "adopted": adopted, "pending": pending},
            ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps(
            {"scanned": len(chapters), "alerts": len(all_alerts)}, ensure_ascii=False)}

    return EventSourceResponse(event_gen())


# ── AI 线规划蓝图（SSE，远期 P1 占位） ──
@router.post("/{project_id}/storylines/generate-plan")
async def generate_plan(project_id: int, req: PlanRequest,
                        db: Session = Depends(get_story_db)):
    """AI 生成线规划蓝图（SSE 流式）。复用 llm-create 的识别建线逻辑。"""
    async def event_gen():
        cfg = load_config()
        if not cfg.llm.api_key:
            yield {"event": "error", "data": json.dumps(
                {"message": "未配置 LLM API Key"}, ensure_ascii=False)}
            return
        from novel_agent.llm.client import LLMClient
        from novel_agent.storyline.creator import (
            apply_storylines, build_outline_text, suggest_storylines,
        )
        from novel_agent.bible.repository import BibleRepository
        client = LLMClient(cfg.get_agent_llm("summarizer"))
        try:
            repo = BibleRepository(db, project_id=project_id)
            outline_text = build_outline_text(repo)
            yield {"event": "collect_done", "data": json.dumps(
                {"chars": len(outline_text)}, ensure_ascii=False)}
            existing = db.query(Storyline).filter_by(project_id=project_id).all()
            suggestions = await suggest_storylines(
                client, outline_text, [l.name for l in existing])
            yield {"event": "suggestions", "data": json.dumps(
                suggestions, ensure_ascii=False)}
            stats = apply_storylines(db, project_id, suggestions, existing)
            yield {"event": "done", "data": json.dumps(stats, ensure_ascii=False)}
        except Exception as e:
            logger.warning("generate-plan 失败: %s", e)
            yield {"event": "error", "data": json.dumps(
                {"message": f"线规划失败：{e}"}, ensure_ascii=False)}
        finally:
            await client.close()

    return EventSourceResponse(event_gen())


@router.post("/{project_id}/storylines/llm-create")
async def llm_create_storylines(project_id: int,
                                db: Session = Depends(get_story_db)):
    """LLM 识别创建叙事线（SSE）：从卷纲/弧段/章纲/摘要识别主线支线暗线并建线。

    事件：collect_done / suggestions / done / error。
    与 generate-plan 同一实现，独立入口便于前端语义化调用。
    """
    async def event_gen():
        cfg = load_config()
        if not cfg.llm.api_key:
            yield {"event": "error", "data": json.dumps(
                {"message": "未配置 LLM API Key"}, ensure_ascii=False)}
            return
        from novel_agent.llm.client import LLMClient
        from novel_agent.storyline.creator import (
            apply_storylines, build_outline_text, suggest_storylines,
        )
        from novel_agent.bible.repository import BibleRepository
        client = LLMClient(cfg.get_agent_llm("summarizer"))
        try:
            repo = BibleRepository(db, project_id=project_id)
            outline_text = build_outline_text(repo)
            yield {"event": "collect_done", "data": json.dumps(
                {"chars": len(outline_text)}, ensure_ascii=False)}
            existing = db.query(Storyline).filter_by(project_id=project_id).all()
            suggestions = await suggest_storylines(
                client, outline_text, [l.name for l in existing])
            yield {"event": "suggestions", "data": json.dumps(
                suggestions, ensure_ascii=False)}
            stats = apply_storylines(db, project_id, suggestions, existing)
            yield {"event": "done", "data": json.dumps(stats, ensure_ascii=False)}
        except Exception as e:
            logger.warning("llm-create 失败: %s", e)
            yield {"event": "error", "data": json.dumps(
                {"message": f"叙事线识别创建失败：{e}"}, ensure_ascii=False)}
        finally:
            await client.close()

    return EventSourceResponse(event_gen())


# ── 从大纲导入线（远期 P1 占位） ──
@router.post("/{project_id}/storylines/import-from-outlines")
def import_from_outlines(project_id: int, db: Session = Depends(get_story_db)):
    return {"imported": 0, "message": "从大纲导入线功能在 P1 阶段实现"}


# ── 线系统回写细纲（远期 P1 占位） ──
@router.post("/{project_id}/storylines/push-to-outlines")
def push_to_outlines(project_id: int, db: Session = Depends(get_story_db)):
    return {"pushed": 0, "message": "回写细纲功能在 P1 阶段实现"}
