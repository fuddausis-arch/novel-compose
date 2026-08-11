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
from novel_agent.orchestrator.prompts import STYLE_REFINE_SYSTEM_PROMPT, build_writer_system_prompt
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.orchestrator.text_utils import clean_chapter_text, _looks_like_json_not_prose
from novel_agent.orchestrator.utils import (
    books_for_beat, genre_matches_corpus, get_temperature_for_narrative,
)
from novel_agent.orchestrator.constants import BOOK_TAGS, BEAT_TAG_MAP
from novel_agent.protocol.applier import DeltaApplier
from novel_agent.protocol.schemas import Delta, SummaryDelta, ForeshadowDelta
from novel_agent.state_common import ReviewStatus, ChapterGenStatus
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


# 参考文件注入策略（不硬截断，遵循"看全"原则）：
# 参考文件可能达几 MB，全量塞入会撑爆上下文；但也不能"拿着半截就跑"。
# 改为：每文件注入开篇 N 个"完整段落块"（按段落切分，块内语义完整，不做 2000 字硬切），
# 并明确引导——需要完整参考时通过指令读取（用户配置过：参考文件通过指令控制读取，不每次全读）。
_REFERENCE_PER_FILE_BLOCKS = 2       # 每文件注入完整块数
_REFERENCE_BLOCK_CHARS = 1500        # 每块目标字数（按段落切分，不硬切句子）


def _split_full_blocks(text: str, block_chars: int) -> list[str]:
    """按段落把文本切成若干"完整块"（块内段落完整，不做 2000 字式硬截断）。"""
    paras = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    blocks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) > block_chars:
            blocks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        blocks.append(cur)
    return blocks


def _build_reference_injections(project_id: int) -> str:
    """读取项目参考文件内容并注入 prompt（每文件开篇完整段落样例 + 引导读取）。

    参考文件存储于 project_data/projects/{id}/references/（upload_reference API
    写入的纯文本）。无参考文件或读取失败时返回空字符串，不影响原有生成流程。
    """
    try:
        from novel_agent.api.routes_references import get_all_reference_text
        ref_text = get_all_reference_text(project_id)
    except Exception as e:
        logger.debug("_build_reference_injections: 参考文件读取失败: %s", e)
        return ""
    if not ref_text.strip():
        return ""
    # get_all_reference_text 以 “【参考文件：...】” 分块，每块对应一个文件
    parts = []
    for block in ref_text.split("【参考文件："):
        block = block.strip()
        if not block:
            continue
        # 块首是文件名（到换行为止），恢复完整格式
        if "\n" in block:
            fname, _, body = block.partition("\n")
            header = f"【参考文件：{fname.strip()}】"
        else:
            header, body = "【参考文件】", block
        body = body.strip()
        if not body:
            continue
        blocks = _split_full_blocks(body, _REFERENCE_BLOCK_CHARS)
        sample = "\n\n".join(blocks[:_REFERENCE_PER_FILE_BLOCKS])
        parts.append(
            f"{header}\n{sample}\n"
            f"（该参考文件共 {len(body)} 字，此处注入开篇完整段落样例；"
            f"如需完整参考文件内容，请通过指令读取。）"
        )
    if not parts:
        return ""
    logger.info("_build_reference_injections: 注入 %d 个参考文件 (project=%d)", len(parts), project_id)
    return "\n\n".join(parts)


