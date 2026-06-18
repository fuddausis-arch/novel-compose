# 前端重构：三栏工作台 + SSE 流式 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 把当前"四 tab 平铺"重构为"三栏工作台 + SSE 实时流水线"，对齐 InkOS/91Writing/NovelCrafter 主流模式。左栏资产树、中栏工作区、右栏 AI 事件流；生成过程用 SSE 实时推送节点状态，不阻塞。

**Architecture:** 后端新增 SSE 端点（`/api/chapters/generate/stream`），用 LangGraph astream 产出节点级 update 事件，经 sse-starlette 推前端。前端重写为三栏布局，EventSource 接收 SSE 实时渲染流水线节点状态。仍用纯静态 HTML/JS（无构建链）。

**Tech Stack:** LangGraph astream(stream_mode=["updates"])、sse-starlette、EventSource API、纯静态前端

---

## 前置说明

- 工作目录 `C:\Users\LYY\Desktop\vibe coding`，venv `.venv`
- M1-M4 + 真实验证已完成（92 测试），main 干净
- 已验证 LangGraph astream 能产出节点级 update 事件（assemble/write/audit/polish/save/summarize）
- sse-starlette 已装
- 从 main 拉 `frontend-redesign` 分支

## 文件结构

```
novel_agent/api/
├── routes_chapters.py          # 修改：加 SSE 流式端点
└── routes_planning.py          # 修改：规划也加 SSE
frontend/
├── index.html                  # 重写：三栏布局
├── app.js                      # 重写：EventSource + 三栏交互
└── style.css                   # 重写：三栏样式
tests/
└── test_api_stream.py          # 新增：SSE 端点测试
```

---

## Task 1: 后端 SSE 端点（章节生成流式）

**Files:**
- Modify: `novel_agent/api/routes_chapters.py`
- Test: `tests/test_api_stream.py`

- [ ] **Step 1: 给 routes_chapters.py 加 SSE 流式端点**

在现有 `/generate`（同步）之外，加 `/generate/stream`（SSE）。用 LangGraph astream 产出节点事件：

```python
from sse_starlette.sse import EventSourceResponse
import json

@router.get("/generate/stream")
async def generate_chapter_stream(project_id: int, chapter: int, title: str,
                                  thread_id: str | None = None):
    """SSE 流式生成章节，实时推送节点状态。"""
    cfg = load_config()
    set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    repo = BibleRepository(db, project_id=project_id)
    runner = ChapterRunner(cfg, repo=repo)

    async def event_generator():
        import uuid
        tid = thread_id or str(uuid.uuid4())
        initial = {"project_id": project_id, "chapter": chapter, "title": title,
                   "context": "", "draft": "", "status": "pending", "error": "",
                   "word_count": 0, "draft_version": 0, "review_iterations": 0}
        try:
            async for mode, chunk in runner.graph.astream(
                initial,
                config={"configurable": {"thread_id": tid}},
                stream_mode=["updates"],
            ):
                if mode == "updates":
                    for node_name, node_output in chunk.items():
                        yield {"event": "node", "data": json.dumps({
                            "node": node_name,
                            "output": node_output,
                        }, ensure_ascii=False, default=str)}
            yield {"event": "done", "data": json.dumps({"status": "completed", "thread_id": tid})}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
        finally:
            runner.close()
            db.close()

    return EventSourceResponse(event_generator())
```

- [ ] **Step 2: 写测试 tests/test_api_stream.py**

```python
"""测试 SSE 流式端点。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


def test_generate_stream_emits_node_events(client):
    """SSE 端点应产出 node 事件序列 + done 事件。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))):
        mock = MagicMock()
        mock.generate = AsyncMock(side_effect=["草稿", "润色", '{"core_events":"e"}'])
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        # TestClient 的 GET 流式
        with client.stream("GET", f"/api/chapters/generate/stream?project_id={pid}&chapter=1&title=ch1") as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
            assert "node" in events
            assert "done" in events
```

