"""测试 SSE 流式章节生成端点。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from novel_agent.api.app import create_app


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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROJECT_DATA_DIR", str(tmp_path / "project_data"))
    return TestClient(create_app(project_data_dir=tmp_path / "project_data"))


def test_generate_stream_emits_node_events(client):
    """SSE 端点应产出 node 事件序列 + done 事件。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))), \
         patch("langgraph.types.interrupt", return_value="approve"), \
         patch("novel_agent.orchestrator.nodes._load_random_human_chapter", return_value=None):
        mock = MagicMock()
        # 编排管线含 world_engine/context_trimmer/analyze_style/summarize/post_hoc 节点，
        # 每个都调用 generate。write 期待正文，其余期待 JSON。按 system prompt 区分。
        async def fake_generate(prompt, system=None, **kw):
            from novel_agent.orchestrator.prompts import WRITER_SYSTEM_PROMPT
            if system == WRITER_SYSTEM_PROMPT:
                return _REAL_DRAFT
            return '{"ok":true}'
        mock.generate = AsyncMock(side_effect=fake_generate)
        mock.close = AsyncMock()
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        with client.stream("GET", f"/api/chapters/generate/stream?project_id={pid}&chapter=1&title=ch1") as resp:
            assert resp.status_code == 200
            event_types = []
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_types.append(line.split(":", 1)[1].strip())
            assert "node" in event_types
            assert "done" in event_types


def test_generate_stream_node_events_contain_pipeline_stages(client):
    """node 事件应包含 assemble/write/audit 等流水线阶段。"""
    pid = client.post("/api/projects", json={"title": "x"}).json()["id"]
    from novel_agent.audit.schemas import AuditReport
    with patch("novel_agent.orchestrator.runner.LLMClient") as MockLLM, \
         patch("novel_agent.audit.auditor.LLMClient") as MockAuditLLM, \
         patch("novel_agent.audit.auditor.Auditor.audit",
               new=AsyncMock(return_value=AuditReport(passed=True, overall_score=85, summary="ok"))), \
         patch("langgraph.types.interrupt", return_value="approve"), \
         patch("novel_agent.orchestrator.nodes._load_random_human_chapter", return_value=None):
        mock = MagicMock()
        # 编排管线含 world_engine/context_trimmer/analyze_style/summarize/post_hoc 节点，
        # 每个都调用 generate。write 期待正文，其余期待 JSON。按 system prompt 区分。
        async def fake_generate(prompt, system=None, **kw):
            from novel_agent.orchestrator.prompts import WRITER_SYSTEM_PROMPT
            if system == WRITER_SYSTEM_PROMPT:
                return _REAL_DRAFT
            return '{"ok":true}'
        mock.generate = AsyncMock(side_effect=fake_generate)
        mock.close = AsyncMock()
        MockLLM.return_value = mock
        MockAuditLLM.return_value = MagicMock()
        nodes_seen = set()
        with client.stream("GET", f"/api/chapters/generate/stream?project_id={pid}&chapter=1&title=ch1") as resp:
            import json
            current_event = None
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and current_event == "node":
                    try:
                        d = json.loads(line.split(":", 1)[1].strip())
                        nodes_seen.add(d["node"])
                    except Exception:
                        pass
        assert "assemble" in nodes_seen
        assert "write" in nodes_seen
        assert "audit" in nodes_seen
