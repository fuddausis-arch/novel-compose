"""FastAPI app 工厂 + 静态文件挂载。"""
from __future__ import annotations
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# 全局限流器单例：路由文件通过 import 复用同一实例，使 app.state.limiter
# 与装饰器绑定的对象一致，测试中可用 app.state.limiter.enabled = False 整体禁用。
limiter = Limiter(key_func=get_remote_address)


def create_app(project_data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="多 Agent 小说生成 API", version="0.4.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if project_data_dir:
        project_data_dir.mkdir(parents=True, exist_ok=True)
        app.state.project_data_dir = project_data_dir
    # 注册路由
    from novel_agent.api import routes_projects, routes_planning, routes_chapters, routes_bible, routes_generation, routes_config, routes_telemetry, routes_chat
    app.include_router(routes_projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(routes_planning.router, prefix="/api/planning", tags=["planning"])
    app.include_router(routes_chapters.router, prefix="/api/chapters", tags=["chapters"])
    app.include_router(routes_bible.router, prefix="/api/bible", tags=["bible"])
    app.include_router(routes_generation.router, prefix="/api/generation", tags=["generation"])
    app.include_router(routes_config.router, prefix="/api/config", tags=["config"])
    app.include_router(routes_telemetry.router, prefix="/api/telemetry", tags=["telemetry"])
    app.include_router(routes_chat.router, prefix="/api/chat", tags=["chat"])
    # 静态前端（生产构建后的 dist 目录）
    dist_dir = None
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式：dist 在 exe 同级
        dist_dir = Path(sys.executable).parent / "frontend" / "dist"
    else:
        dist_dir = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
    return app
