"""去除AI味蒸馏法 API：作品导入 / 多轮蒸馏 / Skill 管理 / 技能融合 / 效果对比。

- GET    /api/distillation/works                  列出所有作品
- POST   /api/distillation/works                  导入作品（title + content 或 file_path）
- GET    /api/distillation/works/{id}             作品详情（含 chunks 元信息）
- DELETE /api/distillation/works/{id}             删除作品（级联删除 chunks/rounds/skills）
- POST   /api/distillation/works/{id}/distill     开始蒸馏（SSE 流式进度）
- GET    /api/distillation/works/{id}/skills      该作品生成的所有 Skill
- GET    /api/distillation/skills                 列出所有蒸馏 Skill
- GET    /api/distillation/skills/{id}            Skill 详情
- PUT    /api/distillation/skills/{id}            更新 Skill（名称/描述/内容/标签/状态）
- DELETE /api/distillation/skills/{id}            删除 Skill（同时删除 Skills 系统 JSON 文件）
- POST   /api/distillation/fuse                   融合 Skill（skill_ids + weights + name）
- GET    /api/distillation/fusions                列出所有融合方案
- POST   /api/distillation/works/{id}/cancel   取消正在进行的蒸馏（优雅停止，保留已完成部分）
- GET    /api/distillation/status/{work_id}       蒸馏进度
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from novel_agent.config import load_config, LLMConfig
from novel_agent.distillation.engine import DistillationEngine
from novel_agent.api.routes_skills import rebuild_skill_index, remove_skill_from_index
from novel_agent.distillation.store import get_store
from novel_agent.llm.client import LLMClient

logger = logging.getLogger(__name__)
router = APIRouter()

# 蒸馏单次 LLM 请求的 read 超时（秒）。DeepSeek 深度思考 + 10 万字片段实测 15~45 秒一轮，
# 远低于此值；代理/网络链路假死时 keep-alive 连接会挂到超时才失败，
# 3 分钟兜底 + client 换新连接重试（max_retries=3），既保证慢轮次能完成，
# 又避免假死连接长时间卡住进度（表现为"蒸馏没增流"）。
DISTILL_TIMEOUT = 180.0

# 待取消的蒸馏任务（按 work_id）。连接断开（切页）不再取消后台任务，
# 只有显式调用 cancel 端点才中断——保证切页后任务继续、回来进度还在。
_CANCELLED_WORKS: set[int] = set()

# 正在蒸馏（运行中或排队中）的 work_id，用于同书防重：
# 前端页面刷新/重复点击可能对同一本书发起多个请求，这里直接拒绝第二个，
# 避免同一本书多个任务并行（浪费 LLM 调用、DB 写冲突）。
_RUNNING_DISTILLS: set[int] = set()

# 多书并发调度：同时最多蒸馏 _MAX_CONCURRENT_DISTILL 本书，超出排队（前端收到 queued 事件）。
# 用 Condition + 计数实现（asyncio.Semaphore 无法反馈排队信息）。
_MAX_CONCURRENT_DISTILL = 5
_distill_cond = asyncio.Condition()
_distill_in_schedule = 0  # 已进入调度（运行中 + 排队中）的书数量

# work_id -> 正在执行的蒸馏 asyncio.Task。
# 取消端点通过它立即中断正在进行的 AI 调用：否则任务要等 LLM 超时（最长 35 分钟）才退出，
# 期间一直占着并发槽位，后续任务排队饿死（表现为"启动后静默、进度不动"）。
_RUNNING_TASKS: dict[int, asyncio.Task] = {}


async def _enqueue_distill(on_event, is_cancelled) -> bool:
    """进入并发调度。超过上限先发 queued 事件再等待槽位。

    返回 False 表示排队期间被取消（无需执行）；True 表示已获得运行资格。
    """
    global _distill_in_schedule
    async with _distill_cond:
        _distill_in_schedule += 1
        if _distill_in_schedule > _MAX_CONCURRENT_DISTILL:
            await on_event({
                "type": "queued",
                "running": _MAX_CONCURRENT_DISTILL,
                "waiting": _distill_in_schedule - _MAX_CONCURRENT_DISTILL,
            })
        try:
            while _distill_in_schedule > _MAX_CONCURRENT_DISTILL:
                if is_cancelled():
                    _release_distill_slot()
                    return False
                await _distill_cond.wait()
        except asyncio.CancelledError:
            # 排队等待槽位时被取消：await wait() 抛 CancelledError，
            # 计数必须在 except 里同步释放，否则槽位泄漏、
            # 后续任务永远排队不被启动。
            _release_distill_slot()
            raise
    return True


def _release_distill_slot() -> None:
    """同步释放一个并发调度槽位（并唤醒等待者）。

    必须用同步版本：asyncio.Condition 的 async with / wait() 都是协程，
    任务被 cancel() 后 finally 中的 await 会再次抛 CancelledError，
    async 版本的释放逻辑永远执行不到，导致 _distill_in_schedule 只增不减、
    槽位永久泄漏——之后所有蒸馏任务都会卡在排队、永远不被启动
    （表现为"任务完成后不补位 / 新任务排队不动"）。
    Condition.notify_all() 是同步方法，计数递减 + 唤醒都不需要 await。
    """
    global _distill_in_schedule
    _distill_in_schedule = max(0, _distill_in_schedule - 1)
    try:
        _distill_cond.notify_all()
    except Exception:
        pass


# ---- Pydantic 模型 ----


class WorkImport(BaseModel):
    """作品导入请求：content 与 file_path 二选一。"""
    title: str
    content: str | None = None
    file_path: str | None = None


class DistillRequest(BaseModel):
    """蒸馏请求。"""
    rounds: int = 7  # 每片段的蒸馏轮数（维度数），兼容旧调用；dimensions 存在时以 dimensions 为准
    levels: int = 1  # 蒸馏级数：1=一次蒸馏（碎片）；2=二次蒸馏（浓缩提炼）；3=三次蒸馏（再浓缩）
    dimensions: list[int] | None = None  # 要蒸馏的维度编号列表（1-19，见 ROUND_DIMENSIONS）；None=全部维度
    retry_failed: bool = False  # 补蒸馏模式：只重跑失败的片段/轮次，跳过已成功的
    skip_done_rounds: bool = False  # 隔离模式：跳过已成功完成的维度（同书多次蒸馏不同维度时不重复、不覆盖）
    agent_role: str = "auditor"  # 蒸馏是分析型任务，用低温度角色
    enable_thinking: bool | None = None  # 思考模式开关：None=跟随模型/provider 默认；False=关闭（火山 coding 网关不兼容思考参数，会自动降级关闭）
    # 模型设置（可选）：不填则跟随 config.yaml 的 agent_role 配置
    provider: str | None = None          # 供应商名（从 model_providers.json 读真实 base_url/api_key）
    model: str | None = None             # 供应商模式下的模型名
    custom_base_url: str | None = None   # 自定义模式：接口地址
    custom_api_key: str | None = None    # 自定义模式：API Key（仅本次使用，不落盘）
    custom_model: str | None = None      # 自定义模式：模型名


class SkillUpdate(BaseModel):
    """Skill 更新字段（均可选）。"""
    name: str | None = None
    description: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    status: str | None = None


class FuseRequest(BaseModel):
    """Skill 融合请求。"""
    skill_ids: list[int] = []           # 蒸馏 DB skill ID
    skill_files: list[str] = []         # 拆书 skill 文件名（非 DB 记录）
    weights: list[float] | None = None
    name: str
    description: str = ""
    delete_originals: bool = False  # 融合成功后删除参与融合的原 Skill（DB 记录 + JSON 文件）
    agent_role: str = "auditor"  # 融合是分析型任务，用低温度角色
    # 模型设置（可选）：不填则跟随 config.yaml 的 agent_role 配置
    provider: str | None = None
    model: str | None = None
    custom_base_url: str | None = None
    custom_api_key: str | None = None
    custom_model: str | None = None


class CompareRequest(BaseModel):
    """效果对比请求。"""
    prompt: str
    skill_id: int | None = None
    agent_role: str = "writer"  # 对比生成是创作型任务，用高温度角色


# ---- 辅助 ----


def _engine() -> DistillationEngine:
    return DistillationEngine(get_store())


def _resolve_llm_config(cfg, req) -> LLMConfig:
    """按请求体解析蒸馏用 LLM 配置。

    优先级（低→高）：
    1. 跟随全局：cfg.get_agent_llm(req.agent_role)（config.yaml）
    2. 供应商模型：req.provider（从 model_providers.json 读真实 base_url/api_key，
       不经过前端脱敏，密钥不出服务端）+ req.model
    3. 自定义：req.custom_base_url / custom_api_key / custom_model（api_key 仅本次使用）
    最后应用 auditor 角色采样参数（低温度，蒸馏是分析型任务）。
    """
    import copy

    base: LLMConfig | None = None
    if req.provider:
        # 供应商模式：从 model_providers.json 读取完整配置（api_key 真实值，不经前端）
        from novel_agent.api.routes_models import _load_providers

        for p in _load_providers():
            if p.get("name") == req.provider:
                models = p.get("models") or []
                base = LLMConfig(
                    base_url=str(p.get("base_url", "")).rstrip("/") or "https://api.openai.com/v1",
                    api_key=str(p.get("api_key", "")),
                    model=req.model or (models[0] if models else ""),
                    # 思考模式跟随供应商在「模型管理」页的配置（null=默认，由 client 按网关自动适配）
                    enable_thinking=p.get("enable_thinking"),
                )
                break
        if base is None:
            raise HTTPException(400, f"供应商不存在: {req.provider}")
    elif req.custom_base_url or req.custom_model:
        # 自定义模式：直接传接口地址/密钥/模型名
        fallback = cfg.get_agent_llm(req.agent_role)
        base = LLMConfig(
            base_url=(req.custom_base_url or "").rstrip("/") or "https://api.openai.com/v1",
            api_key=req.custom_api_key or fallback.api_key,
            model=req.custom_model or req.model or fallback.model,
            max_tokens=fallback.max_tokens,
        )
    else:
        # 跟随全局：config.yaml 中 agent_role 的配置
        base = cfg.get_agent_llm(req.agent_role)

    # 统一应用 auditor 采样参数（温度五级光谱：分析/裁决用低温度）
    result = copy.copy(base)
    for key, value in cfg.ROLE_PARAMS.get("auditor", {}).items():
        setattr(result, key, value)
    # 统一蒸馏请求 read 超时（三种配置来源都覆盖）：挂死的假死连接最多等 10 分钟
    # 即由 client 超时并换新连接重发，不再死等 35 分钟
    result.timeout = DISTILL_TIMEOUT
    # 请求级显式思考开关优先（前端弹窗可临时覆盖供应商配置；None=跟随供应商配置）
    if req.enable_thinking is not None:
        result.enable_thinking = req.enable_thinking
    return result


def _skill_view(skill: dict) -> dict:
    """Skill dict 视图：tags 反序列化为 list。"""
    view = dict(skill)
    try:
        view["tags"] = json.loads(view.get("tags") or "[]")
    except (json.JSONDecodeError, TypeError):
        view["tags"] = []
    return view


def _fusion_view(fusion: dict) -> dict:
    """融合方案视图：JSON 字段反序列化 + 附带融合 Skill 文件名。"""
    view = dict(fusion)
    try:
        view["skill_ids"] = json.loads(view.pop("skill_ids_json") or "[]")
        view["weights"] = json.loads(view.pop("weights_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        view.setdefault("skill_ids", [])
        view.setdefault("weights", [])
    view["skill_file"] = view.get("skill_file") or f"distill_fusion_{view['id']}"
    return view


def _remove_skill_file(name: str) -> None:
    """删除 Skills 系统中对应的 JSON 文件（若存在）。"""
    safe = "".join(c for c in name if c.isalnum() or c in ("-", "_"))
    if not safe:
        return
    path = load_config().project_data_dir / "skills" / f"{safe}.json"
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.warning("删除 skill 文件失败 %s: %s", path, e)


# ---- 作品管理 ----


@router.get("/works")
def list_works():
    """列出所有蒸馏作品。"""
    return {"works": get_store().list_works()}


@router.post("/works")
def import_work(req: WorkImport):
    """导入作品：直接传 content，或给 file_path 由服务端读取。"""
    if not req.title.strip():
        raise HTTPException(400, "标题不能为空")
    content = req.content
    source_type = "corpus"
    if not content:
        if not req.file_path:
            raise HTTPException(400, "content 与 file_path 必须提供一个")
        path = Path(req.file_path)
        if not path.exists() or not path.is_file():
            raise HTTPException(404, f"文件不存在: {req.file_path}")
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            raise HTTPException(500, f"读取文件失败: {e}")
        source_type = "file"
    try:
        result = _engine().import_text(
            title=req.title.strip(), content=content,
            source_type=source_type, file_path=req.file_path,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    work = get_store().get_work(result["work_id"])
    return {"created": True, "work": work}


@router.post("/works/upload")
async def import_work_upload(
    file: UploadFile = File(...),
    title: str = Form(""),
):
    """上传文件（PDF/EPUB/DOCX/TXT）导入蒸馏作品。

    复用 file_extract 提取文本，再走蒸馏 import_text 管线。
    """
    from novel_agent.utils.file_extract import extract_text_or_image

    content, is_image = await extract_text_or_image(file)
    if is_image or not content.strip():
        raise HTTPException(400, "文件内容为空或为图片")

    book_title = title or (file.filename or "").rsplit(".", 1)[0] or "未命名作品"
    try:
        result = _engine().import_text(
            title=book_title, content=content,
            source_type="upload", file_path=file.filename,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    work = get_store().get_work(result["work_id"])
    return {"created": True, "work": work}


@router.get("/works/{work_id}")
def get_work(work_id: int):
    """作品详情（含 chunks 元信息 + 内容预览）。"""
    store = get_store()
    work = store.get_work(work_id)
    if not work:
        raise HTTPException(404, f"作品不存在: {work_id}")
    chunks = store.list_chunks(work_id)
    # 附带每个片段的内容预览（前 200 字），不回传全量内容
    full = store.list_chunks(work_id, include_content=True)
    preview_map = {c["id"]: c["content"][:200] for c in full}
    for c in chunks:
        c["preview"] = preview_map.get(c["id"], "")
    return {"work": work, "chunks": chunks}


@router.delete("/works/{work_id}")
def delete_work(work_id: int):
    """删除作品（级联删除 chunks/rounds/skills，并清理 Skills 系统文件）。"""
    store = get_store()
    work = store.get_work(work_id)
    if not work:
        raise HTTPException(404, f"作品不存在: {work_id}")
    for skill in store.list_skills(work_id):
        _remove_skill_file(skill["name"])
    store.delete_work(work_id)
    return {"deleted": True, "work_id": work_id}


# ---- 蒸馏 ----


@router.post("/works/{work_id}/distill")
async def distill_work(work_id: int, req: DistillRequest):
    """SSE 流式蒸馏整部作品。

    事件类型：
    - chunk_start {chunk_id, chunk_index, char_count}
    - round_start {chunk_id, round_num, dimension}
    - round_done {chunk_id, round_num, round_id}
    - round_failed {chunk_id, round_num, error}
    - skill_created {skill_id, skill_name, chunk_index, round_num}
    - chunk_done {chunk_id, status}
    - work_done {status, done_rounds, total_rounds, skills_count, ...}
    - error {error}
    """
    store = get_store()
    if not store.get_work(work_id):
        raise HTTPException(404, f"作品不存在: {work_id}")
    # 同书防重：同一本书已有蒸馏任务（运行中或排队）时拒绝重复启动，
    # 防止前端重复点击/刷新后重发导致的重复蒸馏
    if work_id in _RUNNING_DISTILLS:
        raise HTTPException(409, "这本书正在蒸馏中（含排队），请勿重复启动")
    # 清除可能残留的取消标记：重新发起蒸馏 = 明确的重新开始意图。
    # 若旧任务被取消时标记未清除，引擎每轮 is_cancelled 检查会直接判取消，
    # 表现为"点蒸馏后界面不动"。
    _CANCELLED_WORKS.discard(work_id)
    _RUNNING_DISTILLS.add(work_id)
    if req.rounds < 1:
        raise HTTPException(400, "rounds 必须 ≥ 1")
    if req.levels < 1:
        raise HTTPException(400, "levels 必须 ≥ 1")
    # 校验维度编号：必须在 ROUND_DIMENSIONS 范围内（动态取，当前 1-19）
    from novel_agent.distillation.engine import ROUND_DIMENSIONS

    if req.dimensions is not None:
        invalid = [d for d in req.dimensions if d not in ROUND_DIMENSIONS]
        if invalid:
            raise HTTPException(400, f"无效的蒸馏维度编号: {invalid}（可选范围 1-{len(ROUND_DIMENSIONS)}）")

    cfg = load_config()

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        async def _run():
            client = None
            try:
                # 多书并发调度：超过 _MAX_CONCURRENT_DISTILL 本时排队，前端收到 queued 事件
                if not await _enqueue_distill(on_event, lambda: work_id in _CANCELLED_WORKS):
                    # 排队期间被取消：直接结束，不启动蒸馏
                    await queue.put({"type": "cancelled", "work_id": work_id})
                    await queue.put(None)
                    _CANCELLED_WORKS.discard(work_id)
                    return
                # client 构造必须在 try 内：非法 agent_role / 供应商时解析抛错，
                # 否则任务死亡、queue 收不到哨兵，SSE 生成器永久挂死
                client = LLMClient(_resolve_llm_config(cfg, req))
                engine = DistillationEngine(get_store())
                await engine.distill_work(
                    work_id, client, dimensions=req.dimensions, levels=req.levels,
                    retry_failed=req.retry_failed, skip_done_rounds=req.skip_done_rounds,
                    on_event=on_event,
                    is_cancelled=lambda: work_id in _CANCELLED_WORKS,
                    enable_thinking=req.enable_thinking,
                )
            except asyncio.CancelledError:
                # CancelledError 继承 BaseException（Python 3.9+），不会被 except Exception 捕获。
                # SSE 断连时 ASGI 可能取消生成器任务，CancelledError 传播到 _run；
                # 如果不在这里捕获并更新状态，DB 会永远停在 "distilling"，
                # 前端看到"蒸馏中"但进度不动（任务已死）。
                logger.warning("蒸馏任务被取消 (work_id=%d)，更新状态为 cancelled", work_id)
                try:
                    get_store().update_work_status(work_id, "cancelled")
                except Exception:
                    pass
                # task.cancel() 后任务已处于取消状态，此处 await 可能再抛
                # CancelledError 并跳过 finally 的清理逻辑（防重标记残留），包 try 保护。
                try:
                    await queue.put({"type": "cancelled", "work_id": work_id})
                except asyncio.CancelledError:
                    pass
                raise  # 重新抛出，让 asyncio 正确标记任务为 cancelled
            except Exception as e:
                logger.exception("蒸馏执行异常 (work_id=%d)", work_id)
                try:
                    get_store().update_work_status(work_id, "failed")
                except Exception:
                    pass
                try:
                    await queue.put({"type": "error", "error": str(e)})
                except asyncio.CancelledError:
                    pass
            finally:
                # 取消标记必须最先清除（同步操作）：若任务被 cancel 后 finally 中
                # 的 await 再抛 CancelledError，最后的 discard 永远不会执行，
                # 残留标记会毒害下一次蒸馏——引擎每轮检查 is_cancelled 直接判取消，
                # 表现为"换模型/重新点蒸馏后界面不动"。清完再释放槽位。
                _CANCELLED_WORKS.discard(work_id)
                # 任务结束（成功/失败/取消/排队被取消）都要解除防重标记
                _RUNNING_DISTILLS.discard(work_id)
                _RUNNING_TASKS.pop(work_id, None)
                # 同步释放调度槽位：任务被 cancel 后此处 await 会再抛
                # CancelledError，async 版本导致槽位泄漏、后续任务永远排队。
                _release_distill_slot()
                if client is not None:
                    try:
                        await client.close()
                    except asyncio.CancelledError:
                        pass
                # 蒸馏可能产出/更新 skill JSON，重建索引（含向量层）保证可搜。
                # 必须放线程池执行：全量重建会对所有 skill 做 embedding（每批 10 个），
                # 同步执行会阻塞 asyncio event loop，导致其他蒸馏任务/请求全部冻结（页面"没增流"假死）。
                try:
                    await asyncio.to_thread(rebuild_skill_index)
                except Exception as e:
                    logger.warning("蒸馏后重建 skill 索引失败: %s", e)
                try:
                    await queue.put(None)  # 结束哨兵
                except asyncio.CancelledError:
                    pass

        task = asyncio.create_task(_run())
        _RUNNING_TASKS[work_id] = task
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                etype = event.get("type", "message")
                yield {"event": etype, "data": json.dumps(event, ensure_ascii=False)}
        except asyncio.CancelledError:
            raise
        finally:
            # 客户端断开（切页/刷新）不取消后台任务：蒸馏进度已持久化到 DB，
            # 任务继续跑完，用户切回页面可通过 /status 看到实时进度。
            # 不在 finally 中 await task：SSE 断连时生成器被取消，await task
            # 可能再次触发 CancelledError 并杀死后台任务（Python 3.11 行为）。
            # _RUNNING_TASKS 持有 task 强引用，不会被 GC；任务自己在 finally
            # 中更新 DB 状态 + 清理 _RUNNING_TASKS。
            if not task.done():
                logger.info("SSE 断连，后台蒸馏任务继续运行 (work_id=%d)", work_id)

    # ping=15：单轮 LLM 调用可达数分钟，期间无字节会被代理/浏览器掐断
    return EventSourceResponse(event_gen(), ping=15)


@router.get("/status/{work_id}")
def distill_status(work_id: int):
    """获取蒸馏进度。"""
    store = get_store()
    if not store.get_work(work_id):
        raise HTTPException(404, f"作品不存在: {work_id}")
    return store.progress(work_id)


@router.post("/works/{work_id}/cancel")
def cancel_distill(work_id: int):
    """取消正在进行的蒸馏：置取消标记，蒸馏循环在下一个片段/轮次边界优雅停止。

    已完成的片段/轮次产物保留；work 状态置为 cancelled（前端可显示"已中断"）。
    连接断开（切页）不触发取消——只有显式调用本端点才中断。
    若任务正在 AI 调用中（可能最长等 35 分钟超时），直接 cancel 其 asyncio.Task
    立即中断，避免任务占着并发槽位不放、后续任务排队饿死。
    """
    store = get_store()
    if not store.get_work(work_id):
        raise HTTPException(404, f"作品不存在: {work_id}")
    _CANCELLED_WORKS.add(work_id)
    # 立即中断正在执行的蒸馏任务（若在排队等待槽位，enqueue 的 is_cancelled 分支会自行退出）
    task = _RUNNING_TASKS.get(work_id)
    if task and not task.done():
        task.cancel()
    try:
        store.update_work_status(work_id, "cancelled")
    except Exception as e:
        logger.warning("取消蒸馏时更新 work 状态失败: %s", e)
    return {"cancelled": True, "work_id": work_id}


# ---- Skill 管理 ----


@router.get("/works/{work_id}/skills")
def list_work_skills(work_id: int):
    """获取该作品生成的所有 Skill。"""
    store = get_store()
    if not store.get_work(work_id):
        raise HTTPException(404, f"作品不存在: {work_id}")
    skills = [_skill_view(s) for s in store.list_skills(work_id)]
    return {"skills": skills}


@router.get("/skills")
def list_skills():
    """列出所有蒸馏 Skill + 拆书 Skill（供融合选择）。"""
    store = get_store()
    skills = [_skill_view(s) for s in store.list_skills()]

    # 也扫描 Skills 系统中的拆书 skill（source="book-to-skill"）
    skills_dir = load_config().project_data_dir / "skills"
    if skills_dir.exists():
        import json as _json
        for p in sorted(skills_dir.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    data = _json.load(f)
                if data.get("source") != "book-to-skill":
                    continue
                # 构造与蒸馏 skill 兼容的视图
                sections = data.get("sections", [])
                content_parts = []
                for sec in sections:
                    if isinstance(sec, dict) and sec.get("content"):
                        content_parts.append(sec["content"])
                skills.append({
                    "id": -1,  # 非 DB 记录，用 -1 标记
                    "work_id": -1,
                    "work_title": "拆书导入",
                    "chunk_index": -1,
                    "round_num": 0,
                    "name": data.get("name", ""),
                    "description": data.get("description", ""),
                    "content": "\n\n".join(content_parts) or data.get("overview", ""),
                    "tags": [],
                    "status": "active",
                    "source": "book-to-skill",
                    "file_name": data.get("name", ""),
                })
            except (json.JSONDecodeError, OSError):
                continue

    return {"skills": skills}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: int):
    """Skill 详情。"""
    skill = get_store().get_skill(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill 不存在: {skill_id}")
    return _skill_view(skill)


@router.put("/skills/{skill_id}")
def update_skill(skill_id: int, req: SkillUpdate):
    """更新 Skill（名称/描述/内容/标签/状态），同步更新 Skills 系统 JSON 文件。"""
    store = get_store()
    skill = store.get_skill(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill 不存在: {skill_id}")
    updates = req.model_dump(exclude_unset=True)
    # name 是 Skills 系统文件名，只允许字母数字下划线横线
    new_name = updates.get("name")
    if new_name:
        safe = "".join(c for c in new_name if c.isalnum() or c in ("-", "_"))
        if safe != new_name:
            raise HTTPException(400, f"无效的 skill 名称（仅允许字母数字-_）: {new_name}")
    store.update_skill(skill_id, **updates)
    updated = store.get_skill(skill_id)
    # 同步 Skills 系统文件：改名则移动文件，改内容/描述/状态则重写。
    # status 变更（active/archived）会影响文件中的 enabled 字段，
    # 归档(archived)的 skill 写入 enabled=False，注入侧会跳过它。
    if new_name and new_name != skill["name"]:
        _remove_skill_file(skill["name"])
    if updates.keys() & {"name", "description", "content", "tags", "status"}:
        view = _skill_view(updated)
        # 重写文件时保留原分类（rule/material，用户可手动改）；文件不存在时按名字推断
        category = "rule"
        try:
            from novel_agent.api.routes_skills import _skill_category
            _p = load_config().project_data_dir / "skills" / f"{view['name']}.json"
            if _p.exists():
                category = json.loads(_p.read_text(encoding="utf-8")).get("category") or category
            else:
                category = _skill_category(view["name"], "")
        except Exception:
            pass
        DistillationEngine(get_store())._write_skill_file(
            view["name"], view["name"], view["description"],
            view["content"], view["tags"], status=view.get("status", "active"),
            category=category,
        )
        # 增量更新索引（避免编辑单个 skill 触发全量 rebuild + 全量 embedding 的慢）
        try:
            from novel_agent.api.routes_skills import upsert_skill_index
            upsert_skill_index(view["name"])
        except Exception as e:
            logger.warning("skill 索引增量更新失败（降级全量重建）: %s", e)
            rebuild_skill_index()
    return {"updated": True, "skill": _skill_view(updated)}


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: int):
    """删除 Skill（同时删除 Skills 系统 JSON 文件）。

    索引只做增量移除（不触发全量重建）——删除一个 skill 无需重新 embedding
    上千条目的向量库，避免删除长时间转圈。
    """
    store = get_store()
    skill = store.get_skill(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill 不存在: {skill_id}")
    _remove_skill_file(skill["name"])
    store.delete_skill(skill_id)
    try:
        remove_skill_from_index(skill["name"])
    except Exception as e:
        logger.warning("skill 索引增量移除失败（降级全量重建）: %s", e)
        rebuild_skill_index()
    return {"deleted": True, "skill_id": skill_id}


# ---- 融合 ----


@router.post("/fuse")
async def fuse_skills(req: FuseRequest):
    """SSE 流式融合多个 Skill（蒸馏 DB skill + 拆书 skill 均可）。

    v2：融合 = LLM 提炼浓缩（非简单拼接）——把多个 Skill 交给模型提炼成一份
    精炼总纲，高权重来源优先保留；模型不可用时自动回退为按权重拼接。

    事件类型：
    - fuse_start {skill_count}
    - fuse_batch_start {batch, total}
    - fuse_batch_done {batch, total}
    - fuse_done {fusion: {...refined, skill_file, deleted_count}}
    - error {error}
    """
    if not req.name.strip():
        raise HTTPException(400, "融合方案名称不能为空")
    if not req.skill_ids and not req.skill_files:
        raise HTTPException(400, "至少选择一个 Skill")

    cfg = load_config()
    store = get_store()

    # 收集拆书 skill（从文件加载，传给引擎的 extra_skills）
    file_skills = []
    skills_dir = cfg.project_data_dir / "skills"
    for fname in req.skill_files:
        path = skills_dir / f"{fname}.json"
        if not path.exists():
            raise HTTPException(404, f"拆书 Skill 文件不存在: {fname}")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            sections = data.get("sections", [])
            content_parts = [s["content"] for s in sections if isinstance(s, dict) and s.get("content")]
            file_skills.append({
                "name": data.get("name", fname),
                "description": data.get("description", ""),
                "content": "\n\n".join(content_parts) or data.get("overview", ""),
                "work_title": "拆书导入",
                "chunk_index": -1,
                "round_num": 0,
                "tags": [],
                "source": "book-to-skill",
            })
        except (json.JSONDecodeError, OSError) as e:
            raise HTTPException(500, f"读取拆书 Skill 失败: {e}")

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        async def _run():
            client = None
            result = None
            try:
                engine = _engine()
                await on_event({"type": "fuse_start", "skill_count": len(file_skills) + len(req.skill_ids)})
                # 蒸馏是分析型任务：client 构造失败（如非法模型）时回退为无 client 拼接
                try:
                    client = LLMClient(_resolve_llm_config(cfg, req))
                    result = await engine.fuse_skills(
                        req.skill_ids, req.weights, req.name.strip(), req.description,
                        client=client, extra_skills=file_skills, on_event=on_event,
                    )
                except Exception as e:
                    logger.warning("融合提炼 client 构造失败，回退为拼接: %s", e)
                    result = await engine.fuse_skills(
                        req.skill_ids, req.weights, req.name.strip(), req.description,
                        client=None, extra_skills=file_skills, on_event=on_event,
                    )
            except Exception as e:
                logger.exception("融合执行异常")
                await queue.put({"type": "error", "error": str(e)})
                return
            finally:
                if client is not None:
                    await client.close()
                await queue.put(None)  # 结束哨兵（正常/异常路径都保证 SSE 流结束）

            # 融合成功后按需批量删除原 Skill（DB 记录 + skills/*.json 文件）
            deleted_count = 0
            if req.delete_originals:
                for sid in req.skill_ids:
                    skill = store.get_skill(sid)
                    if not skill:
                        continue
                    _remove_skill_file(skill["name"])  # 删 skills/{name}.json
                    if store.delete_skill(sid):
                        deleted_count += 1
                for fname in req.skill_files:
                    _remove_skill_file(fname)
                    deleted_count += 1
                logger.info("融合后删除原 Skill %d 个（fusion=%s）", deleted_count, req.name)

            try:
                rebuild_skill_index()
            except Exception as e:
                logger.warning("融合后重建 skill 索引失败: %s", e)
            # 融合完成：更新方案状态 + 产物文件名（前端据此区分"融合中/已完成"）
            try:
                store.update_fusion_status(result["fusion_id"], "done", result["skill_file"])
            except Exception as e:
                logger.warning("更新融合方案状态失败: %s", e)
            fusion = store.get_fusion(result["fusion_id"])
            view = _fusion_view(fusion)
            view["refined"] = result["refined"]
            view["skill_file"] = result["skill_file"]
            view["deleted_count"] = deleted_count
            logger.info("Skill 融合完成: fusion_id=%d name=%s refined=%s",
                        result["fusion_id"], req.name, result["refined"])
            await queue.put({"type": "fuse_done", "fusion": view})

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                etype = event.get("type", "message")
                yield {"event": etype, "data": json.dumps(event, ensure_ascii=False)}
        except asyncio.CancelledError:
            raise
        finally:
            # 客户端断开（切页）不取消融合：融合是后台任务，方案记录已持久化，
            # 产物生成后写入 skills 目录，切回页面通过 /fusions 仍可见。
            if not task.done():
                await task

    return EventSourceResponse(event_gen(), ping=15)


@router.get("/fusions")
def list_fusions():
    """列出所有融合方案。"""
    fusions = [_fusion_view(f) for f in get_store().list_fusions()]
    return {"fusions": fusions}


@router.get("/fusions/{fusion_id}/skill")
def get_fusion_skill(fusion_id: int):
    """读取融合产物的 Skill 文件内容（供融合方案列表"查看"用）。"""
    fusion = get_store().get_fusion(fusion_id)
    if not fusion:
        raise HTTPException(404, f"融合方案不存在: {fusion_id}")
    skills_dir = load_config().project_data_dir / "skills"
    base = f"distill_fusion_{fusion_id}"
    path = skills_dir / f"{base}.json"
    if not path.exists():
        cands = sorted(skills_dir.glob(f"{base}_*.json"))
        path = cands[0] if cands else None
    if not path or not path.exists():
        # 融合产物文件可能被手动清理：降级为提示，不让前端报错
        return {
            "name": base,
            "description": "",
            "tags": [],
            "distilled": False,
            "content": f"（融合产物文件已不存在：skills/{base}.json 可能已被删除，无法查看正文）",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(500, f"读取融合 Skill 失败: {e}")
    # 拼装可读的 markdown 正文（sections 里存的是提炼/拼接后的内容）
    content_parts = [s.get("content", "") for s in data.get("sections", []) if isinstance(s, dict)]
    return {
        "name": data.get("name", base),
        "description": data.get("description", ""),
        "tags": data.get("tags", []),
        "distilled": bool(data.get("distilled")),
        "content": "\n\n".join(p for p in content_parts if p) or "",
    }


@router.delete("/fusions/{fusion_id}")
def delete_fusion(fusion_id: int):
    """删除融合方案（DB 记录 + skills 目录下残留的产物文件）。"""
    store = get_store()
    if not store.get_fusion(fusion_id):
        raise HTTPException(404, f"融合方案不存在: {fusion_id}")
    # 清理产物文件（含冲突时的 _uuid 后缀变体）
    skills_dir = load_config().project_data_dir / "skills"
    removed = 0
    for path in list(skills_dir.glob(f"distill_fusion_{fusion_id}*.json")):
        try:
            path.unlink()
            removed += 1
        except OSError as e:
            logger.warning("删除融合产物文件失败 %s: %s", path, e)
    store.delete_fusion(fusion_id)
    try:
        rebuild_skill_index()
    except Exception as e:
        logger.warning("删除融合方案后重建 skill 索引失败: %s", e)
    logger.info("融合方案已删除: fusion_id=%d（清理文件 %d 个）", fusion_id, removed)
    return {"deleted": True, "fusion_id": fusion_id, "removed_files": removed}


# ---- 效果对比 ----


@router.post("/compare")
async def compare(req: CompareRequest):
    """效果对比：同一 prompt 下，"无章纲直出" vs "加载蒸馏 Skill 直出"。"""
    if not req.prompt.strip():
        raise HTTPException(400, "prompt 不能为空")
    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm(req.agent_role))
    try:
        result = await _engine().compare_generate(
            req.prompt, client, skill_id=req.skill_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("效果对比生成异常")
        raise HTTPException(500, f"生成失败: {e}")
    finally:
        if client is not None:
            await client.close()
    skill = result.get("skill")
    return {
        "baseline": result["baseline"],
        "with_skill": result["with_skill"],
        "skill": _skill_view(skill) if skill else None,
    }


# ---- 人物级蒸馏 ----


class CharacterDistillRequest(BaseModel):
    """角色蒸馏请求。"""
    work_id: int
    character_name: str
    agent_role: str = "auditor"
    # 模型设置（可选）：不填则跟随 config.yaml 的 agent_role 配置
    provider: str | None = None
    model: str | None = None
    custom_base_url: str | None = None
    custom_api_key: str | None = None
    custom_model: str | None = None


@router.post("/distill-character")
async def distill_character(req: CharacterDistillRequest):
    """蒸馏单个角色的对话风格（SSE 流式）。

    从作品中提取该角色的出场段落，让 LLM 分析说话风格，
    生成 character-style skill 供对话写作时注入。
    """
    store = get_store()
    if not store.get_work(req.work_id):
        raise HTTPException(404, f"作品不存在: {req.work_id}")
    if not req.character_name.strip():
        raise HTTPException(400, "角色名不能为空")

    cfg = load_config()

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            await queue.put(event)

        async def _run():
            client = None
            try:
                client = LLMClient(_resolve_llm_config(cfg, req))
                engine = DistillationEngine(get_store())
                await engine.distill_character(
                    req.work_id, req.character_name.strip(), client,
                    on_event=on_event,
                )
            except asyncio.CancelledError:
                logger.warning("角色蒸馏任务被取消 (work_id=%d)", req.work_id)
                raise
            except Exception as e:
                logger.exception("角色蒸馏异常 (work_id=%d char=%s)",
                                 req.work_id, req.character_name)
                await queue.put({"type": "error", "error": str(e)})
            finally:
                _RUNNING_TASKS.pop(req.work_id, None)
                if client is not None:
                    await client.close()
                # 角色蒸馏可能产出 skill JSON，重建索引保证可搜。
                # 与整书蒸馏一致：放线程池执行，避免同步 embedding 阻塞 asyncio event loop。
                try:
                    await asyncio.to_thread(rebuild_skill_index)
                except Exception as e:
                    logger.warning("角色蒸馏后重建 skill 索引失败: %s", e)
                await queue.put(None)

        task = asyncio.create_task(_run())
        _RUNNING_TASKS[req.work_id] = task
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                etype = event.get("type", "message")
                yield {"event": etype, "data": json.dumps(event, ensure_ascii=False)}
        except asyncio.CancelledError:
            raise
        finally:
            # 客户端断开不取消后台任务（切页后任务继续跑完，产出不丢）
            # 与整书蒸馏一致：不 await task，避免 SSE 断连时杀死后台任务
            if not task.done():
                logger.info("SSE 断连，角色蒸馏任务继续运行 (work_id=%d)", req.work_id)

    return EventSourceResponse(event_gen(), ping=15)


# ---- 诊断 ----


@router.get("/debug/state")
def debug_state():
    """诊断端点：返回蒸馏模块内部状态（用于排查并发/卡死问题）。"""
    return {
        "running_distills": list(_RUNNING_DISTILLS),
        "cancelled_works": list(_CANCELLED_WORKS),
        "in_schedule": _distill_in_schedule,
        "max_concurrent": _MAX_CONCURRENT_DISTILL,
        "running_tasks": {
            str(k): {"done": v.done(), "cancelled": v.cancelled()}
            for k, v in _RUNNING_TASKS.items()
        },
    }


# ---- 盲测评估 ----


class BlindEvalRequest(BaseModel):
    """盲测评估请求。"""
    skill_id: int
    prompt: str
    agent_role: str = "writer"


@router.post("/blind-eval")
async def blind_evaluate(req: BlindEvalRequest):
    """对蒸馏 Skill 做盲测评估。

    1. 用 skill 和不用 skill 分别生成一段文字
    2. 随机打乱顺序让 LLM 盲评
    3. 返回评估结果（哪段更接近原作风格、评分、理由）
    """
    if not req.prompt.strip():
        raise HTTPException(400, "prompt 不能为空")
    cfg = load_config()
    client = LLMClient(cfg.get_agent_llm(req.agent_role))
    try:
        result = await _engine().blind_evaluate(
            skill_id=req.skill_id,
            prompt=req.prompt.strip(),
            client=client,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.exception("盲测评估异常")
        raise HTTPException(500, f"评估失败: {e}")
    finally:
        if client is not None:
            await client.close()
    return {
        "baseline": result["baseline"],
        "with_style": result["with_style"],
        "judgment": result["judgment"],
        "skill": _skill_view(result.get("skill")),
    }
