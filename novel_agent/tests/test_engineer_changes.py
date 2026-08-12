"""工程师改动深度测试：world_structure district 层级 + 时间线兜底逻辑 + P0 系列配置。"""
from __future__ import annotations

import json

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


# ── P0-2 标签+权重双机制（工程师改动）─────────────────────

from novel_agent.memory.core import CoreMemoryAssembler, sort_assets_by_tag_weight


class _Asset:
    """轻量资产桩：模拟 ORM 对象（name/tags/weight + 扩展属性）。"""

    def __init__(self, name="", tags=None, weight=50, **kw):
        self.name = name
        self.tags = tags or []
        self.weight = weight
        for k, v in kw.items():
            setattr(self, k, v)


def test_sort_tag_weight_hit_first_desc():
    """命中（标签出现在上下文）的在前，同标签内 weight 降序，未命中的垫底。"""
    items = [
        _Asset(name="张三", tags=["宗门"], weight=30),
        _Asset(name="李四", tags=["宗门"], weight=90),
        _Asset(name="王五", tags=["散修"], weight=80),
    ]
    sorted_items, hits = sort_assets_by_tag_weight(items, "本章细纲：宗门大会")
    names = [x.name for x in sorted_items]
    assert names.index("李四") < names.index("张三") < names.index("王五")
    assert {x.name for x in hits} == {"李四", "张三"}


def test_sort_tag_weight_name_hit_strong():
    """名称命中=强命中，即使未打标签也排前。"""
    items = [_Asset(name="魔渊"), _Asset(name="青云宗")]
    sorted_items, hits = sort_assets_by_tag_weight(items, "第5章 勇闯魔渊")
    assert sorted_items[0].name == "魔渊"
    assert [x.name for x in hits] == ["魔渊"]


def test_sort_tag_weight_dict_compat():
    """活跃实体是 dict 列表，排序函数需兼容 dict 输入。"""
    items = [{"name": "火系", "tags": ["火"], "weight": 10},
             {"name": "冰系", "tags": ["冰"], "weight": 80}]
    sorted_items, hits = sort_assets_by_tag_weight(items, "本章：烈火焚城")
    assert sorted_items[0]["name"] == "火系"
    assert [x["name"] for x in hits] == ["火系"]


@pytest.fixture()
def repo_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/p02.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _make_repo(s, project_id=99):
    from novel_agent.bible.repository import BibleRepository
    s.add(m.Project(id=project_id, title="测试书"))
    s.commit()
    return BibleRepository(db=s, project_id=project_id)


def test_p02_repo_readwrite_tags_weight(repo_session):
    """repository 读写 tags/weight：create/update 透传生效。"""
    repo = _make_repo(repo_session)
    c = repo.create_character(name="沈青", role="主角", tags=["宗门"], weight=95)
    repo_session.commit()
    got = repo.get_character("沈青")
    assert got.tags == ["宗门"]
    assert got.weight == 95
    repo.update_character("沈青", weight=60)
    assert repo.get_character("沈青").weight == 60


def test_p02_assemble_tagged_assets_injection(repo_session):
    """标签命中补充段：本章细纲命中副本/地点标签或名称 → 注入，且高权重排前。"""
    repo = _make_repo(repo_session)
    repo_session.add(m.Outline(
        project_id=99, level="chapter", order=1, title="第1章",
        summary="本章：攻打青云宗，主角进入魔渊副本"))
    repo_session.add(m.Instance(project_id=99, name="魔渊试炼", tags=["副本", "魔渊"],
                                weight=90, description="魔渊深处的试炼"))
    repo_session.add(m.Instance(project_id=99, name="灵田", tags=["日常"], weight=10,
                                description="种田日常副本"))
    repo_session.add(m.Location(project_id=99, name="青云宗", tags=["宗门"], weight=80,
                                description="正道第一宗门"))
    repo_session.commit()
    asm = CoreMemoryAssembler(repo)
    text = asm.assemble(chapter=1, max_chars=4000)
    assert "【标签命中设定】" in text
    seg = text[text.index("【标签命中设定】"):]
    assert "魔渊试炼" in seg
    assert "青云宗" in seg
    assert "灵田" not in seg           # 未命中标签的副本不注入
    assert seg.index("魔渊试炼") < seg.index("青云宗")  # weight 90 排在 80 前


def test_p02_world_settings_sorted_by_tag_weight(repo_session):
    """世界观设定按标签命中+权重排序：命中标签的高权重条目排前。"""
    repo = _make_repo(repo_session)
    repo_session.add(m.WorldSetting(project_id=99, category="规则", title="灵气复苏",
                                    content="灵气浓度每十年翻倍", tags=["灵气"], weight=40))
    repo_session.add(m.WorldSetting(project_id=99, category="规则", title="宗门大战",
                                    content="宗门恩怨不可化解", tags=["宗门"], weight=90))
    repo_session.commit()
    asm = CoreMemoryAssembler(repo)
    text = asm.assemble(chapter=1, max_chars=4000)
    assert "宗门大战" in text and "灵气复苏" in text
    assert text.index("宗门大战") < text.index("灵气复苏")


# ── P1-1 过渡写手空转修复（工程师改动）─────────────────────

from novel_agent.workflows.loader import _has_transition_slots


def test_transition_slots_text_marker():
    """骨架文本含 [SLOT_TRANSITION_ 标记 → 有过渡槽。"""
    raw = '{"skeleton": "他没有回头。[SLOT_TRANSITION_场景切换]", "slots": {}}'
    assert _has_transition_slots(raw) is True


def test_transition_slots_in_slots_field():
    """骨架 slots.TRANSITION 非空（文本无标记）→ 有过渡槽。"""
    raw = '{"skeleton": "无标记文本", "slots": {"TRANSITION": ["场景切换"]}}'
    assert _has_transition_slots(raw) is True


def test_transition_slots_absent():
    """骨架无任何过渡槽（历史实测：slots 只有 DIALOGUE/ACTION 等）→ 无过渡槽。"""
    raw = json.dumps({
        "skeleton": "他推开门。[SLOT_DIALOGUE_质问]",
        "slots": {"DIALOGUE": ["质问"], "ACTION": ["推门"]},
    })
    assert _has_transition_slots(raw) is False


def test_transition_slots_empty_or_bad():
    """空串/空 JSON/非法 JSON → 无过渡槽（安全兜底，不抛异常）。"""
    assert _has_transition_slots("") is False
    assert _has_transition_slots("{}") is False
    assert _has_transition_slots("not-json") is False


# ── P1-3 mvp 前置依赖友好报错（工程师改动）─────────────────

from novel_agent.workflows.loader import _mvp_precheck_missing


def test_mvp_precheck_missing_reports_both(tmp_path):
    """空工作区：同时缺 build 与 story-plan 产物，中文可读。"""
    missing = _mvp_precheck_missing(tmp_path)
    assert len(missing) == 2
    assert any("build" in m for m in missing)
    assert any("story-plan" in m for m in missing)


def test_mvp_precheck_ok_when_products_exist(tmp_path):
    """上游产物齐全：前置检查通过（空列表）。"""
    (tmp_path / "meta").mkdir(parents=True)
    (tmp_path / "meta" / "story_plan.md").write_text("plan", encoding="utf-8")
    (tmp_path / "meta" / "world_foundation.md").write_text("wf", encoding="utf-8")
    assert _mvp_precheck_missing(tmp_path) == []
