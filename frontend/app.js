const PIPELINE_NODES = [
  {key:'assemble', name:'装配上下文', icon:'📋'},
  {key:'write', name:'写作正文', icon:'✍️'},
  {key:'audit', name:'审校', icon:'🔍'},
  {key:'rewrite', name:'重写', icon:'🔄'},
  {key:'polish', name:'润色', icon:'✨'},
  {key:'save_text', name:'保存正文', icon:'💾'},
  {key:'summarize', name:'抽取摘要', icon:'📝'},
];
let currentProject = null, currentThread = null, evtSource = null;

async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (!r.ok) throw new Error((await r.json().catch(()=>({detail:r.statusText}))).detail);
  return r.json();
}
const $ = id => document.getElementById(id);
const esc = s => String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ---- 项目 ----
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

// ---- 资产树 ----
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
      ${chars.map(c=>`<div class="asset-item" data-asset="char" data-id="${esc(c.name)}">👤 ${esc(c.name)} <span class="asset-badge">${esc(c.role||'')}</span></div>`).join('') || '<div class="empty-state" style="padding:10px">无</div>'}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">伏笔 (${fs.length})</div>
      ${fs.map(f=>`<div class="asset-item" data-asset="fs" data-id="${esc(f.id)}">🔖 ${esc(f.id)} <span class="asset-badge ${f.status}">${f.status}</span></div>`).join('') || '<div class="empty-state" style="padding:10px">无</div>'}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">大纲 (${outs.length})</div>
      ${outs.map(o=>`<div class="asset-item" data-asset="outline" data-id="${o.order}">📖 第${o.order}章 ${esc(o.title||'')}</div>`).join('') || '<div class="empty-state" style="padding:10px">无</div>'}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">章节 (${chs.length})</div>
      ${chs.map(c=>`<div class="asset-item" data-asset="chapter" data-id="${c.chapter}">📄 第${c.chapter}章</div>`).join('') || '<div class="empty-state" style="padding:10px">无</div>'}
    </div>`;
  tree.querySelectorAll('.asset-item').forEach(el=>{
    el.onclick = ()=>{ tree.querySelectorAll('.asset-item').forEach(x=>x.classList.remove('active'));
      el.classList.add('active'); renderAsset(el.dataset.asset, el.dataset.id); };
  });
}

// ---- 工作区渲染 ----
async function renderAsset(type, id) {
  const body = $('workspace-body'); const title = $('workspace-title');
  try {
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
      body.innerHTML = `<div class="detail-card"><h4>${esc(c.name)} <span class="asset-badge">${esc(c.role||'')}</span></h4>
        ${Object.entries(c).filter(([k])=>k!=='name'&&k!=='role').map(([k,v])=>`<div class="detail-row"><span class="detail-label">${k}</span>${esc(v||'—')}</div>`).join('')}</div>`;
    } else if (type==='chapter') {
      const r = await api(`/api/chapters/${id}/text`);
      title.textContent = `第${id}章`;
      body.innerHTML = `<div class="chapter-text">${esc(r.text)}</div>`;
    } else if (type==='fs') {
      const fs = await api(`/api/bible/${currentProject}/foreshadows`);
      const f = fs.find(x=>x.id===id)||{};
      title.textContent = `伏笔 ${id}`;
      body.innerHTML = `<div class="detail-card"><h4>${esc(f.id)} <span class="asset-badge ${f.status}">${f.status}</span></h4>
        <div class="detail-row"><span class="detail-label">描述</span>${esc(f.description||'')}</div>
        <div class="detail-row"><span class="detail-label">埋设章</span>${f.plant_chapter||'—'}</div>
        <div class="detail-row"><span class="detail-label">回收章</span>${f.resolve_chapter||'—'}</div></div>`;
    } else if (type==='outline') {
      const outs = await api(`/api/bible/${currentProject}/outlines`);
      const o = outs.find(x=>String(x.order)===String(id))||{};
      title.textContent = `第${id}章 大纲`;
      body.innerHTML = `<div class="detail-card"><h4>第${o.order}章 ${esc(o.title||'')}</h4>
        <div class="detail-row"><span class="detail-label">摘要</span>${esc(o.summary||'')}</div></div>`;
    }
  } catch(e) { body.innerHTML = `<div class="empty-state">加载失败：${esc(e.message)}</div>`; }
}

// ---- 流水线节点 ----
function renderPipeline() {
  $('pipeline-nodes').innerHTML = PIPELINE_NODES.map(n=>
    `<div class="pipe-node" id="node-${n.key}"><span class="pipe-icon">${n.icon}</span>
     <span class="pipe-name">${n.name}</span><span class="pipe-meta" id="meta-${n.key}"></span></div>`
  ).join('');
}
function setNodeStatus(key, status, meta='') {
  const el = $('node-'+key); if (!el) return;
  el.className = 'pipe-node ' + status;
  $('meta-'+key).textContent = meta;
}
function log(msg){ const el=$('event-log'); el.textContent+=msg+'\n'; el.scrollTop=el.scrollHeight; }

// ---- SSE 生成 ----
$('generate-btn').onclick = ()=>{
  if (!currentProject) return alert('先在左侧选择项目');
  const ch = prompt('章节号','1'); if(!ch) return;
  const title = prompt('章节标题','第'+ch+'章'); if(!title) return;
  startGenerate(currentProject, parseInt(ch), title);
};
function startGenerate(pid, ch, title) {
  if (evtSource) evtSource.close();
  PIPELINE_NODES.forEach(n=>setNodeStatus(n.key,''));
  $('pipeline-tag').textContent='生成中'; $('pipeline-tag').className='tag tag-running';
  $('event-log').textContent='';
  log(`▶ 开始生成第${ch}章《${title}》`);
  evtSource = new EventSource(`/api/chapters/generate/stream?project_id=${pid}&chapter=${ch}&title=${encodeURIComponent(title)}`);
  evtSource.addEventListener('node', e=>{
    const d = JSON.parse(e.data);
    setNodeStatus(d.node, 'active');
    const meta = d.output?.review_iterations ? `第${d.output.review_iterations}轮` :
                 d.output?.word_count ? `${d.output.word_count}字` :
                 d.output?.passed!==undefined ? (d.output.passed?'达标':'重写') : '';
    if (meta) setNodeStatus(d.node, 'active', meta);
    const idx = PIPELINE_NODES.findIndex(n=>n.key===d.node);
    for (let i=0;i<idx;i++) if ($('node-'+PIPELINE_NODES[i].key).className.includes('active')) setNodeStatus(PIPELINE_NODES[i].key,'done');
    log(`  ${d.node}: ${meta||'进行中'}`);
  });
  evtSource.addEventListener('done', e=>{
    $('pipeline-tag').textContent='完成'; $('pipeline-tag').className='tag tag-success';
    PIPELINE_NODES.forEach(n=>setNodeStatus(n.key,'done'));
    log('✓ 生成完成'); evtSource.close(); loadAssets();
  });
  evtSource.addEventListener('error', e=>{
    $('pipeline-tag').textContent='错误'; $('pipeline-tag').className='tag tag-error';
    log('✗ 连接错误'); evtSource.close();
  });
}

// ---- 规划 ----
$('plan-btn').onclick = async ()=>{
  if(!currentProject) return alert('先选项目');
  const vol = prompt('卷名','卷一'); if(!vol) return;
  const tid = 'plan_'+Date.now(); currentThread = tid;
  $('pipeline-tag').textContent='规划中'; $('pipeline-tag').className='tag tag-running';
  $('event-log').textContent=''; log('启动卷级规划...');
  try {
    const r = await api('/api/planning/run',{method:'POST',body:JSON.stringify({
      project_id:currentProject, volume:vol, chapter_count:8, thread_id:tid})});
    log('规划完成，等待人审'); $('human-review').style.display='flex';
    $('pipeline-tag').textContent='待人审'; $('pipeline-tag').className='tag tag-warning';
    $('workspace-title').textContent='人审：卷级规划';
    $('workspace-body').innerHTML = `<div class="detail-card"><h4>卷规划结果</h4>
      <pre style="white-space:pre-wrap;font-size:12px;line-height:1.6">${esc(JSON.stringify(r,null,2))}</pre></div>`;
  } catch(e){ log('规划失败：'+e.message); $('pipeline-tag').textContent='失败'; $('pipeline-tag').className='tag tag-error'; }
};
$('approve-btn').onclick = async ()=>{
  if(!currentThread) return;
  $('pipeline-tag').textContent='恢复中'; $('pipeline-tag').className='tag tag-running';
  try {
    await api('/api/planning/resume',{method:'POST',body:JSON.stringify({thread_id:currentThread,approved:true})});
    log('✓ 人审通过，设定/大纲已写入圣经');
    $('human-review').style.display='none';
    $('pipeline-tag').textContent='完成'; $('pipeline-tag').className='tag tag-success';
    loadAssets();
  } catch(e){ log('恢复失败：'+e.message); }
};
$('reject-btn').onclick = async ()=>{
  if(!currentThread) return;
  await api('/api/planning/resume',{method:'POST',body:JSON.stringify({thread_id:currentThread,approved:false})});
  log('已打回'); $('human-review').style.display='none';
  $('pipeline-tag').textContent='已打回'; $('pipeline-tag').className='tag tag-idle';
};

renderPipeline(); loadProjects();
