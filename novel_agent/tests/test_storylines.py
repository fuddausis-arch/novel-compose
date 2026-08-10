"""叙事线系统：模型 + CRUD 接口 + 扫描测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.bible import models as m
from novel_agent.bible.models import Base


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


# ── Task 1: 数据模型 ──────────────────────────────────


def test_storyline_model_fields(db_session):
    line = m.Storyline(
        project_id=1, name="调查线", line_type="复仇线",
        tags=["主线", "暗线"], status="active", progress=30,
        planned_resolve_chapter=12, volume="卷一",
    )
    db_session.add(line)
    db_session.commit()
    assert line.id is not None
    assert line.tags == ["主线", "暗线"]


def test_storyline_node_and_relation(db_session):
    a = m.Storyline(project_id=1, name="调查线", tags=["主线"])
    b = m.Storyline(project_id=1, name="身世线", tags=["暗线"])
    db_session.add_all([a, b])
    db_session.commit()
    node = m.StorylineNode(storyline_id=a.id, node_type="event", chapter=5, title="真凶现身")
    rel = m.StorylineRelation(project_id=1, source_storyline_id=a.id,
                              target_storyline_id=b.id, relation_type="intersect", chapter=8)
    db_session.add_all([node, rel])
    db_session.commit()
    assert node.id is not None and rel.id is not None


def test_delete_line_cascades(db_session):
    a = m.Storyline(project_id=1, name="调查线", tags=["主线"])
    db_session.add(a)
    db_session.commit()
    node = m.StorylineNode(storyline_id=a.id, node_type="event", chapter=1, title="埋点")
    db_session.add(node)
    db_session.commit()
    db_session.delete(a)
    db_session.commit()
    assert db_session.query(m.StorylineNode).filter_by(storyline_id=a.id).count() == 0


# ── Task 2: CRUD 接口 + meta ─────────────────────────


@pytest.fixture()
def story_client(db_session):
    from fastapi import FastAPI
    from novel_agent.api.routes_storylines import router, get_story_db
    app = FastAPI()
    app.include_router(router, prefix="/api/storylines")
    app.dependency_overrides[get_story_db] = lambda: db_session
    return TestClient(app)


def test_storylines_crud(story_client):
    r = story_client.post("/api/storylines/1/storylines", json={
        "name": "调查线", "line_type": "复仇线", "tags": ["主线", "暗线"],
        "status": "active", "progress": 10, "planned_resolve_chapter": 12, "volume": "卷一",
    })
    assert r.status_code == 200
    line = r.json()
    assert line["tags"] == ["主线", "暗线"]

    sid = line["id"]
    r = story_client.get("/api/storylines/1/storylines")
    assert r.status_code == 200 and any(x["id"] == sid for x in r.json()["items"])

    r = story_client.put(f"/api/storylines/1/storylines/{sid}", json={"progress": 50})
    assert r.status_code == 200 and r.json()["progress"] == 50

    r = story_client.delete(f"/api/storylines/1/storylines/{sid}")
    assert r.status_code == 200
    r = story_client.get("/api/storylines/1/storylines")
    assert all(x["id"] != sid for x in r.json()["items"])


def test_storylines_meta(story_client):
    r = story_client.get("/api/storylines/meta")
    assert r.status_code == 200
    data = r.json()
    assert "tags" in data and "statuses" in data and "relation_types" in data


def test_storyline_nodes_and_relations(story_client):
    a = story_client.post("/api/storylines/1/storylines", json={"name": "调查线", "tags": ["主线"]}).json()
    b = story_client.post("/api/storylines/1/storylines", json={"name": "身世线", "tags": ["暗线"]}).json()
    r = story_client.post(f"/api/storylines/1/storylines/{a['id']}/nodes", json={
        "node_type": "event", "chapter": 5, "title": "真凶现身",
    })
    assert r.status_code == 200
    r = story_client.post("/api/storylines/1/storylines/relations", json={
        "source_storyline_id": a["id"], "target_storyline_id": b["id"],
        "relation_type": "intersect", "chapter": 8,
    })
    assert r.status_code == 200
    # 删除线后节点随之消失（CRUD 层级联）
    story_client.delete(f"/api/storylines/1/storylines/{a['id']}")
    detail = story_client.get(f"/api/storylines/1/storylines/{a['id']}/detail")
    assert detail.status_code == 404


def test_storyline_filter_and_detail(story_client):
    a = story_client.post("/api/storylines/1/storylines", json={
        "name": "调查线", "tags": ["主线", "明线"], "volume": "卷一"}).json()
    story_client.post("/api/storylines/1/storylines", json={
        "name": "身世线", "tags": ["暗线"], "volume": "卷一"}).json()
    r = story_client.get("/api/storylines/1/storylines?tag=主线")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1 and r.json()["items"][0]["name"] == "调查线"

    detail = story_client.get(f"/api/storylines/1/storylines/{a['id']}/detail")
    assert detail.status_code == 200
    assert "nodes" in detail.json() and "relations" in detail.json()


# ── Task 3: 双通道扫描器 ─────────────────────────────


def test_rule_scan_chapter_detects_overdue(db_session):
    from novel_agent.storyline.scanner import rule_scan_chapter
    f = m.Foreshadow(
        project_id=1, foreshadow_id="F-001", tier="long",
        plant_chapter=1, status="planted", planned_resolve_chapter=3,
    )
    db_session.add(f)
    db_session.commit()
    result = rule_scan_chapter(db_session, project_id=1, chapter=5, text="", lines=[])
    assert any(a["type"] == "foreshadow_overdue" for a in result["alerts"])


def test_rule_scan_chapter_detects_broken_line(db_session):
    from novel_agent.storyline.scanner import rule_scan_chapter
    line = m.Storyline(project_id=1, name="调查线", tags=["主线"], last_active_chapter=1)
    db_session.add(line)
    db_session.commit()
    result = rule_scan_chapter(db_session, project_id=1, chapter=6, text="", lines=[line],
                               break_threshold=5)
    assert any(a["type"] == "line_stalled" for a in result["alerts"])
    # 未达阈值不断线
    result2 = rule_scan_chapter(db_session, project_id=1, chapter=3, text="", lines=[line],
                                break_threshold=5)
    assert not any(a["type"] == "line_stalled" for a in result2["alerts"])


def test_cross_validate_agrees_and_disagrees():
    from novel_agent.storyline.scanner import cross_validate
    agree = cross_validate({"progressed": True}, {"progressed": True})
    assert agree["verdict"] == "adopt"
    assert agree["adopted_progressed"] is True
    conflict = cross_validate({"progressed": True}, {"progressed": False})
    assert conflict["verdict"] == "pending"
    assert conflict["adopted_progressed"] is None


# ── 深度测试 d1: 边界/异常 ───────────────────────────


def test_create_line_blank_name_rejected(story_client):
    r = story_client.post("/api/storylines/1/storylines", json={"name": "  "})
    assert r.status_code == 400


def test_create_line_progress_clamped(story_client):
    r = story_client.post("/api/storylines/1/storylines", json={
        "name": "越界线", "progress": 150})
    assert r.status_code == 200 and r.json()["progress"] == 100
    r = story_client.post("/api/storylines/1/storylines", json={
        "name": "负进度线", "progress": -5})
    assert r.status_code == 200 and r.json()["progress"] == 0


def test_update_missing_line_404(story_client):
    r = story_client.put("/api/storylines/1/storylines/99999", json={"progress": 50})
    assert r.status_code == 404
    r = story_client.delete("/api/storylines/1/storylines/99999")
    assert r.status_code == 404
    r = story_client.get("/api/storylines/1/storylines/99999/detail")
    assert r.status_code == 404


def test_node_on_missing_line_404(story_client):
    r = story_client.post("/api/storylines/1/storylines/99999/nodes", json={
        "node_type": "event", "title": "孤儿节点"})
    assert r.status_code == 404


def test_self_relation_rejected(story_client):
    a = story_client.post("/api/storylines/1/storylines", json={"name": "A线"}).json()
    r = story_client.post("/api/storylines/1/storylines/relations", json={
        "source_storyline_id": a["id"], "target_storyline_id": a["id"],
        "relation_type": "merge"})
    assert r.status_code == 400


def test_update_node_and_relation(story_client):
    a = story_client.post("/api/storylines/1/storylines", json={"name": "A线"}).json()
    n = story_client.post(f"/api/storylines/1/storylines/{a['id']}/nodes", json={
        "node_type": "event", "chapter": 2, "title": "初版"}).json()
    r = story_client.put(f"/api/storylines/storyline-nodes/{n['id']}", json={"title": "改版"})
    assert r.status_code == 200 and r.json()["title"] == "改版"
    b = story_client.post("/api/storylines/1/storylines", json={"name": "B线"}).json()
    rel = story_client.post("/api/storylines/1/storylines/relations", json={
        "source_storyline_id": a["id"], "target_storyline_id": b["id"], "relation_type": "merge"}).json()
    r = story_client.put(f"/api/storylines/storyline-relations/{rel['id']}", json={
        "source_storyline_id": a["id"], "target_storyline_id": b["id"],
        "relation_type": "conflict", "chapter": 10})
    assert r.status_code == 200 and r.json()["relation_type"] == "conflict"
    r = story_client.delete(f"/api/storylines/storyline-nodes/{n['id']}")
    assert r.status_code == 200
    r = story_client.delete(f"/api/storylines/storyline-relations/{rel['id']}")
    assert r.status_code == 200


def test_search_and_filter_combined(story_client):
    story_client.post("/api/storylines/1/storylines", json={
        "name": "复仇线", "tags": ["暗线"], "status": "paused", "volume": "卷一"})
    story_client.post("/api/storylines/1/storylines", json={
        "name": "时间线主", "tags": ["主线", "明线"], "status": "active", "volume": "卷二"})
    # 状态筛选
    r = story_client.get("/api/storylines/1/storylines?status=paused")
    assert len(r.json()["items"]) == 1 and r.json()["items"][0]["name"] == "复仇线"
    # 搜索（线名/类型/摘要）
    r = story_client.get("/api/storylines/1/storylines?search=时间线")
    assert len(r.json()["items"]) == 1 and r.json()["items"][0]["name"] == "时间线主"
    # 无命中
    r = story_client.get("/api/storylines/1/storylines?search=不存在的东西")
    assert r.json()["items"] == []


# ── 深度测试 d2: 扫描器 ──────────────────────────────


def test_rule_scan_break_threshold_boundary(db_session):
    """断线判定边界：gap == threshold-1 不报，== threshold 报。"""
    from novel_agent.storyline.scanner import rule_scan_chapter
    line = m.Storyline(project_id=1, name="调查线", tags=["主线"], last_active_chapter=1)
    db_session.add(line)
    db_session.commit()
    # gap=3 < 5 → 不报
    r = rule_scan_chapter(db_session, project_id=1, chapter=4, text="", lines=[line], break_threshold=5)
    assert not any(a["type"] == "line_stalled" for a in r["alerts"])
    # gap=4 < 5 → 不报
    r = rule_scan_chapter(db_session, project_id=1, chapter=5, text="", lines=[line], break_threshold=5)
    assert not any(a["type"] == "line_stalled" for a in r["alerts"])
    # gap=5 >= 5 → 报
    r = rule_scan_chapter(db_session, project_id=1, chapter=6, text="", lines=[line], break_threshold=5)
    assert any(a["type"] == "line_stalled" for a in r["alerts"])


def test_rule_scan_foreshadow_resolve_boundary(db_session):
    """伏笔逾期边界：planned == chapter 不报；已回收/废弃不报；超期才报。"""
    from novel_agent.storyline.scanner import rule_scan_chapter
    f1 = m.Foreshadow(project_id=1, foreshadow_id="F-001", plant_chapter=1,
                      status="planted", planned_resolve_chapter=5)   # 计划第5章
    f2 = m.Foreshadow(project_id=1, foreshadow_id="F-002", plant_chapter=1,
                      status="resolved", planned_resolve_chapter=3)  # 已回收，即使过期也不报
    f3 = m.Foreshadow(project_id=1, foreshadow_id="F-003", plant_chapter=1,
                      status="abandoned", planned_resolve_chapter=3) # 已废弃不报
    db_session.add_all([f1, f2, f3])
    db_session.commit()
    # 第5章：正好到计划章，未超期 → F-001 不报
    r = rule_scan_chapter(db_session, project_id=1, chapter=5, text="", lines=[])
    assert not any(a["foreshadow_id"] == "F-001" for a in r["alerts"])
    # 第6章：超期 → F-001 报；F-002/F-003 不报
    r = rule_scan_chapter(db_session, project_id=1, chapter=6, text="", lines=[])
    assert any(a["foreshadow_id"] == "F-001" for a in r["alerts"])
    assert not any(a["foreshadow_id"] == "F-002" for a in r["alerts"])
    assert not any(a["foreshadow_id"] == "F-003" for a in r["alerts"])


def test_cross_validate_all_combinations():
    from novel_agent.storyline.scanner import cross_validate
    assert cross_validate({"progressed": False}, {"progressed": False})["verdict"] == "adopt"
    assert cross_validate({"progressed": False}, {"progressed": False})["adopted_progressed"] is False
    assert cross_validate({"progressed": True}, {"progressed": False})["verdict"] == "pending"
    assert cross_validate({"progressed": False}, {"progressed": True})["verdict"] == "pending"


class _FakeClient:
    """mock LLMClient：返回预设文本。"""

    def __init__(self, result: str):
        self.result = result
        self.last_user = ""
        self.last_system = ""

    async def generate(self, user, system=None, temperature=0.7, node_name="", **kw):
        self.last_user = user
        self.last_system = system
        return self.result


def test_llm_scan_valid_json():
    from novel_agent.storyline.scanner import llm_scan_chapter
    import asyncio
    fake = _FakeClient(
        '{"line_results": [{"storyline_id": 1, "name": "调查线", "progressed": true,'
        ' "progress_delta": 10, "notes": "真凶线索出现"}],'
        ' "alerts": [{"type": "dark_underprepared", "severity": "info", "storyline_id": 2,'
        ' "message": "暗线铺垫不足"}]}'
    )
    result = asyncio.run(llm_scan_chapter(fake, 5, "正文内容", []))
    assert len(result["line_results"]) == 1
    assert result["line_results"][0]["progressed"] is True
    assert result["alerts"][0]["type"] == "dark_underprepared"
    # prompt 包含章节与正文
    assert "第5章" in fake.last_user


def test_llm_scan_garbage_no_crash():
    """LLM 返回垃圾文本：解析失败返回空结果，不抛异常。"""
    from novel_agent.storyline.scanner import llm_scan_chapter
    import asyncio
    fake = _FakeClient("这不是 JSON，纯乱码！！！")
    result = asyncio.run(llm_scan_chapter(fake, 3, "正文", []))
    assert result["line_results"] == [] and result["alerts"] == []


def test_llm_user_text_truncated():
    from novel_agent.storyline.scanner import _build_llm_user
    long_text = "啊" * 10000
    user = _build_llm_user(8, long_text, [])
    assert "第8章" in user
    assert len(user) < 6600  # 正文截断 6000 + 摘要等


def test_rule_scan_empty_lines_no_line_alerts(db_session):
    from novel_agent.storyline.scanner import rule_scan_chapter
    r = rule_scan_chapter(db_session, project_id=1, chapter=10, text="", lines=[])
    assert all(a["type"] != "line_stalled" for a in r["alerts"])


# ── 深度测试 d3: SSE scan 端点连通性 ──────────────────


class _FakeLLMClient:
    """scan 端点内部 LLMClient 的替身：返回固定的双通道判定。"""

    def __init__(self, *a, **kw):
        self.calls = 0

    async def generate(self, user, system=None, temperature=0.7, node_name="", **kw):
        self.calls += 1
        return (
            '{"line_results": [{"storyline_id": %s, "name": "调查线", "progressed": true,'
            ' "progress_delta": 10}], "alerts": []}' % self._line_id
        )

    _line_id = 0


class _FakeRecallMemory:
    def __init__(self, cfg, project_id):
        pass

    def read_chapter_text(self, chapter):
        return "第%d章正文：主角调查发现真凶线索。" % chapter


def test_scan_sse_event_sequence(story_client, monkeypatch):
    """SSE 事件序列：scan_start → rule_result → line_result(adopt) → alerts → done。"""
    import json as _json
    import novel_agent.api.routes_storylines as rs
    import novel_agent.config as _cfg_mod

    # 建一条线 + 一个逾期伏笔，让规则通道也有输出
    line = story_client.post("/api/storylines/1/storylines", json={
        "name": "调查线", "tags": ["主线"], "last_active_chapter": 0}).json()
    _FakeLLMClient._line_id = line["id"]

    real_load = _cfg_mod.load_config
    def fake_load():
        cfg = real_load()
        cfg.llm.api_key = "test-key-not-real"
        return cfg
    monkeypatch.setattr(rs, "load_config", fake_load)
    # scan 端点在函数内局部 import，需 patch 真实来源模块
    monkeypatch.setattr("novel_agent.llm.client.LLMClient", _FakeLLMClient)
    monkeypatch.setattr("novel_agent.memory.recall.RecallMemory", _FakeRecallMemory)

    with story_client.stream(
        "POST", "/api/storylines/1/storylines/scan", json={"chapter": 1}
    ) as resp:
        assert resp.status_code == 200, resp.text
        assert "text/event-stream" in resp.headers.get("content-type", "")
        raw = "".join(resp.iter_text())

    # 解析 SSE 事件
    events = []
    cur_event = None
    for ln in raw.splitlines():
        if ln.startswith("event: "):
            cur_event = ln[7:].strip()
        elif ln.startswith("data: ") and cur_event:
            events.append((cur_event, _json.loads(ln[6:])))
    names = [e[0] for e in events]
    assert names[0] == "scan_start"
    assert "rule_result" in names
    assert "line_result" in names
    assert "alerts" in names and "done" in names
    assert names[-1] == "done"
    # line_result 交叉验证通过（规则未推进 + LLM 判定推进 → pending，因为规则说没推进）
    # 这里规则通道没有 last_active_chapter → progressed=False；LLM=True → pending
    for name, data in events:
        if name == "line_result":
            assert data["verdict"] in ("adopt", "pending")


def test_scan_no_api_key_400(story_client, monkeypatch):
    """未配置 API Key：扫描返回 400。"""
    import novel_agent.api.routes_storylines as rs
    import novel_agent.config as _cfg_mod
    real_load = _cfg_mod.load_config
    def fake_load():
        cfg = real_load()
        cfg.llm.api_key = ""
        return cfg
    monkeypatch.setattr(rs, "load_config", fake_load)
    r = story_client.post("/api/storylines/1/storylines/scan", json={"chapter": 1})
    assert r.status_code == 400
