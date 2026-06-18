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
const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ---- 事件委托：所有 data-act 按钮统一处理 ----
document.addEventListener('click', async (e)=>{
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  const type = btn.dataset.type || '';
  const id = btn.dataset.id || '';
  if (act==='edit') renderEditForm(type, id || null);
  else if (act==='delete') { if(confirm(`确定删除${labelOf(type)} ${id}？`)) deleteAsset(type, id); }
  else if (act==='delete-project') { if(confirm('确定删除整个项目及其所有数据？不可恢复！')) deleteProject(id); }
  else if (act==='save') saveAsset(type, id || null);
  else if (act==='cancel') renderAsset(type, id || null);
  else if (act==='edit-chapter') editChapter(id);
  else if (act==='save-chapter') saveChapter(id);
  else if (act==='delete-chapter') { if(confirm(`确定删除第${id}章？`)) deleteChapter(id); }
  else if (act==='do-import') doImport(btn.dataset.pid);
});

// ---- 项目 ----
async function loadProjects() {
  const ps = await api('/api/projects');
  const sel = $('project-select');
  sel.innerHTML = '<option value="">选择项目</option>' + ps.map(p=>`<option value="${p.id}">${esc(p.title)}</option>`).join('');
  if (currentProject) sel.value = currentProject;
  sel.onchange = ()=>{ if(sel.value){ currentProject=parseInt(sel.value); loadAssets(); } };
}
$('new-project-btn').onclick = async ()=>{
  const title = prompt('项目标题'); if(!title) return;
  await api('/api/projects',{method:'POST',body:JSON.stringify({title,genre:prompt('类型','科幻')||'',summary:prompt('一句话简介')||''})});
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
  const item = (asset, id, html) => `<div class="asset-item" data-asset="${asset}" data-id="${esc(id)}">${html}</div>`;
  tree.innerHTML = `
    <div class="asset-group">
      <div class="asset-group-title">设定</div>
      ${item('overview','','📋 项目概览')}
      ${item('import','','📥 导入设定')}
      ${item('export','','📤 导出TXT')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">角色 (${chars.length}) <span class="add-btn" data-add="char">+</span></div>
      ${chars.map(c=>item('char',c.name,`👤 ${esc(c.name)} <span class="asset-badge">${esc(c.role||'')}</span>`)).join('')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">伏笔 (${fs.length}) <span class="add-btn" data-add="fs">+</span></div>
      ${fs.map(f=>item('fs',f.id,`🔖 ${esc(f.id)} <span class="asset-badge ${f.status}">${f.status}</span>`)).join('')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">大纲 (${outs.length}) <span class="add-btn" data-add="outline">+</span></div>
      ${outs.map(o=>item('outline',o.order,`📖 第${o.order}章 ${esc(o.title||'')}`)).join('')}
    </div>
    <div class="asset-group">
      <div class="asset-group-title">章节 (${chs.length})</div>
      ${chs.map(c=>item('chapter',c.chapter,`📄 第${c.chapter}章`)).join('')}
    </div>`;
  tree.querySelectorAll('.asset-item').forEach(el=>{
    el.onclick = ()=>{ tree.querySelectorAll('.asset-item').forEach(x=>x.classList.remove('active'));
      el.classList.add('active'); renderAsset(el.dataset.asset, el.dataset.id); };
  });
  tree.querySelectorAll('.add-btn').forEach(el=>{
    el.onclick = (e)=>{ e.stopPropagation(); renderEditForm(el.dataset.add, null); };
  });
}