- [ ] **Step 3: 运行测试**

```bash
.venv\Scripts\python.exe -m pytest tests/test_api_stream.py -v
```
Expected: 1 PASS

- [ ] **Step 4: Commit**

```bash
git add . && git commit -m "feat(api): SSE 流式章节生成端点（节点级事件推送）"
```

---

## Task 2: 前端三栏布局（HTML + CSS）

**Files:**
- Rewrite: `frontend/index.html`, `frontend/style.css`

- [ ] **Step 1: 重写 index.html 为三栏**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>小说工作台</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="workspace">
  <!-- 左栏：资产树 -->
  <aside class="left-pane">
    <div class="pane-header">
      <select id="project-select" class="select"></select>
      <button class="btn-icon" id="new-project-btn" title="新建项目">+</button>
    </div>
    <div class="asset-tree" id="asset-tree">
      <!-- 动态生成：项目概览/设定/角色/大纲/伏笔/章节 -->
    </div>
    <div class="left-actions">
      <button class="btn btn-primary btn-block" id="plan-btn">卷级规划</button>
    </div>
  </aside>

  <!-- 中栏：工作区 -->
  <main class="center-pane">
    <div class="pane-header">
      <h2 id="workspace-title">选择左侧资产或章节</h2>
    </div>
    <div class="workspace-body" id="workspace-body">
      <div class="empty-state">从左侧选择项目资产，或点击章节开始阅读/编辑</div>
    </div>
    <div class="workspace-footer" id="workspace-footer"></div>
  </main>

  <!-- 右栏：AI 事件流 -->
  <aside class="right-pane">
    <div class="pane-header">
      <h3>AI 流水线</h3>
      <span id="pipeline-tag" class="tag tag-idle">空闲</span>
    </div>
    <div class="pipeline-nodes" id="pipeline-nodes">
      <!-- 节点状态卡片 -->
    </div>
    <div class="event-log" id="event-log"></div>
    <div class="right-actions">
      <button class="btn btn-primary btn-block" id="generate-btn">生成下一章</button>
      <div class="human-review" id="human-review" style="display:none">
        <button class="btn btn-success btn-block" id="approve-btn">✓ 通过大纲</button>
        <button class="btn btn-danger btn-block" id="reject-btn">✕ 打回</button>
      </div>
    </div>
  </aside>
</div>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 重写 style.css 为三栏样式**

