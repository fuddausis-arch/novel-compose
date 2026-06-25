"""编排节点函数：每个节点接收 state + 依赖，返回 state 更新。

节点设计为接受依赖注入（repo/llm_client/recall/applier/auditor），
便于测试 mock 和 runner 组装。

M3 扩展：写审分离 + 反馈循环节点（audit/polish/rewrite/summarize）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.audit.validator import (
    run_deterministic_checks, check_pleasure_gap, check_golden_three,
    check_volume_climax,
)
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.memory.core import CoreMemoryAssembler
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.orchestrator.text_utils import clean_chapter_text, _looks_like_json_not_prose
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, SummaryDelta, ForeshadowDelta
from novel_agent.templates.style_guides.few_shot_samples import get_few_shot_for_beat

logger = logging.getLogger(__name__)

WRITER_SYSTEM_PROMPT = (
    "你是一位资深网络小说写手。根据给定的设定和上下文，"
    "创作引人入胜的网文章节正文。\n\n"
    "【核心原则】"
    "你必须严格遵循上下文中提供的已有设定（世界观/角色/伏笔/大纲/前文摘要），"
    "不得凭空捏造与已有设定矛盾的内容。角色性格、位置、情绪状态必须连续，"
    "伏笔状态必须一致，剧情发展必须符合大纲脉络。\n\n"
    "【角色锚点——写出活人味】"
    "主角不是人形容器，是一个活过的人。他的每一个反应都必须有个人历史的影子。"
    "遇到异常时，不要写通用反应（害怕/逃跑/骂脏话），要写'这个人因为经历过X所以会这样反应'。"
    "一个社畜遇到时间停滞会想'甲方催不了了真爽'，一个赌徒遇到危险会算概率，"
    "一个被背叛过的人不会轻易相信引路人——角色的独特思维方式必须压在所有反应底下。\n\n"
    "【禁止文件式设定传递】"
    "设定必须通过对话、场景、角色反应自然展现，禁止用以下方式传递信息："
    "- 角色翻阅文件/报告/实验记录/日记来获取设定（这是AI偷懒）"
    "- 大段旁白直接讲解世界观规则（这是说明书不是小说）"
    "- 老人/导师长篇大论讲解设定（这是NPC发任务）"
    "正确做法：角色在日常场景中'撞见'设定，通过误解→纠正→理解的过程传递信息。\n\n"
    "【对话必须有博弈】"
    "对话不是NPC发任务。两个人说话时必须有：试探、信息不对称、或立场冲突。"
    "禁止单向信息灌输（A说B听B问A答）。"
    "正确的对话：A试探→B反问→A加码→B暴露底线→达成或破裂。"
    "引路人不能只是'告诉你规则然后让你选'，必须有自己的目的和隐藏信息。\n\n"
    "【段落节奏——最重要】"
    "段落是呼吸的单位，不是每句话都自成一段。"
    "正常叙事段落由3-6句组成，句子之间有逻辑关联。"
    "独句段只用于强调、场景切换、或关键对话回应，一章内独句段不超过5处。"
    "一章内必须有长段落（心理描写/环境渲染）、中段落（叙事过渡）、短段落（爆发点），三者交替。"
    "如果连续5段以上都是独句段，就是废稿。\n\n"
    "【节奏呼吸——必须有起伏】"
    "一章不能全程紧张。必须有张有弛：紧张段→松弛段→再紧张。"
    "结尾不要总是悬念炸弹——有时候一个松弛的收尾（主角回家、喝水、想事情）"
    "比又一个'黑影浮现'更有力量。读者需要喘气。\n\n"
    "【句式变化】"
    "长句写心理和环境，中句写叙事和过渡，短句只用于爆发点（战斗高潮/情绪冲击/关键揭示）。"
    "一章内三种句式必须交替出现，形成呼吸感。\n\n"
    "【AI味黑名单——禁止使用以下表达】"
    "- '深吸一口气'（AI最爱的动作描写，用'喘了口气'或具体动作替代）"
    "- '心跳如擂鼓/心跳快得像要炸开'（陈词滥调，用具体感受替代）"
    "- '嘴角微微上扬/嘴角勾起一抹弧度'（AI专属表情，用具体动作替代）"
    "- '像被定格的照片/像时间凝固了'（AI明喻模板，删掉比喻直接写）"
    "- '瞳孔一缩/瞳孔骤缩'（AI最爱，用'愣住了'或具体反应替代）"
    "- '后背一阵发凉/后背发凉'（AI标记词，用具体恐惧反应替代）"
    "- '系统提示音/脑海中响起声音'（AI网文套路，用角色自己的感知替代）"
    "- 连续使用'忽然/突然/猛地'（AI节奏标记词，一章不超过2次）\n\n"
    "【对话自然度】"
    "对话不是电报。正常人有废话、有犹豫、有打断。不允许出现乒乓球式对答（A一句B一句A一句）。"
    "对话中穿插动作和沉默。允许10-20%的对话是闲聊或吐槽。\n\n"
    "【对话模拟法——产生博弈感的核心方法】"
    "写对话密集的场景时，不要直接'写一段对话'。按以下步骤模拟："
    "1. 先想清楚每个参与者的goal（他想要什么）、secret（他藏着什么）、leverage（他手里有什么牌）。"
    "2. 对话是双方用语言试探对方底线的过程——A试探→B反问或回避→A加码→B暴露或反击→达成/破裂。"
    "3. 潜台词：角色很少直接说心里话。'你看着办吧'可能是威胁也可能是妥协——上下文决定。"
    "4. 每个角色说话方式必须不同——不能所有人都说标准的普通话书面语。"
    "   老油条说话绕弯子，年轻人说话直接，紧张的人会重复，心虚的人会过度解释。"
    "5. 引路人/导师角色绝不能只是'告诉你规则然后让你选'——他必须有自己的目的和隐藏信息，"
    "   他说的每句话都是在引导主角走向他想要的结果。\n\n"
    "只输出正文，不要解释。"
)


# ---- 按任务类型动态调整 temperature ----
# narrative_function → temperature 映射
_TEMP_MAP: dict[str, float] = {
    "战斗": 0.6,       # 战斗需要紧凑逻辑，降低随机性
    "智斗": 0.4,       # 推理博弈需要严谨
    "高潮": 0.9,       # 高潮允许更激烈的创意
    "冲突": 0.8,       # 冲突场景需要爆发力
    "转折": 0.7,       # 转折需要出人意料但合逻辑
    "揭示": 0.5,       # 揭示需要精准信息控制
    "开篇钩子": 0.85,  # 开篇要抓眼球
    "人物塑造": 0.9,   # 人物塑造需要细腻情感
    "关系建立": 0.85,  # 关系互动需要温度
    "悬念设置": 0.7,   # 悬念需要克制
    "铺垫": 0.6,       # 铺垫需要稳重
    "过渡": 0.6,       # 过渡不需要太多创意
    "收束": 0.5,       # 收束需要收得住
    "伏笔": 0.6,       # 伏笔需要精确
    "挫折": 0.8,       # 挫折需要情感冲击
    "世界观铺陈": 0.5, # 设定传递需要准确
}


def _get_temperature_for_narrative(narrative_function: str, base_temp: float = 0.8) -> float:
    """根据章节叙事功能动态调整 temperature。

    高创意任务（情感/高潮/人物）→ 高温度
    高逻辑任务（推理/揭示/收束）→ 低温度
    匹配不到时用 base_temp。
    """
    if not narrative_function:
        return base_temp
    for key, temp in _TEMP_MAP.items():
        if key in narrative_function:
            return temp
    return base_temp


def assemble_context(state: ChapterGenState, repo: BibleRepository,
                     archival: Any | None = None) -> dict:
    """节点 1：装配章节上下文（core memory + 可选 archival 检索 + 题材文风标杆）。"""
    assembler = CoreMemoryAssembler(repo, archival=archival)
    query = f"第{state['chapter']}章 {state.get('title', '')} 的相关前文"
    context = assembler.assemble(chapter=state["chapter"], query=query)

    # 注入题材模板：推荐约束包 + 规则类型 + 文风标杆
    try:
        from novel_agent.references.search import canonical_genre
        from novel_agent.templates.loader import GenreLoader
        project = repo.get_project()
        if project and project.genre:
            cg = canonical_genre(project.genre)
            loader = GenreLoader()
            genre_parts = []
            if loader.exists(cg):
                recommended = loader.extract_recommended_constraints(cg)
                if recommended:
                    genre_parts.append(recommended)
                rule_types = loader.extract_rule_types(cg)
                if rule_types:
                    genre_parts.append(rule_types)
                benchmark = loader.extract_style_benchmark(cg)
                if benchmark:
                    genre_parts.append(benchmark)
            if genre_parts:
                genre_block = "\n\n".join(genre_parts)
                context = f"{context}\n\n【题材模板】\n{genre_block}"
    except Exception as e:
        logger.debug("assemble_context: 注入题材模板失败: %s", e)

    return {"context": context, "status": "assembled"}


def _build_chapter_brief(outline, repo) -> str:
    """从大纲构建章节约束清单，让 writer 知道这章必须写什么。

    约束分级：硬约束（≤3个，必须完成）+ 软约束（尽量做到，不牺牲正文质量）。
    LLM 不擅长同时满足 8 个异构约束，分级后聚焦核心目标。
    """
    if not outline:
        return ""
    hard_parts = []  # 硬约束：必须完成
    soft_parts = []  # 软约束：尽量做到

    # 章节概要（参考，不是约束）
    summary_text = outline.summary or ""

    # ---- 硬约束（最多3个） ----
    # 1. 爽点交付
    beats = _safe_json_loads(outline.required_beats)
    if beats:
        beat_lines = []
        for b in beats:
            tier = b.get("tier", "")
            btype = b.get("type", "")
            intensity = b.get("intensity", "")
            detail = b.get("detail", "")
            beat_lines.append(f"  - {tier}级爽点：{btype}（强度{intensity}）")
            if detail:
                beat_lines.append(f"    执行备注（含毒点警告，必须规避）：{detail}")
        hard_parts.append("爽点交付：\n" + "\n".join(beat_lines))

    # 2. 角色决策
    cc = _safe_json_loads(outline.character_constraints)
    char_dec = ""
    if cc and isinstance(cc, dict):
        char_dec = cc.pop("_character_decision", "")
        if char_dec:
            hard_parts.append(f"角色决策：{char_dec}")

    # 3. 章末钩子
    hooks = _safe_json_loads(outline.required_hooks)
    if hooks and isinstance(hooks, dict):
        htype = hooks.get("type", "")
        strength = hooks.get("target_strength", "")
        hard_parts.append(f"章末钩子：类型{htype}，强度{strength}")

    # ---- 软约束（尽量做到） ----
    # 欠账（背景压力，不要硬塞）
    debts = _safe_json_loads(outline.owed_debts)
    if debts:
        debt_lines = []
        for d in debts:
            dtype = d.get("type", "")
            desc = d.get("desc", "")
            pressure = d.get("pressure", "")
            debt_lines.append(f"  - {dtype}：{desc}（压力值{pressure}）")
        soft_parts.append("欠账（作为背景压力自然体现，不要硬塞）：\n" + "\n".join(debt_lines))

    # 信息增量
    if cc and isinstance(cc, dict):
        info_inc = cc.pop("_info_increment", "")
        nf = cc.pop("narrative_function", "")
        info_focus = cc.pop("info_focus", "")
        char_decisions = cc.pop("character_decisions", "")
        if nf:
            soft_parts.append(f"剧情功能参考：{nf}")
        if info_focus:
            soft_parts.append(f"信息焦点参考：{info_focus}")
        if info_inc:
            soft_parts.append(f"信息增量参考：{info_inc}")
        if char_decisions:
            soft_parts.append(f"角色决策清单参考：{char_decisions}")
        # 角色状态约束
        cc_lines = []
        for char_name, constraints in cc.items():
            if isinstance(constraints, dict):
                cc_lines.append(f"  - {char_name}：位置={constraints.get('location','')}，情绪={constraints.get('emotion','')}")
        if cc_lines:
            soft_parts.append("角色状态参考（保持一致）：\n" + "\n".join(cc_lines))

    # 伏笔
    try:
        to_plant = repo.get_foreshadows_to_plant(outline.order if outline.order else 0)
        if to_plant:
            plant_lines = [f"  - {f.foreshadow_id}：{f.description}" for f in to_plant]
            soft_parts.append("可埋伏笔（自然融入，不要硬塞）：\n" + "\n".join(plant_lines))
    except Exception:
        pass
    try:
        to_resolve = repo.get_foreshadows_to_resolve(outline.order if outline.order else 0)
        if to_resolve:
            resolve_lines = [f"  - {f.foreshadow_id}：{f.description}" for f in to_resolve]
            soft_parts.append("可回收伏笔（自然融入）：\n" + "\n".join(resolve_lines))
    except Exception:
        pass

    # 用户聊天反馈（软约束）
    try:
        from novel_agent.chat.repository import ChatRepository
        chat_repo = ChatRepository(repo.db, repo.project_id)
        feedbacks = chat_repo.get_pending_feedback(outline.order if outline.order else 0)
        if feedbacks:
            fb_lines = [f"  - {f.feedback}" for f in feedbacks]
            soft_parts.append("用户聊天反馈（作为软约束尽量满足，不覆盖硬约束）：\n" + "\n".join(fb_lines))
            chat_repo.mark_feedback_applied([f.id for f in feedbacks])
    except Exception as e:
        logger.debug("_build_chapter_brief 注入用户反馈失败: %s", e)

    # 组装
    parts = []
    if summary_text:
        parts.append(f"【本章概要】\n{summary_text}")
    if hard_parts:
        parts.append("【硬约束——必须完成，写不好就重写】")
        for i, h in enumerate(hard_parts[:3], 1):
            parts.append(f"  {i}. {h}")
    if soft_parts:
        parts.append("【软约束——尽量做到，但不要牺牲正文质量】")
        for s in soft_parts:
            parts.append(f"  - {s}")
    if not hard_parts and not soft_parts:
        return ""
    # 阶段标记
    if outline.phase == "opening":
        parts.append("【阶段：黄金三章——必须快速抓住读者，节奏要快，信息要密集】")
    elif outline.phase == "shangjia":
        parts.append("【阶段：上架章——必须有重磅爽点或大转折】")
    return "\n".join(parts)


def _safe_json_loads(text: str):
    """安全 JSON 解析，失败返回 None。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