// ---- 工作区渲染 ----
async function renderAsset(type, id) {
  const body = $('workspace-body'); const title = $('workspace-title');
  try {
    if (type==='overview') {
      const p = await api(`/api/projects/${currentProject}`);
      title.textContent = p.title;
      body.innerHTML = `<div class="detail-card">
        <div class="card-actions">
          <button class="btn btn-primary btn-sm" data-act="edit" data-type="project" data-id="${currentProject}">✎ 编辑</button>
          <button class="btn btn-danger btn-sm" data-act="delete-project" data-id="${currentProject}">🗑 删除项目</button>
        </div>
        <h4>${esc(p.title)}</h4>
        <div class="detail-row"><span class="detail-label">类型</span>${esc(p.genre||'')}</div>
        <div class="detail-row"><span class="detail-label">简介</span>${esc(p.summary||'')}</div>
        <div class="detail-row"><span class="detail-label">风格</span>${esc(p.style||'')}</div></div>`;
    } else if (type==='import') {
      title.textContent = '导入设定';
      body.innerHTML = `<div class="detail-card"><h4>批量导入世界观/设定</h4>
        <p style="color:var(--text-dim);font-size:12px;margin-bottom:8px">粘贴 JSON，含 characters/foreshadows/outlines 数组</p>
        <textarea id="import-text" class="edit-textarea" placeholder='{"characters":[{"name":"主角","role":"主角"}]}'></textarea>
        <button class="btn btn-primary" data-act="do-import" data-pid="${currentProject}">导入</button></div>`;
    } else if (type==='export') {
      title.textContent = '导出';
      body.innerHTML = `<div class="detail-card"><h4>导出全部章节为 TXT</h4>
        <button class="btn btn-primary" onclick="window.open('/api/chapters/export/txt?project_id=${currentProject}','_blank')">下载 TXT</button></div>`;
    } else if (type==='char') {
      const chars = await api(`/api/bible/${currentProject}/characters`);
      const c = chars.find(x=>x.name===id) || {};
      title.textContent = `角色：${id}`;
      const rows = Object.entries(c).filter(([k])=>k!=='name'&&k!=='role'&&k!=='id')
        .map(([k,v])=>`<div class="detail-row"><span class="detail-label">${k}</span>${esc(v||'—')}</div>`).join('');
      body.innerHTML = `<div class="detail-card">
        <div class="card-actions">
          <button class="btn btn-primary btn-sm" data-act="edit" data-type="char" data-id="${esc(id)}">✎ 编辑</button>
          <button class="btn btn-danger btn-sm" data-act="delete" data-type="char" data-id="${esc(id)}">🗑 删除</button>
        </div><h4>${esc(c.name)} <span class="asset-badge">${esc(c.role||'')}</span></h4>${rows}</div>`;
    } else if (type==='chapter') {
      const r = await api(`/api/chapters/${id}/text`);
      title.textContent = `第${id}章`;
      body.innerHTML = `<div class="detail-card">
        <div class="card-actions">
          <button class="btn btn-primary btn-sm" data-act="edit-chapter" data-id="${id}">✎ 编辑正文</button>
          <button class="btn btn-danger btn-sm" data-act="delete-chapter" data-id="${id}">🗑 删除章节</button>
        </div><div class="chapter-text">${esc(r.text)}</div></div>`;
    } else if (type==='fs') {
      const fs = await api(`/api/bible/${currentProject}/foreshadows`);
      const f = fs.find(x=>x.id===id)||{};
      title.textContent = `伏笔 ${id}`;
      body.innerHTML = `<div class="detail-card">
        <div class="card-actions">
          <button class="btn btn-primary btn-sm" data-act="edit" data-type="fs" data-id="${esc(id)}">✎ 编辑</button>
          <button class="btn btn-danger btn-sm" data-act="delete" data-type="fs" data-id="${esc(id)}">🗑 删除</button>
        </div><h4>${esc(f.id)} <span class="asset-badge ${f.status}">${f.status}</span></h4>
        <div class="detail-row"><span class="detail-label">描述</span>${esc(f.description||'')}</div>
        <div class="detail-row"><span class="detail-label">埋设章</span>${f.plant_chapter||'—'}</div>
        <div class="detail-row"><span class="detail-label">回收章</span>${f.resolve_chapter||'—'}</div></div>`;
    } else if (type==='outline') {
      const outs = await api(`/api/bible/${currentProject}/outlines`);
      const o = outs.find(x=>String(x.order)===String(id))||{};
      title.textContent = `第${id}章 大纲`;
      body.innerHTML = `<div class="detail-card">
        <div class="card-actions">
          <button class="btn btn-primary btn-sm" data-act="edit" data-type="outline" data-id="${id}">✎ 编辑</button>
          <button class="btn btn-danger btn-sm" data-act="delete" data-type="outline" data-id="${id}">🗑 删除</button>
        </div><h4>第${o.order}章 ${esc(o.title||'')}</h4>
        <div class="detail-row"><span class="detail-label">摘要</span>${esc(o.summary||'')}</div></div>`;
    }
  } catch(e) { body.innerHTML = `<div class="empty-state">加载失败：${esc(e.message)}</div>`; }
}

