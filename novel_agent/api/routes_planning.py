"""规划 API：启动卷级规划 + 人审① resume。"""
from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.planning.runner import VolumeRunner

logger = logging.getLogger(__name__)

router = APIRouter()


class PlanRequest(BaseModel):
    project_id: int
    volume: str = "卷一"
    chapter_count: int = 30
    thread_id: str
    custom_prompt: str = ""
    target_volumes: int = 0
    golden_finger: str = ""
    protagonist: str = ""
    constitution: str = ""


class ResumeRequest(BaseModel):
    project_id: int
    thread_id: str
    approved: bool
    edits: str = ""


class DetectRequest(BaseModel):
    project_id: int
    result: dict


def _get_repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    return db, BibleRepository(db, project_id=project_id)


@router.post("/run")
async def run_planning(req: PlanRequest):
    db, repo = _get_repo(req.project_id)
    runner = VolumeRunner(load_config(), repo=repo)
    try:
        result = await runner.run(
            volume=req.volume, chapter_count=req.chapter_count,
            thread_id=req.thread_id, custom_prompt=req.custom_prompt,
            target_volumes=req.target_volumes,
            golden_finger=req.golden_finger,
            protagonist=req.protagonist,
            constitution=req.constitution)
        await runner.aclose()
        result["thread_id"] = req.thread_id
        return result
    finally:
        db.close()


def _planning_node_progress(node_name: str) -> int:
    return {
        "plan": 30,
        "design": 60,
        "review": 80,
        "apply": 100,
    }.get(node_name, 0)


