"""测试 API：项目/规划/章节/圣经（mock LLM）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA", str(tmp_path / "project_data"))
    monkeypatch.setenv("NOVEL_CONFIG_PATH", str(tmp_path / "test_config.yaml"))
    (tmp_path / "project_data").mkdir()
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


# ---- 项目 API ----

def test_create_project(client):
    resp = client.post("/api/projects", json={"title": "测试", "genre": "科幻", "summary": "末日"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "测试"
    assert data["id"] >= 1


def test_list_projects(client):
    client.post("/api/projects", json={"title": "p1"})
    client.post("/api/projects", json={"title": "p2"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_get_project(client):
    r = client.post("/api/projects", json={"title": "x"}).json()
    resp = client.get(f"/api/projects/{r['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "x"


# ---- 圣经 API ----

def test_bible_characters(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    # 直接建角色（绕过规划）
    from novel_agent.bible.database import SessionLocal, set_config
    from novel_agent.bible.models import Base, Character
    from novel_agent.config import load_config
    cfg = load_config(); set_config(cfg)
    from novel_agent.bible import database as db_mod
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    db.add(Character(project_id=pid, name="刘洋", role="主角"))
    db.commit(); db.close()
    resp = client.get(f"/api/bible/{pid}/characters")
    assert resp.status_code == 200
    assert any(c["name"] == "刘洋" for c in resp.json())


def test_bible_foreshadows_empty(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    resp = client.get(f"/api/bible/{pid}/foreshadows")
    assert resp.status_code == 200
    assert resp.json() == []


def test_bible_factions(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/factions").json() == []
    r = client.post(f"/api/bible/{pid}/factions", json={"name": "光明教会", "type": "宗教"})
    assert r.status_code == 200
    fid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/factions").json()[0]["name"] == "光明教会"
    r = client.put(f"/api/bible/{pid}/factions/{fid}", json={"name": "光明教会", "type": "神殿"})
    assert r.status_code == 200
    assert r.json()["type"] == "神殿"
    assert client.delete(f"/api/bible/{pid}/factions/{fid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/factions").json() == []


def test_bible_faction_relationships(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    f1 = client.post(f"/api/bible/{pid}/factions", json={"name": "A"}).json()["id"]
    f2 = client.post(f"/api/bible/{pid}/factions", json={"name": "B"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/faction-relationships").json() == []
    r = client.post(f"/api/bible/{pid}/faction-relationships",
                    json={"source_faction_id": f1, "target_faction_id": f2, "relation_type": "敌对"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/faction-relationships").json()[0]["relation_type"] == "敌对"
    r = client.put(f"/api/bible/{pid}/faction-relationships/{rid}",
                   json={"source_faction_id": f1, "target_faction_id": f2, "relation_type": "同盟"})
    assert r.status_code == 200
    assert r.json()["relation_type"] == "同盟"
    assert client.delete(f"/api/bible/{pid}/faction-relationships/{rid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/faction-relationships").json() == []


def test_bible_character_relationships(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/character-relationships").json() == []
    r = client.post(f"/api/bible/{pid}/character-relationships",
                    json={"source_character": "刘洋", "target_character": "林夏", "relation_type": "合作"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/character-relationships").json()[0]["target_character"] == "林夏"
    r = client.put(f"/api/bible/{pid}/character-relationships/{rid}",
                   json={"source_character": "刘洋", "target_character": "林夏", "relation_type": "挚友"})
    assert r.status_code == 200
    assert r.json()["relation_type"] == "挚友"
    assert client.delete(f"/api/bible/{pid}/character-relationships/{rid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/character-relationships").json() == []


def test_bible_monsters(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    assert client.get(f"/api/bible/{pid}/monsters").json() == []
    r = client.post(f"/api/bible/{pid}/monsters", json={"name": "魔狼", "rank": "B"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert client.get(f"/api/bible/{pid}/monsters").json()[0]["name"] == "魔狼"
    r = client.put(f"/api/bible/{pid}/monsters/{mid}", json={"name": "魔狼", "rank": "A"})
    assert r.status_code == 200
    assert r.json()["rank"] == "A"
    assert client.delete(f"/api/bible/{pid}/monsters/{mid}").status_code == 200
    assert client.get(f"/api/bible/{pid}/monsters").json() == []


def test_bible_tier_and_importance(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    r = client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋", "importance": "主角"})
    assert r.status_code == 200
    assert r.json()["importance"] == "主角"
    r = client.post(f"/api/bible/{pid}/factions", json={"name": "光明教会", "tier": "顶级势力"})
    assert r.status_code == 200
    assert r.json()["tier"] == "顶级势力"
    r = client.post(f"/api/bible/{pid}/monsters", json={"name": "魔狼", "tier": "精英"})
    assert r.status_code == 200
    assert r.json()["tier"] == "精英"


def test_entity_appearances_api(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋"})
    r = client.post(f"/api/bible/{pid}/entity-appearances",
                    json={"entity_type": "character", "entity_id": "刘洋",
                          "chapter": 1, "role_in_chapter": "lead"})
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["entity_id"] == "刘洋"
    r = client.get(f"/api/bible/{pid}/entity-appearances?entity_type=character&chapter=1")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r = client.put(f"/api/bible/{pid}/entity-appearances/{aid}",
                   json={"role_in_chapter": "participant"})
    assert r.status_code == 200
    assert r.json()["role_in_chapter"] == "participant"
    assert client.delete(f"/api/bible/{pid}/entity-appearances/{aid}").status_code == 200


def test_record_appearances_api(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋"})
    r = client.post(f"/api/bible/{pid}/chapters/2/record-appearances",
                    json={"appearances": [{"entity_type": "character", "entity_id": "刘洋",
                                           "chapter": 2, "role_in_chapter": "lead"}]})
    assert r.status_code == 200
    assert r.json()["recorded"] == 1


def test_generate_faction_api(client):
    pid = client.post("/api/projects", json={"title": "x", "genre": "玄幻"}).json()["id"]
    with patch("novel_agent.llm.client.LLMClient") as MockLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(return_value='{"name":"暗影盟","tier":"一流势力","type":"刺客组织","alignment":"中立邪恶","description":"暗中行事"}')
        MockLLM.return_value = mock
        r = client.post(f"/api/bible/{pid}/generate-faction",
                        json={"name_hint": "暗影盟", "type": "刺客组织"})
    assert r.status_code == 200
    assert r.json()["name"] == "暗影盟"
    assert r.json()["tier"] == "一流势力"


def test_generate_monster_api(client):
    pid = client.post("/api/projects", json={"title": "x", "genre": "玄幻"}).json()["id"]
    with patch("novel_agent.llm.client.LLMClient") as MockLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(return_value='{"name":"深渊魔狼","tier":"精英","species":"魔兽","rank":"B","attributes":"暗属性"}')
        MockLLM.return_value = mock
        r = client.post(f"/api/bible/{pid}/generate-monster",
                        json={"name_hint": "深渊魔狼", "species": "魔兽"})
    assert r.status_code == 200
    assert r.json()["name"] == "深渊魔狼"
    assert r.json()["tier"] == "精英"


def test_generate_character_relationship_api(client):
    pid = client.post("/api/projects", json={"title": "x", "genre": "玄幻"}).json()["id"]
    client.post(f"/api/bible/{pid}/characters", json={"name": "刘洋"})
    client.post(f"/api/bible/{pid}/characters", json={"name": "林夏"})
    with patch("novel_agent.llm.client.LLMClient") as MockLLM:
        mock = MagicMock()
        mock.generate = AsyncMock(return_value='{"relation_type":"合作","relation_subtype":"战友","strength":7,"description":"并肩作战"}')
        MockLLM.return_value = mock
        r = client.post(f"/api/bible/{pid}/generate-character-relationship",
                        json={"source_character": "刘洋", "target_character": "林夏",
                              "relation_type_hint": "合作"})
    assert r.status_code == 200
    assert r.json()["relation_type"] == "合作"
    assert r.json()["source_character"] == "刘洋"


# ---- 章节 API（mock LLM + auditor） ----

# 真实中文段落（避免触发 deslop 确定性检测的 adjacent-repetition）
_REAL_PARAGRAPHS = [
    "刘洋推开车间的门，机油味扑面而来。发动机的轰鸣声在四面墙壁间回荡。他擦了擦手上的油污，拿起扳手走向那台老旧的拖拉机。",
    "拖拉机停在角落，锈迹爬满轮毂。他蹲下身子，检查底部的漏油处。远处传来几声犬吠，打破了厂区清晨的寂静。",
    "他皱起眉头，把扳手塞进口袋。这破机器修了三回，每次都是新问题。油封老化，螺栓滑丝，冷却液也漏得厉害。",
    "门口传来脚步声。老周探头进来，手里拎着两瓶豆奶。还忙着呢？嗯，再修一会儿。刘洋没抬头。",
    "阳光透过破窗斜射进来，照在沾满油渍的水泥地上。他直起腰，活动了一下僵硬的肩膀。蚊子在耳边嗡嗡作响。",
    "工具箱里乱七八糟，扳手、螺丝刀、钳子堆在一起。他翻出那把十字螺丝刀，开始拆卸左侧的挡泥板。螺母锈死了，拧不动。",
    "他从抽屉里翻出一罐除锈剂，喷了几下，等了片刻，再拧。这次螺母松动了。他把挡泥板卸下来，靠墙放好。",
    "雨开始下了，雨水顺着檐角滴落，砸在水泥地上。他听着雨声，心里盘算着该换哪些零件。油封、皮带、滤芯，得去镇上进货。",
    "午后的车间闷热难当。背心早被汗水浸透。他拧紧最后一颗螺栓，长舒一口气，拍了拍拖拉机褪色的外壳。",
    "灰尘在光柱里飞舞，像细碎的金粉飘落下来。他坐下来，点了一根烟，烟雾在空气里盘旋上升。时间慢了下来。",
    "晚饭是馒头配咸菜，他就着开水吃完。窗外的雨还在下，敲打着铁皮屋顶。他翻开账本，记下今天的开销。",
    "夜里他睡在车间的小床上。蚊子咬得睡不着，他索性爬起来，借着月光继续研究那台柴油机的图纸。",
    "天还没亮，公鸡先叫了。他披上外套，去屋后的小溪洗了把脸。水冰凉刺骨，人一下子清醒过来。",
    "他回到车间，发动拖拉机试试。引擎咳嗽了几声，终于启动。轰鸣声此刻听来竟像晨曲。他满意地笑了。",
    "邻居老李过来借工具。两人闲聊了几句今年的收成。老李说今年雨水多，麦子怕是要减产。刘洋点点头，没说话。",
    "中午他去了趟镇上。五金店的老板娘认识他，给他打了九折。他把零件装上三轮车，绑牢，慢悠悠骑回去。",
]
_REAL_DRAFT = "\n\n".join(_REAL_PARAGRAPHS * 2)


def test_generate_chapter(client):
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))), \
         patch("langgraph.types.interrupt", return_value="approve"), \
         patch("novel_agent.orchestrator.nodes._load_random_human_chapter", return_value=None):
        mock = MagicMock()

        # 编排管线新增 world_engine/context_trimmer/analyze_style/summarize/post_hoc 节点，
        # 每个节点都调用 generate。write 节点期待正文，其余节点期待 JSON。
        # 按 system prompt 区分：write 用 WRITER_SYSTEM_PROMPT。
        async def fake_generate(prompt, system=None, **kw):
            from novel_agent.orchestrator.prompts import WRITER_SYSTEM_PROMPT
            if system == WRITER_SYSTEM_PROMPT:
                return _REAL_DRAFT
            return '{"ok":true}'

        mock.generate = AsyncMock(side_effect=fake_generate)
        mock.close = AsyncMock()
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        resp = client.post("/api/chapters/generate", json={
            "project_id": pid, "chapter": 1, "title": "第一章"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


# ---- 配置 API ----

def test_get_llm_config(client):
    resp = client.get("/api/config/llm")
    assert resp.status_code == 200
    data = resp.json()
    assert "base_url" in data
    assert "api_key" in data
    assert "model" in data


def test_update_llm_config(client):
    resp = client.put("/api/config/llm", json={
        "base_url": "https://openai.local/v1",
        "model": "gpt-local-model",
        "temperature": 0.5,
    })
    assert resp.status_code == 200
    assert resp.json()["saved"] is True

    resp = client.get("/api/config/llm")
    data = resp.json()
    assert data["base_url"] == "https://openai.local/v1"
    assert data["model"] == "gpt-local-model"
    assert data["temperature"] == 0.5
