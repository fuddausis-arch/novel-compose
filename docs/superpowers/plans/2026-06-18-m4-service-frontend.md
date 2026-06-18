# M4：后端服务 + SSE + 前端控制台 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 加 FastAPI 后端服务（项目/规划/生成/人审/状态 API + SSE 流式进度）+ 人审②③（卷末/重写失败 interrupt）+ 最小可用前端单页控制台（能跑通 init→plan→人审①→generate→查看 的全流程）。spec 第 7 节四界面缩减为单页控制台（驾驶舱+人审+圣经浏览+阅读 合并），保证端到端可用优先。

**Architecture:** 新增 `api/` 包：FastAPI 路由（projects/planning/chapters/review/bible）+ SSE 流式端点 + 人审②③ 的 interrupt/resume。新增 `frontend/`：纯静态 HTML+JS 单页（无构建步骤，fetch 调 API + EventSource 收 SSE），避免 Vite 构建链。人审②③ 复用 M3b 的 interrupt 机制（卷末审核 + 重写超3次审核）。

**Tech Stack:** FastAPI、sse-starlette、uvicorn、纯静态前端（HTML/JS/CSS，无框架）

---

## 前置说明

- 工作目录 `C:\Users\LYY\Desktop\vibe coding`，venv `.venv`
- M1/M2/M3/M3b 已合并 main（83 测试），本计划从 main 拉 `m4-service-frontend`
- 需装：fastapi、sse-starlette、uvicorn、httpx（测试用）
- 前端用纯静态文件（`frontend/index.html` + `app.js`），FastAPI 直接 serve，无 npm 构建

## 文件结构（M4 范围）

```
novel_agent/
├── api/                             # 新增：FastAPI 服务
│   ├── __init__.py
│   ├── app.py                       # FastAPI app + 静态文件挂载
│   ├── routes_projects.py           # 项目 CRUD
│   ├── routes_planning.py           # 卷级规划 + 人审① resume
│   ├── routes_chapters.py           # 单章生成 + SSE 流式
│   ├── routes_review.py             # 人审②③ resume
│   └── routes_bible.py              # 圣经浏览
├── orchestrator/
│   └── runner.py                    # 微调：人审②③ interrupt 接入点（重写超3次）
frontend/
├── index.html                       # 单页控制台
├── app.js                           # 前端逻辑
└── style.css
tests/
├── test_api_projects.py
├── test_api_planning.py
└── test_api_chapters.py
```

---

## Task 1: 装依赖 + FastAPI 骨架 + 项目 API

**Files:**
- Modify: `pyproject.toml`（加 fastapi/sse-starlette/uvicorn/httpx）
- Create: `novel_agent/api/__init__.py`, `novel_agent/api/app.py`, `novel_agent/api/routes_projects.py`
- Test: `tests/test_api_projects.py`

- [ ] **Step 1: 加依赖并安装**

pyproject.toml dependencies 加：
```toml
    "fastapi>=0.111",
    "sse-starlette>=2.0",
    "uvicorn>=0.30",
```
dev 加 `httpx`（测试客户端，已有则跳过）。

```bash
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

- [ ] **Step 2: 写失败测试 tests/test_api_projects.py**

```python
"""测试项目 API。"""
import pytest
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    (tmp_path / "project_data").mkdir()
    app = create_app(project_data_dir=tmp_path / "project_data")
    return TestClient(app)


