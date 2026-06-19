"""测试仓储 CRUD。"""
import pytest

from novel_agent.bible.database import SessionLocal, engine
from novel_agent.bible.models import Base, Project, Character, Foreshadow, TruthEvent
from novel_agent.bible.repository import BibleRepository


@pytest.fixture
def repo():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # 建一个项目
    p = Project(title="测试小说", genre="科幻")
    db.add(p)
    db.commit()
    db.refresh(p)
    yield BibleRepository(db, project_id=p.id)
    db.close()


def test_create_character(repo):
    c = repo.create_character(name="刘洋", role="主角", personality="冷静")
    assert c.id is not None
    assert c.name == "刘洋"


def test_character_importance(repo):
    c = repo.create_character(name="刘洋", role="主角", importance="主角")
    assert c.importance == "主角"
    c2 = repo.get_character("刘洋")
    assert c2.importance == "主角"


def test_faction_tier(repo):
    f = repo.create_faction(name="光明教会", type="宗教", tier="顶级势力")
    assert f.tier == "顶级势力"


def test_monster_tier(repo):
    m = repo.create_monster(name="深渊魔狼", species="魔兽", tier="精英")
    assert m.tier == "精英"


def test_create_foreshadow(repo):
    f = repo.create_foreshadow(
        foreshadow_id="S-001", tier="short", plant_chapter=1,
        description="修理厂地下室神秘文物箱", planned_resolve_chapter=3,
    )
    assert f.status == "pending"
    assert f.foreshadow_id == "S-001"


def test_update_foreshadow_status(repo):
    f = repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
    repo.update_foreshadow_status("S-001", "planted")
    f2 = repo.get_foreshadow("S-001")
    assert f2.status == "planted"


def test_append_truth_event(repo):
    repo.append_event(chapter=1, type="foreshadow_planted", entity_id="S-001",
                      payload={"method": "对话暗示"})
    events = repo.list_events(chapter=1)
    assert len(events) == 1
    assert events[0].type == "foreshadow_planted"
    assert events[0].payload["method"] == "对话暗示"


def test_get_pending_foreshadows(repo):
    repo.create_foreshadow(foreshadow_id="S-001", tier="short", plant_chapter=1)
    repo.create_foreshadow(foreshadow_id="S-002", tier="short", plant_chapter=2)
    repo.update_foreshadow_status("S-001", "planted")
    pending = repo.get_foreshadows_by_status("pending")
    assert len(pending) == 1
    assert pending[0].foreshadow_id == "S-002"


def test_faction_crud(repo):
    f = repo.create_faction(name="光明教会", type="宗教", alignment="守序善良")
    assert f.id is not None
    assert repo.get_faction(f.id).name == "光明教会"
    assert len(repo.list_factions()) == 1
    assert repo.delete_faction(f.id) is True
    assert repo.get_faction(f.id) is None


def test_faction_relationship_cascade(repo):
    f1 = repo.create_faction(name="光明教会")
    f2 = repo.create_faction(name="黑暗议会")
    rel = repo.create_faction_relationship(source_faction_id=f1.id, target_faction_id=f2.id,
                                           relation_type="敌对", strength=5)
    assert rel.id is not None
    assert len(repo.list_faction_relationships()) == 1
    assert repo.delete_faction(f1.id) is True
    assert repo.list_faction_relationships() == []


def test_character_relationship_crud(repo):
    r = repo.create_character_relationship(source_character="刘洋", target_character="林夏",
                                           relation_type="合作", strength=3)
    assert r.id is not None
    assert repo.get_character_relationship(r.id).source_character == "刘洋"
    assert len(repo.list_character_relationships()) == 1
    assert repo.delete_character_relationship(r.id) is True
    assert repo.get_character_relationship(r.id) is None


def test_monster_crud(repo):
    m = repo.create_monster(name="深渊魔狼", species="魔兽", rank="B")
    assert m.id is not None
    assert repo.get_monster(m.id).name == "深渊魔狼"
    assert len(repo.list_monsters()) == 1
    assert repo.delete_monster(m.id) is True
    assert repo.get_monster(m.id) is None


def test_entity_appearance_crud(repo):
    c = repo.create_character(name="刘洋", role="主角")
    a = repo.create_entity_appearance(
        entity_type="character", entity_id=c.name, chapter=1,
        role_in_chapter="lead", context_snippet="开篇出场")
    assert a.id is not None
    assert repo.get_entity_appearance(a.id).entity_id == c.name
    assert len(repo.list_entity_appearances(chapter=1)) == 1
    assert len(repo.get_appearances_for_entity("character", c.name)) == 1
    assert repo.delete_entity_appearance(a.id) is True
    assert repo.get_entity_appearance(a.id) is None


def test_record_appearances(repo):
    c = repo.create_character(name="刘洋", role="主角")
    f = repo.create_faction(name="光明教会")
    created = repo.record_appearances(2, [
        {"entity_type": "character", "entity_id": c.name, "role_in_chapter": "lead", "context_snippet": "主导"},
        {"entity_type": "faction", "entity_id": str(f.id), "role_in_chapter": "background"},
    ])
    assert len(created) == 2
    assert len(repo.list_entity_appearances(chapter=2)) == 2
    # 重复记录应覆盖
    created2 = repo.record_appearances(2, [
        {"entity_type": "character", "entity_id": c.name, "role_in_chapter": "mention"},
    ])
    assert len(created2) == 1
    assert len(repo.list_entity_appearances(chapter=2)) == 1


def test_get_active_entities_for_chapter(repo):
    c = repo.create_character(name="刘洋", role="主角", importance="主角",
                              current_location="东海市", current_emotion="愤怒")
    repo.create_entity_appearance(entity_type="character", entity_id=c.name,
                                  chapter=3, role_in_chapter="lead")
    repo.create_entity_appearance(entity_type="character", entity_id=c.name,
                                  chapter=4, role_in_chapter="participant")
    repo.append_event(chapter=4, type="relationship_change",
                      entity_id="刘洋-林夏", payload={"relation_type": "合作"})
    active = repo.get_active_entities_for_chapter(5, window=3)
    assert len(active["characters"]) == 1
    assert active["characters"][0]["name"] == "刘洋"
    assert active["characters"][0]["importance"] == "主角"
