const API = '';
let currentProject = null;
let currentThread = null;

async function api(path, opts = {}) {
  const r = await fetch(API + path, {headers: {'Content-Type': 'application/json'}, ...opts});
  if (!r.ok) {
    const err = await r.json().catch(() => ({detail: r.statusText}));
    throw new Error(err.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

function setStatus(label, cls) {
  const el = document.getElementById('pipeline-status');
  el.textContent = label;
  el.className = 'tag ' + cls;
}
function log(msg) {
  const el = document.getElementById('status-log');
  const ts = new Date().toLocaleTimeString();
  el.textContent += `[${ts}] ${msg}\n`;
  el.scrollTop = el.scrollHeight;
}

// ---- 项目 ----
async function loadProjects() {
  const projects = await api('/api/projects');
  const list = document.getElementById('project-list');
  list.innerHTML = projects.map(p =>
    `<div class="proj" data-id="${p.id}">${escapeHtml(p.title)}</div>`).join('')
    || '<div class="empty">无项目</div>';
  list.querySelectorAll('.proj').forEach(el => {
    el.onclick = () => selectProject(el.dataset.id, el);
  });
}
function selectProject(id, el) {
  currentProject = id;
  document.querySelectorAll('.proj').forEach(x => x.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('current-project-tag').textContent = `项目 #${id}`;
  loadBible();
  loadChapterList();
}

document.getElementById('new-project-btn').onclick = async () => {
  const title = prompt('项目标题');
  if (!title) return;
  const genre = prompt('类型', '科幻') || '';
  const summary = prompt('一句话简介') || '';
  await api('/api/projects', {method: 'POST', body: JSON.stringify({title, genre, summary})});
  loadProjects();
};

// ---- 规划 ----
document.getElementById('plan-btn').onclick = async () => {
  if (!currentProject) return alert('请先在左侧选择项目');
  const volume = prompt('卷名', '卷一');
  if (!volume) return;
  const tid = 'plan_' + Date.now();
  currentThread = tid;
  setStatus('规划中…', 'tag-running');
  log(`启动卷级规划：${volume}`);
  try {
    const r = await api('/api/planning/run', {method: 'POST', body: JSON.stringify({
      project_id: parseInt(currentProject), volume, chapter_count: 8, thread_id: tid})});
    log('规划完成，等待人审①');
    showReview(r);
    setStatus('待人审', 'tag-warning') ;
    document.querySelector('[data-tab="review"]').click();
  } catch (e) {
    log('规划失败：' + e.message);
    setStatus('失败', 'tag-error');
  }
};

// ---- 生成 ----
document.getElementById('generate-btn').onclick = async () => {
  if (!currentProject) return alert('请先选择项目');
  const ch = prompt('章节号', '1');
  if (!ch) return;
  const title = prompt('章节标题', '第' + ch + '章');
  setStatus('生成中…', 'tag-running');
  log(`生成第 ${ch} 章…`);
  try {
    const r = await api('/api/chapters/generate', {method: 'POST', body: JSON.stringify({
      project_id: parseInt(currentProject), chapter: parseInt(ch), title})});
    log(`第${ch}章完成：${r.status}，${r.word_count||0}字，审阅${r.review_iterations||0}次`);
    setStatus('完成', 'tag-success');
    loadBible();
    loadChapterList();
  } catch (e) {
    log('生成失败：' + e.message);
    setStatus('失败', 'tag-error');
  }
};

// ---- 人审 ----
function showReview(r) {
  const el = document.getElementById('review-content');
  const plan = r.volume_plan || {};
  const vols = (plan.volumes || []).map(v =>
    `  ${v.name}（${v.chapters}章）：${v.summary||''}`).join('\n');
  el.textContent = `卷规划：\n${vols || JSON.stringify(plan, null, 2)}\n\n` +
    `设定角色：${((r.settings||{}).characters||[]).map(c=>c.name).join(', ') || '无'}\n` +
    `大纲章数：${((r.outline||{}).chapters||[]).length}\n\nthread_id: ${r.thread_id||currentThread}`;
}
document.getElementById('approve-btn').onclick = async () => {
  if (!currentThread) return alert('无可恢复的人审');
  setStatus('恢复中…', 'tag-running');
  try {
    const r = await api('/api/planning/resume', {method: 'POST', body: JSON.stringify({
      thread_id: currentThread, approved: true})});
    log('人审通过，设定/大纲已写入圣经');
    setStatus('完成', 'tag-success');
    loadBible();
  } catch (e) {
    log('恢复失败：' + e.message);
    setStatus('失败', 'tag-error');
  }
};
document.getElementById('reject-btn').onclick = async () => {
  if (!currentThread) return alert('无可恢复的人审');
  const r = await api('/api/planning/resume', {method: 'POST', body: JSON.stringify({
    thread_id: currentThread, approved: false})});
  log('已打回');
  setStatus('已打回', 'tag-idle');
};

// ---- 圣经 ----
async function loadBible() {
  if (!currentProject) return;
  const [chars, fs, outlines, sums] = await Promise.all([
    api(`/api/bible/${currentProject}/characters`),
    api(`/api/bible/${currentProject}/foreshadows`),
    api(`/api/bible/${currentProject}/outlines`),
    api(`/api/bible/${currentProject}/summaries`),
  ]);
  document.getElementById('char-count').textContent = chars.length;
  document.getElementById('fs-count').textContent = fs.length;
  document.getElementById('ol-count').textContent = outlines.length;
  document.getElementById('sum-count').textContent = sums.length;

  document.getElementById('bible-chars').innerHTML = chars.length ? chars.map(c =>
    `<div class="char-item"><div class="char-name">${escapeHtml(c.name)} <span style="color:var(--text-dim);font-size:11px">${escapeHtml(c.role||'')}</span></div>
     <div class="char-meta">${escapeHtml(c.personality||'')} ${c.current_location?'· '+escapeHtml(c.current_location):''}</div></div>`
  ).join('') : '<div class="empty">无角色</div>';

  document.getElementById('bible-fs').innerHTML = fs.length ? fs.map(f =>
    `<div class="fs-item"><span class="fs-id">${escapeHtml(f.id)}</span>
     <span class="fs-status ${f.status}">${f.status}</span>
     <span style="font-size:11px;color:var(--text-dim)">${escapeHtml((f.description||'').slice(0,40))}</span></div>`
  ).join('') : '<div class="empty">无伏笔</div>';

  document.getElementById('bible-ol').innerHTML = outlines.length ? outlines.map(o =>
    `<div class="ol-item"><div class="ol-title">第${o.order}章 ${escapeHtml(o.title||'')}</div>
     <div class="ol-summary">${escapeHtml(o.summary||'')}</div></div>`
  ).join('') : '<div class="empty">无大纲</div>';

  document.getElementById('bible-sum').innerHTML = sums.length ? sums.map(s =>
    `<div class="sum-item"><div class="sum-title">第${s.chapter}章 ${escapeHtml(s.title||'')} <span style="color:var(--text-dim);font-size:11px">${s.word_count}字</span></div>
     <div class="sum-events">${escapeHtml(s.core_events||'')}</div></div>`
  ).join('') : '<div class="empty">无摘要</div>';
}

// ---- 阅读 ----
async function loadChapterList() {
  if (!currentProject) return;
  try {
    const chapters = await api(`/api/chapters/list?project_id=${currentProject}`);
    const sel = document.getElementById('chapter-select');
    sel.innerHTML = '<option value="">选择章节</option>' + chapters.map(c =>
      `<option value="${c.chapter}">第${c.chapter}章</option>`).join('');
    sel.onchange = () => { if (sel.value) loadChapterText(parseInt(sel.value)); };
  } catch (e) {}
}
async function loadChapterText(ch) {
  try {
    const r = await api(`/api/chapters/${ch}/text`);
    document.getElementById('reader-content').textContent = r.text || '无正文';
  } catch (e) {
    document.getElementById('reader-content').textContent = '加载失败：' + e.message;
  }
}

// ---- 工具 ----
function escapeHtml(s) {
  return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
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
