"""工程师改动深度测试：world_structure district 层级 + 时间线兜底逻辑 + P0 系列配置。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_agent.bible import models as m
from novel_agent.bible.models import Base
from novel_agent.bible.world_structure import (
    TIER_PRIORITY, classify_tier, validate_hierarchy,
)
from novel_agent.config import Config, load_config, save_config


# ── world_structure：district 层级（工程师改动）─────────────


def test_district_classify_new_rules():
    """新增 district 层级：街区/街道/城区后缀归 district。"""
    assert classify_tier("城东安全区") == "district"
    assert classify_tier("商业区") == "district"
    assert classify_tier("老城区") == "district"
    assert classify_tier("地下黑市") == "site"          # 反例保护：市场不算行政区域
    assert classify_tier("蜂巢公寓迷宫") == "dungeon"     # 迷宫不被 district 的"区"误伤
    assert classify_tier("灰烬农场带边缘哨站") == "other"  # 哨站无匹配后缀
    assert classify_tier("主城") == "city"
    assert classify_tier("大唐帝国") == "kingdom"


def test_district_tier_priority_sane():
    """district 位于 city 与 site 之间：city > district > site。"""
    assert TIER_PRIORITY["city"] > TIER_PRIORITY["district"] > TIER_PRIORITY["site"]
    assert TIER_PRIORITY["district"] == 3


def test_validate_city_parent_district_child_ok():
    """城 作为父级、街区 作为子级 → 相邻层级，不报 tier_mismatch。"""
    locations = [
        {"name": "主城", "parent_name": "", "tier": "city"},
        {"name": "城东安全区", "parent_name": "主城", "tier": "district"},
    ]
    issues = validate_hierarchy(locations)
    assert not any(i["issue"] == "tier_mismatch" for i in issues)


def test_validate_cross_level_still_reports():
    """跨级仍然报警：town 不可能作为 kingdom 的父级（7 > 4+1）。"""
    locations = [
        {"name": "大唐帝国", "parent_name": "清水村", "tier": "kingdom"},
        {"name": "清水村", "parent_name": "", "tier": "town"},
    ]
    issues = validate_hierarchy(locations)
    assert any(i["issue"] == "tier_mismatch" for i in issues)


def test_validate_missing_parent_and_cycle_still_detected():
    """原有校验（父缺失/循环引用）不受改动影响。"""
    issues = validate_hierarchy([
        {"name": "孤城", "parent_name": "不存在的城", "tier": "city"},
    ])
    assert any(i["issue"] == "missing_parent" for i in issues)
    issues = validate_hierarchy([
        {"name": "A城", "parent_name": "B城", "tier": "city"},
        {"name": "B城", "parent_name": "A城", "tier": "city"},
    ])
    assert any(i["issue"] == "circular_reference" for i in issues)


# ── 时间线兜底逻辑（工程师改动）────────────────────────────


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def tl_client(db_session):
    from fastapi import FastAPI
    from novel_agent.api.routes_timeline import router, get_db
    app = FastAPI()
    app.include_router(router, prefix="/api/timeline")
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_timeline_character_lane_fallback(db_session, tl_client):
    """无出场记录时：用状态变更聚合"活跃角色"兜底泳道。"""
    db_session.add(m.StateChange(
        project_id=1, entity_type="角色", entity_id="张三",
        chapter=3, field="位置", old_value="城东", new_value="地下黑市",
    ))
    db_session.commit()
    r = tl_client.get("/api/timeline/1")
    assert r.status_code == 200
    lane = r.json()["lanes"]["characters"]
    assert any(x["entity"] == "张三" and x["chapter"] == 3 for x in lane)


def test_timeline_emotion_lane_fallback(db_session, tl_client):
    """无情感弧线记录时：用情绪字段的状态变更兜底情感泳道。"""
    db_session.add(m.StateChange(
        project_id=1, entity_type="角色", entity_id="李四",
        chapter=2, field="emotion", old_value="平静", new_value="愤怒",
    ))
    db_session.add(m.StateChange(
        project_id=1, entity_type="角色", entity_id="王五",
        chapter=2, field="位置", old_value="a", new_value="b",  # 非情绪字段，不应进情感泳道
    ))
    db_session.commit()
    r = tl_client.get("/api/timeline/1")
    lane = r.json()["lanes"]["emotions"]
    assert any(x["character"] == "李四" and x["emotion_after"] == "愤怒" for x in lane)
    assert not any(x["character"] == "王五" for x in lane)


def test_timeline_empty_project_no_crash(db_session, tl_client):
    """空项目：所有泳道为空数组，不崩溃。"""
    r = tl_client.get("/api/timeline/1")
    assert r.status_code == 200
    d = r.json()
    assert d["lanes"]["characters"] == []
    assert d["lanes"]["emotions"] == []
    assert list(d["chapter_range"]) == [0, 0]


def test_timeline_emotion_arc_primary_source(db_session, tl_client):
    """有情感弧线记录时优先用 EmotionArc，不用兜底。"""
    db_session.add(m.EmotionArc(
        project_id=1, chapter=1, character_name="赵六",
        emotion_before="平静", emotion_after="紧张", event="遭遇异兽",
    ))
    db_session.add(m.StateChange(
        project_id=1, entity_type="角色", entity_id="赵六",
        chapter=9, field="emotion", old_value="x", new_value="y",
    ))
    db_session.commit()
    r = tl_client.get("/api/timeline/1")
    lane = r.json()["lanes"]["emotions"]
    assert len(lane) == 1 and lane[0]["character"] == "赵六"
    assert lane[0]["chapter"] == 1  # 来自 EmotionArc，不是兜底的 chapter=9


# ── P0-3 内容题材红线放开开关（工程师改动）─────────────────


def test_content_redline_default_released():
    """默认放开：content_redline_enabled 默认 True（用户拍板内容题材放开）。"""
    cfg = Config()
    assert cfg.content_redline_enabled is True


def test_content_redline_load_from_yaml(tmp_path):
    """load_config 能读 yaml 开关：true 放开 / false 启用拦截 / "false" 字符串按语义解析。"""
    y = tmp_path / "cfg.yaml"
    y.write_text("content_redline_enabled: false\n", encoding="utf-8")
    cfg = load_config(y)
    assert cfg.content_redline_enabled is False

    y.write_text("content_redline_enabled: \"false\"\n", encoding="utf-8")
    cfg = load_config(y)
    assert cfg.content_redline_enabled is False  # 字符串 false 不误判为 True


def test_content_redline_save_roundtrip(tmp_path):
    """save_config 写回开关，再 load 能读回一致值。"""
    y = tmp_path / "cfg.yaml"
    cfg = Config()
    cfg.content_redline_enabled = False
    save_config(cfg, y)
    cfg2 = load_config(y)
    assert cfg2.content_redline_enabled is False
    cfg2.content_redline_enabled = True
    save_config(cfg2, y)
    cfg3 = load_config(y)
    assert cfg3.content_redline_enabled is True
