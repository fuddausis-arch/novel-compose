"""模块C：记忆管理测试（EntityAppearance / 快照 / 级联 / 渐进披露）。

覆盖：
1. record_appearances：删除重建语义、字段白名单过滤
2. get_active_entities_for_chapter：窗口聚合、类型分类
3. build_snapshot：角色裁剪、伏笔上限
4. update_character 改名级联：EntityAppearance 同步改名
5. delete_entity_appearances_for_chapter
6. 跨项目隔离：多项目不串数据
"""
from __future__ import annotations

import pytest

from novel_agent.bible.database import SessionLocal, engine
from novel_agent.bible.models import (
    Base, Project, Character, Foreshadow, EntityAppearance, StateSnapshot,
)
from novel_agent.bible.repository import BibleRepository
from novel_agent.memory.snapshot import build_snapshot, save_snapshot


@pytest.fixture
def repo():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    p = Project(title="测试小说", genre="科幻")
    db.add(p)
    db.commit()
    db.refresh(p)
    yield BibleRepository(db, project_id=p.id)
    db.close()


# ----------------------------------------------------------------------
# record_appearances：删除重建
# ----------------------------------------------------------------------
class TestRecordAppearances:
    def test_delete_and_recreate(self, repo):
        """record_appearances 应删除同章旧记录再插入新记录。"""
        repo.record_appearances(1, [
            {"entity_type": "character", "entity_id": "张三",
             "role_in_chapter": "lead", "context_snippet": "第一次"},
        ])
        repo.record_appearances(1, [
            {"entity_type": "character", "entity_id": "李四",
             "role_in_chapter": "mention", "context_snippet": "第二次"},
        ])
        apps = repo.list_entity_appearances(chapter=1)
        assert len(apps) == 1  # 旧记录已被删除
        assert apps[0].entity_id == "李四"

    def test_fields_whitelist_filtered(self, repo):
        """record_appearances 只保留白名单字段，多余字段被丢弃。"""
        repo.record_appearances(1, [{
            "entity_type": "character", "entity_id": "张三",
            "role_in_chapter": "lead", "context_snippet": "s",
            "evil_injection": "hack", "chapter": 999,  # 白名单外字段
        }])
        app = repo.list_entity_appearances(chapter=1)[0]
        assert app.chapter == 1  # chapter 由参数控制，不来自 dict
        assert not hasattr(app, "evil_injection")

    def test_empty_list_clears_chapter(self, repo):
        """传入空列表应清空该章出场记录。"""
        repo.record_appearances(1, [{"entity_type": "character", "entity_id": "张三"}])
        repo.record_appearances(1, [])
        assert repo.list_entity_appearances(chapter=1) == []

    def test_other_chapter_untouched(self, repo):
        repo.record_appearances(1, [{"entity_type": "character", "entity_id": "张三"}])
        repo.record_appearances(2, [{"entity_type": "character", "entity_id": "李四"}])
        assert len(repo.list_entity_appearances(chapter=1)) == 1
        assert len(repo.list_entity_appearances(chapter=2)) == 1


# ----------------------------------------------------------------------
# get_active_entities_for_chapter：窗口聚合
# ----------------------------------------------------------------------
class TestActiveEntities:
    def test_window_filtering(self, repo):
        for name in ("张三", "李四", "王五"):
            repo.create_character(name=name)
        repo.record_appearances(1, [{"entity_type": "character", "entity_id": "张三"}])
        repo.record_appearances(3, [{"entity_type": "character", "entity_id": "李四"}])
        repo.record_appearances(10, [{"entity_type": "character", "entity_id": "王五"}])
        # window=3，查询 ch3：只看 ch1-3
        active = repo.get_active_entities_for_chapter(3, window=3)
        names = {c["name"] for c in active.get("characters", [])}
        assert "张三" in names and "李四" in names
        assert "王五" not in names

    def test_type_classification(self, repo):
        c = repo.create_character(name="张三")
        f = repo.create_faction(name="光明教会")
        m = repo.create_monster(name="深渊魔狼")
        repo.record_appearances(1, [
            {"entity_type": "character", "entity_id": "张三", "role_in_chapter": "lead"},
            {"entity_type": "faction", "entity_id": str(f.id), "role_in_chapter": "background"},
            {"entity_type": "monster", "entity_id": str(m.id), "role_in_chapter": "mention"},
        ])
        active = repo.get_active_entities_for_chapter(1)
        assert any(x["name"] == "张三" for x in active.get("characters", []))
        assert any(x["name"] == "光明教会" for x in active.get("factions", []))
        assert any(x["name"] == "深渊魔狼" for x in active.get("monsters", []))

    def test_invalid_faction_id_ignored(self, repo):
        repo.record_appearances(1, [
            {"entity_type": "faction", "entity_id": "not-an-int"},
        ])
        active = repo.get_active_entities_for_chapter(1)
        assert active.get("factions") == []

    def test_window_default_3(self, repo):
        for name in ("张三", "李四"):
            repo.create_character(name=name)
        repo.record_appearances(1, [{"entity_type": "character", "entity_id": "张三"}])
        repo.record_appearances(4, [{"entity_type": "character", "entity_id": "李四"}])
        active = repo.get_active_entities_for_chapter(4)  # 默认 window=3 -> ch2-4
        names = {c["name"] for c in active.get("characters", [])}
        assert "李四" in names
        assert "张三" not in names