// ---- 编辑表单 ----
async function renderEditForm(type, id) {
  const body = $('workspace-body'); const title = $('workspace-title');
  let existing = {};
  try {
    if (id !== null && type !== 'project') {
      if (type==='char') existing = (await api(`/api/bible/${currentProject}/characters`)).find(x=>x.name===id)||{};
      else if (type==='fs') existing = (await api(`/api/bible/${currentProject}/foreshadows`)).find(x=>x.id===id)||{};
      else if (type==='outline') existing = (await api(`/api/bible/${currentProject}/outlines`)).find(x=>String(x.order)===String(id))||{};
    } else if (type==='project' && id) {
      existing = await api(`/api/projects/${id}`);
    }
  } catch(e) { body.innerHTML = `<div class="empty-state">加载失败：${esc(e.message)}</div>`; return; }
  title.textContent = id ? `编辑${labelOf(type)}` : `新建${labelOf(type)}`;
  // id 用 data 属性传递，避免引号嵌套
  const safeId = id === null ? '' : esc(id);
  const saveBtn = `<button class="btn btn-primary" data-act="save" data-type="${type}" data-id="${safeId}">保存</button>`;
  const cancelBtn = `<button class="btn btn-ghost" data-act="cancel" data-type="${type}" data-id="${safeId}">取消</button>`;
  if (type==='char') body.innerHTML = charForm(existing, saveBtn, cancelBtn);
  else if (type==='fs') body.innerHTML = fsForm(existing, saveBtn, cancelBtn);
  else if (type==='outline') body.innerHTML = outlineForm(existing, saveBtn, cancelBtn);
  else if (type==='project') body.innerHTML = projectForm(existing, saveBtn, cancelBtn);
}

function labelOf(t){return {char:'角色',fs:'伏笔',outline:'大纲',project:'项目'}[t]||t;}

function field(label, key, val, type='text') {
  return `<div class="form-row"><label>${label}</label><input type="${type}" id="fld-${key}" value="${esc(val==null?'':val)}"></div>`;
}
function area(label, key, val) {
  return `<div class="form-row"><label>${label}</label><textarea id="fld-${key}" class="edit-textarea">${esc(val==null?'':val)}</textarea></div>`;
}

function charForm(c, save, cancel) {
  return `<div class="detail-card edit-form">
    ${field('姓名','name',c.name)}${field('身份','role',c.role)}${area('性格','personality',c.personality)}
    ${area('动机','motivation',c.motivation)}${field('当前位置','current_location',c.current_location)}
    ${field('当前情绪','current_emotion',c.current_emotion)}${area('已知信息','known_info',c.known_info)}
    ${area('背景','background',c.background)}${area('角色弧线','arc',c.arc)}
    <div class="form-actions">${save}${cancel}</div></div>`;
}
function fsForm(f, save, cancel) {
  return `<div class="detail-card edit-form">
    ${field('ID','foreshadow_id',f.id||f.foreshadow_id)}${field('层级','tier',f.tier)}
    ${area('描述','description',f.description)}${field('埋设章','plant_chapter',f.plant_chapter,'number')}
    ${field('回收章','planned_resolve_chapter',f.resolve_chapter||f.planned_resolve_chapter,'number')}
    ${field('状态','status',f.status||'pending')}
    <div class="form-actions">${save}${cancel}</div></div>`;
}
function outlineForm(o, save, cancel) {
  return `<div class="detail-card edit-form">
    ${field('章节号','order',o.order,'number')}${field('标题','title',o.title)}
    ${area('摘要','summary',o.summary)}${field('层级','level',o.level||'chapter')}
    <div class="form-actions">${save}${cancel}</div></div>`;
}
function projectForm(p, save, cancel) {
  return `<div class="detail-card edit-form">
    ${field('标题','title',p.title)}${field('类型','genre',p.genre)}
    ${area('简介','summary',p.summary)}${area('风格','style',p.style)}
    <div class="form-actions">${save}${cancel}</div></div>`;
}

