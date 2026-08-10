"""Phase 1 新增节点：世界状态推演、上下文语义裁剪、后验裁决。

借鉴 bishu-novel 的 novel-observer / novel-world-context-trimmer / novel-chapter-observer + novel-arbiter，
为流水线增加"写前推演世界暗流"、"写前裁剪无关上下文"、"写后检测设定漂移"三个环节。

温度策略（借鉴 bishu-novel 温度五级光谱）：
- world_engine / context_trimmer / post_hoc 均使用 0.3 低温度，确保推演/裁剪/裁决的确定性。
"""
from __future__ import annotations

import json
import logging

from novel_agent.bible.models import WorldState, WorldEvent, PostHocResult
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.orchestrator.state import ChapterGenState
from novel_agent.orchestrator.nodes import _check_cancelled
from novel_agent.utils.json_parser import parse_json_strict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 节点 1：world_engine —— 世界状态推演（写之前推演世界暗流）
# ---------------------------------------------------------------------------

async def world_engine(state: ChapterGenState, *,
                       llm_client: LLMClient,
                       repo: BibleRepository) -> dict:
    """世界状态推演节点：写之前推演世界暗流。

    借鉴 bishu-novel novel-observer，温度 0.3。
    维护：势力动态、暗线运行、世界事件、世界时间推进。
    不读章节正文，只读大纲和上一章世界状态。

    失败策略：skip（不阻塞流水线），返回空 world_state/world_events。
    """
    cancel = _check_cancelled(state, "world_engine")
    if cancel:
        return cancel

    chapter = state.get("chapter", 0)
    try:
        # ---- 读取世界设定 ----
        world_settings = repo.list_world_settings()
        settings_text = _format_world_settings(world_settings)

        # ---- 读取本章大纲 ----
        outline = repo.get_outline_by_chapter(chapter)
        outline_text = ""
        if outline:
            outline_text = f"本章概要：{outline.summary or ''}\n"
            if outline.required_beats:
                outline_text += f"本章爽点：{outline.required_beats}\n"
            if outline.character_constraints:
                outline_text += f"角色约束：{outline.character_constraints}\n"

        # ---- 读取上一章世界状态（优先从 WorldState 表，回退 StateSnapshot） ----
        prev_world_state = ""
        try:
            prev_ws = repo.db.query(WorldState).filter(
                WorldState.project_id == repo.project_id,
                WorldState.chapter == chapter - 1,
            ).first()
            if prev_ws:
                prev_world_state = json.dumps({
                    "world_time": prev_ws.world_time or "",
                    "time_advanced_days": prev_ws.time_advanced_days or 0,
                    "forces": prev_ws.forces or [],
                    "undercurrents": prev_ws.undercurrents or [],
                }, ensure_ascii=False, indent=2)
        except Exception:
            pass
        # 回退：从 StateSnapshot 读取（兼容旧数据）
        if not prev_world_state:
            prev_snapshot = repo.get_latest_state_snapshot(chapter)
            if prev_snapshot and prev_snapshot.snapshot_data:
                # 快照中可能包含 world_state 字段
                snap = prev_snapshot.snapshot_data
                if isinstance(snap, dict) and snap.get("world_state"):
                    prev_world_state = json.dumps(snap["world_state"], ensure_ascii=False, indent=2)

        # ---- 读取卷纲/近纲（提供更宏观的剧情方向） ----
        volume_outline = ""
        try:
            outlines = repo.list_outlines(level="volume")
            if outlines:
                # 找到包含当前章节的卷
                for vol in outlines:
                    vol_outlines = repo.list_outlines(level="chapter", parent_id=vol.id)
                    if vol_outlines:
                        ch_orders = [o.order for o in vol_outlines]
                        if ch_orders and chapter >= min(ch_orders) and chapter <= max(ch_orders):
                            volume_outline = f"卷纲：{vol.title or ''} - {vol.summary or ''}"
                            break
        except Exception:
            pass

        # ---- 读取上一章后验裁决结果（注入设定冲突提醒） ----
        prev_post_hoc_conflicts = ""
        try:
            prev_post_hoc = repo.db.query(PostHocResult).filter(
                PostHocResult.project_id == repo.project_id,
                PostHocResult.chapter == chapter - 1,
            ).first()
            if prev_post_hoc and prev_post_hoc.world_adjudication:
                # 提取 verdict=conflict 的项
                conflicts = [
                    item for item in prev_post_hoc.world_adjudication
                    if isinstance(item, dict) and item.get("verdict") == "conflict"
                ]
                if conflicts:
                    prev_post_hoc_conflicts = json.dumps(conflicts, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # ---- 构建 LLM prompt ----
        system_prompt = (
            "你是世界状态机，是这个小说世界的物理引擎。\n"
            "你的职责是在每章正文写出之前，推演世界暗流的运行。\n\n"
            "【铁律】\n"
            "1. 你不读章节正文（正文还没写），只读大纲和世界设定。\n"
            "2. 你维护四类信息：势力动态、暗线运行、世界事件、新增世界信息。\n"
            "3. 每条信息标记距主角的距离：近/中/远/迷雾。\n"
            "4. 你推演的是'主角视线之外正在发生的事'，为后续章节埋伏笔。\n"
            "5. 输出纯 JSON，不要输出任何说明文字。"
        )

        # 构建后验冲突提醒段落（如有）
        conflict_section = f"【上一章后验发现的设定冲突】\n{prev_post_hoc_conflicts}\n\n" if prev_post_hoc_conflicts else ""

        user_prompt = (
            f"【世界设定】\n{settings_text or '（暂无世界设定）'}\n\n"
            f"【上一章世界状态】\n{prev_world_state or '（第一章，无上一章状态）'}\n\n"
            f"【本章大纲】\n{outline_text or '（暂无大纲）'}\n\n"
            f"【卷纲方向】\n{volume_outline or '（暂无卷纲）'}\n\n"
            f"{conflict_section}"
            "请推演本章写出来之前，世界各势力、暗线、事件的状态变化。\n\n"
            "输出 JSON 格式：\n"
            "{\n"
            '  "world_time": "当前世界时间描述",\n'
            '  "time_advanced_days": 0,\n'
            '  "forces": [{"name":"势力名","status":"当前状态","distance":"近/中/远/迷雾","change":"本章变化"}],\n'
            '  "undercurrents": [{"name":"暗线名","status":"运行中/浮出/爆发","distance":"近/中/远/迷雾","progress":"进展描述"}],\n'
            '  "on_camera_events": [{"event":"台上事件","distance":"近","chapter_relevance":"与本章关系"}],\n'
            '  "off_camera_events": [{"event":"台下事件","distance":"中/远/迷雾","impact":"潜在影响"}],\n'
            '  "undercurrent_progress": [{"name":"暗线名","progress_percent":0,"next_milestone":"下一个里程碑"}],\n'
            '  "power_shift": [{"from":"势力A","to":"势力B","type":"资源/地位/情报","amount":"变化量"}]\n'
            "}\n"
            "只输出 JSON。"
        )

        raw = await llm_client.generate(
            user_prompt, system=system_prompt,
            temperature=0.3, thinking=True,
        )
        world_data = parse_json_strict(raw)

        if not world_data:
            logger.warning("world_engine 第%d章：LLM 返回无法解析的 JSON，跳过世界推演", chapter)
            return {"world_state": "", "world_events": ""}

        world_state_json = json.dumps(world_data, ensure_ascii=False)
        # world_events 取 off_camera_events + undercurrents 作为事件摘要
        events = []
        for e in world_data.get("off_camera_events", []):
            if isinstance(e, dict):
                events.append({"type": "off_camera", **e})
        for u in world_data.get("undercurrents", []):
            if isinstance(u, dict):
                events.append({"type": "undercurrent", **u})
        world_events_json = json.dumps(events, ensure_ascii=False)

        logger.info("world_engine 第%d章：世界推演完成，势力%d条，暗线%d条，台下事件%d条",
                    chapter,
                    len(world_data.get("forces", [])),
                    len(world_data.get("undercurrents", [])),
                    len(world_data.get("off_camera_events", [])))

        # ---- 写入 WorldState + WorldEvent 表 ----
        try:
            # 先删除同章旧记录（支持重跑）
            for old_ws in repo.db.query(WorldState).filter(
                WorldState.project_id == repo.project_id,
                WorldState.chapter == chapter,
            ).all():
                repo.db.delete(old_ws)
            for old_we in repo.db.query(WorldEvent).filter(
                WorldEvent.project_id == repo.project_id,
                WorldEvent.chapter == chapter,
            ).all():
                repo.db.delete(old_we)

            repo.db.add(WorldState(
                project_id=repo.project_id,
                chapter=chapter,
                world_time=world_data.get("world_time", "") or "",
                time_advanced_days=world_data.get("time_advanced_days", 0) or 0,
                forces=world_data.get("forces", []) or [],
                undercurrents=world_data.get("undercurrents", []) or [],
            ))
            repo.db.add(WorldEvent(
                project_id=repo.project_id,
                chapter=chapter,
                on_camera_events=world_data.get("on_camera_events", []) or [],
                off_camera_events=world_data.get("off_camera_events", []) or [],
                undercurrent_progress=world_data.get("undercurrent_progress", []) or [],
                power_shift=world_data.get("power_shift", []) or [],
            ))
            repo.db.commit()
        except Exception as db_exc:
            # 写入失败不阻塞流水线
            logger.warning("world_engine 第%d章：写入 WorldState/WorldEvent 失败（不阻塞流水线）: %s", chapter, db_exc)
            repo.db.rollback()

        return {"world_state": world_state_json, "world_events": world_events_json}

    except Exception as e:
        # 失败不阻塞流水线（skip 策略）
        logger.warning("world_engine 第%d章失败（不阻塞流水线）: %s", chapter, e)
        return {"world_state": "", "world_events": ""}


# ---------------------------------------------------------------------------
# 节点 2：context_trimmer —— 上下文语义裁剪
# ---------------------------------------------------------------------------

async def context_trimmer(state: ChapterGenState, *,
                          llm_client: LLMClient,
                          repo: BibleRepository) -> dict:
    """上下文语义裁剪节点：按场景判断哪些世界设定本章不需要。

    借鉴 bishu-novel novel-world-context-trimmer，温度 0.3，thinking=false。
    输出减法列表，Python 确定性执行裁剪。

    失败策略：用原始上下文（不阻塞流水线）。
    """
    cancel = _check_cancelled(state, "context_trimmer")
    if cancel:
        return cancel

    chapter = state.get("chapter", 0)
    context = state.get("context", "")
    if not context:
        logger.info("context_trimmer 第%d章：上下文为空，跳过裁剪", chapter)
        return {"trimmed_context": ""}

    try:
        # ---- 读取世界设定和角色列表 ----
        world_settings = repo.list_world_settings()
        characters = repo.list_characters()

        # 构建世界设定摘要（维度名 -> 二级字段名列表）
        settings_summary = {}
        for ws in world_settings:
            category = ws.category or "其他"
            if category not in settings_summary:
                settings_summary[category] = []
            settings_summary[category].append(ws.title or "未命名")

        # 角色名列表
        char_names = [c.name for c in characters if c.name]

        # ---- 构建 LLM prompt ----
        system_prompt = (
            "你是过滤器，不是创作者。\n"
            "你的任务是判断哪些世界设定信息本章不需要，输出减法列表。\n\n"
            "【裁剪判断铁律】\n"
            "对每个世界设定二级字段，问三个问题：\n"
            "1. 本章场景需要这个信息吗？\n"
            "2. 卷纲/近纲提到这个信息吗？\n"
            "3. 隐含关联需要这个信息吗？（如角色A的背景涉及势力B）\n"
            "三个问题全'否'才裁掉。\n\n"
            "对每个角色，问两个问题：\n"
            "1. 本章大纲提到这个角色吗？\n"
            "2. 这个角色与本章出场角色有直接关系吗？\n"
            "两个问题全'否'才裁掉。\n\n"
            "输出纯 JSON，不要输出说明文字。"
        )

        user_prompt = (
            f"【本章上下文（assemble 产出）】\n{context[:6000]}\n\n"
            f"【世界设定维度和字段】\n{json.dumps(settings_summary, ensure_ascii=False, indent=2) or '（无）'}\n\n"
            f"【角色列表】\n{', '.join(char_names) or '（无）'}\n\n"
            f"【本章大纲概要】\n"
        )
        outline = repo.get_outline_by_chapter(chapter)
        if outline:
            user_prompt += f"{outline.summary or '（无概要）'}\n"
        else:
            user_prompt += "（无大纲）\n"

        user_prompt += (
            "\n请输出减法列表 JSON：\n"
            "{\n"
            '  "维度名1": ["要删的二级字段名数组"],\n'
            '  "维度名2": ["要删的二级字段名数组"],\n'
            '  "characters": ["要删的角色名数组"]\n'
            "}\n"
            "只输出 JSON。只列出要裁掉的，不要列出要保留的。"
        )

        raw = await llm_client.generate(
            user_prompt, system=system_prompt,
            temperature=0.3, thinking=False,
        )
        subtract_list = parse_json_strict(raw)

        if not subtract_list:
            logger.info("context_trimmer 第%d章：LLM 未返回有效减法列表，保留原始上下文", chapter)
            return {"trimmed_context": context}

        # ---- Python 确定性执行裁剪 ----
        trimmed = context

        # 裁剪世界设定字段：按维度名+字段名删除上下文中的相关段落
        chars_to_remove = subtract_list.pop("characters", [])
        chars_to_remove = chars_to_remove if isinstance(chars_to_remove, list) else []

        for dimension, fields in subtract_list.items():
            if not isinstance(fields, list):
                continue
            for field_name in fields:
                if isinstance(field_name, str) and field_name:
                    # 删除上下文中包含该字段名的行
                    trimmed = _remove_context_block(trimmed, field_name)

        # 裁剪角色：删除上下文中该角色的相关段落
        for char_name in chars_to_remove:
            if isinstance(char_name, str) and char_name:
                trimmed = _remove_context_block(trimmed, char_name)

        # 防御：裁剪后不能为空（如果裁剪过度，回退原始上下文）
        if len(trimmed.strip()) < len(context.strip()) * 0.3:
            logger.warning("context_trimmer 第%d章：裁剪后上下文不足原文30%%，回退原始上下文", chapter)
            return {"trimmed_context": context}

        logger.info("context_trimmer 第%d章：裁剪完成 %d->%d 字（删%d个字段，%d个角色）",
                    chapter, len(context), len(trimmed),
                    sum(len(v) for v in subtract_list.values() if isinstance(v, list)),
                    len(chars_to_remove))

        return {"trimmed_context": trimmed}

    except Exception as e:
        # 失败用原始上下文（不阻塞流水线）
        logger.warning("context_trimmer 第%d章失败（回退原始上下文）: %s", chapter, e)
        return {"trimmed_context": context}


# ---------------------------------------------------------------------------
# 节点 3：post_hoc —— 后验裁决
# ---------------------------------------------------------------------------

async def post_hoc(state: ChapterGenState, *,
                   llm_client: LLMClient,
                   repo: BibleRepository) -> dict:
    """后验裁决节点：章节写完后检测设定漂移和故事偏差。

    借鉴 bishu-novel novel-chapter-observer + novel-arbiter，温度 0.3。
    两个 LLM 调用串行：observer -> arbiter。

    失败策略：skip（不阻塞流水线），返回空 post_hoc_results。
    """
    cancel = _check_cancelled(state, "post_hoc")
    if cancel:
        return cancel

    chapter = state.get("chapter", 0)
    polished = state.get("polished", "")
    if not polished:
        logger.info("post_hoc 第%d章：无 polished 正文，跳过后验裁决", chapter)
        return {"post_hoc_results": {}}

    try:
        # ---- 读取设定约束 ----
        world_settings = repo.list_world_settings()
        settings_text = _format_world_settings(world_settings)

        characters = repo.list_characters()
        char_text = "\n".join(
            f"- {c.name}（{c.role}）：位置={c.current_location or ''}，情绪={c.current_emotion or ''}"
            for c in characters if c.name
        )

        foreshadows = repo.list_foreshadows()
        fs_text = "\n".join(
            f"- {f.foreshadow_id}（状态={f.status}）：{f.description}"
            for f in foreshadows
        )

        outline = repo.get_outline_by_chapter(chapter)
        outline_constraints = ""
        if outline:
            outline_constraints = (
                f"概要：{outline.summary or ''}\n"
                f"爽点要求：{outline.required_beats or ''}\n"
                f"钩子要求：{outline.required_hooks or ''}\n"
                f"欠账：{outline.owed_debts or ''}\n"
            )

        # ================================================================
        # 第一轮 LLM：observer —— 提取四类差异
        # ================================================================
        observer_system = (
            "你是章节观察者。你的任务是对比'正文实际产出'和'设定约束'，提取差异。\n"
            "你不做裁决，只做观察和记录。\n"
            "输出纯 JSON，不要输出说明文字。"
        )

        observer_prompt = (
            f"【本章正文】\n{polished[:8000]}\n\n"
            f"【世界设定】\n{settings_text or '（无）'}\n\n"
            f"【角色设定】\n{char_text or '（无）'}\n\n"
            f"【伏笔状态】\n{fs_text or '（无）'}\n\n"
            f"【大纲约束】\n{outline_constraints or '（无）'}\n\n"
            "请提取以下四类差异：\n\n"
            "1. world_diff：正文中的世界设定与既定设定的差异（如新增设定、矛盾设定）\n"
            "2. story_diff：正文与大纲要求的故事差异（如爽点未交付、钩子缺失、欠账未处理）\n"
            "3. character_diff：角色行为/状态/位置与设定的差异\n"
            "4. unplanned_events：正文中出现的计划外事件（大纲没要求但写出来的事件）\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "world_diff": [{"item":"差异项","expected":"设定要求","actual":"正文实际","severity":"high/medium/low"}],\n'
            '  "story_diff": [{"item":"差异项","expected":"大纲要求","actual":"正文实际","severity":"high/medium/low"}],\n'
            '  "character_diff": [{"item":"差异项","character":"角色名","expected":"设定状态","actual":"正文状态","severity":"high/medium/low"}],\n'
            '  "unplanned_events": [{"event":"计划外事件","context":"出现场景","potential":"潜在影响"}]\n'
            "}\n"
            "只输出 JSON。"
        )

        observer_raw = await llm_client.generate(
            observer_prompt, system=observer_system,
            temperature=0.3, thinking=True,
        )
        observer_data = parse_json_strict(observer_raw)

        if not observer_data:
            logger.warning("post_hoc 第%d章：observer 返回无法解析的 JSON，跳过后验裁决", chapter)
            return {"post_hoc_results": {}}

        logger.info("post_hoc 第%d章 observer 完成：世界差异%d条，故事差异%d条，角色差异%d条，计划外事件%d条",
                    chapter,
                    len(observer_data.get("world_diff", [])),
                    len(observer_data.get("story_diff", [])),
                    len(observer_data.get("character_diff", [])),
                    len(observer_data.get("unplanned_events", [])))

        # ================================================================
        # 第二轮 LLM：arbiter —— 裁决
        # ================================================================
        arbiter_system = (
            "你是裁决者。你收到观察者的差异报告，需要对每条差异做出裁决。\n"
            "输出纯 JSON，不要输出说明文字。"
        )

        arbiter_prompt = (
            f"【观察者差异报告】\n{json.dumps(observer_data, ensure_ascii=False, indent=2)}\n\n"
            f"【世界设定参考】\n{settings_text[:2000] or '（无）'}\n\n"
            f"【大纲约束参考】\n{outline_constraints or '（无）'}\n\n"
            "请对每条差异做出裁决：\n\n"
            "1. 对 world_diff（世界事实差异）：裁决为 adopt（采纳为新设定）/ pending（待定，需人工确认）/ conflict（冲突，需修正）\n"
            "2. 对 story_diff（故事差异）：确认 landed（已落地）/ missed（遗漏）/ deviated（偏离）\n"
            "3. 对 unplanned_events（计划外事件）：归类为 hook（可作为未来钩子）/ debt（新增欠账）/ discard（丢弃，不影响后续）\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "world_adjudication": [{"item":"差异项","verdict":"adopt/pending/conflict","reason":"裁决理由"}],\n'
            '  "story_adjudication": [{"item":"差异项","verdict":"landed/missed/deviated","reason":"裁决理由"}],\n'
            '  "event_classification": [{"event":"事件","verdict":"hook/debt/discard","reason":"归类理由"}],\n'
            '  "summary": {"total_issues": 0, "critical_count": 0, "adopt_count": 0, "missed_count": 0}\n'
            "}\n"
            "只输出 JSON。"
        )

        arbiter_raw = await llm_client.generate(
            arbiter_prompt, system=arbiter_system,
            temperature=0.3, thinking=True,
        )
        arbiter_data = parse_json_strict(arbiter_raw)

        # ---- 写入 PostHocResult 表 ----
        try:
            # 先删除同章旧记录（支持重跑）
            for old_ph in repo.db.query(PostHocResult).filter(
                PostHocResult.project_id == repo.project_id,
                PostHocResult.chapter == chapter,
            ).all():
                repo.db.delete(old_ph)

            arbiter = arbiter_data or {}
            repo.db.add(PostHocResult(
                project_id=repo.project_id,
                chapter=chapter,
                world_diff=observer_data.get("world_diff", []) or [],
                story_diff=observer_data.get("story_diff", []) or [],
                character_diff=observer_data.get("character_diff", []) or [],
                unplanned_events=observer_data.get("unplanned_events", []) or [],
                world_adjudication=arbiter.get("world_adjudication", []) or [],
                story_adjudication=arbiter.get("story_adjudication", []) or [],
                event_classification=arbiter.get("event_classification", []) or [],
                summary=arbiter.get("summary", {}) or {},
            ))
            repo.db.commit()
        except Exception as db_exc:
            # 写入失败不阻塞流水线
            logger.warning("post_hoc 第%d章：写入 PostHocResult 失败（不阻塞流水线）: %s", chapter, db_exc)
            repo.db.rollback()

        if not arbiter_data:
            logger.warning("post_hoc 第%d章：arbiter 返回无法解析的 JSON，仅保留 observer 结果", chapter)
            return {"post_hoc_results": {"observer": observer_data, "arbiter": {}}}

        logger.info("post_hoc 第%d章 arbiter 完成：%s",
                    chapter, arbiter_data.get("summary", {}))

        return {"post_hoc_results": {"observer": observer_data, "arbiter": arbiter_data}}

    except Exception as e:
        # 失败不阻塞流水线（skip 策略）
        logger.warning("post_hoc 第%d章失败（不阻塞流水线）: %s", chapter, e)
        return {"post_hoc_results": {}}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _format_world_settings(world_settings) -> str:
    """格式化世界设定列表为文本摘要。"""
    if not world_settings:
        return ""
    parts = []
    for ws in world_settings:
        line = f"[{ws.category or '其他'}] {ws.title or '未命名'}"
        if ws.content:
            # 截取前200字避免 prompt 过长
            content = ws.content[:200]
            if len(ws.content) > 200:
                content += "..."
            line += f"：{content}"
        parts.append(line)
    return "\n".join(parts)


def _remove_context_block(text: str, keyword: str) -> str:
    """从上下文文本中删除包含关键词的行块。

    策略：删除包含关键词的整行。如果该行是段落标题（以【或[开头），
    则删除该标题到下一个标题之间的所有行。
    """
    if not keyword or not text:
        return text
    lines = text.split("\n")
    result = []
    skip_until_next_header = False
    for line in lines:
        stripped = line.strip()
        # 如果在跳过模式中，遇到新的标题行则停止跳过
        if skip_until_next_header:
            if stripped.startswith("【") or stripped.startswith("[") or stripped.startswith("#"):
                skip_until_next_header = False
                result.append(line)
            continue
        # 检查当前行是否包含关键词
        if keyword in line:
            # 如果是标题行，跳过直到下一个标题
            if stripped.startswith("【") or stripped.startswith("[") or stripped.startswith("#"):
                skip_until_next_header = True
            # 非标题行：直接跳过该行
            continue
        result.append(line)
    return "\n".join(result)
