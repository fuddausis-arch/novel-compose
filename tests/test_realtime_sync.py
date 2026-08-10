"""写章实时同步（断链①③）与图谱脏标记（断链②）回归测试。

覆盖：
- PUT 章节正文 → EntityAppearance 出场记录自动写入（文本匹配，无需 LLM/提交）
- PUT 章节正文 → 叙事线 light_scan 自动推进 last_active_chapter/progress（规则通道，零成本）
- 同一章重复保存 → 线进度只 +1 一次（幂等，不虚高）
- 内容版本 vs 图谱版本：写内容后 dirty，保存图谱后干净
- 资产写操作（角色/大纲/势力）触发内容版本 bump（仓储层统一挂钩）
"""
from __future__ import annotations

import pytest


@pytest.fixture
def repo():
    """独立仓储 fixture（内存引擎 + 临时项目），验证资产写操作触发 bump。"""
    from novel_agent.bible.database import SessionLocal, engine
    from novel_agent.bible.models import Base, Project
    from novel_agent.bible.repository import BibleRepository
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    p = Project(title="测试小说", genre="科幻")
    db.add(p)
    db.commit()
    db.refresh(p)
    yield BibleRepository(db, project_id=p.id)
    db.close()


# ── 断链①③：写章即更新（出场记录 + 叙事线轻扫） ──

def _create_character(client, pid: int, name: str) -> None:
    r = client.post(f"/api/bible/{pid}/characters", json={"name": name, "role": "主角"})
    assert r.status_code == 200, r.text


def test_save_chapter_writes_appearance_and_light_scan(client, sample_project):
    """手动保存章节正文后：出场记录 + 叙事线进度应自动更新（不依赖提交/手动扫描）。"""
    pid = sample_project
    _create_character(client, pid, "林渊")
    r = client.post(f"/api/storylines/{pid}/storylines", json={
        "name": "主线·复仇", "tags": ["主线", "林渊"], "status": "active", "progress": 0})
    assert r.status_code == 200, r.text
    line_id = r.json()["id"]

    r = client.put(f"/api/chapters/1/text?project_id={pid}",
                   json={"title": "第一章", "content": "林渊踏入废土，复仇之火燃烧。"})
    assert r.status_code == 200, r.text

    # 出场记录已写：第1章应有林渊（角色）
    apps = client.get(f"/api/bible/{pid}/entity-appearances?chapter=1").json()
    assert isinstance(apps, list), apps
    assert any(a["entity_type"] == "character" and a["entity_id"] == "林渊"
               for a in apps), apps

    # 叙事线轻扫：last_active_chapter=1，progress +1
    lines = client.get(f"/api/storylines/{pid}/storylines").json()["items"]
    line = next(l for l in lines if l["id"] == line_id)
    assert line["last_active_chapter"] == 1, line
    assert line["progress"] >= 1, line


def test_save_chapter_light_scan_idempotent(client, sample_project):
    """同一章重复保存（自动保存/重复提交）：线进度只 +1 一次，不虚高。"""
    pid = sample_project
    r = client.post(f"/api/storylines/{pid}/storylines", json={
        "name": "暗线", "tags": ["暗线", "废土"], "status": "active", "progress": 0})
    assert r.status_code == 200, r.text
    line_id = r.json()["id"]

    for _ in range(3):
        r = client.put(f"/api/chapters/1/text?project_id={pid}",
                       json={"title": "第一章", "content": "废土的天空很暗。"})
        assert r.status_code == 200, r.text

    lines = client.get(f"/api/storylines/{pid}/storylines").json()["items"]
    line = next(l for l in lines if l["id"] == line_id)
    assert line["last_active_chapter"] == 1, line
    assert line["progress"] == 1, line


def test_generation_path_writes_appearance(client, sample_project):
    """标准生成路径（recall.save_chapter_text 直调）同样补写出场记录。"""
    pid = sample_project
    _create_character(client, pid, "苏城")
    # 模拟生成器/工作流落盘：不走 PUT 路由，直接调 recall.save_chapter_text
    from novel_agent.config import load_config
    from novel_agent.memory.recall import RecallMemory
    cfg = load_config()
    recall = RecallMemory(cfg, project_id=pid)
    recall.save_chapter_text(2, "第二章", "苏城与怪物搏斗，废土风沙扑面。")

    apps = client.get(f"/api/bible/{pid}/entity-appearances?chapter=2").json()
    assert any(a["entity_id"] == "苏城" for a in apps), apps


# ── 断链②：图谱脏标记 ──

def test_graph_dirty_marking(tmp_path, monkeypatch):
    """内容版本 vs 图谱版本：写内容后 dirty，保存图谱后干净；再写内容又变脏。"""
    monkeypatch.setenv("NOVEL_PROJECT_DATA_DIR", str(tmp_path / "project_data"))
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(tmp_path / "no-such-config.yaml"))
    monkeypatch.delenv("NOVEL_TEST_DB", raising=False)

    from novel_agent.graphs.version import bump_content, mark_graph_generated, is_graph_dirty

    assert bump_content(1) == 1
    assert is_graph_dirty(1, 7) is True
    mark_graph_generated(1, 7)
    assert is_graph_dirty(1, 7) is False
    # 再次写内容 → 又变脏
    assert bump_content(1) == 2
    assert is_graph_dirty(1, 7) is True
    # 其它未刷新图谱同样脏
    assert is_graph_dirty(1, 8) is True


def test_asset_writes_bump_content(repo, monkeypatch):
    """角色/大纲/势力写操作 → 内容版本 bump（仓储层统一挂钩，覆盖所有入口）。"""
    import novel_agent.graphs.version as vmod
    calls: list[int] = []
    monkeypatch.setattr(vmod, "bump_content", lambda pid: calls.append(pid) or 0)

    repo.create_character(name="新角色", role="配角")
    repo.create_outline(level="chapter", order=1, title="第一章")
    repo.create_faction(name="新势力")
    repo.create_foreshadow(foreshadow_id="F-001", description="测试伏笔")

    assert len(calls) >= 4, calls
    assert all(c == repo.project_id for c in calls), calls