# ----------------------------------------------------------------------
# build_snapshot / save_snapshot
# ----------------------------------------------------------------------
class TestSnapshot:
    def test_character_cap_15(self, repo):
        """快照最多 15 个角色。"""
        for i in range(20):
            repo.create_character(name=f"角色{i}", role="配角")
        snap = build_snapshot(repo, 1)
        assert len(snap["characters"]) <= 15

    def test_priority_roles_included(self, repo):
        """主角/反派始终在快照中。"""
        repo.create_character(name="主角", role="主角")
        repo.create_character(name="反派", role="反派")
        snap = build_snapshot(repo, 1)
        names = {c["name"] for c in snap["characters"]}
        assert "主角" in names and "反派" in names

    def test_foreshadow_cap_20(self, repo):
        """快照伏笔最多 20 条。"""
        for i in range(25):
            repo.create_foreshadow(foreshadow_id=f"S-{i:03d}", tier="short", plant_chapter=1)
        snap = build_snapshot(repo, 1)
        assert len(snap["foreshadows"]) <= 20

    def test_resolved_foreshadows_excluded(self, repo):
        repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
        repo.create_foreshadow(foreshadow_id="S-002", tier="short", plant_chapter=1)
        # 走合法状态机：pending -> planted -> resolved
        repo.update_foreshadow_status("S-001", "planted")
        repo.update_foreshadow_status("S-001", "resolved")
        snap = build_snapshot(repo, 1)
        ids = [f["id"] for f in snap["foreshadows"]]
        assert "S-001" not in ids
        assert "S-002" in ids

    def test_save_snapshot_replace_same_chapter(self, repo):
        """同章快照重复保存应替换而非累积。"""
        save_snapshot(repo, 1, {"chapter": 1, "characters": []}, drift_score=0)
        save_snapshot(repo, 1, {"chapter": 1, "characters": [{"name": "x"}]}, drift_score=1)
        snaps = repo.db.query(StateSnapshot).filter(
            StateSnapshot.project_id == repo.project_id,
            StateSnapshot.chapter == 1,
        ).all()
        assert len(snaps) == 1
        assert snaps[0].drift_score == 1


# ----------------------------------------------------------------------
# update_character 改名级联
# ----------------------------------------------------------------------
class TestRenameCascade:
    def test_rename_updates_appearances(self, repo):
        repo.create_character(name="张三", role="配角")
        repo.record_appearances(1, [
            {"entity_type": "character", "entity_id": "张三", "role_in_chapter": "mention"},
        ])
        repo.record_appearances(2, [
            {"entity_type": "character", "entity_id": "张三", "role_in_chapter": "lead"},
        ])
        updated = repo.update_character("张三", name="张叁")
        assert updated.name == "张叁"
        apps = repo.list_entity_appearances(entity_type="character", entity_id="张叁")
        assert len(apps) == 2
        assert all(a.entity_id == "张叁" for a in apps)
        # 旧名无残留
        old = repo.list_entity_appearances(entity_type="character", entity_id="张三")
        assert old == []

    def test_rename_does_not_touch_other_chars(self, repo):
        repo.create_character(name="张三")
        repo.create_character(name="李四")
        repo.record_appearances(1, [
            {"entity_type": "character", "entity_id": "张三", "role_in_chapter": "lead"},
            {"entity_type": "character", "entity_id": "李四", "role_in_chapter": "mention"},
        ])
        repo.update_character("张三", name="张叁")
        li = repo.list_entity_appearances(entity_type="character", entity_id="李四")
        assert len(li) == 1 and li[0].entity_id == "李四"

    def test_rename_same_name_noop(self, repo):
        repo.create_character(name="张三")
        repo.record_appearances(1, [{"entity_type": "character", "entity_id": "张三"}])
        repo.update_character("张三", name="张三")
        apps = repo.list_entity_appearances(entity_type="character", entity_id="张三")
        assert len(apps) == 1


# ----------------------------------------------------------------------
# 跨项目隔离
# ----------------------------------------------------------------------
class TestProjectIsolation:
    def test_appearances_isolated(self):
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        p1 = Project(title="项目1")
        p2 = Project(title="项目2")
        db.add_all([p1, p2])
        db.commit()
        db.refresh(p1)
        db.refresh(p2)
        r1 = BibleRepository(db, p1.id)
        r2 = BibleRepository(db, p2.id)
        r1.record_appearances(1, [{"entity_type": "character", "entity_id": "张三"}])
        r2.record_appearances(1, [{"entity_type": "character", "entity_id": "李四"}])
        assert len(r1.list_entity_appearances()) == 1
        assert len(r2.list_entity_appearances()) == 1
        assert r1.list_entity_appearances()[0].entity_id == "张三"
        assert r2.list_entity_appearances()[0].entity_id == "李四"
        db.close()
