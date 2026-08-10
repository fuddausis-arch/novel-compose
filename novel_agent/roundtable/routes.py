"""圆桌会议 REST API 路由

独立的 APIRouter，前缀 /api/roundtable（在 app.py 注册时挂载）。

从 DeterminFlow 移植，适配 NovelAgent：
- 移除 event_bus 依赖，事件通过 SSE 端点 /{session_id}/stream 实时推送
- 保留全部 13+ 端点：create/list/get/start/stop/transcript/shared-memory/
  delete/pause/resume/inject/nominate/seats(add/remove)/structured-conclusion
- 新增 GET /{session_id}/stream：SSE 实时事件流（rt_token/rt_turn_start/...）

Phase 2：创建时支持 strategy 和 compressor 配置，共享记忆查询端点
Phase 3：暂停/恢复、用户插话/点名、动态增减席位、结构化结论查询
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger("roundtable")

# 不设 prefix，在 app.py 注册时通过 prefix="/api/roundtable" 挂载
router = APIRouter(tags=["roundtable"])


# ============ 请求模型 ============

class SeatConfig(BaseModel):
    role_name: str = Field(description="角色名称")
    system_prompt: str = Field(default="", description="该角色的 system prompt")
    temperature: float = Field(default=0.7, description="温度参数")
    model_name: str | None = Field(default=None, description="可选独立模型")
    is_moderator: bool = Field(default=False, description="是否为主持人")


class CompressorConfig(BaseModel):
    enabled: bool = Field(default=False, description="是否启用上下文压缩")
    window_size: int = Field(default=20, ge=5, le=100, description="滑动窗口大小")
    summary_interval: int = Field(default=0, ge=0, le=10, description="摘要间隔轮次（0=不自动摘要）")


class CreateRoundtableRequest(BaseModel):
    topic: str = Field(description="讨论主题")
    seats: list[SeatConfig] = Field(description="席位配置列表", min_length=2)
    max_rounds: int = Field(default=3, ge=1, le=20, description="最大讨论轮次")
    strategy: str = Field(default="round_robin", description="调度策略: round_robin | moderator_decides")
    compressor: CompressorConfig | None = Field(default=None, description="上下文压缩配置")


# Phase 3 请求模型

class InjectRequest(BaseModel):
    content: str = Field(description="插话内容", min_length=1)


class NominateRequest(BaseModel):
    target_seat_id: str | None = Field(default=None, description="目标席位 ID")
    target_name: str | None = Field(default=None, description="目标角色名称（可模糊匹配）")
    content: str = Field(default="", description="附带的问题或评论")


class AddSeatRequest(BaseModel):
    role_name: str = Field(description="角色名称")
    system_prompt: str = Field(default="", description="该角色的 system prompt")
    temperature: float = Field(default=0.7, description="温度参数")
    model_name: str | None = Field(default=None, description="可选独立模型")
    is_moderator: bool = Field(default=False, description="是否为主持人")


# ============ 辅助函数 ============

def _get_rt_manager(request: Request):
    """从 app.state 获取 RoundtableManager 单例。"""
    if not hasattr(request.app.state, "roundtable_manager"):
        raise HTTPException(status_code=503, detail="圆桌会议管理器未初始化，请检查服务配置")
    return request.app.state.roundtable_manager


def _get_session(mgr, session_id: str):
    """获取会话，不存在则 404。"""
    session = mgr.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到圆桌会议 {session_id}")
    return session


# ============ API 端点 ============

@router.post("")
async def create_roundtable(body: CreateRoundtableRequest, request: Request):
    """创建一场新的圆桌会议"""
    mgr = _get_rt_manager(request)

    # 校验策略
    valid_strategies = {"round_robin", "moderator_decides"}
    if body.strategy not in valid_strategies:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的调度策略: {body.strategy}，可选: {', '.join(valid_strategies)}"
        )

    seats_config = [s.model_dump() for s in body.seats]
    compressor_config = body.compressor.model_dump() if body.compressor else None

    session = mgr.create(
        topic=body.topic,
        seats_config=seats_config,
        max_rounds=body.max_rounds,
        strategy=body.strategy,
        compressor_config=compressor_config,
    )

    return {
        "success": True,
        "session": session.get_summary(),
    }


@router.get("")
async def list_roundtables(request: Request):
    """列出所有圆桌会议"""
    mgr = _get_rt_manager(request)
    return {
        "roundtables": mgr.list_all(),
        "total": len(mgr.sessions),
    }


@router.get("/{session_id}")
async def get_roundtable_detail(session_id: str, request: Request):
    """获取圆桌会议详情"""
    mgr = _get_rt_manager(request)
    session = _get_session(mgr, session_id)

    data = session.to_dict()
    data["current_speaker"] = (
        session.current_speaker.role_name if session.current_speaker else None
    )
    data["current_speaker_seat_id"] = (
        session.current_speaker.seat_id if session.current_speaker else None
    )
    # Phase 2: 策略名称
    data["strategy"] = session.strategy_name
    return data


@router.post("/{session_id}/start")
async def start_roundtable(session_id: str, request: Request):
    """开始圆桌会议讨论"""
    mgr = _get_rt_manager(request)
    result = await mgr.start(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/{session_id}/stop")
async def stop_roundtable(session_id: str, request: Request):
    """终止圆桌会议"""
    mgr = _get_rt_manager(request)
    result = await mgr.stop(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/{session_id}/transcript")
async def get_transcript(session_id: str, request: Request):
    """获取讨论记录"""
    mgr = _get_rt_manager(request)
    session = _get_session(mgr, session_id)

    return {
        "transcript": [t.to_dict() for t in session.transcript],
        "total": len(session.transcript),
        "current_round": session.current_round,
    }


@router.get("/{session_id}/shared-memory")
async def get_shared_memory(session_id: str, request: Request):
    """获取共享记忆（Phase 2）"""
    mgr = _get_rt_manager(request)
    session = _get_session(mgr, session_id)

    return {
        "shared_memory": session.shared_memory.to_dict(),
        "session_id": session_id,
    }


@router.delete("/{session_id}")
async def delete_roundtable(session_id: str, request: Request):
    """删除圆桌会议"""
    mgr = _get_rt_manager(request)
    result = await mgr.delete(session_id)
    if not result["success"]:
        status_code = 404 if "未找到" in result["message"] else 400
        raise HTTPException(status_code=status_code, detail=result["message"])
    return result


# ============ SSE 实时事件流（NovelAgent 适配，替代 event_bus）============

@router.get("/{session_id}/stream")
async def stream_roundtable(session_id: str, request: Request):
    """
    SSE 实时事件流。

    订阅会话的所有事件（rt_token / rt_turn_start / rt_turn_end /
    rt_round_end / rt_started / rt_ended / speaker_selected /
    moderator_decision / roundtable_summary / roundtable_conclusion /
    rt_paused / rt_resumed / rt_seat_added / rt_seat_removed / rt_deleted）。

    客户端通过 EventSource 连接，收到 rt_ended 或 rt_deleted 后应关闭连接。
    """
    mgr = _get_rt_manager(request)
    session = _get_session(mgr, session_id)

    # 订阅事件队列
    queue = session.event_broadcaster.subscribe()

    async def event_gen():
        try:
            # 如果会话已结束，先推送最终状态再关闭
            if session.status == "ended":
                yield {
                    "event": "rt_ended",
                    "data": json.dumps({
                        "type": "rt_ended",
                        "roundtable_id": session_id,
                        "total_rounds": session.current_round,
                        "transcript_count": len(session.transcript),
                    }, ensure_ascii=False),
                }
                return

            while True:
                if await request.is_disconnected():
                    logger.info(f"Roundtable SSE: 客户端断开连接 {session_id}")
                    break
                try:
                    # 15 秒无事件则发 ping 保活
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue

                etype = event.get("type", "message")
                yield {
                    "event": etype,
                    "data": json.dumps(event, ensure_ascii=False),
                }

                # 会议结束或删除：推送完毕后关闭流
                if etype in ("rt_ended", "rt_deleted"):
                    break
        finally:
            session.event_broadcaster.unsubscribe(queue)

    # ping=15：agent 单次发言可达数分钟，期间无字节会被代理掐断
    return EventSourceResponse(event_gen(), ping=15)


# ============ Phase 3 新增端点 ============

@router.post("/{session_id}/pause")
async def pause_roundtable(session_id: str, request: Request):
    """暂停圆桌会议"""
    mgr = _get_rt_manager(request)
    result = await mgr.pause(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/{session_id}/resume")
async def resume_roundtable(session_id: str, request: Request):
    """恢复圆桌会议"""
    mgr = _get_rt_manager(request)
    result = await mgr.resume(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/{session_id}/inject")
async def inject_to_roundtable(session_id: str, body: InjectRequest, request: Request):
    """用户插话"""
    mgr = _get_rt_manager(request)
    result = await mgr.inject(session_id, body.content)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/{session_id}/nominate")
async def nominate_speaker(session_id: str, body: NominateRequest, request: Request):
    """点名某个 seat 发言"""
    mgr = _get_rt_manager(request)
    if not body.target_seat_id and not body.target_name:
        raise HTTPException(status_code=400, detail="必须提供 target_seat_id 或 target_name")
    result = await mgr.nominate(
        session_id,
        target_seat_id=body.target_seat_id,
        target_name=body.target_name,
        content=body.content,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/{session_id}/seats")
async def add_seat_to_roundtable(session_id: str, body: AddSeatRequest, request: Request):
    """动态添加席位"""
    mgr = _get_rt_manager(request)
    result = await mgr.add_seat(session_id, body.model_dump())
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.delete("/{session_id}/seats/{seat_id}")
async def remove_seat_from_roundtable(session_id: str, seat_id: str, request: Request):
    """动态移除席位"""
    mgr = _get_rt_manager(request)
    result = await mgr.remove_seat(session_id, seat_id)
    if not result["success"]:
        status_code = 404 if "未找到" in result["message"] else 400
        raise HTTPException(status_code=status_code, detail=result["message"])
    return result


@router.get("/{session_id}/structured-conclusion")
async def get_structured_conclusion(session_id: str, request: Request):
    """获取结构化结论（Phase 3）"""
    mgr = _get_rt_manager(request)
    session = _get_session(mgr, session_id)

    sc = session.shared_memory.structured_conclusion
    return {
        "session_id": session_id,
        "has_structured_conclusion": sc is not None,
        "structured_conclusion": sc,
        "shared_memory": session.shared_memory.to_dict(),
    }
