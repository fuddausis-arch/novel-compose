"""FastAPI app 工厂 + 静态文件挂载。"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response, JSONResponse


class SPAStaticFiles(StaticFiles):
    """SPA 静态文件：未命中的路径回退 index.html（支持前端路由深链接/刷新）。
    但 /api/* 路径不回退，返回 JSON 404。"""

    async def get_response(self, path: str, scope) -> Response:
        # /api/ 路径直接返回 JSON 404，不走 SPA 回退
        full_path = scope.get("path", "")
        if full_path.startswith("/api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": f"Not Found: {full_path}"},
            )
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404:
                return await super().get_response("index.html", scope)
            raise

# 全局限流器单例：路由文件通过 import 复用同一实例，使 app.state.limiter
# 与装饰器绑定的对象一致，测试中可用 app.state.limiter.enabled = False 整体禁用。
limiter = Limiter(key_func=get_remote_address)


def create_app(project_data_dir: Path | None = None) -> FastAPI:
    print("[create_app] 开始初始化 FastAPI 应用", flush=True)
    app = FastAPI(title="多 Agent 小说生成 API", version="0.4.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # CORS：开发本机 + 手机 App 壳（Capacitor WebView）来源；
    # 部署后可用环境变量 NOVEL_ALLOW_ORIGINS 追加远程前端域名（逗号分隔）
    _extra_origins = [o.strip() for o in os.environ.get("NOVEL_ALLOW_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:8000", "http://127.0.0.1:8000",
            # 手机 App 壳来源（Capacitor WebView 加载本地打包产物时）
            "capacitor://localhost",
            "https://localhost",
            *_extra_origins,
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 确保项目数据目录存在（打包模式默认 %APPDATA%/NovelCompose/project_data）
    if project_data_dir:
        project_data_dir.mkdir(parents=True, exist_ok=True)
        app.state.project_data_dir = project_data_dir
        print(f"[create_app] 项目数据目录（参数注入）: {project_data_dir}", flush=True)
    else:
        try:
            from novel_agent.config import load_config
            cfg = load_config()
            cfg.project_data_dir.mkdir(parents=True, exist_ok=True)
            app.state.project_data_dir = cfg.project_data_dir
            print(f"[create_app] 项目数据目录（config 加载）: {cfg.project_data_dir}", flush=True)
        except Exception as e:
            print(f"[create_app] 警告：无法创建项目数据目录: {e}", file=sys.stderr, flush=True)
    # 初始化圆桌会议管理器（从 SQLite 恢复历史会话）
    try:
        from novel_agent.roundtable.runner import RoundtableManager
        app.state.roundtable_manager = RoundtableManager()
        app.state.roundtable_manager.load_sessions()
        print(f"[create_app] 圆桌会议管理器已初始化，已加载 {len(app.state.roundtable_manager.sessions)} 个会话", flush=True)
    except Exception as e:
        print(f"[create_app] 警告：圆桌会议管理器初始化失败: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
    # 注册路由：逐个 import，单个失败不影响其他路由，并打印日志便于诊断
    # 每项格式: (模块名, 前缀) 或 (模块名, 前缀, 路由器属性名)
    _router_specs = [
        ("routes_projects", "/api/projects"),
        ("routes_planning", "/api/planning"),
        ("routes_chapters", "/api/chapters"),
        ("routes_bible", "/api/bible"),
        ("routes_generation", "/api/generation"),
        ("routes_config", "/api/config"),
        ("routes_telemetry", "/api/telemetry"),
        ("routes_chat", "/api/chat"),
        ("routes_references", "/api/bible"),
        ("routes_bible", "/api/references", "references_router"),
        ("routes_health", "/api"),
        # Phase 6: 配置管理后端 CRUD 路由
        ("routes_skills", "/api/skills"),
        ("routes_rules", "/api/rules"),
        ("routes_prompts", "/api/prompts"),
        ("routes_agents", "/api/agents"),
        ("routes_models", "/api/models"),
        ("routes_preset_phrases", "/api/preset-phrases"),
        ("routes_user_injection", "/api/user-injection"),
        ("routes_plugins", "/api/plugins"),
        # Phase 6.28: 工作区管理后端（会话树/附件/文件管理）
        ("routes_workspace", "/api/workspace"),
        # Phase 6.17: 工作流引擎（7 条 bishu-novel 移植工作流）
        ("routes_workflows", "/api/workflows"),
        # Cron 定时任务 + 压缩监控
        ("routes_cron", "/api/cron"),
        ("routes_compression", "/api/compression"),
        # 去除AI味蒸馏法：作品导入/多轮蒸馏/Skill生成/融合/效果对比
        ("routes_distillation", "/api/distillation"),
        # 小说内容图谱：人物/势力/伏笔/章节/地图 + 地点 CRUD
        ("routes_graphs", "/api/bible"),
        # 自定义工作流：用户可视化编辑器创建的工作流
        ("routes_custom_workflows", "/api/bible"),
        # 圆桌会议：多 Agent 讨论引擎（从 DeterminFlow 移植，SQLite + LLMClient + SSE）
        ("routes_roundtable", "/api/roundtable"),
        # 故事时间线：聚合圣经表输出多泳道时间线
        ("routes_timeline", "/api/timeline"),
        # 实体卡片：为卡片抽屉系统提供实体完整详情
        ("routes_entity_cards", ""),
        # 百科卡：五类实体摘要列表 + 出场场景索引
        ("routes_encyclopedia", ""),
    ]
    from novel_agent.api import (
        routes_projects, routes_planning, routes_chapters, routes_bible,
        routes_generation, routes_config, routes_telemetry, routes_chat, routes_references,
        routes_health,
        routes_skills, routes_rules, routes_prompts, routes_agents,
        routes_models, routes_preset_phrases, routes_user_injection, routes_plugins,
        routes_workspace, routes_workflows,
        routes_cron, routes_compression,
        routes_distillation,
        routes_graphs, routes_custom_workflows,
        routes_timeline,
        routes_entity_cards,
        routes_encyclopedia,
    )
    # 圆桌会议路由在 novel_agent.roundtable 包内（非 novel_agent.api），单独导入
    from novel_agent.roundtable import routes as routes_roundtable
    _router_modules = {
        "routes_projects": routes_projects,
        "routes_planning": routes_planning,
        "routes_chapters": routes_chapters,
        "routes_bible": routes_bible,
        "routes_generation": routes_generation,
        "routes_config": routes_config,
        "routes_telemetry": routes_telemetry,
        "routes_chat": routes_chat,
        "routes_references": routes_references,
        "routes_health": routes_health,
        "routes_skills": routes_skills,
        "routes_rules": routes_rules,
        "routes_prompts": routes_prompts,
        "routes_agents": routes_agents,
        "routes_models": routes_models,
        "routes_preset_phrases": routes_preset_phrases,
        "routes_user_injection": routes_user_injection,
        "routes_plugins": routes_plugins,
        "routes_workspace": routes_workspace,
        "routes_workflows": routes_workflows,
        "routes_cron": routes_cron,
        "routes_compression": routes_compression,
        "routes_distillation": routes_distillation,
        "routes_graphs": routes_graphs,
        "routes_custom_workflows": routes_custom_workflows,
        "routes_roundtable": routes_roundtable,
        "routes_timeline": routes_timeline,
        "routes_entity_cards": routes_entity_cards,
        "routes_encyclopedia": routes_encyclopedia,
    }
    for spec in _router_specs:
        name = spec[0]
        prefix = spec[1]
        attr = spec[2] if len(spec) > 2 else "router"
        try:
            mod = _router_modules[name]
            app.include_router(getattr(mod, attr), prefix=prefix, tags=[name])
            print(f"[create_app] 路由已注册: {name}.{attr} -> {prefix}", flush=True)
        except Exception as e:
            print(f"[create_app] 路由注册失败 {name}.{attr}: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
    # 静态前端（生产构建后的 dist 目录）
    dist_dir = None
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式：dist 在 exe 同级
        dist_dir = Path(sys.executable).parent / "frontend" / "dist"
    else:
        dist_dir = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", SPAStaticFiles(directory=str(dist_dir), html=True), name="frontend")
        print(f"[create_app] 静态前端已挂载: {dist_dir}", flush=True)
    else:
        print(f"[create_app] 警告：前端 dist 不存在: {dist_dir}", file=sys.stderr, flush=True)
    print("[create_app] 应用初始化完成", flush=True)
    return app


# 模块级 app 实例：供 uvicorn novel_agent.api.app:app 直接启动
app = create_app()
