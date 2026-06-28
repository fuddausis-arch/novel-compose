"""测试 M3 新增节点：audit/polish/route_after_audit。"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.orchestrator.state import ChapterGenState


# 真实中文段落（多段不同内容，避免触发 deslop 的 long-sentence-repetition 检测）
# 注意：避免反复使用仿佛/缓缓/斑驳/这一刻等 AI 限频词（每章上限1次或0次）
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
    "路上遇到一辆抛锚的小轿车。司机急得团团转。刘洋停车看了一眼，是电瓶没电了。他用三轮车的电瓶搭了一下，车子启动了。",
    "司机要给钱，他摆摆手不要。司机硬塞给他一包烟。他收下了。回到车间，天已经快黑了。他把零件分类放好。",
    "晚饭后他坐在门口抽烟，看远处山影渐沉。星星一颗一颗亮起来。狗在脚边趴着，尾巴偶尔扫一下地面。",
    "他想起小时候，父亲也是这样坐在门口抽烟。那时候家里穷，父亲修了一辈子拖拉机。这门手艺传到他手上，第三代了。",
    "第二天他起得早，先把昨天买的零件换上。新油封装好，皮带调紧，滤芯换新。他擦擦手，发动一下试试。",
    "引擎转得顺多了。他满意地拍拍机身，像是拍一匹老马的脖子。这机器还能再战几年。他心想。",
    "下午他帮邻居修了辆自行车。链条掉了几次，他调了一下后拨，好了。邻居送他一兜子鸡蛋，他推辞不过收下了。",
    "傍晚下了一场暴雨，车间里漏了几个地方。他搬来盆子接水，叮咚叮咚响。他苦笑，明年得把屋顶翻修一下。",
    "夜里他做了一个梦，梦见父亲坐在拖拉机上，冲他招手。醒来枕头湿了一片。他翻了个身，又沉沉睡去。",
    "清晨他爬起来，先去菜地看了看。黄瓜结了不少，西红柿也红了。他摘了几根，准备中午下饭。",
    "回到车间，他开始整理昨天剩下的活。一台收音机坏了，他拆开看了下，是线圈松了。三两下修好。声音又响了起来。",
    "中午老周来串门，带了一瓶烧酒。两人坐在门口对饮，聊起年轻时的事。老周说他当年也想当 mechanic，没成。",
    "下午他骑着三轮车去隔壁村帮人修水泵。水泵卡死了，他拆开清理了一下杂质，装回去，好了。人家给了他一只鸡。",
    "回家的路上，天色突变，乌云压顶。他加快速度，雨还是淋了下来。到家时浑身湿透，鸡倒是被雨布盖得好好的。",
    "晚上他炖了那只鸡，香味飘出老远。老周闻味过来，端着饭碗。两人就着一锅鸡，把那瓶烧酒喝了个底朝天。",
    "第二天他醒来时头还有点疼。喝了碗稀饭，才缓过劲来。他决定今天歇一天，不修东西了。难得清闲。",
]
_REAL_DRAFT = "\n\n".join(_REAL_PARAGRAPHS * 2)  # 32 段 × 2，约 2700+ 字（超过 word_min=2200）


@pytest.fixture
def repo(tmp_config):
    from novel_agent.bible import database as db_mod
    set_config(tmp_config)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title="测试", genre="科幻")
    db.add(p); db.commit(); db.refresh(p)
    r = BibleRepository(db, project_id=p.id)
    r.create_character(name="刘洋", role="主角")
    yield r
    db.close()


@pytest.mark.asyncio
async def test_audit_node(repo):
    from novel_agent.orchestrator.nodes import audit_chapter
    from novel_agent.audit.schemas import AuditReport
    mock_auditor = AsyncMock()
    mock_auditor.audit = AsyncMock(return_value=AuditReport(
        passed=True, overall_score=85, summary="达标"))
    state = ChapterGenState(
        project_id=repo.project_id, chapter=1, title="第一章",
        draft=_REAL_DRAFT, draft_version=1, review_iterations=0,
    )
    result = await audit_chapter(state, auditor=mock_auditor, repo=repo)
    assert result["status"] == "audited"
    assert result["review_iterations"] == 1


@pytest.mark.asyncio
async def test_polish_node():
    from novel_agent.orchestrator.nodes import polish_chapter
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=_REAL_DRAFT)
    state = ChapterGenState(chapter=1, title="x", draft=_REAL_DRAFT, status="audited")
    result = await polish_chapter(state, llm_client=mock_client)
    assert "刘洋" in result["polished"]
    assert result["status"] == "polished"


def test_route_after_audit_pass():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": True, "overall_score": 85, "issues": []},
        review_iterations=1,
    )
    # 通过审计→走人审（style_refine 映射到 human_review 节点）
    assert route_after_audit(state) == "style_refine"


def test_route_after_audit_fail_under_limit():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=1,
    )
    assert route_after_audit(state) == "rewrite"


def test_route_after_audit_fail_over_limit():
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=3,
    )
    # 重写上限到（>=max_iterations=4 才降级，3 次仍 rewrite）
    # 注意：max_iterations=4，所以 review_iterations=3 仍返回 rewrite
    assert route_after_audit(state) == "rewrite"


def test_route_after_audit_degrade_after_max_iterations():
    """超过 max_iterations（4 轮）后降级→skip_review。"""
    from novel_agent.orchestrator.nodes import route_after_audit
    state = ChapterGenState(
        audit_report={"passed": False, "overall_score": 50, "issues": []},
        review_iterations=4,
    )
    assert route_after_audit(state) == "skip_review"


@pytest.mark.asyncio
async def test_rewrite_node():
    from novel_agent.orchestrator.nodes import rewrite_chapter
    from novel_agent.audit.schemas import AuditReport, Issue
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value="重写草稿")
    state = ChapterGenState(
        chapter=1, title="第一章", context="设定", draft="旧草稿",
        draft_version=1, review_iterations=1,
        audit_report=AuditReport(
            passed=False, overall_score=50,
            issues=[Issue(dimension="人物OOC", severity="critical", message="不符")],
            suggestions=["重写对话"],
        ).model_dump(),
    )
    result = await rewrite_chapter(state, llm_client=mock_client)
    assert result["draft"] == "重写草稿"
    assert result["draft_version"] == 2
    assert result["status"] == "drafted"


def test_human_review_node_returns_pending():
    """人审节点使用 langgraph interrupt() 暂停，测试时 mock 为 approve。"""
    from unittest.mock import patch
    from novel_agent.orchestrator.nodes import human_review
    state = ChapterGenState(chapter=1, title="x", draft="正文", status="audited")
    # mock interrupt 返回 "approve"
    with patch("langgraph.types.interrupt", return_value="approve"):
        result = human_review(state)
    assert result["review_decision"] == "approve"
    assert result["status"] == "reviewed"


def test_route_after_review_approve():
    """人审通过（默认/approve）→style_refine。"""
    from novel_agent.orchestrator.graph import route_after_review
    state = ChapterGenState(review_decision="approve")
    assert route_after_review(state) == "style_refine"
    # 未设置决策时默认通过
    assert route_after_review(ChapterGenState()) == "style_refine"


def test_route_after_review_reject():
    """人审驳回→rewrite。"""
    from novel_agent.orchestrator.graph import route_after_review
    state = ChapterGenState(review_decision="reject")
    assert route_after_review(state) == "rewrite"
