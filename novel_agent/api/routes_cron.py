"""Cron 定时任务管理 API。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.cron.scheduler import CronJob, CronScheduler, CronStore

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局单例
_store = CronStore()
_scheduler = CronScheduler(store=_store)

# 内置任务：定时清理过期交互式创作会话（每分钟）
_BUILTIN_CLEANUP_JOB_ID = "builtin_cleanup_interactive_sessions"
_CLEANUP_JOB_TYPE = "cleanup_interactive"


def _cleanup_interactive_runner(parameters: dict) -> dict:
    """内置任务 runner：清理过期的交互式创作会话。"""
    from novel_agent.chat.session_store import get_session_store

    removed = get_session_store().cleanup_expired_interactive()
    logger.info("cron 内置任务执行：清理 %d 个过期交互会话", removed)
    return {"ok": True, "removed": removed}


def start_cron_scheduler() -> None:
    """注册内置任务并启动调度器（幂等，可重复调用；失败不抛异常）。"""
    try:
        _scheduler.register_runner(_CLEANUP_JOB_TYPE, _cleanup_interactive_runner)
        existing = _store.load_job(_BUILTIN_CLEANUP_JOB_ID)
        if existing is None:
            _scheduler.add_job(CronJob(
                id=_BUILTIN_CLEANUP_JOB_ID,
                name="定时清理过期交互会话",
                schedule="* * * * *",  # 每分钟
                workflow_type=_CLEANUP_JOB_TYPE,
                parameters={},
                enabled=True,
            ))
        _scheduler.start()
    except Exception as e:
        logger.warning("启动 cron 调度器失败: %s", e)


def stop_cron_scheduler() -> None:
    """停止调度器（失败不抛异常）。"""
    try:
        _scheduler.stop()
    except Exception as e:
        logger.warning("停止 cron 调度器失败: %s", e)


class CreateCronJobRequest(BaseModel):
    id: str
    name: str
    schedule: str  # cron 表达式
    workflow_type: str  # batch_generate / post_hoc / snapshot
    parameters: dict = {}
    enabled: bool = True


class UpdateCronJobRequest(BaseModel):
    name: str | None = None
    schedule: str | None = None
    workflow_type: str | None = None
    parameters: dict | None = None
    enabled: bool | None = None


@router.get("")
def list_cron_jobs():
    """列出所有定时任务。"""
    jobs = _store.load_jobs()
    return {"jobs": [j.to_dict() for j in jobs], "total": len(jobs)}


@router.get("/{job_id}")
def get_cron_job(job_id: str):
    """获取单个任务详情。"""
    job = _store.load_job(job_id)
    if job is None:
        raise HTTPException(404, f"未找到任务: {job_id}")
    return job.to_dict()


@router.post("")
def create_cron_job(req: CreateCronJobRequest):
    """创建定时任务。"""
    job = CronJob(
        id=req.id,
        name=req.name,
        schedule=req.schedule,
        workflow_type=req.workflow_type,
        parameters=req.parameters,
        enabled=req.enabled,
    )
    _scheduler.add_job(job)
    return {"success": True, "job": job.to_dict()}


@router.put("/{job_id}")
def update_cron_job(job_id: str, req: UpdateCronJobRequest):
    """更新定时任务。"""
    job = _store.load_job(job_id)
    if job is None:
        raise HTTPException(404, f"未找到任务: {job_id}")
    if req.name is not None:
        job.name = req.name
    if req.schedule is not None:
        job.schedule = req.schedule
    if req.workflow_type is not None:
        job.workflow_type = req.workflow_type
    if req.parameters is not None:
        job.parameters = req.parameters
    if req.enabled is not None:
        job.enabled = req.enabled
    _scheduler.add_job(job)  # upsert
    return {"success": True, "job": job.to_dict()}


@router.delete("/{job_id}")
def delete_cron_job(job_id: str):
    """删除定时任务。"""
    job = _store.load_job(job_id)
    if job is None:
        raise HTTPException(404, f"未找到任务: {job_id}")
    _scheduler.remove_job(job_id)
    return {"success": True, "message": f"已删除任务: {job_id}"}


@router.post("/{job_id}/trigger")
def trigger_cron_job(job_id: str):
    """手动触发一次任务执行。"""
    result = _scheduler.trigger_job(job_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "触发失败"))
    return result


@router.post("/{job_id}/toggle")
def toggle_cron_job(job_id: str, enabled: bool = True):
    """启用/禁用任务。"""
    job = _store.load_job(job_id)
    if job is None:
        raise HTTPException(404, f"未找到任务: {job_id}")
    job.enabled = enabled
    _scheduler.add_job(job)
    return {"success": True, "job_id": job_id, "enabled": enabled}