@router.get("/run/stream")
async def run_planning_stream(
    request: Request,
    project_id: int,
    volume: str = "卷一",
    chapter_count: int = 30,
    thread_id: str | None = None,
    custom_prompt: str = "",
    target_volumes: int = 0,
    golden_finger: str = "",
    constitution: str = "",
    protagonist: str = "",
):
    """SSE 流式全书规划：推送节点完成事件，最后返回完整结果。

    全书规划仅含 plan(卷结构+立意) → design(世界观/角色) → review → apply(落库卷大纲+设定)。
    章纲不再在此生成，交由"大纲管理"页面单独触发。
    target_volumes/golden_finger/protagonist/constitution/custom_prompt 作为约束注入 Planner 与 Architect。
    """
    import asyncio
    import json
    import uuid
    from sse_starlette.sse import EventSourceResponse

    # 初始化阶段：把可能抛异常的代码（config 加载、VolumeRunner 初始化、
    # chromadb PersistentClient、项目校验）放进 try-except，
    # 出错时通过 SSE error 事件返回具体错误，而不是让 FastAPI 返回 500
    # 导致前端只能看到模糊的「SSE 错误」。
    init_error: str | None = None
    cfg = None
    db = None
    repo = None
    runner = None
    try:
        cfg = load_config()
        set_config(cfg)
        from novel_agent.bible import database as db_mod
        Base.metadata.create_all(bind=db_mod.engine)
        db = SessionLocal()
        repo = BibleRepository(db, project_id=project_id)
        runner = VolumeRunner(cfg, repo=repo)
        await runner._ensure_async()
        runner._validate_project()
    except Exception as e:
        init_error = f"{type(e).__name__}: {e}"
        import traceback
        traceback.print_exc()
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        if runner is not None:
            try:
                await runner.aclose()
            except Exception:
                pass

    tid = thread_id or str(uuid.uuid4())
    state = {
        "project_id": project_id,
        "volume": volume,
        "chapter_count": chapter_count,
        "target_volumes": target_volumes,
        "custom_prompt": custom_prompt,
        "golden_finger": golden_finger,
        "protagonist": protagonist,
        "constitution": constitution,
        "status": "pending",
    }

    async def event_generator():
        # 初始化失败：直接通过 SSE error 事件返回，前端能看到具体原因
        if init_error:
            yield {"event": "error", "data": json.dumps({"error": init_error}, ensure_ascii=False)}
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def producer():
            try:
                async for mode, chunk in runner.graph.astream(
                    state,
                    config={"configurable": {"thread_id": tid}},
                    stream_mode=["updates"],
                ):
                    if await request.is_disconnected():
                        logger.info("run_planning_stream: 客户端已断开，停止规划 thread_id=%s", tid)
                        await queue.put({"event": "error", "data": json.dumps({"error": "用户取消或连接断开"}, ensure_ascii=False)})
                        break
                    if mode == "updates":
                        for node_name, _node_output in chunk.items():
                            progress = _planning_node_progress(node_name)
                            await queue.put({
                                "event": "node",
                                "data": json.dumps({
                                    "node": node_name,
                                    "progress": progress,
                                }, ensure_ascii=False),
                            })
                # 流结束：可能停在 review 中断点，取当前状态返回完整结果
                final_state = await runner.graph.aget_state(
                    config={"configurable": {"thread_id": tid}}
                )
                result = dict(final_state.values) if final_state else {}
                result["thread_id"] = tid
                await queue.put({"event": "done", "data": json.dumps(result, ensure_ascii=False, default=str)})
            except Exception as e:
                await queue.put({"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)})
            finally:
                await runner.aclose()
                db.close()

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                    if event["event"] in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except asyncio.CancelledError:
                    pass

    return EventSourceResponse(event_generator())


@router.post("/resume")
async def resume_planning(req: ResumeRequest):
    db, repo = _get_repo(req.project_id)
    runner = VolumeRunner(load_config(), repo=repo)
    try:
        result = await runner.resume(
            {"approved": req.approved, "edits": req.edits}, thread_id=req.thread_id)
        await runner.aclose()
        return result
    finally:
        db.close()


def _detect_planning_issues(result: dict, repo: BibleRepository) -> list[dict]:
    """导入前检测：把规划结果与现有资产比对，返回潜在冲突/错误。

    全书规划只检测：角色重复、世界设定重复、卷大纲覆盖。
    章纲/伏笔不再在此检测（已交由大纲管理页面）。
    """
    issues: list[dict] = []
    existing_chars = {c.name for c in repo.list_characters()}
    existing_ws = {(w.category, w.title) for w in repo.list_world_settings() if w.title}
    existing_volume_orders = {o.order for o in repo.list_outlines(level="volume")}

    settings = result.get("settings") or {}
    for c in settings.get("characters", []):
        name = (c.get("name") or "").strip()
        if not name:
            continue
        if name in existing_chars:
            issues.append({
                "type": "duplicate_character",
                "severity": "warning",
                "message": f"角色「{name}」已存在，导入将跳过",
            })

    for ws in settings.get("world_settings", []):
        category = (ws.get("category") or "").strip()
        title = (ws.get("title") or "").strip()
        if not title:
            continue
        if (category, title) in existing_ws:
            issues.append({
                "type": "duplicate_world_setting",
                "severity": "warning",
                "message": f"世界设定「{category}/{title}」已存在，导入将跳过",
            })

    volume_plan = result.get("volume_plan") or {}
    for idx, v in enumerate(volume_plan.get("volumes", []), start=1):
        if idx in existing_volume_orders:
            issues.append({
                "type": "duplicate_volume_outline",
                "severity": "warning",
                "message": f"第{idx}卷大纲已存在，导入将覆盖",
            })
        if not (v.get("name") or "").strip():
            issues.append({
                "type": "missing_volume_name",
                "severity": "warning",
                "message": f"第{idx}卷缺少卷名，将以「卷{idx}」补齐",
            })

    return issues


@router.post("/detect")
async def detect_planning_issues_endpoint(req: DetectRequest):
    db, repo = _get_repo(req.project_id)
    try:
        issues = _detect_planning_issues(req.result, repo)
        return {"issues": issues}
    finally:
        db.close()
