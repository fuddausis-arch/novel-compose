"""Telemetry API：元认知监控 + Token 账本 + 压缩/工具统计 + 系统状态。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.config import load_config
from novel_agent.telemetry.metacog import MetacogStore
from novel_agent.utils.token_usage import ledger as _token_ledger

router = APIRouter()


def _get_project_dir(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(404, "项目不存在")
        return cfg.project_dir(project_id)
    finally:
        db.close()


@router.get("/metacog/{project_id}")
def get_metacog(project_id: int, limit: int = 100):
    """读取项目的批量生成元认知监控指标。"""
    project_dir = _get_project_dir(project_id)
    store = MetacogStore(project_dir)
    return {"project_id": project_id, "metrics": store.list_metrics(limit=limit)}


@router.put("/metacog/{project_id}/rate/{chapter}")
def rate_chapter(project_id: int, chapter: int, rating: int):
    """人读评分（1-5 分），更新指定章节的 human_rating。"""
    project_dir = _get_project_dir(project_id)
    store = MetacogStore(project_dir)
    if rating < 1 or rating > 5:
        raise HTTPException(400, "评分必须 1-5")
    updated = store.rate(chapter, rating)
    if not updated:
        raise HTTPException(404, f"第{chapter}章无生成记录")
    return {"saved": True, "chapter": chapter, "rating": rating}


# ---- Token 账本统计 ----


@router.get("/tokens")
def get_token_stats():
    """Token 账本统计：总计、按节点、按模型聚合（复用 token_usage.ledger）。"""
    return {
        "total": _token_ledger.get_total(),
        "by_node": _token_ledger.get_by_node(),
        "by_model": _token_ledger.get_by_model(),
        "records": _token_ledger.to_dict(),
    }


# ---- 压缩统计 ----


# 压缩策略描述（key 与 CompressionStrategy.value 对应）
_STRATEGY_DESCRIPTIONS = {
    "none": "不压缩",
    "micro": "微压缩：只压缩工具结果，保留对话消息",
    "full": "全量压缩：LLM 摘要全部历史消息",
    "reactive": "渐进式丢弃：API 413 错误时从最旧消息开始删除",
}


@router.get("/compression")
def get_compression_stats():
    """压缩统计：返回压缩引擎配置和策略信息。

    当前压缩器为无状态调用（不持久化统计），此处返回策略枚举和配置常量，
    便于前端展示可用压缩能力。后续可扩展为持久化压缩记录统计。
    """
    from novel_agent.utils.context_compressor import CompressionStrategy

    strategies = [
        {
            "name": s.value,
            "description": _STRATEGY_DESCRIPTIONS.get(s.value, ""),
        }
        for s in CompressionStrategy
    ]
    return {
        "strategies": strategies,
        "config": {
            "micro_keep_recent_tools": 5,
            "full_keep_recent_tokens": 8000,
            "full_summary_max_tokens": 1000,
            "keep_recent_msgs": 6,
            "chars_per_token": 4,
        },
        "message": "压缩器为无状态调用，暂无持久化统计数据",
    }


# ---- 工具调用统计 ----


@router.get("/tools")
def get_tool_stats():
    """工具调用统计：从 Token 账本中提取节点维度的调用信息。

    当前工具调用未单独持久化统计，此处基于 Token 账本的 node_name 维度
    推导工具相关节点的调用频次。后续可扩展为独立的工具调用日志。
    """
    by_node = _token_ledger.get_by_node()
    # 从节点名中识别工具相关调用（node_name 包含 tool/executor 等关键词）
    tool_related = {}
    for node_name, stats in by_node.items():
        name_lower = node_name.lower()
        if any(kw in name_lower for kw in ("tool", "executor", "chat", "agent")):
            tool_related[node_name] = stats
    return {
        "total_calls": _token_ledger.get_total()["call_count"],
        "by_node": by_node,
        "tool_related_nodes": tool_related,
        "message": "工具调用统计基于 Token 账本推导，独立工具日志待后续实现",
    }


# ---- 系统状态 ----


@router.get("/system")
def get_system_status():
    """系统状态：复用 routes_health 的健康检查逻辑。"""
    from novel_agent.api.routes_health import health_check
    return health_check()
