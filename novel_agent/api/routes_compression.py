"""压缩监控 API。

统计与日志从压缩日志文件（project_data/compression_log.jsonl）读取，
该文件由 novel_agent.utils.context_compressor 在每次实际压缩时追加写入。
返回结构保持与旧版一致（total_compressions/avg_ratio/total_tokens_saved/strategies
与 logs/total/limit/offset），不破坏前端。
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/stats")
def get_compression_stats():
    """获取压缩统计信息（从压缩日志文件聚合）。"""
    from novel_agent.utils.context_compressor import CompressionStrategy, compression_stats

    strategies = []
    for s in CompressionStrategy:
        strategies.append({
            "key": s.value,
            "name": s.name,
            "description": "",
        })
    stats = compression_stats()
    return {
        "total_compressions": stats["total_compressions"],
        "avg_ratio": stats["avg_ratio"],
        "total_tokens_saved": stats["total_tokens_saved"],
        "strategies": strategies,
    }


@router.get("/logs")
def get_compression_logs(limit: int = 50, offset: int = 0):
    """获取压缩历史日志（从压缩日志文件读取，最新在前）。"""
    from novel_agent.utils.context_compressor import count_compression_logs, load_compression_logs

    logs = load_compression_logs(limit=limit, offset=offset)
    return {
        "logs": logs,
        "total": count_compression_logs(),
        "limit": limit,
        "offset": offset,
    }