```css
:root {
  --bg: #0f1117; --bg-elev: #1a1d27; --bg-card: #232734; --border: #2d3142;
  --text: #e4e6eb; --text-dim: #8b8f9e; --primary: #6366f1; --primary-hover: #7c7ff5;
  --success: #10b981; --danger: #ef4444; --warning: #f59e0b; --accent: #ec4899;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       background: var(--bg); color: var(--text); font-size: 14px; overflow: hidden; }

.workspace { display: grid; grid-template-columns: 240px 1fr 300px; height: 100vh; }

.pane-header { display: flex; align-items: center; justify-content: space-between;
               padding: 10px 14px; border-bottom: 1px solid var(--border); min-height: 48px; }
.pane-header h2, .pane-header h3 { font-size: 14px; font-weight: 600; }

/* 左栏 */
.left-pane { background: var(--bg-elev); border-right: 1px solid var(--border);
             display: flex; flex-direction: column; overflow: hidden; }
.asset-tree { flex: 1; overflow-y: auto; padding: 8px; }
.asset-group { margin-bottom: 8px; }
.asset-group-title { font-size: 11px; color: var(--text-dim); text-transform: uppercase;
                     letter-spacing: 1px; padding: 8px 8px 4px; }
.asset-item { padding: 7px 10px; border-radius: 6px; cursor: pointer; font-size: 13px;
              color: var(--text-dim); display: flex; align-items: center; gap: 6px; }
.asset-item:hover { background: var(--bg-card); color: var(--text); }
.asset-item.active { background: var(--primary); color: #fff; }
.asset-badge { font-size: 10px; background: var(--bg-card); padding: 1px 5px; border-radius: 4px; }
.asset-item.active .asset-badge { background: rgba(255,255,255,.2); }
.left-actions { padding: 10px; border-top: 1px solid var(--border); }

/* 中栏 */
.center-pane { display: flex; flex-direction: column; overflow: hidden; background: var(--bg); }
.workspace-body { flex: 1; overflow-y: auto; padding: 24px 32px; }
.workspace-footer { border-top: 1px solid var(--border); padding: 10px 16px; min-height: 48px; }

/* 右栏 */
.right-pane { background: var(--bg-elev); border-left: 1px solid var(--border);
              display: flex; flex-direction: column; overflow: hidden; }
.pipeline-nodes { padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.pipe-node { background: var(--bg-card); border-radius: 6px; padding: 8px 10px;
             display: flex; align-items: center; gap: 8px; font-size: 12px; opacity: .4;
             transition: all .2s; }
.pipe-node.active { opacity: 1; border-left: 3px solid var(--primary); }
.pipe-node.done { opacity: .7; }
.pipe-node.done .pipe-icon { color: var(--success); }
.pipe-node.error { opacity: 1; border-left: 3px solid var(--danger); }
.pipe-icon { width: 16px; text-align: center; }
.pipe-name { flex: 1; }
.pipe-meta { font-size: 11px; color: var(--text-dim); }
.event-log { flex: 1; overflow-y: auto; padding: 8px 12px; font-family: monospace;
             font-size: 11px; white-space: pre-wrap; color: var(--text-dim); border-top: 1px solid var(--border); }
.right-actions { padding: 10px; border-top: 1px solid var(--border); }
.human-review { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }

/* 通用 */
.btn { border: none; border-radius: 6px; padding: 8px 12px; font-size: 13px; cursor: pointer;
       font-family: inherit; color: #fff; transition: all .15s; }
.btn-block { width: 100%; } .btn-primary { background: var(--primary); }
.btn-primary:hover { background: var(--primary-hover); }
.btn-success { background: var(--success); } .btn-danger { background: var(--danger); }
.btn-icon { background: var(--bg-card); border: 1px solid var(--border); color: var(--text);
            border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 16px; }
.select { background: var(--bg-card); border: 1px solid var(--border); color: var(--text);
          padding: 6px 8px; border-radius: 6px; font-size: 13px; font-family: inherit; flex: 1; }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.tag-idle { background: var(--bg-card); color: var(--text-dim); }
.tag-running { background: rgba(99,102,241,.2); color: var(--primary); }
.tag-success { background: rgba(16,185,129,.2); color: var(--success); }
.tag-error { background: rgba(239,68,68,.2); color: var(--danger); }
.tag-warning { background: rgba(245,158,11,.2); color: var(--warning); }
.empty-state { color: var(--text-dim); text-align: center; padding: 60px 20px; font-style: italic; }

/* 资产详情卡（中栏） */
.detail-card { background: var(--bg-elev); border: 1px solid var(--border); border-radius: 8px;
               padding: 16px; margin-bottom: 12px; }
.detail-card h4 { font-size: 14px; margin-bottom: 8px; }
.detail-row { display: flex; gap: 12px; padding: 4px 0; font-size: 13px; }
.detail-label { color: var(--text-dim); min-width: 80px; }
.chapter-text { line-height: 1.9; font-size: 15px; white-space: pre-wrap; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
```

- [ ] **Step 3: Commit**

```bash
git add . && git commit -m "feat(frontend): 三栏布局（资产树/工作区/AI事件流）"
```

---

## Task 3: 前端交互逻辑（EventSource + 资产树 + 工作区）

**Files:**
- Rewrite: `frontend/app.js`

- [ ] **Step 1: 重写 app.js**

核心：项目下拉、资产树生成、工作区渲染、SSE EventSource 接收节点事件实时渲染流水线、生成/规划/人审操作。