def _build_bible_injections(repo: BibleRepository, chapter_num: int, skill_context: str = "") -> str:
    """从 Bible 注入红线、梗、导入章纲约束，供 writer 节点使用。

    与 routes_generation.py 中 interactive_chat_stream 的注入逻辑保持一致，
    确保正式写作页和交互式创作都遵守相同的 Bible 约束。
    """
    parts: list[str] = []

    # 注入：导入章纲（套壳改写模式）
    try:
        from novel_agent.bible.models import ImportedChapter
        imp_ch = repo.db.query(ImportedChapter).filter(
            ImportedChapter.project_id == repo.project_id,
            ImportedChapter.chapter_order == chapter_num,
        ).first()
        if imp_ch:
            imported_text = (
                f"【导入章纲--套壳改写基底（第{chapter_num}章）】\n"
                f"标题：{imp_ch.title}\n"
            )
            if imp_ch.meta_info:
                imported_text += f"元信息：{imp_ch.meta_info}\n"
            if imp_ch.chapter_outline:
                imported_text += f"章纲：{imp_ch.chapter_outline}\n"
            if imp_ch.detail_outline:
                imported_text += f"细纲：{imp_ch.detail_outline}\n"
            if imp_ch.pleasure_hooks:
                imported_text += f"爽点/钩子：{imp_ch.pleasure_hooks}\n"
            if imp_ch.shell_annotation:
                imported_text += f"套壳标注：{imp_ch.shell_annotation}\n"
            imported_text += (
                "\n【套壳改写要求】\n"
                "- 严格按照上述章纲和细纲的剧情骨架写正文\n"
                "- 套壳标注中【骨】保留的部分绝对不可改变\n"
                "- 套壳标注中【皮】可改的部分可以换皮（人名/地名/系统名等）\n"
                "- 爽点和钩子必须完整交付\n"
            )
            parts.append(imported_text)
    except Exception as e:
        logger.debug("_build_bible_injections: 导入章纲加载失败: %s", e)

    # 注入：红线（绝对约束）
    try:
        from novel_agent.bible.models import RedLine
        red_lines = repo.db.query(RedLine).filter(
            RedLine.project_id == repo.project_id,
            RedLine.enabled == True,
        ).filter(
            (RedLine.scope == "project") |
            ((RedLine.scope == "chapter") & (RedLine.chapter_num == chapter_num))
        ).all()
        if red_lines:
            hard_lines = [r for r in red_lines if r.severity == "hard"]
            soft_lines = [r for r in red_lines if r.severity == "soft"]
            red_text = ""
            if hard_lines:
                red_text += "【红线--绝对不可违反（违反则废稿）】\n"
                for i, r in enumerate(hard_lines, 1):
                    scope_tag = f"[第{r.chapter_num}章]" if r.scope == "chapter" else "[全书]"
                    red_text += f"{i}. {scope_tag} {r.content}\n"
                red_text += "\n"
            if soft_lines:
                red_text += "【软约束--尽量遵守】\n"
                for i, r in enumerate(soft_lines, 1):
                    scope_tag = f"[第{r.chapter_num}章]" if r.scope == "chapter" else "[全书]"
                    red_text += f"{i}. {scope_tag} {r.content}\n"
                red_text += "\n"
            parts.append(red_text)
    except Exception as e:
        logger.debug("_build_bible_injections: 红线加载失败: %s", e)

    # 注入：梗（笑点/桥段/彩蛋）
    try:
        from novel_agent.bible.models import Gag
        gags = repo.db.query(Gag).filter(
            Gag.project_id == repo.project_id,
            Gag.status.in_(["待用", "使用中"]),
        ).all()
        if gags:
            gag_text = "【梗--自然融入剧情，不要生硬植入】\n"
            for g in gags:
                gag_text += f"- [{g.category}] {g.name}：{g.description}\n"
                if g.usage_notes:
                    gag_text += f"  使用备注：{g.usage_notes}\n"
            gag_text += "\n"
            parts.append(gag_text)
            # P1#13：注入后标记"已用"，避免同一梗被反复注入；失败仅记日志
            for g in gags:
                try:
                    repo.update_gag(g.id, status="已用")
                except Exception as ge:
                    logger.warning("标记梗「%s」已用失败: %s", g.name, ge)
    except Exception as e:
        logger.debug("_build_bible_injections: 梗加载失败: %s", e)

    # 注入：Skills（启用的能力约束，与交互式创作路径一致）
    # 带上下文注入：普通 skill 全量，语料型 skill（source=corpus，桥段/场景/人设/题材库）
    # 按章节上下文检索相关条目，只注入命中的部分
    try:
        from novel_agent.api.routes_skills import load_enabled_skills_for_injection_with_context
        skills_text = load_enabled_skills_for_injection_with_context(skill_context)
        if skills_text:
            parts.append(skills_text)
    except Exception as e:
        logger.debug("_build_bible_injections: Skills 加载失败: %s", e)

    return "\n\n".join(parts)


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
            # 把题材写入 state，供后续节点的语感库过滤使用（防止跨题材污染）
            state["genre"] = project.genre
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

    # 提取本章 beat_type，供语料型 skill 按上下文检索（桥段/场景/人设/题材库，
    # 替代原先直读 CSV 的参考资料兜底——内容已并入默认语料 skill）
    beat_type = ""
    chapter_summary = ""
    try:
        outline = repo.get_outline_by_chapter(state["chapter"])
        if outline:
            beats = _safe_json_loads(outline.required_beats)
            if beats and isinstance(beats, list) and beats:
                if isinstance(beats[0], dict):
                    beat_type = beats[0].get("type", "")
                elif isinstance(beats[0], str):
                    beat_type = " ".join(beats)
            # 章节概要拼进检索查询词：让关键词/向量都更精准命中素材
            # （只取前 200 字，避免查询词过长稀释权重）
            if outline.summary:
                chapter_summary = outline.summary.strip()[:200]
    except Exception as e:
        logger.debug("assemble_context: 提取 beat_type 失败: %s", e)

    # 阶段6.5b：自动加载梗库文件（与交互式创作保持一致，不需要手动说"读参考文件"）
    try:
        from novel_agent.config import load_config
        cfg = load_config()
        gag_file = cfg.project_dir(repo.project_id) / "gag_library.md"
        gag_library_text = ""
        if gag_file.exists():
            gag_library_text = gag_file.read_text(encoding="utf-8", errors="replace")
        if gag_library_text:
            # 梗库全量注入（"看全"才能选梗），梗库通常几千字，不截断
            gag_library_text = (
                "【梗库参考--每章必须用至少1个梗】\n"
                "以下是本书的梗库，包含笑点/桥段/彩蛋的详细用法。"
                "创作时从中选择适合当前剧情的梗自然融入，不能生硬植入。\n\n"
                f"{gag_library_text}"
            )
            context = f"{context}\n\n{gag_library_text}"
            logger.warning("[DIAG] assemble_context 第%d章：注入梗库参考，gag_library=%d字", state["chapter"], len(gag_library_text))
    except Exception as e:
        logger.debug("assemble_context: 注入梗库参考失败: %s", e)

    # 注入 Bible 级约束：红线、梗、导入章纲 + 技能注入（含语料型 skill 按本章 beat 检索）
    try:
        skill_ctx = (
            f"第{state['chapter']}章 {state.get('title', '')} {beat_type} {chapter_summary}"
        ).strip()
        injection = _build_bible_injections(repo, state["chapter"], skill_context=skill_ctx)
        if injection:
            context = f"{context}\n\n【Bible 约束】\n{injection}"
            logger.info("assemble_context 第%d章：注入 Bible 约束（红线/梗/导入章纲）", state["chapter"])
    except Exception as e:
        logger.debug("assemble_context: 注入 Bible 约束失败: %s", e)

    return {"context": context, "status": "assembled"}