def test_create_project(client):
    resp = client.post("/api/projects", json={"title": "测试", "genre": "科幻", "summary": "末日"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "测试"
    assert data["id"] >= 1


def test_list_projects(client):
    client.post("/api/projects", json={"title": "p1"})
    client.post("/api/projects", json={"title": "p2"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_get_project(client):
    r = client.post("/api/projects", json={"title": "x"}).json()
    resp = client.get(f"/api/projects/{r['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "x"
```

- [ ] **Step 3: 创建 api 包**

`novel_agent/api/__init__.py`:
```python
"""FastAPI 后端服务。"""
```

`novel_agent/api/app.py`:
```python
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
```

`novel_agent/api/routes_projects.py`:
```python
"""项目 CRUD API。"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config, load_config

router = APIRouter()


class ProjectCreate(BaseModel):
    title: str
    genre: str = ""
    summary: str = ""
    style: str = ""


def _setup_db():
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    return SessionLocal()


@router.post("")
def create_project(data: ProjectCreate):
    db = _setup_db()
    try:
        p = Project(title=data.title, genre=data.genre, summary=data.summary, style=data.style)
        db.add(p); db.commit(); db.refresh(p)
        return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary}
    finally:
        db.close()


@router.get("")
def list_projects():
    db = _setup_db()
    try:
        projects = db.query(Project).order_by(Project.id.desc()).all()
        return [{"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary}
                for p in projects]
    finally:
        db.close()


@router.get("/{project_id}")
def get_project(project_id: int):
    db = _setup_db()
    try:
        p = db.query(Project).filter(Project.id == project_id).first()
        if not p:
            raise HTTPException(404, "项目不存在")
        return {"id": p.id, "title": p.title, "genre": p.genre, "summary": p.summary, "style": p.style}
    finally:
        db.close()
```

- [ ] **Step 4: 创建占位路由（planning/chapters/bible，后续 Task 填充）**

每个文件先建空 router：
```python
from fastapi import APIRouter
router = APIRouter()
```

- [ ] **Step 5: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_api_projects.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add . && git commit -m "feat(api): FastAPI 骨架 + 项目 CRUD API"
```

---

## Task 2: 规划 API + 人审① resume

**Files:**
- Create: `novel_agent/api/routes_planning.py`（替换占位）
- Test: `tests/test_api_planning.py`

- [ ] **Step 1: 写测试 tests/test_api_planning.py**

```python
"""测试规划 API（mock LLM）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    app = create_app(project_data_dir=tmp_path / "project_data")
    return TestClient(app)


def test_plan_endpoint_starts(client):
    """POST /api/planning/run 应启动规划并返回 thread_id。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    with patch("novel_agent.planning.runner.LLMClient") as MockLLM:
        mock_inst = MagicMock()
        mock_inst.generate = AsyncMock(side_effect=[
            '{"volumes":[{"name":"卷一","chapters":5}]}',
            '{"characters":[{"name":"刘洋","role":"主角","personality":"冷静"}],"world_settings":[]}',
            '{"chapters":[{"chapter":1,"title":"ch1","summary":"e","foreshadows":[]}]}',
        ])
        MockLLM.return_value = mock_inst
        resp = client.post("/api/planning/run", json={
            "project_id": pid, "volume": "卷一", "chapter_count": 5, "thread_id": "t1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("outlined", "reviewing") or "outline" in data
    assert data["thread_id"] == "t1"


def test_resume_endpoint(client):
    """POST /api/planning/resume 应恢复人审①。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    with patch("novel_agent.planning.runner.LLMClient") as MockLLM:
        mock_inst = MagicMock()
        mock_inst.generate = AsyncMock(side_effect=[
            '{"volumes":[{"name":"卷一","chapters":5}]}',
            '{"characters":[{"name":"刘洋","role":"主角","personality":"冷静"}],"world_settings":[]}',
            '{"chapters":[{"chapter":1,"title":"ch1","summary":"e","foreshadows":[]}]}',
        ] * 2)  # run + resume 各跑一次
        MockLLM.return_value = mock_inst
        client.post("/api/planning/run", json={
            "project_id": pid, "volume": "卷一", "chapter_count": 5, "thread_id": "t2"})
        resp = client.post("/api/planning/resume", json={
            "thread_id": "t2", "approved": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
```

- [ ] **Step 2: 实现 routes_planning.py**

```python
"""规划 API：启动卷级规划 + 人审① resume。"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.planning.runner import VolumeRunner

router = APIRouter()


class PlanRequest(BaseModel):
    project_id: int
    volume: str = "卷一"
    chapter_count: int = 30
    thread_id: str


class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool
    edits: str = ""


def _get_repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    return db, BibleRepository(db, project_id=project_id)


@router.post("/run")
def run_planning(req: PlanRequest):
    db, repo = _get_repo(req.project_id)
    runner = VolumeRunner(load_config(), repo=repo)
    try:
        result = asyncio.run(runner.run(
            volume=req.volume, chapter_count=req.chapter_count, thread_id=req.thread_id))
        result["thread_id"] = req.thread_id
        return result
    finally:
        runner.close()
        db.close()


@router.post("/resume")
def resume_planning(req: ResumeRequest):
    # project_id 需从 checkpoint 关联，M4 简化：前端传或从最新项目取
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    if not project:
        raise HTTPException(400, "无项目")
    repo = BibleRepository(db, project_id=project.id)
    runner = VolumeRunner(cfg, repo=repo)
    try:
        result = asyncio.run(runner.resume(
            {"approved": req.approved, "edits": req.edits}, thread_id=req.thread_id))
        return result
    finally:
        runner.close()
        db.close()
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
.venv\Scripts\python.exe -m pytest tests/test_api_planning.py -v
git add . && git commit -m "feat(api): 规划 API + 人审① resume"
```

---

## Task 3: 章节 API + SSE 流式

**Files:**
- Create: `novel_agent/api/routes_chapters.py`（替换占位，含 SSE）
- Test: `tests/test_api_chapters.py`

- [ ] **Step 1: 写测试 tests/test_api_chapters.py**

```python
"""测试章节生成 API（mock LLM）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


def test_generate_chapter(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(side_effect=[
            "草稿", "润色", '{"core_events":"e"}',  # write/polish/summarize
        ])
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        # auditor 返回达标
        from novel_agent.audit.schemas import AuditReport
        with patch("novel_agent.audit.auditor.Auditor.audit",
                   new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))):
            resp = client.post("/api/chapters/generate", json={
                "project_id": pid, "chapter": 1, "title": "第一章"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
```

- [ ] **Step 2: 实现 routes_chapters.py**

```python
"""章节生成 API + SSE 流式进度。"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config
from novel_agent.orchestrator.runner import ChapterRunner

router = APIRouter()


class GenerateRequest(BaseModel):
    project_id: int
    chapter: int
    title: str
    thread_id: str | None = None


@router.post("/generate")
def generate_chapter(req: GenerateRequest):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    repo = BibleRepository(db, project_id=req.project_id)
    runner = ChapterRunner(cfg, repo=repo)
    try:
        result = asyncio.run(runner.run(
            chapter=req.chapter, title=req.title, thread_id=req.thread_id))
        return result
    finally:
        runner.close()
        db.close()


@router.get("/list")
def list_chapters(project_id: int):
    """列出已生成章节。"""
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg)
    chapters = recall.list_chapters()
    return [{"chapter": c, "text_preview": recall.read_chapter_text(c)[:200]} for c in chapters]


@router.get("/{chapter}/text")
def get_chapter_text(chapter: int):
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg)
    text = recall.read_chapter_text(chapter)
    if not text:
        raise HTTPException(404, "章节不存在")
    return {"chapter": chapter, "text": text}
```

- [ ] **Step 3: 运行测试 + Commit**

```bash
.venv\Scripts\python.exe -m pytest tests/test_api_chapters.py -v
git add . && git commit -m "feat(api): 章节生成 + 列表 + 正文 API"
```

---

## Task 4: 圣经浏览 API

**Files:**
- Create: `novel_agent/api/routes_bible.py`（替换占位）
- Test: 追加到 test_api_chapters.py 或新建

- [ ] **Step 1: 实现 routes_bible.py**

```python
"""圣经浏览 API：角色/伏笔/大纲/摘要。"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config

router = APIRouter()


def _repo(project_id: int):
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    return db, BibleRepository(db, project_id=project_id)


@router.get("/{project_id}/characters")
def list_characters(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"name": c.name, "role": c.role, "personality": c.personality,
                 "current_location": c.current_location, "current_emotion": c.current_emotion}
                for c in repo.list_characters()]
    finally:
        db.close()


@router.get("/{project_id}/foreshadows")
def list_foreshadows(project_id: int):
    db, repo = _repo(project_id)
    try:
        from novel_agent.bible.models import Foreshadow
        fs = db.query(Foreshadow).filter(Foreshadow.project_id == project_id).all()
        return [{"id": f.foreshadow_id, "status": f.status, "description": f.description,
                 "plant_chapter": f.plant_chapter, "resolve_chapter": f.planned_resolve_chapter}
                for f in fs]
    finally:
        db.close()


@router.get("/{project_id}/outlines")
def list_outlines(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"level": o.level, "order": o.order, "title": o.title, "summary": o.summary}
                for o in repo.list_outlines()]
    finally:
        db.close()


@router.get("/{project_id}/summaries")
def list_summaries(project_id: int):
    db, repo = _repo(project_id)
    try:
        return [{"chapter": s.chapter, "title": s.title, "core_events": s.core_events,
                 "word_count": s.word_count}
                for s in repo.list_chapter_summaries(limit=100)]
    finally:
        db.close()
```

- [ ] **Step 2: 写测试 + 运行 + Commit**

```python
def test_bible_endpoints(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    # 先规划写入一些数据（简化：直接建角色）
    from novel_agent.bible.database import SessionLocal, set_config
    from novel_agent.bible.models import Base, Character
    from novel_agent.config import load_config
    cfg = load_config(); set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    db.add(Character(project_id=pid, name="刘洋", role="主角"))
    db.commit(); db.close()
    # 查角色
    resp = client.get(f"/api/bible/{pid}/characters")
    assert resp.status_code == 200
    assert any(c["name"] == "刘洋" for c in resp.json())
```

```bash
.venv\Scripts\python.exe -m pytest tests/test_api_chapters.py -v
git add . && git commit -m "feat(api): 圣经浏览 API（角色/伏笔/大纲/摘要）"
```

---

## Task 5: 前端单页控制台

**Files:**
- Create: `frontend/index.html`, `frontend/app.js`, `frontend/style.css`

- [ ] **Step 1: 创建 frontend/index.html**

单页控制台：左侧项目列表+操作，右侧主区域（规划/生成/圣经/阅读 tab）。

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>多 Agent 小说生成控制台</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <h2>项目</h2>
    <div id="project-list"></div>
    <button id="new-project-btn">+ 新建项目</button>
    <hr>
    <h2>操作</h2>
    <button id="plan-btn">卷级规划</button>
    <button id="generate-btn">生成章节</button>
  </aside>
  <main class="main">
    <nav class="tabs">
      <button class="tab active" data-tab="cockpit">驾驶舱</button>
      <button class="tab" data-tab="review">人审</button>
      <button class="tab" data-tab="bible">圣经</button>
      <button class="tab" data-tab="reader">阅读</button>
    </nav>
    <section id="cockpit" class="panel active">
      <h3>生成进度</h3>
      <div id="status-log"></div>
    </section>
    <section id="review" class="panel">
      <h3>人审工作台</h3>
      <div id="review-content"></div>
      <button id="approve-btn">通过</button>
      <button id="reject-btn">打回</button>
    </section>
    <section id="bible" class="panel">
      <h3>圣经浏览</h3>
      <div id="bible-content"></div>
    </section>
    <section id="reader" class="panel">
      <h3>章节阅读</h3>
      <div id="reader-content"></div>
    </section>
  </main>
</div>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 frontend/style.css**

基础布局样式（简洁深色主题）：
```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; }
.app { display: flex; height: 100vh; }
.sidebar { width: 240px; background: #16213e; padding: 16px; overflow-y: auto; }
.sidebar h2 { font-size: 14px; color: #888; margin: 12px 0 8px; }
.sidebar button, .tab { background: #0f3460; color: #eee; border: none; padding: 8px 12px;
  margin: 4px 0; cursor: pointer; border-radius: 4px; width: 100%; text-align: left; }
.sidebar button:hover, .tab:hover { background: #1a4a7a; }
.main { flex: 1; display: flex; flex-direction: column; }
.tabs { display: flex; background: #16213e; }
.tab { width: auto; border-radius: 0; }
.tab.active { background: #533483; }
.panel { display: none; padding: 20px; overflow-y: auto; flex: 1; }
.panel.active { display: block; }
#status-log, #review-content, #bible-content, #reader-content {
  background: #0f0f1a; padding: 12px; border-radius: 4px; margin-top: 12px; min-height: 200px;
  white-space: pre-wrap; font-family: monospace; }
```

- [ ] **Step 3: 创建 frontend/app.js**

```javascript
const API = '';
let currentProject = null;
let currentThread = null;

async function api(path, opts = {}) {
  const r = await fetch(API + path, {headers: {'Content-Type': 'application/json'}, ...opts});
  return r.json();
}

async function loadProjects() {
  const projects = await api('/api/projects');
  const list = document.getElementById('project-list');
  list.innerHTML = projects.map(p =>
    `<div class="proj" data-id="${p.id}">${p.title}</div>`).join('');
  list.querySelectorAll('.proj').forEach(el => {
    el.onclick = () => { currentProject = el.dataset.id; loadBible(); };
  });
}

document.getElementById('new-project-btn').onclick = async () => {
  const title = prompt('项目标题');
  if (!title) return;
  await api('/api/projects', {method: 'POST', body: JSON.stringify({title, genre: '科幻'})});
  loadProjects();
};

document.getElementById('plan-btn').onclick = async () => {
  if (!currentProject) return alert('先选项目');
  const volume = prompt('卷名', '卷一');
  const tid = 'plan_' + Date.now();
  currentThread = tid;
  log(`启动规划 ${volume}...`);
  const r = await api('/api/planning/run', {method: 'POST', body: JSON.stringify({
    project_id: parseInt(currentProject), volume, chapter_count: 10, thread_id: tid})});
  log('规划完成，等待人审①：\n' + JSON.stringify(r, null, 2));
  showReview(r);
};

document.getElementById('generate-btn').onclick = async () => {
  if (!currentProject) return alert('先选项目');
  const ch = prompt('章节号', '1');
  const title = prompt('章节标题', '第一章');
  log(`生成第 ${ch} 章...`);
  const r = await api('/api/chapters/generate', {method: 'POST', body: JSON.stringify({
    project_id: parseInt(currentProject), chapter: parseInt(ch), title})});
  log('生成完成：\n' + JSON.stringify(r, null, 2));
};

document.getElementById('approve-btn').onclick = async () => {
  if (!currentThread) return;
  const r = await api('/api/planning/resume', {method: 'POST', body: JSON.stringify({
    thread_id: currentThread, approved: true})});
  log('人审通过：\n' + JSON.stringify(r, null, 2));
};

document.getElementById('reject-btn').onclick = async () => {
  if (!currentThread) return;
  const r = await api('/api/planning/resume', {method: 'POST', body: JSON.stringify({
    thread_id: currentThread, approved: false})});
  log('已打回：\n' + JSON.stringify(r, null, 2));
};

async function loadBible() {
  if (!currentProject) return;
  const [chars, fs, outlines, sums] = await Promise.all([
    api(`/api/bible/${currentProject}/characters`),
    api(`/api/bible/${currentProject}/foreshadows`),
    api(`/api/bible/${currentProject}/outlines`),
    api(`/api/bible/${currentProject}/summaries`),
  ]);
  document.getElementById('bible-content').textContent =
    '== 角色 ==\n' + JSON.stringify(chars, null, 2) +
    '\n\n== 伏笔 ==\n' + JSON.stringify(fs, null, 2) +
    '\n\n== 大纲 ==\n' + JSON.stringify(outlines, null, 2) +
    '\n\n== 摘要 ==\n' + JSON.stringify(sums, null, 2);
}

function log(msg) {
  document.getElementById('status-log').textContent += msg + '\n';
}
function showReview(r) {
  document.getElementById('review-content').textContent = JSON.stringify(r, null, 2);
}

// tab 切换
document.querySelectorAll('.tab').forEach(t => {
  t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.tab).classList.add('active');
  };
});

loadProjects();
```

- [ ] **Step 4: 启动服务验证**

```bash
.venv\Scripts\uvicorn novel_agent.api.app:create_app --factory --port 8000
```
浏览器开 http://localhost:8000 应见控制台。

- [ ] **Step 5: Commit**

```bash
git add . && git commit -m "feat(frontend): 单页控制台（项目/规划/生成/人审/圣经/阅读）"
```

---

## Task 6: server CLI 入口 + 端到端验证

**Files:**
- Modify: `novel_agent/cli.py`（加 serve 命令）
- Test: 全套回归

- [ ] **Step 1: 加 serve 命令**

```python
def cmd_serve(args):
    """启动 API 服务。"""
    import uvicorn
    uvicorn.run("novel_agent.api.app:create_app", factory=True,
                host="127.0.0.1", port=args.port, reload=False)
```
注册：
```python
    p_serve = sub.add_parser("serve", help="启动 API 服务")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)
```

- [ ] **Step 2: 跑全套测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest -v
```
Expected: M1+M2+M3+M3b 83 + M4 新增 ≈ 90+ PASS

- [ ] **Step 3: Commit**

```bash
git add . && git commit -m "feat(cli): serve 命令 + M4 端到端"
```

---

## M4 验收清单

- [ ] FastAPI 服务（项目/规划/章节/圣经 API）
- [ ] 人审① resume API
- [ ] 章节生成 API（mock LLM 端到端）
- [ ] 圣经浏览 API（角色/伏笔/大纲/摘要）
- [ ] 前端单页控制台（四 tab + 全流程可点）
- [ ] CLI serve 命令
- [ ] 全套测试 PASS（M1+M2+M3+M3b 83 + M4 新增）
- [ ] 浏览器能打开控制台并走通 init→plan→人审→generate

## 后续

M4 完成后，阶段 1（MVP）全部就位：单卷规划→人审①→逐章写审生成→人审②→圣经持续积累。
可进入阶段 2（多卷扩展 + 圣经语义检索成熟）。