async function saveAsset(type, id) {
  const v = k => { const el = $('fld-'+k); return el ? el.value : ''; };
  try {
    if (type==='char') {
      const data = {name:v('name'),role:v('role'),personality:v('personality'),motivation:v('motivation'),
        current_location:v('current_location'),current_emotion:v('current_emotion'),
        known_info:v('known_info'),background:v('background'),arc:v('arc')};
      if (id) await api(`/api/bible/${currentProject}/characters/${encodeURIComponent(id)}`,{method:'PUT',body:JSON.stringify(data)});
      else await api(`/api/bible/${currentProject}/characters`,{method:'POST',body:JSON.stringify(data)});
    } else if (type==='fs') {
      const data = {foreshadow_id:v('foreshadow_id'),tier:v('tier'),description:v('description'),
        plant_chapter:parseInt(v('plant_chapter')||0),planned_resolve_chapter:parseInt(v('planned_resolve_chapter')||0),status:v('status')};
      if (id) await api(`/api/bible/${currentProject}/foreshadows/${encodeURIComponent(id)}`,{method:'PUT',body:JSON.stringify(data)});
      else await api(`/api/bible/${currentProject}/foreshadows`,{method:'POST',body:JSON.stringify(data)});
    } else if (type==='outline') {
      const data = {order:parseInt(v('order')||0),title:v('title'),summary:v('summary'),level:v('level')};
      if (id) await api(`/api/bible/${currentProject}/outlines/${id}`,{method:'PUT',body:JSON.stringify(data)});
      else await api(`/api/bible/${currentProject}/outlines`,{method:'POST',body:JSON.stringify(data)});
    } else if (type==='project') {
      const data = {title:v('title'),genre:v('genre'),summary:v('summary'),style:v('style')};
      await api(`/api/projects/${id}`,{method:'PUT',body:JSON.stringify(data)});
      loadProjects();
    }
    log(`✓ ${type} 已保存`); loadAssets();
  } catch(e) { alert('保存失败：'+e.message); }
}

async function deleteAsset(type, id) {
  try {
    if (type==='char') await api(`/api/bible/${currentProject}/characters/${encodeURIComponent(id)}`,{method:'DELETE'});
    else if (type==='fs') await api(`/api/bible/${currentProject}/foreshadows/${encodeURIComponent(id)}`,{method:'DELETE'});
    else if (type==='outline') await api(`/api/bible/${currentProject}/outlines/${id}`,{method:'DELETE'});
    log(`✓ 已删除 ${type} ${id}`); loadAssets();
    $('workspace-body').innerHTML = '<div class="empty-state">已删除</div>';
  } catch(e) { alert('删除失败：'+e.message); }
}

async function deleteProject(id) {
  await api(`/api/projects/${id}`,{method:'DELETE'});
  currentProject = null; loadProjects();
  $('asset-tree').innerHTML = '<div class="empty-state">请选择项目</div>';
  $('workspace-body').innerHTML = '<div class="empty-state">项目已删除</div>';
}

async function editChapter(ch) {
  const r = await api(`/api/chapters/${ch}/text`);
  $('workspace-title').textContent = `编辑第${ch}章`;
  $('workspace-body').innerHTML = `<div class="detail-card">
    <div class="card-actions"><button class="btn btn-primary btn-sm" data-act="save-chapter" data-id="${ch}">💾 保存</button></div>
    <textarea id="chapter-edit" class="chapter-edit-area">${esc(r.text)}</textarea></div>`;
}

async function saveChapter(ch) {
  const content = $('chapter-edit').value;
  await api(`/api/chapters/${ch}/text`,{method:'PUT',body:JSON.stringify({title:`第${ch}章`,content})});
  log(`✓ 第${ch}章已保存`); renderAsset('chapter', ch);
}

async function deleteChapter(ch) {
  await api(`/api/chapters/${ch}`,{method:'DELETE'});
  log(`✓ 第${ch}章已删除`); loadAssets();
  $('workspace-body').innerHTML = '<div class="empty-state">章节已删除</div>';
}

async function doImport(pid) {
  const txt = $('import-text').value;
  try {
    const data = JSON.parse(txt);
    const r = await api(`/api/bible/${pid}/import`,{method:'POST',body:JSON.stringify(data)});
    log(`✓ 导入完成：${JSON.stringify(r.imported)}`); loadAssets();
  } catch(e) { alert('导入失败，请检查 JSON 格式：'+e.message); }
}

// ---- 流水线 ----
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
    const meta = d.output && d.output.review_iterations ? `第${d.output.review_iterations}轮` :
                 d.output && d.output.word_count ? `${d.output.word_count}字` :
                 d.output && d.output.passed!==undefined ? (d.output.passed?'达标':'重写') : '';
    if (meta) setNodeStatus(d.node, 'active', meta);
    const idx = PIPELINE_NODES.findIndex(n=>n.key===d.node);
    for (let i=0;i<idx;i++) { const pe=$('node-'+PIPELINE_NODES[i].key); if(pe && pe.className.includes('active')) setNodeStatus(PIPELINE_NODES[i].key,'done'); }
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
