"""工作流引擎 API：7 条 bishu-novel 移植工作流的查询与执行。

- GET  /api/workflows              列出 7 条工作流（id/name/节点数/变量）
- GET  /api/workflows/{id}         获取完整定义（节点/边/网关，供画布可视化）
- POST /api/workflows/{id}/run     SSE 流式执行工作流（node_start/node_done/node_failed/workflow_done）
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from novel_agent.config import load_config
from novel_agent.llm.client import LLMClient
from novel_agent.workflows import (
    WORKFLOW_IDS,
    list_workflows,
    load_definition,
    run_workflow,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RunRequest(BaseModel):
    """工作流执行请求。"""
    project_id: int
    inputs: dict = {}
    agent_role: str = "writer"  # 用哪个角色的 LLM 配置驱动（温度光谱见 config）


@router.get("")
def get_workflows(project_id: int | None = None):
    """列出所有工作流（内置 7 条 + 项目自定义）。

    Query 参数 project_id 可选，传入则合并该项目的自定义工作流。
    """
    return {"workflows": list_workflows(project_id=project_id)}


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, project_id: int | None = None):
    """获取单条工作流的完整定义（内置或自定义）。"""
    try:
        return load_definition(workflow_id, project_id=project_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/{workflow_id}/run")
async def run(workflow_id: str, req: RunRequest):
    """SSE 流式执行工作流（支持内置和自定义工作流）。

    事件类型：
    - node_start {node, label}
    - node_done {node, elapsed_s}
    - node_failed {node, error}
    - workflow_done {status, node_runs}
    - error {error}
    """
    # 先校验工作流存在（内置或自定义）
    try:
        load_definition(workflow_id, project_id=req.project_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    cfg = load_config()
    workspace = cfg.project_dir(req.project_id)

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        async def _run():
            client = None
            try:
                # client 构造必须在 try 内：非法 agent_role 时 get_agent_llm 抛错，
                # 否则任务死亡、queue 收不到哨兵，SSE 生成器永久挂死
                client = LLMClient(cfg.get_agent_llm(req.agent_role))
                result = await run_workflow(
                    workflow_id, req.inputs, client, workspace,
                    on_event=on_event,
                    project_id=req.project_id,
                    cfg=cfg,
                )
                await queue.put({"type": "__result__", "result": result})
            except asyncio.CancelledError:
                # SSE 连接断开/前端取消时，确保资源清理 + 哨兵入队
                logger.info("工作流执行被取消（CancelledError），清理资源")
                raise
            except Exception as e:
                logger.exception("工作流执行异常")
                await queue.put({"type": "error", "error": str(e)})
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass
                await queue.put(None)  # 结束哨兵（即使 CancelledError 也要入队）

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if event.get("type") == "__result__":
                    yield {"event": "workflow_done", "data": json.dumps({
                        "status": event["result"].get("status"),
                        "node_runs": event["result"].get("node_runs", []),
                    }, ensure_ascii=False)}
                    continue
                etype = event.get("type", "message")
                yield {"event": etype, "data": json.dumps(event, ensure_ascii=False)}
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    # ping=15：agent 节点单次 LLM 调用可达数分钟，期间无字节会被代理/浏览器掐断
    return EventSourceResponse(event_gen(), ping=15)
