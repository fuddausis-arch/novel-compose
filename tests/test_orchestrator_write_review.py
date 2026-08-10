"""写审循环端到端集成测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.runner import ChapterRunner


@pytest.fixture
def make_runner(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻", summary="末日")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    runners = []

    def _make(llm_client=None, auditor=None):
        runner = ChapterRunner(tmp_config, repo=r, llm_client=llm_client, auditor=auditor)
        runners.append(runner)
        return runner

    yield _make
    for rn in runners:
        # _aio_conn 在 _ensure_checkpointer 中创建，可能为 None
        if getattr(rn, "_aio_conn", None) is not None:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(rn._aio_conn.close())
                else:
                    loop.run_until_complete(rn._aio_conn.close())
            except Exception:
                pass
    db.close()


# 真实中文段落（避免触发 deslop 确定性检测的 long-sentence-repetition）
_REAL_PARAGRAPHS = [
    "刘洋推开车间的门，机油味扑面而来。发动机的轰鸣声在四面墙壁间回荡。他擦了擦手上的油污，拿起扳手走向那台老旧的拖拉机。",
    "拖拉机停在角落，锈迹爬满轮毂。他蹲下身子，检查底部的漏油处。远处传来几声犬吠，打破了厂区清晨的寂静。",
    "他皱起眉头，把扳手塞进口袋。这破机器修了三回，每次都是新问题。油封老化，螺栓滑丝，冷却液也漏得厉害。",
    "门口传来脚步声。老周探头进来，手里拎着两瓶豆奶。“还忙着呢？”“嗯，再修一会儿。”刘洋没抬头。",
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


@pytest.mark.asyncio
async def test_write_review_pass_on_first_audit(make_runner):
    """审计一次达标 → style_refine → save → summarize 全流程。"""
    mock_llm = MagicMock()
    mock_llm.config = MagicMock(temperature=0.8)
    # 用 system prompt 区分各节点返回值：writer/polish 返回真实草稿，
    # summarize 返回校验 JSON，world_engine/context_trimmer/post_hoc 返回空 JSON（触发优雅跳过）。
    from novel_agent.orchestrator.prompts import STYLE_REFINE_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT

    async def _mock_generate(*args, **kwargs):
        sys = kwargs.get("system") or ""
        if "校验助手" in sys:  # summarize
            return '{"core_events":"事件","characters_present":"刘洋"}'
        if sys == WRITER_SYSTEM_PROMPT or sys == STYLE_REFINE_SYSTEM_PROMPT:
            return _REAL_DRAFT
        return "{}"

    mock_llm.generate = AsyncMock(side_effect=_mock_generate)
    mock_auditor = MagicMock()
    mock_auditor.audit = AsyncMock(return_value=AuditReport(
        passed=True, overall_score=85, summary="达标"))
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    # mock langgraph interrupt 让 human_review 自动 approve
    # mock _load_random_human_chapter 返回 None，让 analyze_style 跳过 LLM 调用
    with patch("langgraph.types.interrupt", return_value="approve"), \
         patch("novel_agent.orchestrator.nodes._load_random_human_chapter", return_value=None):
        result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    # post_hoc 节点会再 +1，故最终为 2
    assert result["review_iterations"] == 2
    assert "刘洋" in runner.recall.read_chapter_text(1)
    assert runner.repo.get_chapter_summary(1) is not None


@pytest.mark.asyncio
async def test_write_review_rewrite_once_then_pass(make_runner):
    """审计不达标 → 重写 → 再审达标。"""
    mock_llm = MagicMock()
    mock_llm.config = MagicMock(temperature=0.8)
    from novel_agent.orchestrator.prompts import STYLE_REFINE_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT

    async def _mock_generate(*args, **kwargs):
        sys = kwargs.get("system") or ""
        if "校验助手" in sys:  # summarize
            return '{"core_events":"事件"}'
        if sys == WRITER_SYSTEM_PROMPT or sys == STYLE_REFINE_SYSTEM_PROMPT:
            return _REAL_DRAFT
        return "{}"

    mock_llm.generate = AsyncMock(side_effect=_mock_generate)
    mock_auditor = MagicMock()
    mock_auditor.audit = AsyncMock(side_effect=[
        AuditReport(passed=False, overall_score=50, issues=[
            Issue(dimension="人物OOC", severity="critical", message="不符")],
            suggestions=["重写对话"]),  # 第一次审：不达标
        AuditReport(passed=True, overall_score=85, summary="达标"),  # 第二次：达标
    ])
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    # mock langgraph interrupt 让 human_review 自动 approve
    # mock _load_random_human_chapter 返回 None，让 analyze_style 跳过 LLM 调用
    with patch("langgraph.types.interrupt", return_value="approve"), \
         patch("novel_agent.orchestrator.nodes._load_random_human_chapter", return_value=None):
        result = await runner.run(chapter=1, title="第一章")

    assert result["status"] == "completed"
    # write + 1 次 rewrite + post_hoc = 3
    assert result["review_iterations"] == 3
    assert result["draft_version"] == 2


@pytest.mark.asyncio
async def test_write_review_fail_after_three(make_runner):
    """连续审计不达标 → 降级接受（连续2轮无改善或超 max_iterations=4），继续 style_refine。"""
    mock_llm = MagicMock()
    # 用函数返回 side_effect，避免调用次数不匹配导致 StopAsyncIteration
    call_count = {"n": 0}

    async def _mock_generate(*args, **kwargs):
        call_count["n"] += 1
        # 用 system prompt 区分：summarize 的 system 含"校验助手"
        sys = kwargs.get("system") or ""
        if "校验助手" in sys:
            return '{"core_events":"事件"}'
        # write/rewrite 返回真实草稿
        return _REAL_DRAFT

    mock_llm.generate = AsyncMock(side_effect=_mock_generate)
    mock_llm.config = MagicMock(temperature=0.8)
    mock_auditor = MagicMock()
    fail_report = AuditReport(passed=False, overall_score=40, summary="始终不达标")
    mock_auditor.audit = AsyncMock(return_value=fail_report)
    runner = make_runner(llm_client=mock_llm, auditor=mock_auditor)

    # mock langgraph interrupt 让 human_review 自动 approve（降级路径不走人审，但保险起见）
    # mock _load_random_human_chapter 返回 None，让 analyze_style 跳过 LLM 调用
    with patch("langgraph.types.interrupt", return_value="approve"), \
         patch("novel_agent.orchestrator.nodes._load_random_human_chapter", return_value=None):
        result = await runner.run(chapter=1, title="第一章")

    # 降级后 status 仍为 completed（不丢弃章节）
    assert result["status"] == "completed"
    # 至少经过 2 次审计（write + 至少 1 次 rewrite）
    assert result["review_iterations"] >= 2
