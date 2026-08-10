"""压缩监控 API。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/stats")
def get_compression_stats():
    """获取压缩统计信息（转发到 telemetry 模块）。"""
    from novel_agent.utils.context_compressor import CompressionStrategy
    strategies = []
    for s in CompressionStrategy:
        strategies.append({
            "key": s.value,
            "name": s.name,
            "description": "",
        })
    return {
        "total_compressions": 0,
        "avg_ratio": 0.0,
        "total_tokens_saved": 0,
        "strategies": strategies,
    }


@router.get("/logs")
def get_compression_logs(limit: int = 50, offset: int = 0):
    """获取压缩历史日志。"""
    return {
        "logs": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }
