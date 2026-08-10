"""健康检查 + SSE Job 端点。

借鉴 bishu-novel 的 API 设计：
- GET /api/health: 健康检查（数据库/LLM/磁盘空间）
- GET /api/health/ready: 就绪检查
- GET /api/jobs/{job_id}/stream: SSE Job 流（用于批量生成进度推送）
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 记录应用启动时间，用于计算 uptime
_START_TIME = time.time()


@router.get("/health")
def health_check() -> dict[str, Any]:
    """健康检查：数据库/LLM/磁盘空间状态。

    借鉴 bishu-novel 的健康检查设计，逐项探测各组件状态：
    - database: 尝试查询 projects 表
    - llm: 检查 API key 是否配置
    - disk: 检查磁盘剩余空间
    - uptime: 应用运行时间（秒）
    """
    # ---- 数据库检查：尝试查询 projects 表 ----
    db_status = "ok"
    try:
        from novel_agent.bible.database import SessionLocal
        from novel_agent.bible.models import Project
        db = SessionLocal()
        try:
            db.query(Project).first()
        finally:
            db.close()
    except Exception as e:
        db_status = "error"
        logger.warning("健康检查：数据库异常: %s", e)

    # ---- LLM 检查：API key 是否配置 ----
    llm_status = "ok"
    try:
        from novel_agent.config import load_config
        cfg = load_config()
        if not cfg.llm.api_key:
            llm_status = "error"
    except Exception as e:
        llm_status = "error"
        logger.warning("健康检查：LLM 配置异常: %s", e)

    # ---- 磁盘空间检查 ----
    disk_info: dict[str, float] = {}
    try:
        from novel_agent.config import load_config
        cfg = load_config()
        check_path = str(cfg.project_data_dir)
        usage = shutil.disk_usage(check_path)
        disk_info["free_gb"] = round(usage.free / (1024 ** 3), 2)
        disk_info["total_gb"] = round(usage.total / (1024 ** 3), 2)
    except Exception as e:
        disk_info["error"] = str(e)

    overall = "ok" if db_status == "ok" and llm_status == "ok" else "degraded"
    return {
        "status": overall,
        "database": db_status,
        "llm": llm_status,
        "disk": disk_info,
        "uptime": round(time.time() - _START_TIME, 1),
    }


@router.get("/health/ready")
def readiness_check() -> dict[str, bool]:
    """就绪检查：简单返回 ready 状态。

    用于负载均衡器/容器编排判断服务是否就绪。
    """
    return {"ready": True}


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """SSE Job 流端点：推送批量生成进度。

    占位实现：后续对接 BookRunner 的进度队列。
    当前发送连接确认事件 + 定期心跳，便于前端 EventSource 预连接。

    Args:
        job_id: 任务 ID（对应 BookRunner 的批量生成任务）
    """
    async def event_generator():
        # 发送初始连接确认事件
        yield f"event: connected\ndata: {job_id}\n\n"
        while True:
            await asyncio.sleep(15)
            # 心跳事件，防止代理/负载均衡器因空闲超时断开连接
            yield f"event: heartbeat\ndata: {time.time()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 禁用 Nginx 等反向代理的缓冲，确保 SSE 实时推送
            "X-Accel-Buffering": "no",
        },
    )