async def write_chapter(state: ChapterGenState,
                        llm_client: LLMClient,
                        repo: BibleRepository | None = None) -> dict:
    """节点 2：调 LLM 生成章节正文。"""
    from novel_agent.templates.style_guide_loader import get_core_constraints
    core_constraints = get_core_constraints()
    # 读取大纲，构建章节约束清单 + 提取 beat_type + narrative_function
    beat_type = ""
    chapter_brief = ""
    narrative_function = ""
    if repo:
        try:
            outline = repo.get_outline_by_chapter(state["chapter"])
            if outline:
                chapter_brief = _build_chapter_brief(outline, repo)
                beats = _safe_json_loads(outline.required_beats)
                if beats and isinstance(beats, list):
                    beat_type = beats[0].get("type", "") if beats else ""
                # 提取 narrative_function 用于动态 temperature
                cc = _safe_json_loads(outline.character_constraints)
                if cc and isinstance(cc, dict):
                    narrative_function = cc.get("narrative_function", "")
        except Exception as e:
            logger.debug("write_chapter 读取大纲失败: %s", e)
    # 根据章节叙事功能动态调整 temperature
    dynamic_temp = _get_temperature_for_narrative(narrative_function, llm_client.config.temperature)
    if narrative_function:
        logger.info("write_chapter 第%d章 narrative_function=%s → temperature=%.2f", state["chapter"], narrative_function, dynamic_temp)
    few_shot = get_few_shot_for_beat(beat_type)

    # 语感检索：如果开启kill-switch且有beat_type，从末日文库检索真实片段替换few-shot
    genre_rag_slices = ""
    try:
        from novel_agent.config import load_config
        _cfg = load_config()
        if getattr(_cfg, "enable_genre_rag", False) and beat_type:
            import chromadb
            from novel_agent.memory.archival import _build_embedding_function
            chroma_dir = _cfg.chroma_dir
            _client = chromadb.PersistentClient(path=str(chroma_dir))
            _ef = _build_embedding_function(_cfg)
            _coll = _client.get_or_create_collection(
                name="genre_archive_doomsday",
                metadata={"hnsw:space": "cosine"},
                embedding_function=_ef,
            )
            if _coll.count() > 0:
                res = _coll.query(query_texts=[beat_type], n_results=5)
                docs = res.get("documents", [[]])[0]
                dists = res.get("distances", [[]])[0]
                slices = []
                for doc, dist in zip(docs, dists):
                    # 阈值过滤：距离>0.7 = 相似度<0.3，跳过低质量结果
                    if dist > 0.7:
                        continue
                    # 截断到500字，总1500字封顶
                    slices.append(doc[:500])
                genre_rag_slices = "\n\n---\n\n".join(slices)[:1500]
                logger.info("write_chapter 第%d章 genre RAG命中 %d条 (beat=%s, 阈值0.7)", state["chapter"], len(slices), beat_type)
    except Exception as e:
        logger.warning("write_chapter 第%d章 genre RAG失败，降级few-shot: %s", state["chapter"], e)

    # 预算策略：RAG优先，few-shot降级兜底
    style_content = genre_rag_slices if genre_rag_slices else few_shot
    prompt = (
        f"<task>请写第{state['chapter']}章《{state.get('title', '')}》正文。</task>\n\n"
        f"<context>\n{state.get('context', '')}\n</context>\n\n"
    )
    if chapter_brief:
        prompt += f"<constraints>\n{chapter_brief}\n</constraints>\n\n"
    prompt += (
        f"<style_reference>\n{style_content}\n{core_constraints}\n</style_reference>\n\n"
        f"<scratchpad>写正文前，先核对以下事项：\n"
        f"1. 本章必须埋设的伏笔：检查constraints中的伏笔清单\n"
        f"2. 本章必须回收的伏笔：检查constraints中的伏笔清单\n"
        f"3. 本章必须交付的爽点：检查constraints中的required_beats，\n"
        f"   并遵守每条的『执行备注』——那是已知毒点，必须规避（不是写作建议，是禁令）。\n"
        f"4. 角色当前位置/情绪是否与前文连续\n"
        f"5. 立意锚点：本章爽点是否服务于全书核心爽点\n"
        f"核对完成后再写正文。</scratchpad>\n\n"
        f"<rules>"
        f"【硬约束铁律】硬约束必须完成。爽点交付——如果大纲要求'打脸'，"
        f"必须写出完整打脸过程（嚣张→压制→不可置信→反抗→屈辱），不能一笔带过。"
        f"字数：正文不少于2500字，重要章节不少于3000字。"
        f"软约束尽量做到——宁可少做一个软约束，也不要把硬约束写成流水账。"
        f"</rules>\n\n"
        f"依据context和constraints写出本章正文。只输出正文，不要输出JSON或格式说明。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT, temperature=dynamic_temp)
        draft = clean_chapter_text(draft, state["chapter"], state.get("title", ""))
        if _looks_like_json_not_prose(draft):
            logger.warning("write_chapter 第%d章：LLM 返回 JSON 而非正文", state["chapter"])
            return {"status": "failed", "error": "LLM 返回了 JSON 而非正文，可能模型理解错误"}
        ver = state.get("draft_version", 0) + 1
        return {"draft": draft, "status": "drafted",
                "draft_version": ver,
                "drafts": [{"version": ver, "text": draft, "score": 0}],
                "word_count": len(re.findall(r'[\u4e00-\u9fff]', draft))}
    except Exception as e:
        logger.warning("write_chapter 第%d章失败：%s", state["chapter"], e)
        return {"status": "failed", "error": str(e)}


async def audit_chapter(state: ChapterGenState, auditor: Auditor,
                        repo: BibleRepository) -> dict:
    """节点：独立审校草稿，返回审计报告。写审分离铁律。"""
    # 草稿为空或生成失败时跳过 LLM 审计，直接返回失败报告
    if state.get("status") == "failed" or not state.get("draft", "").strip():
        logger.warning("audit_chapter 第%d章：草稿为空或生成失败，跳过审计", state["chapter"])
        empty_report = AuditReport(
            passed=False, overall_score=0,
            summary="草稿为空或生成失败，无法审计",
            issues=[Issue(dimension="draft", severity="critical",
                          message="草稿为空或生成失败")],
        )
        return {
            "audit_report": empty_report.model_dump(),
            "review_iterations": state.get("review_iterations", 0) + 1,
            "status": "failed",
        }

    # 确定性硬检查：字数/限频词/伏笔描述关键词命中（字数阈值从CSV读取）
    from novel_agent.audit.validator import _get_threshold
    word_min = int(_get_threshold("字数下限", 2200))
    to_plant = repo.get_foreshadows_to_plant(state["chapter"])
    foreshadows_data = [{"id": f.foreshadow_id, "description": f.description} for f in to_plant]
    det_result = run_deterministic_checks(state["draft"], foreshadows_data, word_min=word_min)

    # 确定性检查结果作为 issues 保留给 rewrite 参考，但不污染 auditor 输入（写审分离铁律）
    det_issues = [Issue(**i) for i in det_result["issues"]]

    # 阶段3：爽点断层检测 + 黄金三章检查 + 卷高潮欠账检查（确定性，需要 repo）
    if repo:
        try:
            pleasure_issues = check_pleasure_gap(repo, state["chapter"])
            golden_issues = check_golden_three(repo, state["chapter"])
            climax_issues = check_volume_climax(repo, state["chapter"])
            for pi in pleasure_issues + golden_issues + climax_issues:
                det_issues.append(Issue(**pi))
        except Exception as e:
            logger.warning("audit_chapter 第%d章：爽点检查失败: %s", state["chapter"], e)

        # B6: 应回收伏笔确定性检查——防止伏笔永远卡在planted/developing
        try:
            from novel_agent.audit.validator import check_foreshadows_resolved
            to_resolve_list = repo.get_foreshadows_to_resolve(state["chapter"])
            if to_resolve_list:
                resolve_data = [{"id": f.foreshadow_id, "description": f.description} for f in to_resolve_list]
                resolve_issues = check_foreshadows_resolved(state["draft"], resolve_data)
                for ri in resolve_issues:
                    det_issues.append(Issue(**ri))
        except Exception as e:
            logger.warning("audit_chapter 第%d章：伏笔回收检查失败: %s", state["chapter"], e)

        # 阶段3.1：拆书分布形状校准——剧情功能/章纲质量/支线生命周期/信息密度
        try:
            from novel_agent.audit.validator import (
                check_narrative_pattern,
                check_outline_quality,
                check_subplot_lifecycle,
                check_info_density_anomaly,
            )
            for fn in (check_narrative_pattern, check_outline_quality,
                       check_subplot_lifecycle, check_info_density_anomaly):
                try:
                    for pi in fn(repo, state["chapter"]):
                        det_issues.append(Issue(**pi))
                except Exception as e:
                    logger.debug("audit_chapter 第%d章：%s 跳过: %s", state["chapter"], fn.__name__, e)
        except Exception as e:
            logger.debug("audit_chapter 第%d章：拆书校准检查跳过: %s", state["chapter"], e)

    # 阶段3.5：跨章语义去重扫描（冷路径软信号，不阻塞）
    try:
        from novel_agent.audit.dedup_scanner import DedupScanner
        from novel_agent.config import load_config
        scanner = DedupScanner(load_config())
        dups = scanner.scan_chapter(state["chapter"], state["draft"])
        for dup in dups:
            det_issues.append(Issue(
                dimension="去重", severity="minor",
                message=f"与第{dup['chapter']}章语义相似({dup['similarity']:.0%})：{dup['matched_content']}",
            ))
    except Exception as e:
        logger.debug("audit_chapter 第%d章：去重扫描跳过: %s", state["chapter"], e)

    # 调 LLM 审计：三视角并行审查（用户/专业/编辑）
    report = await auditor.audit(
        chapter=state["chapter"], title=state.get("title", ""),
        draft=state["draft"], repo=repo,
    )
    iterations = state.get("review_iterations", 0) + 1

    # 审查不通过时触发对抗性讨论（仅第1轮，避免无限循环）
    if not report.passed and iterations == 1 and hasattr(auditor, 'debate'):
        try:
            logger.info("audit_chapter 第%d章：审查不通过（%s），启动对抗性讨论",
                        state["chapter"], report.summary)
            report = await auditor.debate(
                chapter=state["chapter"], title=state.get("title", ""),
                draft=state["draft"], report=report, max_rounds=2,
            )
            logger.info("audit_chapter 第%d章：对抗讨论完成，%s",
                        state["chapter"], "通过" if report.passed else "仍不通过")
        except Exception as e:
            logger.warning("audit_chapter 第%d章：对抗讨论失败: %s", state["chapter"], e)

    # 确定性检查 issues 追加到审计报告；critical 级问题必须阻断放行
    if det_issues:
        report.issues = list(report.issues) + det_issues
        has_critical = any(i.severity == "critical" for i in det_issues)
        if has_critical and report.passed:
            report.passed = False
            logger.warning("audit_chapter 第%d章：确定性检查发现critical问题，覆盖LLM审计结论为不通过",
                          state["chapter"])

    return {
        "audit_report": report.model_dump(),
        "review_iterations": iterations,
        "status": "audited" if report.passed else "needs_rewrite",
    }


def route_after_audit(state: ChapterGenState) -> str:
    """条件边：审计达标→polish；不达标且未超3次→write 回环；超3次→降级接受并polish。"""
    if state.get("status") == "failed":
        logger.warning("route_after_audit 进入 end_failed：status=%s", state.get("status"))
        return "end_failed"
    report = AuditReport(**state.get("audit_report", {}))
    if report.passed:
        return "polish"
    if state.get("review_iterations", 0) >= 3:
        # 降级策略：3次重写仍不通过，取所有草稿中字数最多的（Self-Refine取最高分轮）
        all_drafts = state.get("drafts", [])
        if all_drafts:
            best = max(all_drafts, key=lambda d: len(d.get("text", "")))
            if best.get("text") and len(best["text"]) > len(state.get("draft", "")):
                logger.warning("route_after_audit 降级：取草稿轮v%d（%d字）替换当前轮（%d字）",
                               best["version"], len(best["text"]), len(state.get("draft", "")))
                # 通过返回额外的状态更新提示（LangGraph条件边不能直接改state，但可以在polish节点处理）
        logger.warning("route_after_audit 降级接受：重写超3次，score=%d，继续polish",
                       report.overall_score)
        return "polish"
    return "rewrite"


async def rewrite_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：基于审计建议重写（含对抗讨论修订建议）。"""
    from novel_agent.templates.style_guide_loader import get_core_constraints
    core_constraints = get_core_constraints()
    report = AuditReport(**state.get("audit_report", {}))
    suggestions = "\n".join(f"- {s}" for s in report.suggestions) or "无具体建议"
    issues = "\n".join(f"- {i.dimension}({i.severity}): {i.message}" for i in report.issues) or "无"
    # 对抗讨论记录
    debate_text = ""
    if report.debate_rounds:
        debate_lines = []
        for r in report.debate_rounds:
            debate_lines.append(f"  第{r.get('round',0)}轮：")
            for c in r.get("auditor_criticisms", []):
                debate_lines.append(f"    审查方：{c}")
            for resp in r.get("writer_responses", []):
                agree = "认同" if resp.get("agree") else "反驳"
                debate_lines.append(f"    作者（{agree}）：{resp.get('reason', '')}")
                if resp.get("fix"):
                    debate_lines.append(f"      修改方案：{resp['fix']}")
        debate_text = "\n【对抗讨论记录】\n" + "\n".join(debate_lines) + "\n"

    # A3修复：重写也必须注入硬约束清单+字数要求，防止重写后漏爽点/退文风/变短
    chapter_brief = ""
    few_shot = ""
    try:
        repo = BibleRepository(state.get("project_id", 1))
        outline = repo.get_outline_by_chapter(state["chapter"])
        if outline:
            chapter_brief = _build_chapter_brief(outline, repo)
            # 补few_shot（治A3残留：rewrite也需风格参考）
            beats = _safe_json_loads(outline.required_beats)
            beat_type = beats[0].get("type", "") if beats and isinstance(beats, list) else ""
            if beat_type:
                few_shot = get_few_shot_for_beat(beat_type)
    except Exception:
        pass

    prompt = (
        f"重写第{state['chapter']}章《{state.get('title', '')}》。\n\n"
        f"【上下文】\n{state.get('context', '')}\n\n"
        f"{chapter_brief}\n\n"
        f"{'<style_reference>' + chr(10) + few_shot + chr(10) + '</style_reference>' + chr(10) + chr(10) if few_shot else ''}"
        f"【上一版草稿】\n{state.get('draft', '')}\n\n"
        f"【审计问题】\n{issues}\n\n"
        f"【修订建议】\n{suggestions}\n\n"
        f"{debate_text}\n"
        f"{core_constraints}\n\n"
        f"要求：针对问题重写，严格遵循上述核心写作约束（特别是段落节奏铁律和反AI味要求）。"
        f"【硬约束铁律】硬约束必须完成，尤其是爽点交付——如果大纲要求'打脸'，"
        f"必须写出完整的打脸过程，不能一笔带过。"
        f"字数要求：正文不少于2500字，重要章节不少于3000字。"
        f"最重要：段落要有呼吸感——正常叙事段落3-6句一段，独句段只用于爆发点。不要把每句话都写成单独一段。"
        f"只输出正文，不要输出 JSON 或任何格式说明。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT, temperature=llm_client.config.temperature)
        draft = clean_chapter_text(draft, state["chapter"], state.get("title", ""))
        if _looks_like_json_not_prose(draft):
            return {"status": "failed", "error": "LLM 返回了 JSON 而非正文，可能模型理解错误"}
        ver = state.get("draft_version", 1) + 1
        # Self-Refine：保留全部草稿，不盲取末轮
        all_drafts = list(state.get("drafts", []))
        all_drafts.append({"version": ver, "text": draft, "score": 0})
        return {"draft": draft,
                "draft_version": ver,
                "drafts": all_drafts,
                "word_count": len(re.findall(r'[\u4e00-\u9fff]', draft)), "status": "drafted"}
    except Exception as e:
        logger.warning("rewrite_chapter 第%d章失败：%s", state["chapter"], e)
        return {"status": "failed", "error": str(e)}


async def polish_chapter(state: ChapterGenState, llm_client: LLMClient,
                         repo: BibleRepository | None = None) -> dict:
    """节点：润色优化（文风统一 + AI 痕迹清除）。"""
    # Self-Refine：降级时取所有草稿中中文字数最多的（不盲取末轮）
    all_drafts = state.get("drafts", [])
    current_draft = state.get("draft", "")
    if all_drafts:
        best = max(all_drafts, key=lambda d: len(re.findall(r'[\u4e00-\u9fff]', d.get("text", ""))))
        best_cn = len(re.findall(r'[\u4e00-\u9fff]', best.get("text", "")))
        cur_cn = len(re.findall(r'[\u4e00-\u9fff]', current_draft))
        if best.get("text") and best_cn > cur_cn:
            logger.info("polish_chapter 第%d章：取草稿轮v%d（%d中文字）替换当前轮（%d中文字）",
                       state["chapter"], best["version"], best_cn, cur_cn)
            current_draft = best["text"]
    POLISH_SYSTEM = (
        "你是网文润色编辑。优化语言表达，清除 AI 痕迹词，增强画面感。\n\n"
        "【绝对铁律——不得违反】\n"
        "1. 不得改变剧情、设定、伏笔、角色关系。只改文字表达，不改故事内容。\n"
        "2. 不得增删角色台词的含义，只可调整措辞。\n"
        "3. 不得新增角色、场景、道具。\n\n"
        "【AI味黑名单——必须清除以下表达】\n"
        "- '深吸一口气' → 用'喘了口气'或具体动作替代\n"
        "- '心跳如擂鼓/心跳快得像要炸开' → 用具体感受替代\n"
        "- '嘴角微微上扬/嘴角勾起一抹弧度' → 用具体动作替代\n"
        "- '像被定格的照片/像时间凝固了' → 删掉比喻直接写\n"
        "- '瞳孔一缩/瞳孔骤缩' → 用'愣住了'或具体反应替代\n"
        "- '后背一阵发凉/后背发凉' → 用具体恐惧反应替代\n"
        "- '忽然/突然/猛地' → 一章不超过2次，多余的改为其他过渡\n"
        "- '竟然/不禁/不由得' → 尽量删掉或改写\n\n"
        "【标点修复——必须执行】\n"
        "如果原文有连续40字以上无逗号句号的长句，必须在适当位置插入逗号断句。\n"
        "中文叙事句子的自然长度是10-25字，超过30字必须有标点停顿。\n\n"
        "【排比打断——必须执行】\n"
        "如果原文有连续4个以上相同句式（如连续4个'越来越X'、连续4个'放弃X'、连续4个'碾成X'），\n"
        "只保留前2个，其余的必须改写为不同句式或直接删除。\n"
        "排比是修辞手法不是叙事方式——2个够了，第3个开始就是AI味。\n\n"
        "【感叹号降级——必须执行】\n"
        "每段最多2个感叹号。多余的改为句号或省略号。\n"
        "真正的冲击力来自内容而非标点。冷叙述比感叹号轰炸更有力量。\n\n"
        "【重复递进截断——必须执行】\n"
        "如果原文有'越来越X越来越Y越来越Z'这种连续递进，最多保留2个。\n"
        "如果原文有'放弃X！放弃Y！放弃Z！'这种连续排比感叹，最多保留2个。\n\n"
        "【段落节奏】\n"
        "如果原文每句都是单独一段（碎片化），请将相关句子合并为3-6句的正常叙事段落。"
        "独句段只保留在强调和爆发点。\n\n"
        "只输出润色后正文。不要输出任何说明。"
    )
    prompt = f"润色以下章节正文：\n\n{current_draft}"
    try:
        polished = await llm_client.generate(prompt, system=POLISH_SYSTEM)
        polished = clean_chapter_text(polished, state["chapter"], state.get("title", ""))

        # POLISH后轻量重审：字数+限频词+伏笔关键词命中
        polish_issues = []

        # 后处理：规则修复感叹号轰炸+重复递进，检测无标点长句+排比过载
        from novel_agent.audit.text_post_processor import post_process_text
        polished, pp_issues = post_process_text(polished)
        for issue in pp_issues:
            polish_issues.append(f"{issue.get('type','')}: {issue.get('suggestion','')}")
            logger.info("polish_chapter 第%d章后处理: %s", state["chapter"], issue.get('suggestion', ''))

        # 如果后处理检测到无标点长句或排比过载，做一次LLM修复
        needs_llm_fix = any(i.get('type') in ('long_unpunctuated', 'parallelism_overload') for i in pp_issues)
        if needs_llm_fix:
            fix_prompt = (
                "以下文本有格式问题需要修复。只修复格式，不改剧情：\n"
                "1. 连续40字以上无标点的长句，插入逗号断句\n"
                "2. 连续4+相同句式的排比，只保留前2个\n\n"
                f"{polished}"
            )
            try:
                fixed = await llm_client.generate(fix_prompt, system="你是文字编辑。只修复标点和排比问题，不改剧情。只输出修复后的正文。")
                fixed = clean_chapter_text(fixed, state["chapter"], state.get("title", ""))
                if len(fixed) > len(polished) * 0.7:  # 修复后不应大幅缩短
                    polished = fixed
                    logger.info("polish_chapter 第%d章：LLM格式修复成功", state["chapter"])
            except Exception as e:
                logger.warning("polish_chapter 第%d章LLM格式修复失败: %s", state["chapter"], e)

        # polish 后硬指标闸门：字数/限频词不通过则回 rewrite（伏笔保持软信号）
        from novel_agent.audit.validator import count_chinese_chars, check_forbidden_words, _get_threshold
        word_min = int(_get_threshold("字数下限", 2200))
        cn_count = count_chinese_chars(polished)
        hard_fail = False
        if cn_count < word_min:
            polish_issues.append(f"润色后字数不足：{cn_count}（及格线{word_min}）")
            hard_fail = True
        # 限频词检查
        freq_ok, freq_hits = check_forbidden_words(polished)
        if not freq_ok:
            polish_issues.append(f"限频词超标：{','.join(freq_hits)}")
            if len(freq_hits) >= 4:
                hard_fail = True
        # 伏笔关键词命中检查（软信号，不阻断）
        if repo:
            try:
                to_plant = repo.get_foreshadows_to_plant(state["chapter"])
                if to_plant:
                    from novel_agent.audit.validator import check_foreshadows_planted
                    fs_data = [{"id": f.foreshadow_id, "description": f.description} for f in to_plant]
                    fs_ok, fs_missing = check_foreshadows_planted(polished, fs_data)
                    if not fs_ok:
                        polish_issues.append(f"润色后伏笔关键词丢失：{','.join(fs_missing)}")
            except Exception:
                pass

        if polish_issues:
            logger.warning("polish_chapter 第%d章：轻量重审发现问题: %s",
                          state["chapter"], "; ".join(polish_issues))
            if hard_fail:
                logger.warning("polish_chapter 第%d章：硬指标不通过，回 rewrite", state["chapter"])
                return {"polished": polished, "status": "needs_rewrite",
                        "word_count": cn_count,
                        "polish_review_issues": polish_issues}

        return {"polished": polished, "status": "polished",
                "word_count": len(re.findall(r'[\u4e00-\u9fff]', polished)),
                "polish_review_issues": polish_issues}
    except Exception as e:
        logger.warning("polish_chapter 第%d章失败: %s", state["chapter"], e)
        # polish 失败不阻塞流程，用原草稿继续
        draft = clean_chapter_text(state.get("draft", ""), state["chapter"], state.get("title", ""))
        return {"polished": draft, "status": "polished",
                "polish_warning": str(e)}


def save_text_polished(state: ChapterGenState, recall: RecallMemory) -> dict:
    """节点：保存润色后正文到文件。"""
    content = state.get("polished") or state.get("draft", "")
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=content,
    )
    return {"status": "saved"}


async def summarize_chapter(state: ChapterGenState, llm_client: LLMClient,
                            applier: DeltaApplier,
                            repo: BibleRepository | None = None) -> dict:
    """节点：校验正文是否满足大纲约束，存入摘要 + 检测伏笔回收。

    阶段0核心改变：summarize 不再从正文抽12个字段。
    改为：读本章 Outline 约束载荷 → LLM 核对正文是否满足 → 回写5字段。
    """
    content = state.get("polished") or state.get("draft", "")
    chapter = state["chapter"]

    # 读本章大纲约束（校验器模式：大纲带规范，正文满足规范）
    outline = repo.get_outline_by_chapter(chapter) if repo else None
    constraints = {}
    if outline:
        try:
            constraints = {
                "beats": json.loads(outline.required_beats or "[]"),
                "debts": json.loads(outline.owed_debts or "[]"),
                "hooks": json.loads(outline.required_hooks or "{}"),
                "phase": outline.phase or "regular",
            }
        except (json.JSONDecodeError, TypeError):
            constraints = {}

    to_resolve = repo.get_foreshadows_to_resolve(chapter) if repo else []
    fs_text = ""
    fs_instruction = ""
    if to_resolve:
        fs_text = "\n\n[本章应回收的伏笔]\n" + "\n".join(
            f"- {f.foreshadow_id}: {f.description}" for f in to_resolve)
        fs_instruction = ',"resolved_foreshadows":[]'

    # LLM核对：正文是否满足约束（校验器，非抽取器）
    constraints_json = json.dumps(constraints, ensure_ascii=False, indent=2) if constraints else "{}"
    # 构建beat核对清单：把大纲要求的每个beat列出来，让LLM逐个判断是否交付
    planned_beats = constraints.get("beats", [])
    beat_check_list = ""
    if planned_beats:
        beat_check_list = "\n【本章计划爽点（逐个判断是否交付）】\n"
        for i, b in enumerate(planned_beats):
            beat_check_list += f"{i+1}. tier={b.get('tier','')}, type={b.get('type','')}, intensity={b.get('intensity',0)}\n"
        beat_check_list += "\n对每个计划爽点，在beats_delivered中对应输出，type必须与计划一致，delivered=true/false，delivered_intensity=实际交付强度(1-10)。\n"

    # A2: 喂全文而非前3000字——章末伏笔回收/钩子/角色终位不能被截断
    # 超长章节（>6000字）分段处理：前半+后半+章末500字
    if len(content) > 6000:
        content_for_summary = content[:3000] + "\n...\n" + content[3000:5500] + "\n...\n【章末】\n" + content[-500:]
    else:
        content_for_summary = content

    prompt = (
        f"核对第{chapter}章正文是否满足以下写作约束。\n\n"
        f"【写作约束】\n{constraints_json}\n\n"
        f"{beat_check_list}"
        f"【正文】\n{content_for_summary}\n"
        f"{fs_text}\n\n"
        f"输出JSON：\n"
        f'{{"core_events":"","hook_strength":0,'
        f'"beats_delivered":[{{"tier":"","type":"","delivered":false,"intensity":0,"delivered_intensity":0}}],'
        f'"debts_resolved":[],'
        f'"character_states":[{{"name":"","location":"","emotion":""}}]'
        f'{fs_instruction}}}\n'
        f"只输出JSON。beats_delivered的type必须与计划爽点的type一致。"
    )
    SUM_SYSTEM = "你是网文校验助手。核对正文是否满足大纲约束。只输出 JSON。"
    data = {}
    try:
        raw = await llm_client.generate(prompt, system=SUM_SYSTEM)
        from novel_agent.utils.json_parser import parse_json_strict
        data = parse_json_strict(raw)
        if data is None:
            data = {}
        if not data:
            logger.warning("summarize_chapter 第%d章：LLM 返回无法解析为 JSON，摘要降级为正文前200字", chapter)
    except Exception as e:
        logger.warning("summarize_chapter 第%d章 LLM 调用失败：%s，摘要降级为正文前200字", chapter, e)
        data = {}

    delta = Delta(
        target="chapter_summary", action="create", chapter=chapter,
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(content)),
            core_events=data.get("core_events", content[:200]),
            characters_present=", ".join(cs.get("name", "") for cs in data.get("character_states", [])),
            chapter_hook=f"hook_strength={data.get('hook_strength', 0)}",
        ),
    )
    result = applier.apply(delta)
    if not result.success:
        return {"status": "failed", "error": result.message}

    # 伏笔回收
    resolved_ids = data.get("resolved_foreshadows", []) or []
    for fid in resolved_ids:
        try:
            applier.apply(Delta(
                target="foreshadow", action="resolve", chapter=chapter,
                data=ForeshadowDelta(foreshadow_id=fid),
            ))
        except Exception as e:
            logger.warning("summarize_chapter 第%d章：伏笔回收「%s」失败：%s", chapter, fid, e)

    # 角色状态更新（位置/情绪），写 StateChange + TruthEvent
    for cs in data.get("character_states", []) or []:
        name = cs.get("name", "").strip()
        if name and repo:
            char = repo.get_character(name)
            if char:
                updates = {}
                if cs.get("location"):
                    updates["current_location"] = cs["location"]
                if cs.get("emotion"):
                    updates["current_emotion"] = cs["emotion"]
                if updates:
                    try:
                        # 记录状态变更到 StateChange 表
                        if "current_location" in updates:
                            repo.create_state_change(
                                chapter=chapter, entity_type="角色", entity_id=name,
                                field="location",
                                old_value=char.current_location or "",
                                new_value=updates["current_location"],
                            )
                        if "current_emotion" in updates:
                            repo.create_state_change(
                                chapter=chapter, entity_type="角色", entity_id=name,
                                field="emotion",
                                old_value=char.current_emotion or "",
                                new_value=updates["current_emotion"],
                            )
                        # 记录到 TruthEvent 事件流
                        repo.append_event(
                            chapter=chapter, type="character_state_change",
                            entity_id=name, payload=updates,
                        )
                        repo.update_character(name, **updates)
                    except Exception as e:
                        logger.warning("summarize_chapter 第%d章：更新角色%s状态失败：%s", chapter, name, e)

    # 爽点交付回写 PleasureBeat 表
    for b in data.get("beats_delivered", []) or []:
        try:
            repo.create_pleasure_beat(
                chapter=chapter,
                tier=b.get("tier", ""),
                beat_type=b.get("type", ""),
                intensity=b.get("intensity", 0),
                phase=constraints.get("phase", "regular"),
                delivered=b.get("delivered", False),
                delivered_intensity=b.get("delivered_intensity", b.get("intensity", 0)) if b.get("delivered") else 0,
            )
        except Exception as e:
            logger.warning("summarize_chapter 第%d章：写入PleasureBeat失败：%s", chapter, e)

    # 伏笔回收记录 TruthEvent
    for fid in resolved_ids:
        try:
            repo.append_event(
                chapter=chapter, type="foreshadow_resolved",
                entity_id=fid, payload={"chapter": chapter},
            )
        except Exception:
            pass

    # 回写覆盖率探针（防 silent 失败）
    coverage = {
        "summary": 1 if repo and repo.get_chapter_summary(chapter) else 0,
        "state_changes": len(repo.list_events(chapter=chapter)) if repo else 0,
        "beats_delivered": sum(1 for b in data.get("beats_delivered", []) if b.get("delivered")),
        "debts_resolved": len(data.get("debts_resolved", [])),
        "character_states": len(data.get("character_states", [])),
    }
    logger.info("ch%d 回写覆盖: %s", chapter, coverage)
    if coverage["beats_delivered"] == 0 and constraints.get("beats"):
        logger.warning("ch%d 有beat计划但0交付，可能prompt需调整", chapter)

    # 阶段2：状态快照 + 保真度校验
    if repo:
        try:
            from novel_agent.memory.snapshot import build_snapshot, save_snapshot, validate_snapshot_fidelity
            # 保真度校验（快照 vs 正文）
            fidelity = validate_snapshot_fidelity(repo, chapter, content)
            # 构建并保存快照
            snap_data = build_snapshot(repo, chapter)
            is_full = (chapter % 20 == 0 and chapter > 0)
            save_snapshot(repo, chapter, snap_data,
                         drift_score=fidelity.get("drift_score", 0),
                         is_full_resummary=is_full)
            if fidelity.get("drift_score", 0) >= 5:
                logger.warning("ch%d 快照漂移分数=%d，建议全量重摘要",
                              chapter, fidelity["drift_score"])
            if is_full:
                logger.info("ch%d 触发周期性全量重摘要", chapter)
        except Exception as e:
            logger.warning("ch%d 快照保存失败: %s", chapter, e)

    return {"status": "completed"}


def human_review(state: ChapterGenState) -> dict:
    """人审节点：审计通过后、润色前的人工 checkpoint。

    在 SSE 流式模式下，前端会暂停在此节点，等待用户确认。
    用户可以：通过→继续 polish；驳回→回到 rewrite；直接修改 draft。
    """
    return {"status": "pending_review"}


# ---- M2 保留的兼容节点（旧 graph 测试仍用） ----

def save_text(state: ChapterGenState, recall: RecallMemory) -> dict:
    """M2 兼容：把正文存到文件（不区分 polished）。"""
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=state["draft"],
    )
    return {"status": "saved"}


def save_summary(state: ChapterGenState, applier: DeltaApplier) -> dict:
    """M2 兼容：简化摘要（用 draft 前 200 字）。"""
    draft = state.get("draft", "")
    summary_text = draft[:200] if draft else ""
    delta = Delta(
        target="chapter_summary", action="create", chapter=state["chapter"],
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(draft)),
            core_events=summary_text,
            characters_present="",
        ),
    )
    result = applier.apply(delta)
    if not result.success:
        return {"status": "failed", "error": result.message}
    return {"status": "completed"}