```javascript
const PIPELINE_NODES = [
  {key:'assemble', name:'装配上下文', icon:'📋'},
  {key:'write', name:'写作正文', icon:'✍️'},
  {key:'audit', name:'审校', icon:'🔍'},
  {key:'rewrite', name:'重写', icon:'🔄'},
  {key:'polish', name:'润色', icon:'✨'},
  {key:'save_text', name:'保存正文', icon:'💾'},
  {key:'summarize', name:'抽取摘要', icon:'📝'},
];
let currentProject = null, currentAsset = null, currentThread = null, evtSource = null;

async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (!r.ok) throw new Error((await r.json().catch(()=>({detail:r.statusText}))).detail);
  return r.json();
}
function $(id){return document.getElementById(id);}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

// 项目
async function loadProjects() {
  const ps = await api('/api/projects');
  const sel = $('project-select');
  sel.innerHTML = '<option value="">选择项目</option>' + ps.map(p=>`<option value="${p.id}">${esc(p.title)}</option>`).join('');
  sel.onchange = ()=>{ if(sel.value){ currentProject=parseInt(sel.value); loadAssets(); } };
}
$('new-project-btn').onclick = async ()=>{
  const title = prompt('项目标题'); if(!title) return;
  await api('/api/projects',{method:'POST',body:JSON.stringify({title,genre:prompt('类型','科幻')||''})});
  loadProjects();
};

// 资产树
async function loadAssets() {
  if (!currentProject) return;
  const [chars, fs, outs, sums, chs] = await Promise.all([
    api(`/api/bible/${currentProject}/characters`),
    api(`/api/bible/${currentProject}/foreshadows`),
    api(`/api/bible/${currentProject}/outlines`),
    api(`/api/bible/${currentProject}/summaries`),
    api(`/api/chapters/list?project_id=${currentProject}`).catch(()=>[]),
  ]);
  const tree = $('asset-tree');
  tree.innerHTML = `
    <div class="asset-group">
      <div class="asset-group-title">设定</div>
      <div class="asset-item" data-asset="overview">📋 项目概览</div>
    </div>
    <div class="asset-group">
      <div class="asset-group-title">角色 (${chars.length})</div>
      ${chars.map(c=>`<div class="asset-item" data-asset="char" data-id="${esc(c.name)}">👤 ${esc(c.name)} <span class="asset-badge">${esc(c.role||'')}</span></div>`).join('')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">伏笔 (${fs.length})</div>
      ${fs.map(f=>`<div class="asset-item" data-asset="fs" data-id="${esc(f.id)}">🔖 ${esc(f.id)} <span class="asset-badge ${f.status}">${f.status}</span></div>`).join('')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">大纲 (${outs.length})</div>
      ${outs.map(o=>`<div class="asset-item" data-asset="outline" data-id="${o.order}">📖 第${o.order}章 ${esc(o.title||'')}</div>`).join('')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">章节 (${chs.length})</div>
      ${chs.map(c=>`<div class="asset-item" data-asset="chapter" data-id="${c.chapter}">📄 第${c.chapter}章</div>`).join('')}
    </div>`;
  tree.querySelectorAll('.asset-item').forEach(el=>{
    el.onclick = ()=>{ tree.querySelectorAll('.asset-item').forEach(x=>x.classList.remove('active'));
      el.classList.add('active'); renderAsset(el.dataset.asset, el.dataset.id); };
  });
}

// 工作区渲染
async function renderAsset(type, id) {
  currentAsset = {type, id};
  const body = $('workspace-body'); const title = $('workspace-title');
  if (type==='overview') {
    const p = await api(`/api/projects/${currentProject}`);
    title.textContent = p.title;
    body.innerHTML = `<div class="detail-card"><h4>${esc(p.title)}</h4>
      <div class="detail-row"><span class="detail-label">类型</span>${esc(p.genre||'')}</div>
      <div class="detail-row"><span class="detail-label">简介</span>${esc(p.summary||'')}</div>
      <div class="detail-row"><span class="detail-label">风格</span>${esc(p.style||'')}</div></div>`;
  } else if (type==='char') {
    const chars = await api(`/api/bible/${currentProject}/characters`);
    const c = chars.find(x=>x.name===id) || {};
    title.textContent = `角色：${id}`;
    body.innerHTML = `<div class="detail-card"><h4>${esc(c.name)}</h4>
      ${Object.entries(c).map(([k,v])=>`<div class="detail-row"><span class="detail-label">${k}</span>${esc(v||'')}</div>`).join('')}</div>`;
  } else if (type==='chapter') {
    const r = await api(`/api/chapters/${id}/text`);
    title.textContent = `第${id}章`;
    body.innerHTML = `<div class="chapter-text">${esc(r.text)}</div>`;
  } else if (type==='fs') {
    const fs = await api(`/api/bible/${currentProject}/foreshadows`);
    const f = fs.find(x=>x.id===id)||{};
    title.textContent = `伏笔 ${id}`;
    body.innerHTML = `<div class="detail-card"><h4>${esc(f.id)} <span class="tag tag-warning">${f.status}</span></h4>
      <div class="detail-row"><span class="detail-label">描述</span>${esc(f.description||'')}</div>
      <div class="detail-row"><span class="detail-label">埋设章</span>${f.plant_chapter}</div>
      <div class="detail-row"><span class="detail-label">回收章</span>${f.resolve_chapter}</div></div>`;
  } else if (type==='outline') {
    const outs = await api(`/api/bible/${currentProject}/outlines`);
    const o = outs.find(x=>String(x.order)===String(id))||{};
    title.textContent = `第${id}章 大纲`;
    body.innerHTML = `<div class="detail-card"><h4>第${o.order}章 ${esc(o.title||'')}</h4>
      <div class="detail-row"><span class="detail-label">摘要</span>${esc(o.summary||'')}</div></div>`;
  }
}

// 流水线节点渲染
function renderPipeline() {
  $('pipeline-nodes').innerHTML = PIPELINE_NODES.map(n=>
    `<div class="pipe-node" id="node-${n.key}"><span class="pipe-icon">${n.icon}</span>
     <span class="pipe-name">${n.name}</span><span class="pipe-meta" id="meta-${n.key}"></span></div>`
  ).join('');
}
function setNodeStatus(key, status, meta='') {
  const el = $('node-'+key);
  if (!el) return;
  el.className = 'pipe-node ' + status;
  $('meta-'+key).textContent = meta;
}

// SSE 生成
$('generate-btn').onclick = ()=>{
  if (!currentProject) return alert('先选项目');
  const ch = prompt('章节号','1'); if(!ch) return;
  const title = prompt('标题','第'+ch+'章');
  startGenerate(currentProject, parseInt(ch), title);
};
function startGenerate(pid, ch, title) {
  if (evtSource) evtSource.close();
  PIPELINE_NODES.forEach(n=>setNodeStatus(n.key,''));
  $('pipeline-tag').textContent='生成中'; $('pipeline-tag').className='tag tag-running';
  $('event-log').textContent='';
  evtSource = new EventSource(`/api/chapters/generate/stream?project_id=${pid}&chapter=${ch}&title=${encodeURIComponent(title)}`);
  evtSource.addEventListener('node', e=>{
    const d = JSON.parse(e.data);
    setNodeStatus(d.node, 'active');
    log(`▶ ${d.node}: ${JSON.stringify(d.output).slice(0,80)}`);
    // 标记前序节点完成
    const idx = PIPELINE_NODES.findIndex(n=>n.key===d.node);
    for (let i=0;i<idx;i++) setNodeStatus(PIPELINE_NODES[i].key,'done');
    if (d.output && d.output.review_iterations) setNodeStatus('audit','done',`第${d.output.review_iterations}轮`);
  });
  evtSource.addEventListener('done', e=>{
    $('pipeline-tag').textContent='完成'; $('pipeline-tag').className='tag tag-success';
    PIPELINE_NODES.forEach(n=>setNodeStatus(n.key,'done'));
    log('✓ 生成完成');
    evtSource.close(); loadAssets();
  });
  evtSource.addEventListener('error', e=>{
    $('pipeline-tag').textContent='错误'; $('pipeline-tag').className='tag tag-error';
    log('✗ 错误'); evtSource.close();
  });
}
function log(msg){ const el=$('event-log'); el.textContent+=msg+'\n'; el.scrollTop=el.scrollHeight; }

// 规划
$('plan-btn').onclick = async ()=>{
  if(!currentProject) return alert('先选项目');
  const vol = prompt('卷名','卷一'); if(!vol) return;
  const tid = 'plan_'+Date.now(); currentThread = tid;
  $('pipeline-tag').textContent='规划中'; $('pipeline-tag').className='tag tag-running';
  log('启动规划...');
  try {
    const r = await api('/api/planning/run',{method:'POST',body:JSON.stringify({
      project_id:currentProject, volume:vol, chapter_count:8, thread_id:tid})});
    log('规划完成，待人审'); $('human-review').style.display='flex';
    $('workspace-title').textContent='人审：卷级规划';
    $('workspace-body').innerHTML = `<div class="detail-card"><h4>卷规划</h4>
      <pre style="white-space:pre-wrap;font-size:12px">${esc(JSON.stringify(r,null,2))}</pre></div>`;
  } catch(e){ log('规划失败：'+e.message); }
};
$('approve-btn').onclick = async ()=>{
  if(!currentThread) return;
  const r = await api('/api/planning/resume',{method:'POST',body:JSON.stringify({thread_id:currentThread,approved:true})});
  log('人审通过，已写入圣经'); $('human-review').style.display='none'; loadAssets();
};
$('reject-btn').onclick = async ()=>{
  if(!currentThread) return;
  await api('/api/planning/resume',{method:'POST',body:JSON.stringify({thread_id:currentThread,approved:false})});
  log('已打回'); $('human-review').style.display='none';
};

renderPipeline(); loadProjects();
```

- [ ] **Step 2: 启动服务验证三栏渲染**

```bash
.venv\Scripts\uvicorn novel_agent.api.app:create_app --factory --port 8000
```
浏览器开 http://localhost:8000 应见三栏布局。

- [ ] **Step 3: Commit**

```bash
git add . && git commit -m "feat(frontend): 三栏交互（资产树+工作区+SSE流水线）"
```

---

## Task 4: 规划 SSE + 全流程验证 + 收尾

**Files:**
- Modify: `routes_planning.py`（规划也加 SSE，可选）
- 验证全流程

- [ ] **Step 1: 跑全套测试**

```bash
set NOVEL_TEST_DB=memory && .venv\Scripts\python.exe -m pytest -q
```
Expected: 92 + SSE 测试 PASS

- [ ] **Step 2: 启动服务手动验证**

浏览器走一遍：选项目→点规划→人审通过→点生成→看右栏 SSE 流水线节点实时变化→左栏章节出现→点章节阅读。

- [ ] **Step 3: Commit + 合并**

```bash
git add . && git commit -m "feat(frontend): 三栏工作台 + SSE 流水线重构完成"
```

---

## 验收清单

- [ ] 三栏布局（左资产树/中工作区/右AI事件流）
- [ ] SSE 端点产出节点级事件
- [ ] 右栏流水线节点实时状态（空闲/进行中/完成）
- [ ] 左栏资产树（项目/角色/伏笔/大纲/章节）
- [ ] 中栏工作区按资产类型渲染（概览/角色卡/伏笔/大纲/章节正文）
- [ ] 生成过程不阻塞，可看实时进度
- [ ] 人审通过/打回在右栏内嵌
- [ ] 全套测试 PASS
