"""编排节点函数：每个节点接收 state + 依赖，返回 state 更新。

节点设计为接受依赖注入（repo/llm_client/recall/applier/auditor），
便于测试 mock 和 runner 组装。

M3 扩展：写审分离 + 反馈循环节点（audit/polish/rewrite/summarize）。
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Any

from novel_agent.audit.auditor import Auditor
from novel_agent.audit.schemas import AuditReport, Issue
from novel_agent.audit.validator import (
    run_deterministic_checks, check_pleasure_gap, check_golden_three,
    check_volume_climax,
)
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.core import CoreMemoryAssembler
from novel_agent.memory.recall import RecallMemory
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.orchestrator.text_utils import clean_chapter_text, _looks_like_json_not_prose
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, SummaryDelta, ForeshadowDelta
from novel_agent.templates.style_guides.few_shot_samples import get_few_shot_for_beat

logger = logging.getLogger(__name__)


def _check_cancelled(state: ChapterGenState, node_name: str) -> dict | None:
    """检查是否已被取消，返回取消状态 dict 或 None。"""
    from novel_agent.orchestrator.runner import is_cancelled
    tid = state.get("_thread_id", "")
    if tid and is_cancelled(tid):
        logger.warning("第%d章 %s 节点检测到取消令牌，终止生成", state.get("chapter", 0), node_name)
        return {"status": "failed", "error": "用户取消生成"}
    return None

# ── 语料库按书打标签 ── 每本书代表不同的方向特长 ──
BOOK_TAGS: dict[str, list[str]] = {
    "序列：吃神者 - 不要大脑要小脑":           ["cthulhu", "power", "wasteland", "combat", "politics", "dark"],
    "时停时停时停时停时停时停时停！ - 六个葫芦":  ["cthulhu", "power", "wasteland", "combat", "taboo"],
    "异兽迷城 - 彭湃":                         ["mutation", "power", "combat", "humanity", "mystery"],
    "灵异复苏，永夜降临 - 庆元职高小天才":       ["cthulhu", "horror", "mystery", "dark"],
    "我在精神病院学斩神 - 三九音域":            ["combat", "myth", "power", "cthulhu"],
    "我不是戏神 - 三九音域":                    ["apocalypse", "power", "combat", "mystery"],
    "我无限回档，洞悉所有底牌 - 六个葫芦":       ["cthulhu", "horror", "combat", "dark", "mystery"],
    "十日终焉 - 杀虫队队员":                    ["mystery", "horror", "humanity", "dark", "power"],
    "末日降临？我先降临！ - 板面王仔":           ["wasteland", "survival", "combat", "apocalypse", "power"],
}

# beat_type 关键词 → 标签映射
BEAT_TAG_MAP: dict[str, list[str]] = {
    "cthulhu":    ["古神", "邪神", "低语", "呓语", "不可名状", "理智", "san", "污染", "侵蚀",
                  "旧日", "支配", "深渊", "触手", "诅咒", "疯狂", "寄生", "禁忌", "呓语", "凝视"],
    "power":      ["异能", "觉醒", "序列", "能力", "进化", "权柄", "代价", "异化", "畸变",
                  "超凡", "天赋", "神格", "本源", "法则", "吞噬", "变异"],
    "wasteland":  ["废土", "废墟", "辐射", "荒野", "避难所", "安全区", "聚集地", "变异体",
                  "畸变体", "堡垒", "壁垒"],
    "survival":   ["丧尸", "围城", "感染", "尸潮", "物资", "幸存者", "求生", "食物", "短缺"],
    "combat":     ["搏杀", "厮杀", "猎杀", "围剿", "越级", "斩杀", "激战", "死战",
                  "血腥", "杀戮", "反杀", "对决", "交战"],
    "horror":     ["诡异", "规则", "怪谈", "灵异", "恐怖", "压抑", "阴森", "诡异降临"],
    "myth":       ["神明", "神话", "怪物", "古神", "旧日", "支配者", "邪神", "神兽"],
    "apocalypse":  ["灾变", "灾厄", "末日", "文明崩塌", "末世", "灾难", "大灾变"],
    "humanity":   ["信任", "背叛", "救赎", "抉择", "人性", "牺牲", "羁绊", "温暖"],
    "dark":       ["绝望", "黑暗", "压抑", "崩溃", "残忍", "疯狂", "窒息"],
    "politics":   ["势力", "权谋", "阴谋", "博弈", "算计", "背叛", "阵营"],
    "taboo":      ["收容", "禁忌", "禁忌物", "规则", "异常"],
}


def _books_for_beat(beat_type: str) -> list[str] | None:
    """根据 beat_type 推断应该优先查哪些书。返回 None = 不过滤（查全部）。"""
    if not beat_type:
        return None
    text = beat_type.lower()
    matched_tags: set[str] = set()
    for tag, keywords in BEAT_TAG_MAP.items():
        if any(kw in text for kw in keywords):
            matched_tags.add(tag)
    if not matched_tags:
        return None
    relevant_books = [
        book for book, tags in BOOK_TAGS.items()
        if matched_tags & set(tags)
    ]
    return relevant_books if relevant_books else None

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
    "【网文语感铁律——这是网文，不是文学小说】"
    "你写的是网文，目的是让读者爽、让读者翻页不停，不是让读者停下来品鉴文字。"
    "AI写作像'绅士'，追求精确、克制、留白；人类网文写作像'土匪'，追求粗糙、直给、情绪爆发。"
    "你要把那个优雅的观察者，拉成一个浑身脏泥、满腹牢骚、一边算账一边骂街的活人。"
    "心法：把'他感受到了'全部改成'他妈的，他感受到了'。\n"
    "1. 修辞要'主观情绪评价'不要'客观物性描写'：不要写'灰烬带的日出是灰白色的'，"
    "   要写'天亮了，又是那种灰了吧唧的颜色，看得人心里堵得慌'。主角就是读者的'嘴替'，"
    "   每个环境描写都要带一句主观评价（堵得慌/烦死了/真他妈冷/又来这一套）。"
    "   比喻用'跟狗啃过似的''像糊了一层水泥'这种路人甲秒懂的生活化明喻，禁用'像被封印的一小片活海'这种需要脑补的暗喻。\n"
    "2. 连接要'因为所以'不要'蒙太奇跳跃'：给每一个动作加上'目的'。"
    "   不要写'出楼。旧商业街。翻倒的轿车。'这种空间切换，要写'出了楼就是旧商业街，那里是必经之路，也是最容易被堵的地方'。"
    "   把潜台词全部翻出来：'他之所以走得快，是因为……''如果耽误了，就会……'。"
    "   大胆用'于是''因为''所以''但是''然后''接着''谁知道''毕竟'，把因果链铺明白，让读者不动脑就能跟上。\n"
    "3. 句式要'情绪词前置+短句轰炸'：不要先描述再结论，先把结论/情绪甩出来再补环境。"
    "   '完了。''糟了。''好家伙。''妈的。'——情绪词前置，读者跟着主角情绪走。"
    "   把修饰性从句拆成独立判断句：'是尸臭。但不是新鲜的。林深一闻就知道——这种味儿至少死了四五天了。早就烂透了。'"
    "   短句是主节奏，独句段是常规武器（'滚。''哦。''双喜临门么！'）。少写多层嵌套长难句。\n"
    "4. 人物要'内心戏+庸俗化'不要'沉默的尊严'：每写一个外部动作，补一句内心独白。"
    "   '林深没动'→'林深站在原地，心里骂了一句娘。这两个瘪犊子摆明了是要吃定他。'"
    "   主角可以怕死、可以哆嗦、可以骂城防军、可以幻想吃香喝辣——他是'有脾气的活人'，不是'有尊严的沉默者'。"
    "   允许粗话和口语进入叙事：'他娘的''滚''一肚子坏水''冤种''瘪犊子'。\n"
    "5. 细节要'痛点'不要'象征'：不要写'锈斑像旧世界的地图'（象征），要写'铁皮顶棚锈透了，窟窿眼儿直往脖子里灌冷风，妈的这破棚子不知道还能撑几个冬天'（痛点）。"
    "   所有外部描写必须关联到主角的'生存利益'或'情绪波动'上——这东西让主角哪里不舒服、亏了多少、赚了什么、怕了什么。"
    "   加一句口语化的咒骂或牢骚，这是最廉价也最有效的'人味'添加剂。\n"
    "6. 对话要'潜冲突+脏字称呼'不要'潜台词+克制'：扔掉'我不是跟他们一伙的''我是想找你谈个事'这种克制台词，"
    "   改成'你别紧张，我跟那群拦路抢劫的傻逼不是一伙的。我是从内城偷跑出来的，有个活儿，你敢不敢接？'。"
    "   对话里加脏字、加称呼、加语气词（妈的/老娘/卧槽/敢不敢/你丫），每句对话都要带出人物的'立场'或'情绪'，而不是单纯交代信息。\n"
    "7. 整体语感：像人在耳边讲一个刺激的故事，不是在纸上砌砖石。读者翻页不停就是成功，停在某一页品鉴描写就是失败。\n\n"
    "【对话博弈】"
    "对话不是NPC发任务。两个人说话时必须有：试探、信息不对称、或立场冲突。"
    "禁止单向信息灌输（A说B听B问A答）。"
    "正确的对话：A试探→B反问→A加码→B暴露底线→达成或破裂。"
    "引路人不能只是'告诉你规则然后让你选'，必须有自己的目的和隐藏信息。\n\n"
    "【对话模拟法——产生博弈感的核心方法】"
    "写对话密集的场景时，不要直接'写一段对话'。按以下步骤模拟："
    "1. 先想清楚每个参与者的goal（他想要什么）、secret（他藏着什么）、leverage（他手里有什么牌）。"
    "2. 对话是双方用语言试探对方底线的过程——A试探→B反问或回避→A加码→B暴露或反击→达成/破裂。"
    "3. 每个角色说话方式必须不同——不能所有人都说标准的普通话书面语。"
    "   老油条说话绕弯子，年轻人说话直接，紧张的人会重复，心虚的人会过度解释。"
    "4. 引路人/导师角色绝不能只是'告诉你规则然后让你选'——他必须有自己的目的和隐藏信息，"
    "   他说的每句话都是在引导主角走向他想要的结果。\n\n"
    "【节奏呼吸——有张有弛】"
    "一章不能全程紧张。必须有张有弛：紧张段→松弛段→再紧张。"
    "结尾不要总是悬念炸弹——有时候一个松弛的收尾（主角回家、喝水、想事情）"
    "比又一个'黑影浮现'更有力量。读者需要喘气。\n\n"
    "【AI味黑名单——禁止使用以下表达】"
    "- '深吸一口气'（AI最爱的动作描写，用'喘了口气'或具体动作替代）"
    "- '心跳如擂鼓/心跳快得像要炸开'（陈词滥调，用具体感受替代）"
    "- '嘴角微微上扬/嘴角勾起一抹弧度'（AI专属表情，用具体动作替代）"
    "- '像被定格的照片/像时间凝固了'（AI明喻模板，删掉比喻直接写）"
    "- '瞳孔一缩/瞳孔骤缩'（AI最爱，用'愣住了'或具体反应替代）"
    "- '后背一阵发凉/后背发凉'（AI标记词，用具体恐惧反应替代）"
    "- '系统提示音/脑海中响起声音'（AI网文套路，用角色自己的感知替代）"
    "- 连续使用'忽然/突然/猛地'（AI节奏标记词，一章不超过2次）\n\n"
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
    """节点 1：装配章节上下文（core memory + 可选 archival 检索 + 题材文风标杆 + CSV 参考资料兜底）。"""
    cancel = _check_cancelled(state, "assemble")
    if cancel:
        return cancel
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

    # Gap 1 修复：注入 CSV 参考资料兜底（按 beat_type 检索爽点/桥段/场景/写作技法）
    # 让 writer 拿到"桥段套路库""场景写法库""爽点与节奏库"的直接参考，不依赖大纲 beats 的详细程度
    try:
        from novel_agent.references.search import ReferenceSearch, canonical_genre as _cg
        outline = repo.get_outline_by_chapter(state["chapter"])
        beat_type = ""
        if outline:
            beats = _safe_json_loads(outline.required_beats)
            if beats and isinstance(beats, list) and beats:
                beat_type = beats[0].get("type", "") if isinstance(beats[0], dict) else ""
        project = repo.get_project()
        cg_text = ""
        if project and project.genre:
            cg_text = _cg(project.genre)
        ref_search = ReferenceSearch()
        # 按 beat_type 检索相关参考资料（爽点/桥段/场景/写作技法）
        ref_rows = ref_search.search(
            query=beat_type or state.get("title", ""),
            canonical_genre=cg_text,
            skills=["webnovel-write"],
            limit=6,
        )
        if ref_rows:
            ref_lines = []
            for r in ref_rows:
                cat = r.get("分类", "")
                kw = r.get("关键词", "")
                inst = r.get("指令", "")
                detail = r.get("详细展开", "")
                line = f"- [{cat}] {kw}"
                if inst:
                    line += f"：{inst}"
                if detail:
                    line += f"（{detail}）"
                ref_lines.append(line)
            ref_block = "\n".join(ref_lines)
            context = f"{context}\n\n【参考资料·兜底（按本章beat_type={beat_type or '通用'}检索）】\n{ref_block}"
            logger.info("assemble_context 第%d章：注入CSV参考资料%d条(beat=%s)",
                        state["chapter"], len(ref_rows), beat_type or "通用")
    except Exception as e:
        logger.debug("assemble_context: 注入CSV参考资料失败: %s", e)

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
        # 叙事意图（Phase 4）
        emotion_arc = cc.pop("emotion_arc", "")
        pacing_intent = cc.pop("pacing_intent", "")
        theme_progression = cc.pop("theme_progression", "")
        char_focus = cc.pop("character_focus", "")
        scene_beats = cc.pop("scene_beats", "")
        if nf:
            soft_parts.append(f"剧情功能参考：{nf}")
        if info_focus:
            soft_parts.append(f"信息焦点参考：{info_focus}")
        if info_inc:
            soft_parts.append(f"信息增量参考：{info_inc}")
        if char_decisions:
            soft_parts.append(f"角色决策清单参考：{char_decisions}")
        # 叙事意图注入（核心约束，让 writer 按意图执行而非自由发挥）
        intent_parts = []
        if emotion_arc:
            intent_parts.append(f"  - 情感弧线：{emotion_arc}")
        if pacing_intent:
            intent_parts.append(f"  - 节奏意图：{pacing_intent}")
        if theme_progression:
            intent_parts.append(f"  - 主题推进：{theme_progression}")
        if char_focus:
            intent_parts.append(f"  - 角色弧光：{char_focus}")
        if scene_beats:
            intent_parts.append(f"  - 场景节拍：{scene_beats}")
        if intent_parts:
            hard_parts.append("叙事意图（必须忠实执行）：\n" + "\n".join(intent_parts))
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


async def analyze_style_benchmark(state: ChapterGenState,
                                   llm_client: LLMClient,
                                   repo: BibleRepository | None = None) -> dict:
    """节点：write 前加载人类网文样本并分析其写法特征。

    流程：加载人类章节 → LLM 按7维度分析（土匪式6维度+三拍节奏）→ 存 state。
    分析结果注入 write_chapter 的 prompt，并在 SSE 推送给前端展示。
    """
    cancel = _check_cancelled(state, "analyze_style")
    if cancel:
        return cancel

    # 从大纲提取 beat_type，推断偏好标签
    preferred_tags: list[str] = []
    beat_type = ""
    if repo:
        try:
            outline = repo.get_outline_by_chapter(state["chapter"])
            if outline:
                beats = _safe_json_loads(outline.required_beats)
                if beats and isinstance(beats, list):
                    beat_type = beats[0].get("type", "") if beats else ""
                if beat_type:
                    tags = set()
                    for tag, keywords in BEAT_TAG_MAP.items():
                        if any(kw in beat_type.lower() for kw in keywords):
                            tags.add(tag)
                    preferred_tags = list(tags) if tags else []
        except Exception as e:
            logger.warning("analyze_style 第%d章：提取beat_type失败: %s", state["chapter"], e)

    # 加载人类网文章节
    human_chapter = _load_random_human_chapter(max_chars=2500, preferred_tags=preferred_tags or None)
    if not human_chapter:
        logger.info("analyze_style 第%d章：未加载到人类样本，跳过分析", state["chapter"])
        return {"style_benchmark_text": "", "style_analysis": "", "status": "style_skipped"}

    # LLM 分析人类样本的写法特征
    analyze_prompt = (
        "你是网文写作教练。下面是一段人类网文作家的章节文本。"
        "请分析它的写法特征，提炼出可复用的技巧。分析必须具体，引用原文片段，说明'这样写好在哪里'。\n\n"
        "按以下7个维度逐一分析：\n\n"
        "1. 修辞策略：有没有主观情绪评价？比喻是生活化明喻还是文学化暗喻？主角是不是'嘴替'？\n"
        "2. 连接逻辑：用显性连接词（因为/所以/于是/但是）还是蒙太奇跳跃？动作有没有带'目的'？\n"
        "3. 句式节奏：短句还是长句为主？有没有情绪词前置？独句段怎么用？\n"
        "4. 人物塑造：有没有内心独白/骂娘/吐槽？主角是'有脾气的活人'还是'有尊严的沉默者'？\n"
        "5. 细节筛选：细节是'痛点'（让人不舒服）还是'象征'（需要脑补）？有没有关联生存利益？\n"
        "6. 对话处理：对话有没有脏字/称呼/语气词？是高信息量捅刀还是低信息量潜台词？\n"
        "7. 章节节奏：能不能看出起手式（直接进动作）/中盘（一收一放）/落锤（回收细节制造悬念）？\n\n"
        "每个维度格式：\n"
        "【维度名】\n"
        "原文片段：\"...\"\n"
        "分析：...\n"
        "可复用技巧：...\n\n"
        f"<人类网文样本>\n{human_chapter}\n</人类网文样本>\n\n"
        "只输出分析结果，不要废话。"
    )
    try:
        analysis = await llm_client.generate(analyze_prompt, temperature=0.3)
        logger.info("analyze_style 第%d章：分析完成（%d字），beat_type=%s",
                    state["chapter"], len(analysis or ""), beat_type)
        return {
            "style_benchmark_text": human_chapter,
            "style_analysis": analysis or "",
            "status": "style_analyzed",
        }
    except Exception as e:
        logger.warning("analyze_style 第%d章失败: %s，跳过分析", state["chapter"], e)
        return {"style_benchmark_text": human_chapter, "style_analysis": "", "status": "style_skipped"}


def _style_guides_for_beat(beat_type: str, narrative_function: str) -> str:
    """Gap 3 修复：按 beat_type/narrative_function 动态加载 task-specific style guides。

    style_guide_loader.get_guides_for_generation 把 write_chapter 映射成""（空），
    导致 combat_guide.txt/character_guide.txt 等纯文本写法指南在写章节时一个都不注入。
    此函数按章节类型动态加载，补上这个缺口。

    映射规则：
    - 战斗/搏杀/厮杀/猎杀/围剿/激战/对决 → combat_guide
    - 人物塑造/关系建立/角色弧光 → character_guide
    - 世界观铺陈/设定传递 → worldview_guide
    - 势力/谈判/权谋/博弈 → faction_guide
    """
    from novel_agent.templates.style_guide_loader import get_task_guide
    text = f"{beat_type} {narrative_function}"
    guides: list[tuple[str, str]] = []
    if any(k in text for k in ["战斗", "搏杀", "厮杀", "猎杀", "围剿", "激战", "对决", "交战"]):
        g = get_task_guide("combat")
        if g:
            guides.append(("战斗写法指南", g))
    if any(k in text for k in ["人物塑造", "关系建立", "角色弧光", "感情"]):
        g = get_task_guide("character")
        if g:
            guides.append(("角色写法指南", g))
    if any(k in text for k in ["世界观铺陈", "设定传递", "开篇钩子"]):
        g = get_task_guide("worldview")
        if g:
            guides.append(("世界观写法指南", g))
    if any(k in text for k in ["势力", "谈判", "权谋", "博弈", "阵营"]):
        g = get_task_guide("faction")
        if g:
            guides.append(("势力写法指南", g))
    if not guides:
        return ""
    parts = []
    for name, content in guides:
        parts.append(f"【{name}】\n{content}")
    return "\n\n".join(parts)


async def write_chapter(state: ChapterGenState,
                        llm_client: LLMClient,
                        repo: BibleRepository | None = None,
                        config: Config | None = None) -> dict:
    """节点 2：调 LLM 生成章节正文。"""
    cancel = _check_cancelled(state, "write")
    if cancel:
        return cancel
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

    # Gap 3 修复：按 beat_type/narrative_function 动态注入 task-specific style guides
    # combat_guide.txt / character_guide.txt / worldview_guide.txt / faction_guide.txt
    # 这些是纯文本写法指南，没进 DB，需要按章节类型动态加载
    task_guides = _style_guides_for_beat(beat_type, narrative_function)
    if task_guides:
        logger.info("write_chapter 第%d章：注入task-specific guides(beat=%s, nf=%s)",
                    state["chapter"], beat_type, narrative_function)

    # Gap 4 修复：字数阈值统一从 节奏阈值.csv 读取（单一真源，与 audit 共用）
    from novel_agent.audit.validator import _get_threshold
    word_min = int(_get_threshold("字数下限", 2200))
    word_max = int(_get_threshold("字数上限", 3500))
    word_min_important = int(_get_threshold("字数下限_重要章节", 2500))
    is_important = state.get("chapter", 0) <= 3 or "高潮" in narrative_function or "转折" in narrative_function
    target_min = word_min_important if is_important else word_min

    # 语感检索：如果开启kill-switch且有beat_type，从末日文库检索真实片段替换few-shot
    genre_rag_slices = ""
    try:
        if config is None:
            from novel_agent.config import load_config
            config = load_config()
        if getattr(config, "enable_genre_rag", False) and beat_type:
            import chromadb
            from novel_agent.memory.archival import _build_embedding_function
            chroma_dir = config.chroma_dir
            _client = chromadb.PersistentClient(path=str(chroma_dir))
            _ef = _build_embedding_function(config)
            _coll = _client.get_or_create_collection(
                name="genre_archive_doomsday",
                metadata={"hnsw:space": "cosine"},
                embedding_function=_ef,
            )
            if _coll.count() > 0:
                # 按方向过滤：只查 beat_type 对口的书
                target_books = _books_for_beat(beat_type)
                query_kwargs: dict = {"query_texts": [beat_type], "n_results": 5}
                if target_books:
                    query_kwargs["where"] = {"source_book": {"$in": target_books}}
                res = _coll.query(**query_kwargs)
                # 如果过滤后结果不足3条，降级查全部
                docs = res.get("documents", [[]])[0]
                dists = res.get("distances", [[]])[0]
                if target_books and len(docs) < 3:
                    logger.info("write_chapter 第%d章 过滤后仅%d条，降级查全部", state["chapter"], len(docs))
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
                logger.info("write_chapter 第%d章 genre RAG命中 %d条 (beat=%s, 过滤=%s, 阈值0.7)",
                            state["chapter"], len(slices), beat_type,
                            ",".join(target_books) if target_books else "全部")
    except Exception as e:
        logger.warning("write_chapter 第%d章 genre RAG失败，降级few-shot: %s", state["chapter"], e)

    # 预算策略：RAG优先，few-shot降级兜底
    style_content = genre_rag_slices if genre_rag_slices else few_shot
    # 章纲内容不足时是否允许 AI 自行扩充
    auto_expand = bool(getattr(config, "allow_auto_expand_chapter", True)) if config else True
    expand_hint = (
        "如果章纲简略，可补充对话和冲突，但禁止堆砌环境描写和心理独白来凑字数。"
    ) if auto_expand else ""
    prompt = (
        f"<task>请写第{state['chapter']}章《{state.get('title', '')}》正文。</task>\n\n"
        f"<word_limit>【字数硬上限】正文{word_min}-{word_max}字，重要章节{word_min_important}-{word_max}字，"
        f"{word_max}字是硬性天花板，超过即为废稿。"
        f"宁可剧情紧凑字数偏少，也不要注水。写每个段落前都问自己：这段话推进剧情了吗？没有就删。</word_limit>\n\n"
        f"<context>\n{state.get('context', '')}\n</context>\n\n"
    )
    # 注入人类样本写法分析（analyze_style 节点产出）
    style_analysis = state.get("style_analysis", "")
    if style_analysis:
        prompt += (
            f"<style_analysis>\n这是对人类网文样本的写法分析。"
            f"写正文时必须运用这些技巧，尤其是'可复用技巧'部分。\n"
            f"{style_analysis}\n</style_analysis>\n\n"
        )
    if chapter_brief:
        prompt += f"<constraints>\n{chapter_brief}\n</constraints>\n\n"
    # Gap 3：注入 task-specific style guides（战斗/角色/世界观/势力写法指南）
    if task_guides:
        prompt += f"<task_guides>\n{task_guides}\n</task_guides>\n\n"
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
        f"{expand_hint}"
        f"软约束尽量做到——宁可少做一个软约束，也不要把硬约束写成流水账。"
        f"</rules>\n\n"
        f"<word_limit_reminder>再次强调：正文不超过{word_max}字。这是硬性上限，超过会被判定为废稿。"
        f"网文要快、要脆、要爽，不要慢、不要涩、不要长。短句短段快节奏。</word_limit_reminder>\n\n"
        f"依据context和constraints写出本章正文。只输出正文，不要输出JSON或格式说明。"
    )
    try:
        draft = await llm_client.generate(prompt, system=WRITER_SYSTEM_PROMPT, temperature=dynamic_temp)
        draft = clean_chapter_text(draft, state["chapter"], state.get("title", ""))
        if _looks_like_json_not_prose(draft):
            logger.warning("write_chapter 第%d章：LLM 返回 JSON 而非正文", state["chapter"])
            return {"status": "failed", "error": "LLM 返回了 JSON 而非正文，可能模型理解错误"}
        if not draft.strip():
            logger.warning("write_chapter 第%d章：LLM 返回空正文", state["chapter"])
            return {"status": "failed", "error": "LLM 返回空正文，可能是配额超限或模型异常，请重试"}
        ver = state.get("draft_version", 0) + 1
        return {"draft": draft, "status": "drafted",
                "draft_version": ver,
                "drafts": [{"version": ver, "text": draft, "score": 0}],
                "word_count": len(re.findall(r'[\u4e00-\u9fff]', draft)),
                "_beat_type": beat_type}
    except Exception as e:
        logger.warning("write_chapter 第%d章失败：%s", state["chapter"], e)
        return {"status": "failed", "error": str(e)}


async def audit_chapter(state: ChapterGenState, auditor: Auditor,
                        repo: BibleRepository,
                        config: Config | None = None) -> dict:
    """节点：独立审校草稿，返回审计报告。写审分离铁律。"""
    cancel = _check_cancelled(state, "audit")
    if cancel:
        return cancel
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
    word_max = int(_get_threshold("字数上限", 3500))
    to_plant = repo.get_foreshadows_to_plant(state["chapter"])
    foreshadows_data = [{"id": f.foreshadow_id, "description": f.description} for f in to_plant]
    det_result = run_deterministic_checks(state["draft"], foreshadows_data, word_min=word_min, word_max=word_max)

    # 确定性检查结果作为 issues 保留给 rewrite 参考，但不污染 auditor 输入（写审分离铁律）
    det_issues = [Issue(**i) for i in det_result["issues"]]

    # 阶段3：爽点断层检测 + 黄金三章检查 + 卷高潮欠账检查（确定性，需要 repo）
    if repo:
        try:
            pleasure_issues = check_pleasure_gap(repo, state["chapter"])
            golden_issues = check_golden_three(repo, state["chapter"])
            climax_issues = check_volume_climax(repo, state["chapter"])
            # Gap 5：连续压抑章数 + 钩子连续重复检查
            from novel_agent.audit.validator import (
                check_suppression_streak, check_hook_repetition,
            )
            suppression_issues = check_suppression_streak(repo, state["chapter"])
            hook_issues = check_hook_repetition(repo, state["chapter"])
            for pi in pleasure_issues + golden_issues + climax_issues + suppression_issues + hook_issues:
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

        # L0 角色一致性检查：角色名/位置/状态（零 token 消耗）
        try:
            from novel_agent.audit.validator import (
                check_character_name_consistency,
                check_character_location,
                check_character_state_consistency,
            )
            char_issues = (
                check_character_name_consistency(state["draft"], repo)
                + check_character_location(state["draft"], repo)
                + check_character_state_consistency(state["draft"], repo)
            )
            for ci in char_issues:
                det_issues.append(Issue(**ci))
        except Exception as e:
            logger.warning("audit_chapter 第%d章：L0角色检查失败: %s", state["chapter"], e)

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

    # 审查不通过时触发对抗性讨论（每次不通过都触发，可配置最大轮数）
    if not report.passed and hasattr(auditor, 'debate'):
        try:
            logger.info("audit_chapter 第%d章：审查不通过（%s），启动对抗性讨论（第%d轮）",
                        state["chapter"], report.summary, iterations)
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

    # 置信度计算：高置信度跳过人审，低置信度强制人审
    has_critical = any(i.severity == "critical" for i in det_issues)
    has_important = any(i.severity == "important" for i in det_issues)
    if report.passed and not has_critical and not has_important:
        confidence = "high"
    elif report.passed and not has_critical:
        confidence = "medium"
    else:
        confidence = "low"

    # 回写当前草稿的 audit score 到 drafts（供 route_after_audit 降级时取最高分）
    all_drafts = list(state.get("drafts", []))
    current_ver = state.get("draft_version", 0)
    for d in all_drafts:
        if d.get("version") == current_ver:
            d["score"] = report.overall_score
            break

    return {
        "audit_report": report.model_dump(),
        "review_iterations": iterations,
        "status": "audited" if report.passed else "needs_rewrite",
        "confidence_level": confidence,
        "drafts": all_drafts,
    }


def route_after_audit(state: ChapterGenState) -> str:
    """条件边：审计达标→高置信度跳过人审/中低置信度人审；不达标→连续2轮无改善或超上限则降级。

    降级策略（改进）：
    - 不再用固定3轮硬上限
    - 连续2轮 score 无改善 → 降级
    - 超过可配置上限（默认4轮）→ 降级
    - 降级时取 audit score 最高的草稿（不是字数最多）
    """
    if state.get("status") == "failed":
        logger.warning("route_after_audit 进入 end_failed：status=%s", state.get("status"))
        return "end_failed"
    report = AuditReport(**state.get("audit_report", {}))
    logger.warning("route_after_audit 第%s章：status=%s passed=%s confidence=%s iterations=%s",
                   state.get("chapter"), state.get("status"), report.passed,
                   state.get("confidence_level"), state.get("review_iterations", 0))
    if report.passed:
        logger.warning("route_after_audit 第%s章：走人审", state.get("chapter"))
        return "style_refine"  # 走 human_review（所有通过审计的都人审）

    # 不通过：检查是否应降级
    iterations = state.get("review_iterations", 0)
    max_iterations = 4  # 可配置上限（从 config 读取或硬编码）

    # 字数 critical 问题不参与降级——超字数是硬约束，必须 rewrite 到达标
    has_critical_word_count = any(
        i.severity == "critical" and i.dimension == "字数"
        for i in report.issues
    )
    if has_critical_word_count:
        logger.warning("route_after_audit 第%s章：存在 critical 字数问题，强制 rewrite（不降级）",
                       state.get("chapter"))
        if iterations >= max_iterations:
            # 超过上限仍超字数：硬截断保底，避免无限循环
            logger.warning("route_after_audit 第%s章：rewrite 上限已到仍超字数，硬截断后降级",
                           state.get("chapter"))
            draft = state.get("draft", "")
            from novel_agent.audit.validator import _get_threshold, count_chinese_chars
            hard_max = int(_get_threshold("字数上限", 3500))
            if count_chinese_chars(draft) > hard_max:
                # 按句截断到硬上限（保留完整句子，不切断对话）
                import re
                chars = re.findall(r'[\u4e00-\u9fff]', draft)
                kept = 0
                cut_idx = len(draft)
                for m in re.finditer(r'[\u4e00-\u9fff]', draft):
                    kept += 1
                    if kept >= hard_max:
                        # 往后找到下一个句末标点
                        rest = draft[m.end():]
                        pm = re.search(r'[。！？…\n]', rest)
                        cut_idx = m.end() + (pm.end() if pm else 0)
                        break
                truncated = draft[:cut_idx].rstrip()
                logger.warning("route_after_audit 第%s章：硬截断 %d→%d 字（route 无法改 state，截断由 polish 节点兜底）",
                               state.get("chapter"), count_chinese_chars(draft), count_chinese_chars(truncated))
                return "skip_review"
        return "rewrite"

    # 检查连续2轮 score 无改善
    all_drafts = state.get("drafts", [])
    scores = [d.get("score", 0) for d in all_drafts if d.get("score", 0) > 0]
    no_improvement = False
    if len(scores) >= 2 and scores[-1] <= scores[-2]:
        no_improvement = True
        logger.warning("route_after_audit 第%s章：连续2轮 score 无改善（%d→%d），降级",
                       state.get("chapter"), scores[-2], scores[-1])

    if iterations >= max_iterations or no_improvement:
        # 降级：取 audit score 最高的草稿
        if all_drafts:
            best = max(all_drafts, key=lambda d: d.get("score", 0))
            best_score = best.get("score", 0)
            best_text = best.get("text", "")
            current_text = state.get("draft", "")
            if best_text and best_score > 0 and len(best_text) > len(current_text) * 0.8:
                logger.warning("route_after_audit 降级：取草稿轮v%s（score=%d，%d字）",
                               best.get("version"), best_score, len(best_text))
        logger.warning("route_after_audit 降级接受：iterations=%d，score=%d，继续style_refine",
                       iterations, report.overall_score)
        return "skip_review"
    return "rewrite"


async def rewrite_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：基于审计建议重写（含对抗讨论修订建议）。"""
    cancel = _check_cancelled(state, "rewrite")
    if cancel:
        return cancel
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
    beat_type_rw = ""
    narrative_function_rw = ""
    try:
        repo = BibleRepository(state.get("project_id", 1))
        outline = repo.get_outline_by_chapter(state["chapter"])
        if outline:
            chapter_brief = _build_chapter_brief(outline, repo)
            # 补few_shot（治A3残留：rewrite也需风格参考）
            beats = _safe_json_loads(outline.required_beats)
            beat_type_rw = beats[0].get("type", "") if beats and isinstance(beats, list) else ""
            if beat_type_rw:
                few_shot = get_few_shot_for_beat(beat_type_rw)
            cc = _safe_json_loads(outline.character_constraints)
            if cc and isinstance(cc, dict):
                narrative_function_rw = cc.get("narrative_function", "")
    except Exception:
        pass

    # Gap 4 修复：字数阈值统一从 节奏阈值.csv 读取（与 write_chapter/audit 共用同一真源）
    from novel_agent.audit.validator import _get_threshold
    word_min = int(_get_threshold("字数下限", 2200))
    word_max = int(_get_threshold("字数上限", 3500))
    word_min_important = int(_get_threshold("字数下限_重要章节", 2500))

    # Gap 3 修复：重写也注入 task-specific style guides
    task_guides_rw = _style_guides_for_beat(beat_type_rw, narrative_function_rw)

    prompt = (
        f"重写第{state['chapter']}章《{state.get('title', '')}》。\n\n"
        f"<word_limit>【字数硬上限】正文{word_min}-{word_max}字，重要章节{word_min_important}-{word_max}字，"
        f"{word_max}字是硬性天花板，超过即为废稿。"
        f"如果审计问题里提到超字数，必须大幅删减环境描写和心理独白，只保留推进剧情的内容。</word_limit>\n\n"
        f"【上下文】\n{state.get('context', '')}\n\n"
        f"{chapter_brief}\n\n"
        f"{'<style_reference>' + chr(10) + few_shot + chr(10) + '</style_reference>' + chr(10) + chr(10) if few_shot else ''}"
        f"{('<task_guides>' + chr(10) + task_guides_rw + chr(10) + '</task_guides>' + chr(10) + chr(10)) if task_guides_rw else ''}"
        f"【上一版草稿】\n{state.get('draft', '')}\n\n"
        f"【审计问题】\n{issues}\n\n"
        f"【修订建议】\n{suggestions}\n\n"
        f"{debate_text}\n"
        f"{core_constraints}\n\n"
        f"要求：针对问题重写，严格遵循上述核心写作约束（特别是网文语感铁律和反AI味要求）。"
        f"【硬约束铁律】硬约束必须完成，尤其是爽点交付——如果大纲要求'打脸'，"
        f"必须写出完整的打脸过程，不能一笔带过。"
        f"最重要：网文语感——短句、口语、显性连接词、高信息量对话、标签化细节，追求'脆'和'响'，不要文学化的长句铺陈。"
        f"\n<word_limit_reminder>再次强调：正文不超过{word_max}字。这是硬性上限，超过会被判定为废稿。</word_limit_reminder>"
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
        "【比喻过密——必须削减】\n"
        "- 每千字比喻不超过1-2个，多余的必须删掉。\n"
        "- 喻体必须是日常具象物（熊、水泥、铜铃），禁止华丽抒情性比喻。\n"
        "- 删掉'如同...一般''宛若...似的''仿佛...一样'的密集铺陈。\n"
        "- 比喻只为降低理解门槛，不是增加文学美感。\n\n"
        "【抽象情绪词——必须替换为动作/生理反应】\n"
        "- 禁止'他感到一阵悲伤/愤怒/绝望/恐惧/震惊涌上心头'这类表达。\n"
        "- 悲伤→写具体动作：'摇摇头，长叹一口气''苦笑'\n"
        "- 愤怒→写具体动作：'疯狂地拍着桌子''面皮抽搐'\n"
        "- 恐惧→写生理反应：'汗毛倒立''心中漏了一拍'\n"
        "- 得意→用反差细节：'露出笑容，银牙在血污里惹眼'\n\n"
        "【关联词调整——口语化优先】\n"
        "- '然而'→改为'但是/可是'。'因此'→改为'所以'。\n"
        "- '与此同时''不仅如此'→删掉或改为'接着''而且'。\n"
        "- 多用'却'做句中轻转折，不需要每次都停顿。\n\n"
        "【标点修复——必须执行】\n"
        "如果原文有连续40字以上无逗号句号的长句，必须在适当位置插入逗号断句。\n"
        "中文叙事句子的自然长度是10-25字，超过30字必须有标点停顿。\n\n"
        "【排比打断——必须执行】\n"
        "如果原文有连续4个以上相同句式（如连续4个'越来越X'、连续4个'放弃X'、连续4个'碾成X'），\n"
        "只保留前2个，其余的必须改写为不同句式或直接删除。\n"
        "排比是修辞手法不是叙事方式——2个够了，第3个开始就是AI味。\n\n"
        "【感叹号降级——必须执行】\n"
        "每段最多2个感叹号。多余的改为句号或省略号。\n"
        "叙事描写中不用感叹号，感叹号仅限对话和内心独白。\n"
        "真正的冲击力来自内容而非标点。冷叙述比感叹号轰炸更有力量。\n\n"
        "【重复递进截断——必须执行】\n"
        "如果原文有'越来越X越来越Y越来越Z'这种连续递进，最多保留2个。\n"
        "如果原文有'放弃X！放弃Y！放弃Z！'这种连续排比感叹，最多保留2个。\n\n"
        "【段落节奏】\n"
        "如果原文每句都是单独一段（碎片化），请将相关句子合并为3-6句的正常叙事段落。"
        "独句段只保留在强调和爆发点。\n"
        "关键转折和反应可以用单句独立成段（如'试过了。''确实打不过。'），但不要过度使用。\n\n"
        "【对话提示语精简】\n"
        "- 删掉多余的对话提示语（'他微笑着说''她温柔地开口'），连续对话靠语气区分角色。\n"
        "- 对话提示语后置或省略，不要每句话都配提示语。\n\n"
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
        word_max = int(_get_threshold("字数上限", 3500))
        cn_count = count_chinese_chars(polished)
        hard_fail = False
        if cn_count < word_min:
            polish_issues.append(f"润色后字数不足：{cn_count}（及格线{word_min}）")
            hard_fail = True
        # 超字数硬截断兜底：rewrite 多轮仍超字数时，按句截断到硬上限
        # 这是最终输出前的最后闸门，确保用户拿到的正文绝不超过 word_max
        if cn_count > word_max:
            logger.warning("polish_chapter 第%d章：超字数 %d>%d，硬截断",
                          state["chapter"], cn_count, word_max)
            # 按句截断：找到第 word_max 个中文字后的下一个句末标点
            kept = 0
            cut_idx = len(polished)
            for m in re.finditer(r'[\u4e00-\u9fff]', polished):
                kept += 1
                if kept >= word_max:
                    rest = polished[m.end():]
                    pm = re.search(r'[。！？…\n]', rest)
                    if pm and pm.end() <= 50:  # 句末标点在50字内才接受
                        cut_idx = m.end() + pm.end()
                    else:
                        cut_idx = m.end()  # 硬切
                    break
            before = cn_count
            polished = polished[:cut_idx].rstrip()
            cn_count = count_chinese_chars(polished)
            # 二次验证：如果按句截断后仍超（句末标点太远），硬切到 word_max
            if cn_count > word_max:
                kept = 0
                for i, ch in enumerate(polished):
                    if '\u4e00' <= ch <= '\u9fff':
                        kept += 1
                        if kept >= word_max:
                            polished = polished[:i+1]
                            break
                cn_count = count_chinese_chars(polished)
            polish_issues.append(f"超字数硬截断：{before}→{cn_count}（上限{word_max}）")
            logger.warning("polish_chapter 第%d章：硬截断完成 %d→%d 字",
                          state["chapter"], before, cn_count)
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

        # ── oh-story 7 Gate 去 AI 味后处理（完整版）──
        # 在 polish 完成后、字数/限频词/伏笔检查通过后注入
        # 跳过条件：无 blocking 且 advisory≤2 时 deslop 内部自动跳过 LLM 调用节省 token
        try:
            from novel_agent.audit.deslop_postprocessor import run_deslop_postprocess, get_deslop_summary
            deslop_result = await run_deslop_postprocess(polished, llm_client)
            if not deslop_result["skipped"]:
                deslop_text = deslop_result["processed_text"]
                # deslop 后再次校验字数（不应大幅缩短）
                deslop_cn = len(re.findall(r'[\u4e00-\u9fff]', deslop_text))
                orig_cn = len(re.findall(r'[\u4e00-\u9fff]', polished))
                if orig_cn > 0 and deslop_cn >= int(orig_cn * 0.65):  # 至少保留 65%
                    polished = deslop_text
                    cn_count = deslop_cn
                    logger.info("polish_chapter 第%d章：deslop 后处理完成 - %s",
                               state["chapter"], get_deslop_summary(deslop_result))
                    if deslop_result["rolled_back"]:
                        polish_issues.append("deslop改写后blocking增多，已回退原版本")
                else:
                    logger.warning("polish_chapter 第%d章：deslop 后字数缩水过多 %d→%d，保留 polish 版本",
                                  state["chapter"], orig_cn, deslop_cn)
                    polish_issues.append(f"deslop后字数缩水：{orig_cn}→{deslop_cn}")
            else:
                logger.info("polish_chapter 第%d章：deslop 跳过（确定性检测通过）", state["chapter"])
        except Exception as e:
            logger.warning("polish_chapter 第%d章：deslop 后处理失败（不阻塞）: %s",
                          state["chapter"], e)

        return {"polished": polished, "status": "polished",
                "word_count": len(re.findall(r'[\u4e00-\u9fff]', polished)),
                "polish_review_issues": polish_issues}
    except Exception as e:
        logger.warning("polish_chapter 第%d章失败: %s", state["chapter"], e)
        # polish 失败不阻塞流程，用原草稿继续
        draft = clean_chapter_text(state.get("draft", ""), state["chapter"], state.get("title", ""))
        return {"polished": draft, "status": "polished",
                "polish_warning": str(e)}


def _find_human_chapter_dir() -> Path | None:
    """动态查找人类小说章节目录，兼容开发和打包模式。"""
    import sys as _sys
    candidates: list[Path] = []
    if getattr(_sys, "frozen", False):
        # PyInstaller 打包模式
        exe_dir = Path(_sys.executable).parent
        # _MEIPASS 是 PyInstaller 解压数据的临时目录
        meipass = Path(getattr(_sys, "_MEIPASS", exe_dir))
        candidates.extend([
            meipass / "codex" / "novel_chapters",
            meipass / "小说语料",
            exe_dir / "codex" / "novel_chapters",
            exe_dir / "小说语料",
        ])
    else:
        # 开发模式：项目根目录
        _root = Path(__file__).resolve().parent.parent.parent
        candidates.extend([
            _root / "codex" / "novel_chapters",
            _root / "小说语料",
        ])
    for d in candidates:
        if d.exists() and d.is_dir():
            return d
    return None


def _load_random_human_chapter(max_chars: int = 3000, preferred_tags: list[str] | None = None) -> str | None:
    """从人类作家小说目录随机抽取一章作为风格参考。

    支持两种目录格式：
    - 分章文件: 0001.txt, 0002.txt, ...
    - 完整小说: 书名.txt（随机截取一段）

    preferred_tags: 偏好的节奏标签（如 combat/politics/horror），用于过滤不匹配的章节。
    """
    chapter_dir = _find_human_chapter_dir()
    if not chapter_dir:
        logger.info("人类小说语料目录未找到，style_refine 将跳过风格模仿")
        return None
    # 分章文件（纯数字命名）
    chapter_files = sorted(
        f for f in chapter_dir.glob("*.txt")
        if re.match(r"^\d+\.txt$", f.name)
    )
    if not chapter_files:
        # 降级：从完整小说文件中随机抽取一段
        all_novels = list(chapter_dir.glob("*.txt"))
        if not all_novels:
            logger.warning("人类小说语料目录为空: %s", chapter_dir)
            return None
        picked = random.choice(all_novels)
        try:
            text = picked.read_text(encoding="utf-8", errors="ignore").strip()
            if len(text) > max_chars:
                start = random.randint(0, max(0, len(text) - max_chars))
                text = text[start:start + max_chars]
            logger.info("风格参考：从 %s 随机截取 %d 字", picked.name, len(text))
            return text
        except Exception as e:
            logger.warning("读取人类小说失败 %s: %s", picked.name, e)
            return None

    # 按节奏标签过滤：预映射章节区间到节奏类型
    # 来源：book_analysis 拆书报告卷级分析
    TAG_RANGES: dict[str, list[tuple[int, int]]] = {
        "combat":     [(50, 120), (200, 280), (400, 480), (600, 700), (800, 900), (1100, 1200), (1400, 1506)],
        "politics":   [(120, 200), (350, 400), (550, 600), (900, 1000), (1200, 1300)],
        "horror":     [(1, 50), (280, 350), (480, 550), (700, 800)],
        "humanity":   [(200, 250), (400, 450), (600, 650), (1000, 1100)],
        "dark":       [(1300, 1400)],
        "cthulhu":    [(1, 50), (280, 350), (700, 800), (1300, 1400)],
        "power":      [(50, 120), (200, 300), (500, 600), (800, 900), (1100, 1200)],
        "wasteland":  [(1, 100), (400, 500), (700, 800)],
    }

    candidates = chapter_files
    if preferred_tags:
        # 从偏好标签对应的章节区间中选候选
        candidate_ranges = []
        for tag in preferred_tags:
            candidate_ranges.extend(TAG_RANGES.get(tag, []))
        if candidate_ranges:
            candidates = []
            for f in chapter_files:
                ch_num = int(re.match(r"(\d+)", f.name).group(1))
                for lo, hi in candidate_ranges:
                    if lo <= ch_num <= hi:
                        candidates.append(f)
                        break
            if not candidates:
                candidates = chapter_files  # 过滤后为空则降级为全量

    picked = random.choice(candidates)
    try:
        text = picked.read_text(encoding="utf-8", errors="ignore").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        logger.info("风格参考：随机抽取人类小说 %s（%d字，候选%d篇，tags=%s）",
                    picked.name, len(text), len(candidates), preferred_tags or "无")
        return text
    except Exception as e:
        logger.warning("读取人类小说章节失败 %s: %s", picked.name, e)
        return None


async def style_refine_chapter(state: ChapterGenState, llm_client: LLMClient) -> dict:
    """节点：随机抽取一篇人类小说章节，模仿其写作手法润色正文。

    在 polish 之后、save_text 之前执行。
    不改变剧情/设定/伏笔，只学习人类作家的叙事节奏、句式变化、对话处理、场景转换手法。
    """
    cancel = _check_cancelled(state, "style_refine")
    if cancel:
        return cancel
    # 降级策略：如果 drafts 中有比当前 draft 分数更高的，取最高分草稿
    all_drafts = state.get("drafts", [])
    current_draft = state.get("draft", "")
    if all_drafts:
        best = max(all_drafts, key=lambda d: d.get("score", 0))
        if best.get("score", 0) > 0 and best.get("text"):
            current_cn = len(re.findall(r'[\u4e00-\u9fff]', current_draft))
            best_cn = len(re.findall(r'[\u4e00-\u9fff]', best["text"]))
            if best_cn > current_cn * 0.8:
                logger.info("style_refine 第%d章：使用最高分草稿v%d（score=%d）",
                            state["chapter"], best.get("version"), best.get("score"))
                current_draft = best["text"]
    polished = state.get("polished") or current_draft
    if not polished:
        return {"polished": polished}

    # 从大纲提取 beat_type，推断偏好标签
    preferred_tags: list[str] = []
    beat_type = state.get("_beat_type", "")
    if beat_type:
        tags = set()
        for tag, keywords in BEAT_TAG_MAP.items():
            if any(kw in beat_type.lower() for kw in keywords):
                tags.add(tag)
        preferred_tags = list(tags) if tags else []

    human_chapter = _load_random_human_chapter(max_chars=3000, preferred_tags=preferred_tags or None)
    if not human_chapter:
        logger.info("style_refine 第%d章：未获取到人类小说参考，跳过", state["chapter"])
        return {"polished": polished}

    STYLE_REFINE_SYSTEM = (
        "你是一位精通模仿的网文写手。你会研读人类作家的章节，"
        "学习其语言表达技巧和叙事手法，然后将这些手法运用到目标正文的润色中。\n\n"
        "【绝对铁律——不得违反】\n"
        "1. 不得改变剧情、设定、伏笔、角色关系、角色台词含义。\n"
        "2. 只学习人类作家的'写法'（怎么写），不抄它的'内容'（写什么）。\n"
        "3. 不得新增角色、场景、道具、事件。\n"
        "4. 保持原文的信息量和字数规模，不得大幅缩减或膨胀。\n\n"
        "【语言特征——必须从人类作品中学习并运用】\n\n"
        "一、关联词使用：\n"
        "- 多用'但/但是/可是/却'做转折，少用'然而/因此'。'却'常在句中做轻转折，不停顿。\n"
        "- '所以'远多于'因此'。口语化的'于是'也常用。\n"
        "- 转折词可以独立成段（如'但是。'单独一行），制造节奏停顿。\n"
        "- 几乎不用'与此同时''不仅如此'等书面连接词。\n\n"
        "二、句式特征：\n"
        "- 短句为主。关键转折、反应、判断用单句甚至单词独立成段（如'试过了。''确实打不过。''什么？！'）。\n"
        "- 长句仅用于信息铺陈，且用句号断开，不用逗号连到底。\n"
        "- 大量使用无主语句（'终于到了''试过了'），省略主语增强节奏感。\n"
        "- 主动句为主，极少用'被'字被动句。\n\n"
        "三、修辞克制：\n"
        "- 排比极罕见：最多二项对偶（'无数物种灭绝，无数物种诞生'），禁止三句以上排比。\n"
        "- 比喻低密度：每千字不超过1-2个，喻体必须是日常具象物（熊、水泥、铜铃、杨树叶子），禁止抒情性比喻。\n"
        "- 比喻功能是降低理解门槛，不是增加文学美感。\n"
        "- 禁止'如同...一般''宛若...似的''仿佛...一样'密集铺陈。\n\n"
        "四、情绪表达——核心差异：\n"
        "- 禁止使用抽象情绪词（悲伤、愤怒、绝望、喜悦、恐惧、震惊）。\n"
        "- 情绪必须用外部动作/生理反应/反差细节外化：\n"
        "  紧张→'心中漏了一拍''汗毛倒立'\n"
        "  愤怒→'疯狂地拍着桌子''面皮抽搐'\n"
        "  得意→'露出了笑容，两排银牙在血污里惹眼'（反差细节）\n"
        "  厌恶→'嫌弃地绕开，仿佛绕开一坨狗屎'\n"
        "- 禁止'他感到一阵悲伤涌上心头'这类内心独白式情绪描写。\n\n"
        "五、对话处理：\n"
        "- 对话提示语后置或完全省略。连续对话不加任何提示语，靠语气区分角色。\n"
        "- 允许打断：'滚。'/秦思洋没等他说完——对话被动作截断。\n"
        "- 潜台词：台词字面意义与实际意图形成反差（如边扎刀边说'不用谢'）。\n"
        "- 对话中有博弈感，不是单纯交换信息。\n\n"
        "六、环境与动作：\n"
        "- 环境描写不超过2句，必须绑定人物动作或感知，禁止独立抒情段落。\n"
        "- 动作描写极简，动词驱动，不加修饰（'一脚踹在它身上'而非'用力地一脚踹在它身上'）。\n"
        "- 模糊量词增加生动感：'十刀八刀''像个熊一样''一巴掌'。\n\n"
        "七、语气与口语：\n"
        "- 允许粗话和口语进入叙事：'他娘的''滚''一肚子坏水''冤种'。\n"
        "- 感叹号仅限对话和内心独白，叙事描写保持平叙。\n"
        "- 反问句是重要修辞手段：'核弹都杀不死神明，他的左轮手枪有什么用？'\n\n"
        "八、留白技巧：\n"
        "- 主动悬置部分信息，用'不知道为什么''出于某种原因'跳过解释。\n"
        "- 不解释所有因果关系，让读者自行推断。\n"
        "- 过程可以跳过，直接呈现结果。\n\n"
        "只输出润色后的正文。不要输出任何说明。"
    )

    # 注入核心约束（7 Gate 铁律 + 网文语感铁律），确保风格模仿阶段不弱化反 AI 味约束
    from novel_agent.templates.style_guide_loader import get_core_constraints
    core_constraints = get_core_constraints()

    prompt = (
        f"【人类作家参考章节——学习其写作手法】\n{human_chapter}\n\n"
        f"【需要润色的正文——运用学到的手法改写】\n{polished}\n\n"
        f"【核心写作约束——润色时必须遵守】\n{core_constraints}\n\n"
        "请研读上方人类作家章节的写作手法（叙事节奏、句式、对话、场景转换、情绪、画面感），"
        "将这些手法运用到下方正文的润色中。不改变剧情和设定，只提升写法。"
    )

    try:
        refined = await llm_client.generate(prompt, system=STYLE_REFINE_SYSTEM)
        refined = clean_chapter_text(refined, state["chapter"], state.get("title", ""))
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', refined))
        original_count = len(re.findall(r'[\u4e00-\u9fff]', polished))
        if cn_count < original_count * 0.6:
            logger.warning("style_refine 第%d章：润色后字数降幅过大（%d→%d），保留原文",
                          state["chapter"], original_count, cn_count)
            return {"polished": polished}
        logger.info("style_refine 第%d章：风格模仿完成（%d→%d字）",
                    state["chapter"], original_count, cn_count)
        return {"polished": refined}
    except Exception as e:
        logger.warning("style_refine 第%d章失败: %s", state["chapter"], e)
        return {"polished": polished}


def save_text_polished(state: ChapterGenState, recall: RecallMemory) -> dict:
    """节点：保存润色后正文到文件。"""
    content = state.get("polished") or state.get("draft", "")
    logger.warning("save_text_polished 第%d章：polished_len=%d draft_len=%d content_len=%d",
                   state["chapter"],
                   len(state.get("polished", "") or ""),
                   len(state.get("draft", "") or ""),
                   len(content or ""))
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
    cancel = _check_cancelled(state, "summarize")
    if cancel:
        return cancel

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

    使用 LangGraph interrupt() 暂停执行，等待用户通过 /resume API 传入决策。
    用户可以：approve→继续 style_refine；reject→回到 rewrite。
    """
    from langgraph.types import interrupt

    report = state.get("audit_report", {})
    overall_score = report.get("overall_score", 0) if isinstance(report, dict) else 0
    summary = report.get("summary", "") if isinstance(report, dict) else ""
    issues = report.get("issues", []) if isinstance(report, dict) else []

    # interrupt 暂停执行，等待 Command(resume=decision) 恢复
    decision = interrupt({
        "chapter": state.get("chapter"),
        "title": state.get("title"),
        "overall_score": overall_score,
        "summary": summary,
        "issues": issues[:10] if issues else [],  # 最多传10条，避免payload过大
        "draft_preview": (state.get("draft", "") or "")[:2000],
    })
    return {"review_decision": decision, "status": "reviewed"}


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
