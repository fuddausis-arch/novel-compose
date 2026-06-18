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
    `<div class="proj" data-id="${p.id}">${p.title}</div>`).join('') || '<div style="color:#888">无项目</div>';
  list.querySelectorAll('.proj').forEach(el => {
    el.onclick = () => {
      currentProject = el.dataset.id;
      list.querySelectorAll('.proj').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      loadBible();
    };
  });
}

document.getElementById('new-project-btn').onclick = async () => {
  const title = prompt('项目标题');
  if (!title) return;
  const genre = prompt('类型', '科幻') || '';
  await api('/api/projects', {method: 'POST', body: JSON.stringify({title, genre})});
  loadProjects();
};

document.getElementById('plan-btn').onclick = async () => {
  if (!currentProject) return alert('先选项目');
  const volume = prompt('卷名', '卷一');
  if (!volume) return;
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
  if (!ch) return;
  const title = prompt('章节标题', '第' + ch + '章');
  log(`生成第 ${ch} 章...`);
  const r = await api('/api/chapters/generate', {method: 'POST', body: JSON.stringify({
    project_id: parseInt(currentProject), chapter: parseInt(ch), title})});
  log('生成完成：\n' + JSON.stringify(r, null, 2));
  loadBible();
};

document.getElementById('approve-btn').onclick = async () => {
  if (!currentThread) return alert('无可恢复的人审');
  const r = await api('/api/planning/resume', {method: 'POST', body: JSON.stringify({
    thread_id: currentThread, approved: true})});
  log('人审通过：\n' + JSON.stringify(r, null, 2));
  loadBible();
};

document.getElementById('reject-btn').onclick = async () => {
  if (!currentThread) return alert('无可恢复的人审');
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
  // 阅读区加载最新章
  if (sums.length > 0) {
    const latest = sums[0];
    const text = await api(`/api/chapters/${latest.chapter}/text`);
    document.getElementById('reader-content').textContent = text.text || '无正文';
  }
}

function log(msg) {
  const el = document.getElementById('status-log');
  el.textContent += msg + '\n---\n';
  el.scrollTop = el.scrollHeight;
}
function showReview(r) {
  document.getElementById('review-content').textContent = JSON.stringify(r, null, 2);
}

document.querySelectorAll('.tab').forEach(t => {
  t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.tab).classList.add('active');
  };
});

loadProjects();