def _build_chapter_brief(outline, repo, state=None) -> str:
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
            if isinstance(b, dict):
                tier = b.get("tier", "")
                btype = b.get("type", "")
                intensity = b.get("intensity", "")
                detail = b.get("detail", "")
                beat_lines.append(f"  - {tier}级爽点：{btype}（强度{intensity}）")
                if detail:
                    beat_lines.append(f"    执行备注（含毒点警告，必须规避）：{detail}")
            elif isinstance(b, str):
                beat_lines.append(f"  - {b}")
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
    # 防护：LLM 可能把 owed_debts 生成成字符串数组，d.get() 会崩溃使整份约束失效
    if isinstance(debts, list):
        debts = [d for d in debts if isinstance(d, dict)]
    elif debts is not None and not isinstance(debts, list):
        debts = None
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
            # C2：不在组装约束时标记已应用——生成可能失败，反馈必须保留到正文落盘后再标记。
            # 这里只把 id 暂存进 state，由 _mark_feedbacks_applied 在 summarize 成功后消费。
            if state is not None:
                pending_ids = list(state.get("_pending_feedback_ids") or [])
                pending_ids.extend(f.id for f in feedbacks)
                state["_pending_feedback_ids"] = pending_ids
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


def _mark_feedbacks_applied(state: ChapterGenState, repo: BibleRepository | None = None) -> None:
    """正文真正落盘后标记用户反馈已应用（C2）。

    反馈在 _build_chapter_brief 中只暂存 id 到 state["_pending_feedback_ids"]，
    生成失败时反馈保持 pending 可被后续重跑再次消费；只有 summarize 成功
    （正文已保存）后才调用本函数消费，避免生成失败导致反馈永久丢失。
    """
    pending_ids = state.get("_pending_feedback_ids") or []
    if not pending_ids or not repo:
        return
    try:
        from novel_agent.chat.repository import ChatRepository
        chat_repo = ChatRepository(repo.db, repo.project_id)
        chat_repo.mark_feedback_applied(list(pending_ids))
        state["_pending_feedback_ids"] = []
        logger.info("第%d章：用户反馈 %d 条已标记应用", state.get("chapter"), len(pending_ids))
    except Exception as e:
        logger.warning("第%d章：标记用户反馈已应用失败: %s", state.get("chapter"), e)


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
    genre = state.get("genre", "")
    if repo:
        try:
            # 获取项目题材（优先从 state 取，兜底从 repo 取）
            if not genre:
                project = repo.get_project()
                if project and project.genre:
                    genre = project.genre
                    state["genre"] = genre
            outline = repo.get_outline_by_chapter(state["chapter"])
            if outline:
                beats = _safe_json_loads(outline.required_beats)
                if beats and isinstance(beats, list) and beats:
                    if isinstance(beats[0], dict):
                        beat_type = beats[0].get("type", "")
                    elif isinstance(beats[0], str):
                        beat_type = " ".join(beats)
                if beat_type:
                    tags = set()
                    for tag, keywords in BEAT_TAG_MAP.items():
                        if any(kw in beat_type.lower() for kw in keywords):
                            tags.add(tag)
                    preferred_tags = list(tags) if tags else []
        except Exception as e:
            logger.warning("analyze_style 第%d章：提取beat_type失败: %s", state["chapter"], e)

    # 加载人类网文章节（按题材过滤，防止跨题材污染）
    human_chapter = _load_random_human_chapter(max_chars=2500, preferred_tags=preferred_tags or None,
                                               genre=genre)
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
    - 战斗/搏杀/厮杀/猎杀/围剿/激战/对决/生存/防御/对峙/智斗/阻挡/逃亡/击杀 -> combat_guide
    - 人物塑造/关系建立/角色弧光/盟友/队伍/汇合/维持 -> character_guide
    - 世界观铺陈/设定传递/开篇钩子/识破/感知/情报/发现/规律 -> worldview_guide
    - 势力/谈判/权谋/博弈/阵营/资源/物资/分配 -> faction_guide
    """
    from novel_agent.templates.style_guide_loader import get_task_guide
    text = f"{beat_type} {narrative_function}"
    guides: list[tuple[str, str]] = []
    if any(k in text for k in ["战斗", "搏杀", "厮杀", "猎杀", "围剿", "激战", "对决", "交战", "生存", "防御", "对峙", "智斗", "阻挡", "逃亡", "击杀"]):
        g = get_task_guide("combat")
        if g:
            guides.append(("战斗写法指南", g))
    if any(k in text for k in ["人物塑造", "关系建立", "角色弧光", "感情", "盟友", "队伍", "汇合", "维持"]):
        g = get_task_guide("character")
        if g:
            guides.append(("角色写法指南", g))
    if any(k in text for k in ["世界观铺陈", "设定传递", "开篇钩子", "识破", "感知", "情报", "发现", "规律"]):
        g = get_task_guide("worldview")
        if g:
            guides.append(("世界观写法指南", g))
    if any(k in text for k in ["势力", "谈判", "权谋", "博弈", "阵营", "资源", "物资", "分配"]):
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
                chapter_brief = _build_chapter_brief(outline, repo, state)
                beats = _safe_json_loads(outline.required_beats)
                if beats and isinstance(beats, list) and beats:
                    if isinstance(beats[0], dict):
                        beat_type = beats[0].get("type", "")
                    elif isinstance(beats[0], str):
                        beat_type = " ".join(beats)
                # 提取 narrative_function 用于动态 temperature
                cc = _safe_json_loads(outline.character_constraints)
                if cc and isinstance(cc, dict):
                    narrative_function = cc.get("narrative_function", "")
        except Exception as e:
            logger.debug("write_chapter 读取大纲失败: %s", e)
    # 根据章节叙事功能动态调整 temperature
    dynamic_temp = get_temperature_for_narrative(narrative_function, llm_client.config.temperature)
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
        # 题材门控：只有末日/克苏鲁/异能/恐怖题材才使用末日文库，防止跨题材污染
        genre = state.get("genre", "")
        if getattr(config, "enable_genre_rag", False) and beat_type and genre_matches_corpus(genre):
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
                target_books = books_for_beat(beat_type)
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
                    slices.append(doc)
                genre_rag_slices = "\n\n---\n\n".join(slices)
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
    # 注入：项目参考文件（用户上传，每个文件截断到 2000 字；无参考文件时不注入）
    try:
        _pid = state.get("project_id")
        if _pid:
            ref_injections = _build_reference_injections(_pid)
            if ref_injections:
                prompt += (
                    f"<references>\n以下为本项目上传的参考文件，写作时参考其中的设定/文风/范例，"
                    f"但不得照搬抄袭原文：\n{ref_injections}\n</references>\n\n"
                )
    except Exception as e:
        logger.debug("write_chapter 第%d章 参考文件注入失败: %s", state["chapter"], e)
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
    # 多写手并行模式（Phase 3.4）：state["writer_type"] == "multi"/"muti" 时
    # 走 骨架写手 -> 5 专项并行 -> 整合写手；失败自动回退单写手，流水线不中断
    # （"muti" 兼容 bishu-novel mvp 工作流定义中的拼写）
    if state.get("writer_type") in ("multi", "muti"):
        from novel_agent.orchestrator.multi_writer import write_chapter_multi
        try:
            multi_result = await write_chapter_multi(
                state, llm_client, repo=repo, config=config,
                chapter_brief=chapter_brief,
                word_min=target_min, word_max=word_max,
            )
            if multi_result is not None:
                multi_result["_beat_type"] = beat_type
                logger.info("write_chapter 第%d章：多写手模式完成（%d字）",
                            state["chapter"], multi_result.get("word_count", 0))
                return multi_result
            logger.warning("write_chapter 第%d章：多写手模式未产出，回退单写手", state["chapter"])
        except Exception as e:
            logger.warning("write_chapter 第%d章：多写手模式异常，回退单写手: %s",
                           state["chapter"], e)
    try:
        draft = await llm_client.generate(prompt, system=build_writer_system_prompt(), temperature=dynamic_temp)
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
                "_beat_type": beat_type,
                "_pending_feedback_ids": list(state.get("_pending_feedback_ids") or [])}
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
        scanner = DedupScanner(load_config(), project_id=repo.project_id)
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
        "status": ReviewStatus.AUDITED.value if report.passed else ReviewStatus.NEEDS_REWRITE.value,
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
        return ChapterGenStatus.END_FAILED.value
    report = AuditReport(**state.get("audit_report", {}))
    logger.warning("route_after_audit 第%s章：status=%s passed=%s confidence=%s iterations=%s",
                   state.get("chapter"), state.get("status"), report.passed,
                   state.get("confidence_level"), state.get("review_iterations", 0))
    if report.passed:
        confidence = state.get("confidence_level", "medium")
        if confidence == "high":
            # 高置信度（无 critical/important 问题）跳过人审，直接走润色
            logger.warning("route_after_audit 第%s章：高置信度，跳过人审走润色", state.get("chapter"))
            return "skip_review"
        # 中/低置信度走人审
        logger.warning("route_after_audit 第%s章：confidence=%s，走人审", state.get("chapter"), confidence)
        return "style_refine"  # 走 human_review

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


async def rewrite_chapter(state: ChapterGenState, llm_client: LLMClient,
                          repo: BibleRepository | None = None) -> dict:
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
        # repo 由 graph 注入（rewrite_fn partial 传入）；state.get("_repo") 为旧兼容路径
        repo = repo or state.get("_repo")
        if repo and hasattr(repo, "get_outline_by_chapter"):
            outline = repo.get_outline_by_chapter(state["chapter"])
            if outline:
                chapter_brief = _build_chapter_brief(outline, repo, state)
                beats = _safe_json_loads(outline.required_beats)
                if beats and isinstance(beats, list) and beats:
                    if isinstance(beats[0], dict):
                        beat_type_rw = beats[0].get("type", "")
                    elif isinstance(beats[0], str):
                        beat_type_rw = " ".join(beats)
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

    # 用户人审意见（reject 时由 human_review 节点写入 state.user_feedback）
    user_feedback = (state.get("user_feedback", "") or "").strip()
    user_feedback_block = ""
    if user_feedback:
        user_feedback_block = (
            "\n【用户人审意见（最高优先级，必须尊重并落地）】\n"
            f"{user_feedback}\n\n"
            "说明：以上是用户在审阅上一版草稿后给出的具体意见，重写时必须针对这些意见做针对性修改。"
            "如果意见与审计建议冲突，以用户意见为准。\n\n"
        )

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
        f"{user_feedback_block}"
        f"{core_constraints}\n\n"
        f"要求：针对问题重写，严格遵循上述核心写作约束（特别是网文语感铁律和反AI味要求）。"
        f"【硬约束铁律】硬约束必须完成，尤其是爽点交付——如果大纲要求'打脸'，"
        f"必须写出完整的打脸过程，不能一笔带过。"
        f"最重要：网文语感——短句、口语、显性连接词、高信息量对话、标签化细节，追求'脆'和'响'，不要文学化的长句铺陈。"
        f"\n<word_limit_reminder>再次强调：正文不超过{word_max}字。这是硬性上限，超过会被判定为废稿。</word_limit_reminder>"
        f"只输出正文，不要输出 JSON 或任何格式说明。"
    )
    try:
        draft = await llm_client.generate(prompt, system=build_writer_system_prompt(), temperature=llm_client.config.temperature)
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
                "word_count": len(re.findall(r'[\u4e00-\u9fff]', draft)), "status": "drafted",
                "_pending_feedback_ids": list(state.get("_pending_feedback_ids") or [])}
    except Exception as e:
        logger.warning("rewrite_chapter 第%d章失败：%s", state["chapter"], e)
        return {"status": "failed", "error": str(e)}


async def polish_chapter(state: ChapterGenState, llm_client: LLMClient,
                         repo: BibleRepository | None = None,
                         skip_deslop: bool = False,
                         max_passes: int | None = None,
                         progress_cb=None) -> dict:
    """节点：润色优化（文风统一 + AI 痕迹清除）。

    Args:
        skip_deslop: 为 True 时跳过 oh-story 7 Gate 后处理（用于交互式创作等快速路径）。
        max_passes: 限制 oh-story 后处理的最大 Pass 数（None=不限制）。
        progress_cb: 可选的异步回调函数，用于报告进度。签名: async def cb(stage: str, detail: str)
    """
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
        if progress_cb:
            await progress_cb("AI 润色中", "正在润色正文（清除AI味+标点修复+段落节奏），这是主要步骤，需要1-3分钟...")
        polished = await llm_client.generate(prompt, system=POLISH_SYSTEM)
        polished = clean_chapter_text(polished, state["chapter"], state.get("title", ""))

        # POLISH后轻量重审：字数+限频词+伏笔关键词命中
        polish_issues = []

        # 后处理：规则修复感叹号轰炸+重复递进，检测无标点长句+排比过载
        if progress_cb:
            await progress_cb("规则后处理", "正在执行规则修复（感叹号降级+排比打断+重复截断+标点修复）...")
        from novel_agent.audit.text_post_processor import post_process_text
        polished, pp_issues = post_process_text(polished)
        for issue in pp_issues:
            polish_issues.append(f"{issue.get('type','')}: {issue.get('suggestion','')}")
            logger.info("polish_chapter 第%d章后处理: %s", state["chapter"], issue.get('suggestion', ''))

        # 如果后处理检测到无标点长句或排比过载，做一次LLM修复
        needs_llm_fix = any(i.get('type') in ('long_unpunctuated', 'parallelism_overload') for i in pp_issues)
        if needs_llm_fix:
            if progress_cb:
                await progress_cb("格式修复", "检测到无标点长句/排比过载，正在用LLM修复格式...")
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
        # 交互式创作等快速路径可通过 skip_deslop=True 完全跳过
        if not skip_deslop:
            if progress_cb:
                await progress_cb("深度去AI味", "正在运行 oh-story 7 Gate 多轮深度净化（这是最慢的步骤，需要2-5分钟）...")
            try:
                from novel_agent.audit.deslop_postprocessor import run_deslop_postprocess, get_deslop_summary
                deslop_result = await run_deslop_postprocess(polished, llm_client, max_passes=max_passes)
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


CHAPTER_SPLIT_RE = re.compile(r"^第\s*[0-9一二三四五六七八九十百千零]+\s*章", re.MULTILINE)


def _split_text_into_chapters(text: str) -> list[str]:
    """按「第X章」标题拆分完整小说为章节列表。"""
    matches = list(CHAPTER_SPLIT_RE.finditer(text))
    chapters = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapter = text[start:end].strip()
        if len(chapter) >= 200:
            chapters.append(chapter)
    return chapters


def _load_random_human_chapter(max_chars: int = 4000, preferred_tags: list[str] | None = None,
                              genre: str = "") -> str | None:
    """从人类作家小说目录随机抽取一整章作为风格参考。

    支持两种目录格式：
    - 分章文件: 0001.txt, 0002.txt, ...（直接读取其中一篇即为一章）
    - 完整小说: 书名.txt（按「第X章」拆分后随机抽取完整一章）

    preferred_tags: 偏好的节奏标签（如 combat/politics/horror），用于过滤不匹配的章节。
    genre: 项目题材，用于过滤不匹配的书（防止跨题材污染）。
           非末日/克苏鲁/异能/恐怖题材将跳过语感注入，返回 None。
    """
    # 题材过滤：只有题材匹配的书才参与抽取
    genre_tags = genre_matches_corpus(genre)
    if genre and not genre_tags:
        logger.info("题材'%s'与语感库不匹配，跳过风格参考注入", genre)
        return None

    chapter_dir = _find_human_chapter_dir()
    if not chapter_dir:
        logger.info("人类小说语料目录未找到，style_refine 将跳过风格模仿")
        return None

    # 按节奏标签映射章节区间（基于分章文件序号）
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

    # 分章文件（纯数字命名）：每篇即为一章
    chapter_files = sorted(
        f for f in chapter_dir.glob("*.txt")
        if re.match(r"^\d+\.txt$", f.name)
    )
    if chapter_files:
        candidates = chapter_files
        if preferred_tags:
            candidate_ranges = []
            for tag in preferred_tags:
                candidate_ranges.extend(TAG_RANGES.get(tag, []))
            if candidate_ranges:
                filtered = []
                for f in chapter_files:
                    ch_num = int(re.match(r"(\d+)", f.name).group(1))
                    if any(lo <= ch_num <= hi for lo, hi in candidate_ranges):
                        filtered.append(f)
                if filtered:
                    candidates = filtered
        picked = random.choice(candidates)
        try:
            text = picked.read_text(encoding="utf-8", errors="ignore").strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "\n\n……（本章较长，已截取前部）"
            logger.info("风格参考：随机抽取人类小说 %s（%d字，候选%d篇，tags=%s）",
                        picked.name, len(text), len(candidates), preferred_tags or "无")
            return text
        except Exception as e:
            logger.warning("读取人类小说章节失败 %s: %s", picked.name, e)
            return None

    # 完整小说文件：按「第X章」拆分后随机抽取完整一章
    all_novels = list(chapter_dir.glob("*.txt"))
    if not all_novels:
        logger.warning("人类小说语料目录为空: %s", chapter_dir)
        return None

    if genre_tags:
        all_novels = [
            f for f in all_novels
            if any(t in BOOK_TAGS.get(f.stem, []) for t in genre_tags)
        ]
        if not all_novels:
            logger.info("题材'%s'过滤后无匹配书籍，跳过风格参考", genre)
            return None

    picked = random.choice(all_novels)
    try:
        text = picked.read_text(encoding="utf-8", errors="ignore").strip()
        chapters = _split_text_into_chapters(text)
        if not chapters:
            logger.warning("%s 中未找到「第X章」格式章节，降级为空", picked.name)
            return None

        # 若指定了 preferred_tags，尝试按章节序号过滤
        if preferred_tags and len(chapters) >= max([hi for ranges in TAG_RANGES.values() for lo, hi in ranges], default=0):
            candidate_ranges = []
            for tag in preferred_tags:
                candidate_ranges.extend(TAG_RANGES.get(tag, []))
            if candidate_ranges:
                filtered = [
                    (idx, ch) for idx, ch in enumerate(chapters, start=1)
                    if any(lo <= idx <= hi for lo, hi in candidate_ranges)
                ]
                if filtered:
                    chapters = [ch for _, ch in filtered]

        chapter = random.choice(chapters)
        if len(chapter) > max_chars:
            chapter = chapter[:max_chars] + "\n\n……（本章较长，已截取前部）"
        logger.info("风格参考：从 %s 抽取完整一章（%d字，genre=%s）", picked.name, len(chapter), genre or "未指定")
        return chapter
    except Exception as e:
        logger.warning("读取人类小说失败 %s: %s", picked.name, e)
        return None


def _truncate_to_word_max(text: str, hard_max: int) -> str:
    """确定性末尾截断：超字数时保留完整段落/句子边界，优先在句号后截断（C3）。

    route_after_audit 是路由函数无法改 state，截断必须在此（能写回 polished）兜底。
    """
    if len(re.findall(r'[\u4e00-\u9fff]', text)) <= hard_max:
        return text
    kept = 0
    cut_idx = len(text)
    for m in re.finditer(r'[\u4e00-\u9fff]', text):
        kept += 1
        if kept >= hard_max:
            # 往后找下一个段落边界（\n）或句末标点，在其后截断，保留完整段落/句子
            rest = text[m.end():]
            pm = re.search(r'\n\s*\n|\n|[。！？…]', rest)
            cut_idx = m.end() + (pm.end() if pm else 0)
            break
    return text[:cut_idx].rstrip()


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
    genre = state.get("genre", "")
    if beat_type:
        tags = set()
        for tag, keywords in BEAT_TAG_MAP.items():
            if any(kw in beat_type.lower() for kw in keywords):
                tags.add(tag)
        preferred_tags = list(tags) if tags else []

    human_chapter = _load_random_human_chapter(max_chars=3000, preferred_tags=preferred_tags or None,
                                               genre=genre)
    if not human_chapter:
        logger.info("style_refine 第%d章：未获取到人类小说参考，跳过", state["chapter"])
        return {"polished": polished}

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
        refined = await llm_client.generate(prompt, system=STYLE_REFINE_SYSTEM_PROMPT)
        refined = clean_chapter_text(refined, state["chapter"], state.get("title", ""))
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', refined))
        original_count = len(re.findall(r'[\u4e00-\u9fff]', polished))
        if cn_count < original_count * 0.6:
            logger.warning("style_refine 第%d章：润色后字数降幅过大（%d→%d），保留原文",
                          state["chapter"], original_count, cn_count)
            return {"polished": polished}
        logger.info("style_refine 第%d章：风格模仿完成（%d→%d字）",
                    state["chapter"], original_count, cn_count)
        # C3：超字数硬截断（word_max 单一真源：节奏阈值.csv 的"字数上限"；
        # route_after_audit 无法改 state，截断在此真正生效）
        from novel_agent.audit.validator import _get_threshold
        word_max = int(_get_threshold("字数上限", 3500))
        if cn_count > word_max:
            refined = _truncate_to_word_max(refined, word_max)
            logger.warning("style_refine 第%d章：超字数 %d>%d，末尾截断到 %d 字",
                           state["chapter"], cn_count, word_max,
                           len(re.findall(r'[\u4e00-\u9fff]', refined)))
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
    # 防护：LLM 可能把 required_beats 生成成字符串数组（如 ["small"]）而非对象数组，
    # 此时 b.get() 会崩溃导致整个 summarize 失败（正文已保存却报错）。只保留 dict 元素。
    if isinstance(planned_beats, list):
        planned_beats = [b for b in planned_beats if isinstance(b, dict)]
    else:
        planned_beats = []
    beat_check_list = ""
    if planned_beats:
        beat_check_list = "\n【本章计划爽点（逐个判断是否交付）】\n"
        for i, b in enumerate(planned_beats):
            beat_check_list += f"{i+1}. tier={b.get('tier','')}, type={b.get('type','')}, intensity={b.get('intensity',0)}\n"
        beat_check_list += "\n对每个计划爽点，在beats_delivered中对应输出，type必须与计划一致，delivered=true/false，delivered_intensity=实际交付强度(1-10)。\n"

    # A2: 喂全文--章末伏笔回收/钩子/角色终位不能被截断
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

    # ---- 数据清洗：LLM 返回结构不合法时降级，不让异常冒泡（C1） ----
    character_states = data.get("character_states", []) or []
    if not isinstance(character_states, list):
        logger.warning("summarize_chapter 第%d章：character_states 非列表(%s)，降级为空",
                       chapter, type(character_states).__name__)
        character_states = []
    character_states = [cs for cs in character_states if isinstance(cs, dict)]

    beats_delivered = data.get("beats_delivered", []) or []
    if not isinstance(beats_delivered, list):
        logger.warning("summarize_chapter 第%d章：beats_delivered 非列表(%s)，降级为空",
                       chapter, type(beats_delivered).__name__)
        beats_delivered = []
    beats_delivered = [b for b in beats_delivered if isinstance(b, dict)]

    resolved_foreshadows = data.get("resolved_foreshadows", []) or []
    if not isinstance(resolved_foreshadows, list):
        logger.warning("summarize_chapter 第%d章：resolved_foreshadows 非列表(%s)，降级为空",
                       chapter, type(resolved_foreshadows).__name__)
        resolved_foreshadows = []

    debts_resolved = data.get("debts_resolved", []) or []
    if not isinstance(debts_resolved, list):
        logger.warning("summarize_chapter 第%d章：debts_resolved 非列表(%s)，降级为空",
                       chapter, type(debts_resolved).__name__)
        debts_resolved = []

    core_events = data.get("core_events", "") or ""
    if not isinstance(core_events, str):
        logger.warning("summarize_chapter 第%d章：core_events 非字符串(%s)，转为字符串",
                       chapter, type(core_events).__name__)
        core_events = str(core_events)
    if not core_events.strip():
        core_events = content[:200]

    delta = Delta(
        target="chapter_summary", action="create", chapter=chapter,
        data=SummaryDelta(
            title=state.get("title", ""),
            word_count=state.get("word_count", len(content)),
            core_events=core_events,
            characters_present=", ".join(cs.get("name", "") for cs in character_states),
            chapter_hook=f"hook_strength={data.get('hook_strength', 0)}",
        ),
    )
    try:
        result = applier.apply(delta)
        if not result.success:
            # 摘要应用失败不致命（正文已保存），记 warning 不报整章失败
            logger.warning("summarize_chapter 第%d章：摘要应用失败：%s", chapter, result.message)
    except Exception as e:
        logger.warning("summarize_chapter 第%d章：摘要应用异常：%s", chapter, e)

    # 伏笔回收
    resolved_ids = resolved_foreshadows
    for fid in resolved_ids:
        try:
            applier.apply(Delta(
                target="foreshadow", action="resolve", chapter=chapter,
                data=ForeshadowDelta(foreshadow_id=fid),
            ))
        except Exception as e:
            logger.warning("summarize_chapter 第%d章：伏笔回收「%s」失败：%s", chapter, fid, e)

    # 角色状态更新（位置/情绪），写 StateChange + TruthEvent
    for cs in character_states:
        name = cs.get("name", "").strip()
        if name and repo:
            char = repo.get_character(name)
            if char:
                updates = {}
                if cs.get("location"):
                    updates["current_location"] = cs["location"]
                if cs.get("emotion"):
                    updates["current_emotion"] = cs["emotion"]
                # P1#12：LLM 若输出 known_info/info 字段，累加到角色已知信息
                # （分号拼接，避免覆盖已有；prompt 未要求该字段时 LLM 通常不输出，跳过即可）
                new_info = cs.get("known_info") or cs.get("info")
                if new_info:
                    new_info = str(new_info).strip()
                    if new_info:
                        old_info = (char.known_info or "").strip()
                        updates["known_info"] = (
                            f"{old_info}；{new_info}" if old_info else new_info
                        )
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
            # P0#5：情感弧线落库（时间线"情感弧线泳道"数据源）
            if cs.get("emotion"):
                try:
                    repo.create_emotion_arc(
                        character_name=name, chapter=chapter,
                        event=core_events[:120],
                        emotion_before=str(char.current_emotion or ""),
                        emotion_after=str(cs.get("emotion", "")),
                    )
                except Exception as e:
                    logger.warning("summarize_chapter 第%d章：写入情感弧线失败：%s", chapter, e)

    # 爽点交付回写 PleasureBeat 表
    for b in beats_delivered:
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
            # SQLAlchemy flush 失败后事务被污染，必须 rollback 否则后续操作全报错
            try:
                repo.db.rollback()
            except Exception:
                pass

    # 伏笔回收记录 TruthEvent
    for fid in resolved_ids:
        try:
            repo.append_event(
                chapter=chapter, type="foreshadow_resolved",
                entity_id=fid, payload={"chapter": chapter},
            )
        except Exception:
            pass

    # P0#4：自动关闭已兑现欠账（debts_resolved 为欠账描述，按文本模糊匹配 open 欠账）
    for debt_text in debts_resolved:
        if not debt_text:
            continue
        try:
            for debt in repo.list_open_debts():
                desc = debt.description or ""
                if debt_text in desc or desc in debt_text:
                    repo.resolve_debt(debt.id, chapter)
                    break
        except Exception as e:
            logger.warning("summarize_chapter 第%d章：关闭欠账「%s」失败：%s", chapter, debt_text, e)

    # 回写覆盖率探针（防 silent 失败）
    coverage = {
        "summary": 1 if repo and repo.get_chapter_summary(chapter) else 0,
        "state_changes": len(repo.list_events(chapter=chapter)) if repo else 0,
        "beats_delivered": sum(1 for b in beats_delivered if b.get("delivered")),
        "debts_resolved": len(debts_resolved),
        "character_states": len(character_states),
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

    # P0-② 记忆提炼回流：本章新增设定 → 写回角色/世界观/故事线 + 溯源日志。
    # 只追加不覆盖、失败不阻塞主流程；开关在配置 memory_refine_enabled。
    if repo and llm_client:
        try:
            from novel_agent.config import load_config
            if load_config().memory_refine_enabled:
                from novel_agent.memory.refine import refine_memories
                await refine_memories(repo, llm_client, chapter, content, core_events)
        except Exception as e:
            logger.warning("ch%d 记忆提炼回流失败（不阻塞）: %s", chapter, e)

    # 正文已落盘成功，消费用户反馈（C2：失败不消费，反馈可重跑复用）
    _mark_feedbacks_applied(state, repo)

    return {"status": "completed"}


def human_review(state: ChapterGenState) -> dict:
    """人审节点：审计通过后、润色前的人工 checkpoint。

    使用 LangGraph interrupt() 暂停执行，等待用户通过 /resume API 传入决策。
    用户可以：approve→继续 style_refine；reject→回到 rewrite。
    支持用户附带文字意见（feedback），reject 时意见会注入 rewrite_chapter prompt。
    """
    from langgraph.types import interrupt

    report = state.get("audit_report", {})
    overall_score = report.get("overall_score", 0) if isinstance(report, dict) else 0
    summary = report.get("summary", "") if isinstance(report, dict) else ""
    issues = report.get("issues", []) if isinstance(report, dict) else []

    # interrupt 暂停执行，等待 Command(resume=resume_value) 恢复
    # resume_value 兼容两种格式：
    #   - 字符串（旧版/无意见时）："approve" / "reject"
    #   - 字典（带意见时）：{"decision": "approve"/"reject", "feedback": "用户意见"}
    resume_value = interrupt({
        "chapter": state.get("chapter"),
        "title": state.get("title"),
        "overall_score": overall_score,
        "summary": summary,
        "issues": issues[:10] if issues else [],  # 最多传10条，避免payload过大
        "draft_preview": (state.get("draft", "") or ""),
        "polished": bool(state.get("polished")),
    })

    # 解析 resume_value：兼容字符串和字典
    if isinstance(resume_value, dict):
        decision = resume_value.get("decision", "approve") or "approve"
        feedback = (resume_value.get("feedback", "") or "").strip()
    else:
        decision = resume_value or "approve"
        feedback = ""

    update: dict = {"review_decision": decision, "status": ReviewStatus.REVIEWED.value}
    if feedback:
        update["user_feedback"] = feedback
    return update


# ---- M2 保留的兼容节点（旧 graph 测试仍用） ----

def save_text(state: ChapterGenState, recall: RecallMemory) -> dict:
    """M2 兼容：把正文存到文件（不区分 polished）。"""
    recall.save_chapter_text(
        chapter=state["chapter"], title=state.get("title", ""),
        content=state["draft"],
    )
    return {"status": ChapterGenStatus.SAVED.value}


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
        return {"status": ChapterGenStatus.FAILED.value, "error": result.message}
    return {"status": ChapterGenStatus.COMPLETED.value}
