"""FastAPI app 工厂 + 静态文件挂载。"""
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


def create_app(project_data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="多 Agent 小说生成 API", version="0.4.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])
    if project_data_dir:
        project_data_dir.mkdir(parents=True, exist_ok=True)
        app.state.project_data_dir = project_data_dir
    # 注册路由
    from novel_agent.api import routes_projects, routes_planning, routes_chapters, routes_bible
    app.include_router(routes_projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(routes_planning.router, prefix="/api/planning", tags=["planning"])
    app.include_router(routes_chapters.router, prefix="/api/chapters", tags=["chapters"])
    app.include_router(routes_bible.router, prefix="/api/bible", tags=["bible"])
    # 静态前端
    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    return app
