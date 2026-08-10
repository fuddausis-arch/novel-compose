"""Cron 定时任务管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.cron.scheduler import CronJob, CronScheduler, CronStore

router = APIRouter()

# 全局单例
_store = CronStore()
_scheduler = CronScheduler(store=_store)


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
