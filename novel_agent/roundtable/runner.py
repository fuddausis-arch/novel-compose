"""
圆桌会议执行引擎与管理器

RoundtableRunner: 驱动一场圆桌会议的发言主循环
  - Phase 1: 固定轮询调度
  - Phase 2: 可插拔策略 + Moderator 决策 + 上下文压缩 + 共享记忆
  - Phase 3: 用户干预处理 + 暂停/恢复 + 结构化结论 + 并发安全

RoundtableManager: 管理所有 roundtable 的注册表、创建、启动、终止、持久化

从 DeterminFlow 移植，适配 NovelAgent：
- LLM 调用改为 novel_agent.llm.client.LLMClient（chat_stream / chat）
  - 消息格式：[{"role": "system"/"user", "content": "..."}]（dict，非 langchain）
- 事件推送改为 session.emit_event（EventBroadcaster → SSE），替代全局 event_bus
- 持久化改为 SQLite（store.py），替代 JSON 文件
"""
import asyncio
import copy
import json
import logging
from datetime import datetime, timezone

from novel_agent.config import LLMConfig, load_config
from novel_agent.llm.client import LLMClient
from novel_agent.prompts.roundtable_prompts import (
    MODERATOR_DECISION_PROMPT,
    MODERATOR_SUMMARY_PROMPT,
    MODERATOR_CONCLUSION_PROMPT,
    safe_format,
)
from novel_agent.roundtable import ROUNDTABLE_MAX_IDLE_CYCLES, ROUNDTABLE_MAX_SEATS
from novel_agent.roundtable.models import (
    Seat,
    TurnController,
    TranscriptEntry,
    RoundtableSession,
    ModeratorDecidesStrategy,
    Intervention,
)
from novel_agent.roundtable.store import store as _store
from novel_agent.state_common import RoundtableStatus

logger = logging.getLogger("roundtable")

# 模块级配置缓存：避免每次发言都重新读 YAML
_config_cache: LLMConfig | None = None


def _get_config():
    """获取（缓存的）全局配置。"""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def _safe_truncate(text: str, max_len: int) -> str:
    """安全截断字符串。"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ============================================================
# RoundtableRunner - 执行引擎
# ============================================================

class RoundtableRunner:
    """
    驱动一场圆桌会议的执行引擎。

    Phase 1 流程（round_robin）：
    1. TurnController 选出下一个发言者
    2. 构建该 Seat 的 LLM 上下文
    3. 调用 LLM 流式生成发言
    4. 逐 token 广播 rt_token 事件
    5. 发言结束后追加到 Transcript
    6. 广播 rt_turn_end 事件
    7. 轮次结束时广播 rt_round_end 事件

    Phase 2 新增（moderator_decides）：
    - Moderator LLM 决策下一位发言者
    - 广播 speaker_selected / moderator_decision 事件
    - 阶段摘要和会议结论生成
    - 广播 roundtable_summary / roundtable_conclusion 事件
    """

    # ============ LLMClient 工厂 ============

    def _make_llm_client(
        self,
        seat: Seat | None = None,
        temperature: float | None = None,
        role: str = "debater",
    ) -> LLMClient:
        """
        为某个 Seat（或 Moderator）构建 LLMClient。

        基于 config.get_agent_llm(role) 获取基础配置，
        然后覆盖 seat 的 model_name 和 temperature。

        Args:
            seat: 席位（None 表示 Moderator 系统调用）
            temperature: 温度覆盖（None 时用 seat.temperature）
            role: NovelAgent 角色名（debater/architect 等，用于温度光谱）
        """
        cfg = _get_config()
        base = cfg.get_agent_llm(role)
        llm_cfg = copy.copy(base)
        if seat is not None:
            if seat.model_name:
                llm_cfg.model = seat.model_name
            if temperature is None:
                temperature = seat.temperature
        if temperature is not None:
            llm_cfg.temperature = temperature
        return LLMClient(llm_cfg)

    async def run(self, session: RoundtableSession) -> None:
        """
        主循环：驱动整场圆桌会议。

        该方法应在 asyncio.Task 中运行，不阻塞主线程。

        Phase 3 增强：
        - 每轮调度前检查暂停信号
        - 每轮调度前消费干预队列
        - 使用 session._lock 保护状态修改
        """
        controller = session.turn_controller
        session.status = RoundtableStatus.DISCUSSING.value
        session.save()

        strategy = controller.strategy
        is_moderator_mode = isinstance(strategy, ModeratorDecidesStrategy)

        logger.info(
            f"Roundtable {session.session_id} 开始讨论: "
            f"主题={session.topic!r}, seats={len(session.seats)}, "
            f"strategy={controller.strategy_name}, "
            f"max_rounds={session.max_rounds}"
        )

        # 广播会议开始
        await session.emit_event({
            "type": "rt_started",
            "roundtable_id": session.session_id,
            "topic": session.topic,
            "seats": [s.to_dict() for s in session.seats],
            "max_rounds": session.max_rounds,
            "strategy": controller.strategy_name,
        })

        try:
            while not controller.should_end():
                # Phase 3: 等待暂停恢复信号
                await session._pause_event.wait()

                # Phase 3: 处理干预队列
                should_stop = await self._process_interventions(session)
                if should_stop:
                    break

                if is_moderator_mode:
                    await self._run_moderator_loop(session, controller, strategy)
                else:
                    await self._run_round_robin_loop(session, controller)
                    break  # round_robin 的 while 循环在内部完成

        except asyncio.CancelledError:
            logger.info(f"Roundtable {session.session_id} 被取消")
            session.status = RoundtableStatus.ENDED.value
            raise
        except Exception as e:
            logger.error(
                f"Roundtable {session.session_id} 异常: {e}",
                exc_info=True,
            )
            session.status = RoundtableStatus.ENDED.value

        # 生成结构化会议结论
        if session.transcript:
            await self._generate_conclusion(session)

        # 会议结束
        session.status = RoundtableStatus.ENDED.value
        session.ended_at = datetime.now(timezone.utc).isoformat()
        for s in session.seats:
            s.status = RoundtableStatus.IDLE.value
        session.save()

        # 广播会议结束
        await session.emit_event({
            "type": "rt_ended",
            "roundtable_id": session.session_id,
            "total_rounds": controller.current_round,
            "transcript_count": len(session.transcript),
        })

        logger.info(
            f"Roundtable {session.session_id} 已结束: "
            f"共 {controller.current_round} 轮, "
            f"{len(session.transcript)} 条发言"
        )

    # ============ Round Robin 循环（兼容 Phase 1）============

    async def _run_round_robin_loop(
        self, session: RoundtableSession, controller: TurnController
    ) -> None:
        """Phase 1 兼容的轮询循环，Phase 3 增加暂停和干预支持"""
        while not controller.should_end():
            # Phase 3: 暂停检查
            await session._pause_event.wait()

            # Phase 3: 处理干预队列
            should_stop = await self._process_interventions(session)
            if should_stop:
                return

            seat = controller.next_speaker()
            if seat is None:
                break

            await self._do_speak(seat, session, controller)

            # 前进调度器
            controller.advance()

            # 检查是否一轮结束
            if controller.is_round_end():
                await session.emit_event({
                    "type": "rt_round_end",
                    "roundtable_id": session.session_id,
                    "round": controller.current_round,
                })
                # 重置席位状态
                for s in session.seats:
                    s.status = RoundtableStatus.IDLE.value

                # Phase 2: 检查是否需要生成阶段摘要
                if session.compressor.should_summarize(controller.current_round):
                    await self._generate_round_summary(session, controller.current_round)

            # 定期保存
            session.save()

    # ============ Moderator 决策循环（Phase 2）============

    async def _run_moderator_loop(
        self,
        session: RoundtableSession,
        controller: TurnController,
        strategy: ModeratorDecidesStrategy,
    ) -> None:
        """Moderator 决策驱动的讨论循环，Phase 3 增加暂停和干预支持"""
        max_idle_cycles = ROUNDTABLE_MAX_IDLE_CYCLES

        for _ in range(max_idle_cycles):
            if controller.should_end():
                break

            # Phase 3: 暂停检查
            await session._pause_event.wait()

            # Phase 3: 处理干预队列
            should_stop = await self._process_interventions(session)
            if should_stop:
                return

            # 需要 Moderator 做决策
            if strategy.needs_moderator_decision:
                moderator_seat = session.get_moderator_seat()

                # 广播 Moderator 正在思考
                if moderator_seat:
                    moderator_seat.status = RoundtableStatus.THINKING.value
                    await session.emit_event({
                        "type": "rt_turn_start",
                        "roundtable_id": session.session_id,
                        "seat_id": moderator_seat.seat_id,
                        "speaker_name": moderator_seat.role_name,
                        "round": controller.current_round,
                        "is_moderator_thinking": True,
                    })

                decision = await self._moderator_decide(session)

                if moderator_seat:
                    moderator_seat.status = RoundtableStatus.IDLE.value

                # 广播决策
                await session.emit_event({
                    "type": "moderator_decision",
                    "roundtable_id": session.session_id,
                    "decision": decision,
                })

                action = decision.get("action", "conclude")

                if action == "conclude":
                    strategy.set_decision(should_conclude=True)
                    break

                elif action == "summarize":
                    await self._generate_round_summary(session, controller.current_round)
                    strategy.needs_moderator_decision = True
                    continue

                elif action == "new_round":
                    speaker_id = decision.get("speaker_id")
                    strategy.set_decision(
                        speaker_id=speaker_id,
                        new_round=True,
                    )

                    await session.emit_event({
                        "type": "rt_round_end",
                        "roundtable_id": session.session_id,
                        "round": controller.current_round - 1,
                    })
                    for s in session.seats:
                        s.status = RoundtableStatus.IDLE.value

                    # 检查摘要
                    if session.compressor.should_summarize(controller.current_round - 1):
                        await self._generate_round_summary(session, controller.current_round - 1)

                elif action == "select_speaker":
                    speaker_id = decision.get("speaker_id")
                    if not speaker_id:
                        strategy.set_decision(should_conclude=True)
                        break
                    strategy.set_decision(speaker_id=speaker_id)

                    # 广播选人决策
                    selected_seat = None
                    for s in session.seats:
                        if s.seat_id == speaker_id:
                            selected_seat = s
                            break

                    await session.emit_event({
                        "type": "speaker_selected",
                        "roundtable_id": session.session_id,
                        "seat_id": speaker_id,
                        "speaker_name": selected_seat.role_name if selected_seat else "unknown",
                        "round": controller.current_round,
                        "reason": decision.get("reason", ""),
                    })

            # 尝试获取下一位发言者
            seat = controller.next_speaker()
            if seat is None:
                if strategy.needs_moderator_decision:
                    continue
                break

            await self._do_speak(seat, session, controller)
            controller.advance()
            session.save()

    # ============ 干预队列处理（Phase 3）============

    async def _process_interventions(self, session: RoundtableSession) -> bool:
        """
        处理用户干预队列中的所有待处理事件。

        Returns:
            True 如果应立即结束会议（收到 "end" 干预）
        """
        interventions = session.intervention_queue.drain_all()
        controller = session.turn_controller

        for iv in interventions:
            if iv.intervention_type == "inject":
                # 用户插话：追加到 transcript 并广播
                entry = TranscriptEntry(
                    speaker_seat_id="user",
                    speaker_name="用户插话",
                    content=iv.content,
                    round_number=controller.current_round,
                    entry_type="moderator_note",
                )
                async with session._lock:
                    session.transcript.append(entry)

                await session.emit_event({
                    "type": "rt_turn_end",
                    "roundtable_id": session.session_id,
                    "seat_id": "user",
                    "speaker_name": "用户插话",
                    "round": controller.current_round,
                    "full_content": iv.content,
                })
                logger.info(f"Roundtable {session.session_id} 用户插话: {iv.content[:50]}")

            elif iv.intervention_type == "nominate":
                # 点名：让指定 seat 立即发言
                target = session.get_seat(iv.target_seat_id) if iv.target_seat_id else None
                if not target and iv.content:
                    # 尝试按名称匹配
                    target = session.get_seat_by_name(iv.content)

                if target:
                    # 如果有插话内容，先追加
                    if iv.content and iv.target_seat_id:
                        inject_entry = TranscriptEntry(
                            speaker_seat_id="user",
                            speaker_name="用户",
                            content=f"@{target.role_name} {iv.content}",
                            round_number=controller.current_round,
                            entry_type="moderator_note",
                        )
                        async with session._lock:
                            session.transcript.append(inject_entry)
                        await session.emit_event({
                            "type": "rt_turn_end",
                            "roundtable_id": session.session_id,
                            "seat_id": "user",
                            "speaker_name": "用户",
                            "round": controller.current_round,
                            "full_content": f"@{target.role_name} {iv.content}",
                        })

                    # 让指定 seat 发言
                    await session.emit_event({
                        "type": "speaker_selected",
                        "roundtable_id": session.session_id,
                        "seat_id": target.seat_id,
                        "speaker_name": target.role_name,
                        "round": controller.current_round,
                        "reason": "用户点名",
                    })
                    await self._do_speak(target, session, controller)
                    logger.info(f"Roundtable {session.session_id} 用户点名: {target.role_name}")
                else:
                    logger.warning(f"点名失败：未找到匹配席位 {iv.target_seat_id or iv.content}")

            elif iv.intervention_type == "add_seat":
                # 动态添加席位
                if iv.seat_config:
                    async with session._lock:
                        new_seat = session.add_seat(iv.seat_config)
                    await session.emit_event({
                        "type": "rt_seat_added",
                        "roundtable_id": session.session_id,
                        "seat": new_seat.to_dict(),
                    })
                    session.save()

            elif iv.intervention_type == "remove_seat":
                # 动态移除席位
                if iv.target_seat_id:
                    async with session._lock:
                        removed = session.remove_seat(iv.target_seat_id)
                    if removed:
                        await session.emit_event({
                            "type": "rt_seat_removed",
                            "roundtable_id": session.session_id,
                            "seat_id": iv.target_seat_id,
                            "role_name": removed.role_name,
                        })
                        session.save()

            elif iv.intervention_type == "pause":
                session.pause()
                await session.emit_event({
                    "type": "rt_paused",
                    "roundtable_id": session.session_id,
                    "round": controller.current_round,
                })
                session.save()
                # 暂停后等待恢复
                await session._pause_event.wait()

            elif iv.intervention_type == "resume":
                session.resume()
                await session.emit_event({
                    "type": "rt_resumed",
                    "roundtable_id": session.session_id,
                    "round": controller.current_round,
                })
                session.save()

            elif iv.intervention_type == "end":
                logger.info(f"Roundtable {session.session_id} 用户请求提前结束")
                return True

        return False

    # ============ 通用发言执行 ============

    async def _do_speak(
        self, seat: Seat, session: RoundtableSession, controller: TurnController
    ) -> None:
        """执行一个 Seat 的发言流程"""
        # 更新席位状态
        seat.status = RoundtableStatus.SPEAKING.value
        session.begin_active_turn(seat, controller.current_round)

        # 广播发言开始
        await session.emit_event({
            "type": "rt_turn_start",
            "roundtable_id": session.session_id,
            "seat_id": seat.seat_id,
            "speaker_name": seat.role_name,
            "round": controller.current_round,
        })

        # 执行发言
        content = await self._speak(seat, session)

        # 更新席位状态
        seat.status = RoundtableStatus.DONE.value

        # 记录到 Transcript
        entry = TranscriptEntry(
            speaker_seat_id=seat.seat_id,
            speaker_name=seat.role_name,
            content=content,
            round_number=controller.current_round,
        )
        async with session._lock:
            session.transcript.append(entry)
        session.end_active_turn()

        # 广播发言结束
        await session.emit_event({
            "type": "rt_turn_end",
            "roundtable_id": session.session_id,
            "seat_id": seat.seat_id,
            "speaker_name": seat.role_name,
            "round": controller.current_round,
            "full_content": content,
        })

        logger.info(
            f"Roundtable {session.session_id} - "
            f"R{controller.current_round} {seat.role_name}: "
            f"{content[:80]}..."
        )

    async def _speak(self, seat: Seat, session: RoundtableSession) -> str:
        """
        驱动一个 Seat 的单次发言。

        使用 LLMClient.chat_stream 逐 token 生成，
        同时通过 session.emit_event 推送 rt_token 事件。
        """
        # 构建上下文（dict 格式消息）
        messages = self._build_seat_context(seat, session)

        # 创建该 Seat 专属的 LLMClient
        client = self._make_llm_client(seat)

        # 流式生成
        full_content = ""
        try:
            async for event in client.chat_stream(
                messages, node_name=f"roundtable_{seat.role_name}"
            ):
                if event["type"] == "text_delta":
                    token = event["content"]
                    full_content += token
                    session.append_active_turn(token)
                    await session.emit_event({
                        "type": "rt_token",
                        "roundtable_id": session.session_id,
                        "seat_id": seat.seat_id,
                        "content": token,
                    })
                elif event["type"] == "done":
                    break
        except Exception as e:
            logger.error(f"Seat {seat.role_name} 发言异常: {e}", exc_info=True)
            full_content = f"[{seat.role_name} 发言异常，请稍后重试]"
        finally:
            await client.close()

        return full_content

    def _build_seat_context(
        self, seat: Seat, session: RoundtableSession
    ) -> list[dict]:
        """
        为某个 Seat 构建 LLM 输入消息列表（dict 格式，适配 LLMClient）。

        结构：
        [1] system: 该 Seat 的独立 system prompt
        [2] user: 圆桌会议上下文（主题 + 规则 + 参与者列表）
        [3] user: 共享记忆上下文（Phase 2）
        [4] user: Transcript 历史（支持压缩）
        [5] user: 发言引导
        """
        messages: list[dict] = []
        controller = session.turn_controller

        # [1] System Prompt
        messages.append({"role": "system", "content": seat.system_prompt})

        # [2] 圆桌会议上下文
        participants = "\n".join(
            f"- {s.role_name}{'（主持人）' if s.is_moderator else ''}"
            for s in session.seats
        )
        context = (
            f"# 圆桌会议\n\n"
            f"**讨论主题**: {session.topic}\n\n"
            f"**参与者**:\n{participants}\n\n"
            f"**你的角色**: {seat.role_name}\n\n"
            f"**讨论规则**:\n"
            f"- 这是一场圆桌会议，参与者按顺序依次发言\n"
            f"- 当前是第 {controller.current_round} 轮"
            f"（共 {session.max_rounds} 轮）\n"
            f"- 请围绕主题发表你的观点，可以回应其他参与者的发言\n"
            f"- 发言应简洁、有建设性，控制在 200-500 字之间\n"
        )
        messages.append({"role": "user", "content": context})

        # [3] 共享记忆上下文（Phase 2）
        shared_ctx = session.shared_memory.get_context_text()
        if shared_ctx:
            messages.append({"role": "user", "content": f"# 讨论要点记录\n\n{shared_ctx}"})

        # [4] Transcript 历史（Phase 2: 支持压缩）
        context_entries, summary_prefix = session.compressor.get_context_entries(
            session.transcript, session.shared_memory
        )

        if summary_prefix or context_entries:
            history_parts = []

            if summary_prefix:
                history_parts.append(f"[早期讨论摘要]\n{summary_prefix}\n")

            if context_entries:
                current_round = 0
                for entry in context_entries:
                    if entry.round_number != current_round:
                        current_round = entry.round_number
                        history_parts.append(f"\n--- 第 {current_round} 轮 ---\n")
                    history_parts.append(
                        f"**{entry.speaker_name}**: {entry.content}"
                    )

            transcript_text = (
                "# 讨论记录\n\n"
                "以下是之前的讨论记录：\n\n"
                + "\n\n".join(history_parts)
            )
            messages.append({"role": "user", "content": transcript_text})

        # [5] 发言引导
        messages.append({
            "role": "user",
            "content": f"现在轮到你（{seat.role_name}）发言了。请就讨论主题发表你的观点。"
        })

        return messages

    # ============ Moderator 决策（Phase 2）============

    async def _moderator_decide(self, session: RoundtableSession) -> dict:
        """
        让 Moderator LLM 做出决策。

        Returns:
            {
                "action": "select_speaker" | "new_round" | "conclude" | "summarize",
                "speaker_id": "seat-X" (optional),
                "reason": "决策理由"
            }
        """
        moderator_seat = session.get_moderator_seat()
        controller = session.turn_controller

        participants = "\n".join(
            f"- {s.role_name} (seat_id: {s.seat_id})"
            for s in session.seats
            if not s.is_moderator
        )

        # 生成最近讨论摘要
        recent_entries = session.transcript[-6:] if session.transcript else []
        recent_summary = "\n".join(
            f"[R{e.round_number}] {e.speaker_name}: {_safe_truncate(e.content, 100)}"
            for e in recent_entries
        ) if recent_entries else "（尚无发言记录）"

        prompt = safe_format(MODERATOR_DECISION_PROMPT,
            topic=session.topic,
            current_round=controller.current_round,
            max_rounds=session.max_rounds,
            transcript_count=len(session.transcript),
            participants=participants,
            recent_summary=recent_summary,
        )

        client = self._make_llm_client(moderator_seat, temperature=0.3)
        try:
            result = await client.chat(
                [
                    {"role": "system", "content": "你是一个圆桌会议调度 AI，只返回 JSON 格式的决策。"},
                    {"role": "user", "content": prompt},
                ],
                node_name="roundtable_moderator_decision",
            )
            content = result["content"].strip()

            # 处理可能的 markdown 代码块
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            decision = json.loads(content)

            # 验证决策
            if "action" not in decision:
                decision["action"] = "conclude"

            valid_actions = {"select_speaker", "new_round", "conclude", "summarize"}
            if decision["action"] not in valid_actions:
                decision["action"] = "conclude"

            logger.info(
                f"Moderator 决策: action={decision['action']}, "
                f"reason={decision.get('reason', 'N/A')}"
            )
            return decision

        except Exception as e:
            logger.error(f"Moderator 决策失败: {e}", exc_info=True)
            return {
                "action": "conclude",
                "reason": f"决策出错: {str(e)}",
            }
        finally:
            await client.close()

    # ============ 摘要生成（Phase 2）============

    async def _generate_round_summary(
        self, session: RoundtableSession, round_number: int
    ) -> None:
        """生成某一轮的阶段摘要"""
        # 收集该轮的发言
        round_entries = [
            e for e in session.transcript
            if e.round_number == round_number
        ]
        if not round_entries:
            return

        moderator_seat = session.get_moderator_seat()
        recent_transcript = "\n".join(
            f"**{e.speaker_name}**: {e.content}"
            for e in round_entries
        )

        prompt = safe_format(MODERATOR_SUMMARY_PROMPT,
            topic=session.topic,
            current_round=round_number,
            recent_transcript=recent_transcript,
        )

        client = self._make_llm_client(moderator_seat, temperature=0.3)
        try:
            result = await client.chat(
                [
                    {"role": "system", "content": "你是一个擅长总结的 AI 助手。"},
                    {"role": "user", "content": prompt},
                ],
                node_name="roundtable_summary",
            )

            summary_content = result["content"].strip()

            # 存入共享记忆
            session.shared_memory.add_summary(round_number, summary_content)

            # 追加到 transcript
            moderator_name = moderator_seat.role_name if moderator_seat else "系统"
            entry = TranscriptEntry(
                speaker_seat_id=moderator_seat.seat_id if moderator_seat else "system",
                speaker_name=moderator_name,
                content=summary_content,
                round_number=round_number,
                entry_type="summary",
            )
            async with session._lock:
                session.transcript.append(entry)

            # 广播摘要事件
            await session.emit_event({
                "type": "roundtable_summary",
                "roundtable_id": session.session_id,
                "round": round_number,
                "content": summary_content,
                "source": moderator_name,
            })

            logger.info(f"Roundtable {session.session_id} R{round_number} 摘要已生成")

        except Exception as e:
            logger.error(f"生成摘要失败: {e}", exc_info=True)
        finally:
            await client.close()

    async def _generate_conclusion(self, session: RoundtableSession) -> None:
        """生成结构化会议最终结论（Phase 3 增强）"""
        moderator_seat = session.get_moderator_seat()
        controller = session.turn_controller

        full_lines = [
            f"[R{e.round_number}] {e.speaker_name}: {e.content}"
            for e in session.transcript
            if e.entry_type == "statement"
        ]
        # 完整发言保留直到总量上限（不做 3000 字硬切——硬切会把后半段讨论
        # "半截"丢掉，结论提炼就看不到后半段的决议）
        kept: list[str] = []
        used = 0
        for ln in full_lines:
            if used + len(ln) + 1 > 3000:
                break
            kept.append(ln)
            used += len(ln) + 1
        full_transcript = "\n".join(kept)

        shared_ctx = session.shared_memory.get_context_text()

        prompt = safe_format(MODERATOR_CONCLUSION_PROMPT,
            topic=session.topic,
            total_rounds=controller.current_round,
            transcript_count=len(session.transcript),
            shared_memory_context=shared_ctx or "（无已记录的共享要点）",
            full_transcript=_safe_truncate(full_transcript, 3000),  # 限制长度
        )

        client = self._make_llm_client(moderator_seat, temperature=0.3)
        try:
            result = await client.chat(
                [
                    {"role": "system", "content": "你是一个擅长总结的 AI 助手，只返回 JSON 格式的结论。"},
                    {"role": "user", "content": prompt},
                ],
                node_name="roundtable_conclusion",
            )

            conclusion_content = result["content"].strip()

            # 处理可能的 markdown 代码块
            if conclusion_content.startswith("```"):
                conclusion_content = conclusion_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            # 尝试解析为结构化结论
            moderator_name = moderator_seat.role_name if moderator_seat else "系统"
            structured = None
            try:
                structured = json.loads(conclusion_content)
                # 验证结构
                if not isinstance(structured, dict) or "summary" not in structured:
                    structured = None
            except json.JSONDecodeError:
                structured = None

            if structured:
                # 成功解析结构化结论
                session.shared_memory.set_structured_conclusion(structured)
                session.shared_memory.add_conclusion(structured.get("summary", ""), moderator_name)
                conclusion_text = self._format_structured_conclusion(structured)
            else:
                # 回退到普通文本结论
                session.shared_memory.add_conclusion(conclusion_content, moderator_name)
                conclusion_text = conclusion_content

            entry = TranscriptEntry(
                speaker_seat_id=moderator_seat.seat_id if moderator_seat else "system",
                speaker_name=moderator_name,
                content=conclusion_text,
                round_number=controller.current_round,
                entry_type="conclusion",
            )
            async with session._lock:
                session.transcript.append(entry)

            event_data: dict = {
                "type": "roundtable_conclusion",
                "roundtable_id": session.session_id,
                "content": conclusion_text,
                "source": moderator_name,
                "total_rounds": controller.current_round,
            }
            if structured:
                event_data["structured"] = structured
            await session.emit_event(event_data)

            logger.info(f"Roundtable {session.session_id} 结论已生成 (structured={'yes' if structured else 'no'})")

        except Exception as e:
            logger.error(f"生成结论失败: {e}", exc_info=True)
        finally:
            await client.close()

    @staticmethod
    def _format_structured_conclusion(structured: dict) -> str:
        """将结构化结论格式化为可读 Markdown 文本"""
        parts = []
        if structured.get("summary"):
            parts.append(f"## 📋 会议总结\n\n{structured['summary']}")
        if structured.get("consensus"):
            items = "\n".join(f"- {c}" for c in structured["consensus"])
            parts.append(f"## ✅ 达成共识\n\n{items}")
        if structured.get("disagreements"):
            items = "\n".join(f"- {d}" for d in structured["disagreements"])
            parts.append(f"## ⚠️ 主要分歧\n\n{items}")
        if structured.get("pending_verification"):
            items = "\n".join(f"- {v}" for v in structured["pending_verification"])
            parts.append(f"## 🔍 待验证事项\n\n{items}")
        if structured.get("action_items"):
            items = "\n".join(f"- {a}" for a in structured["action_items"])
            parts.append(f"## 🚀 后续行动项\n\n{items}")
        return "\n\n".join(parts) if parts else "（结论生成异常）"


# ============================================================
# RoundtableManager - 管理器
# ============================================================

class RoundtableManager:
    """
    管理所有圆桌会议的注册表。

    负责：
    - 创建、查询、删除 RoundtableSession
    - 启动/终止讨论的 asyncio.Task
    - 从 SQLite 加载历史会话
    """

    def __init__(self):
        self.sessions: dict[str, RoundtableSession] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._runner = RoundtableRunner()

    # ============ 创建 ============

    def create(
        self,
        topic: str,
        seats_config: list[dict],
        max_rounds: int = 3,
        strategy: str = "round_robin",
        compressor_config: dict | None = None,
    ) -> RoundtableSession:
        """
        创建一场新的圆桌会议。

        Args:
            topic: 讨论主题
            seats_config: 席位配置列表
            max_rounds: 最大轮次
            strategy: 调度策略 ("round_robin" | "moderator_decides")
            compressor_config: 上下文压缩配置
                {"enabled": bool, "window_size": int, "summary_interval": int}

        Returns:
            创建好的 RoundtableSession
        """
        seats = []
        for i, cfg in enumerate(seats_config):
            seat = Seat(
                seat_id=cfg.get("seat_id", f"seat-{i}"),
                role_name=cfg.get("role_name", f"角色{i+1}"),
                system_prompt=cfg.get("system_prompt", f"你是{cfg.get('role_name', f'角色{i+1}')}。"),
                temperature=cfg.get("temperature", 0.7),
                model_name=cfg.get("model_name"),
                allowed_tools=cfg.get("allowed_tools"),
                is_moderator=cfg.get("is_moderator", False),
            )
            seats.append(seat)

        # moderator_decides 策略要求至少有一个 moderator
        if strategy == "moderator_decides":
            has_moderator = any(s.is_moderator for s in seats)
            if not has_moderator:
                # 自动将第一个席位设为 moderator
                seats[0].is_moderator = True
                logger.warning(
                    f"moderator_decides 策略需要主持人，已自动将 {seats[0].role_name} 设为主持人"
                )

        session = RoundtableSession(
            topic=topic,
            seats=seats,
            max_rounds=max_rounds,
            strategy=strategy,
            compressor_config=compressor_config,
        )

        self.sessions[session.session_id] = session
        session.save()

        logger.info(
            f"Roundtable {session.session_id} 已创建: "
            f"topic={topic!r}, seats={len(seats)}, "
            f"strategy={strategy}, max_rounds={max_rounds}"
        )

        return session

    # ============ 启动 ============

    async def start(self, session_id: str) -> dict:
        """
        启动圆桌会议讨论。

        创建 asyncio.Task 驱动 RoundtableRunner。

        Returns:
            {"success": bool, "message": str}
        """
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.status == RoundtableStatus.DISCUSSING.value:
            return {"success": False, "message": "该会议正在进行中"}

        if session.status == RoundtableStatus.ENDED.value:
            return {"success": False, "message": "该会议已结束"}

        # 创建异步任务
        task = asyncio.create_task(
            self._run_session(session),
            name=f"roundtable-{session_id}",
        )
        self._tasks[session_id] = task

        return {"success": True, "message": f"圆桌会议 {session_id} 已开始"}

    async def _run_session(self, session: RoundtableSession) -> None:
        """运行会议的包装器，处理异常和清理"""
        try:
            await self._runner.run(session)
        except asyncio.CancelledError:
            await self._finalize_interrupted_turn(session)
            session.status = RoundtableStatus.ENDED.value
            session.ended_at = datetime.now(timezone.utc).isoformat()
            session.save()
        except Exception as e:
            logger.error(f"Roundtable {session.session_id} 运行异常: {e}", exc_info=True)
            await self._finalize_interrupted_turn(session)
            session.status = RoundtableStatus.ENDED.value
            session.ended_at = datetime.now(timezone.utc).isoformat()
            session.save()
            await session.emit_event({
                "type": "rt_ended",
                "roundtable_id": session.session_id,
                "total_rounds": session.current_round,
                "transcript_count": len(session.transcript),
            })
        finally:
            self._tasks.pop(session.session_id, None)

    async def _finalize_interrupted_turn(self, session: RoundtableSession) -> None:
        """将用户已看到的部分发言固化，避免终止后历史回退。"""
        active_turn = dict(session.active_turn) if session.active_turn else None
        session.end_active_turn()
        if not active_turn:
            return

        seat_id = str(active_turn.get("seat_id") or "")
        speaker_name = str(active_turn.get("speaker_name") or seat_id)
        content = str(active_turn.get("content") or "")
        round_number = int(active_turn.get("round") or session.current_round)
        seat = session.get_seat(seat_id)
        if seat:
            seat.status = RoundtableStatus.IDLE.value
        if not content:
            return

        entry = TranscriptEntry(
            speaker_seat_id=seat_id,
            speaker_name=speaker_name,
            content=content,
            round_number=round_number,
        )
        async with session._lock:
            session.transcript.append(entry)
        await session.emit_event({
            "type": "rt_turn_end",
            "roundtable_id": session.session_id,
            "seat_id": seat_id,
            "speaker_name": speaker_name,
            "round": round_number,
            "full_content": content,
            "interrupted": True,
        })

    # ============ 终止 ============

    async def stop(self, session_id: str) -> dict:
        """终止正在进行的圆桌会议"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.status not in (RoundtableStatus.DISCUSSING.value, RoundtableStatus.PAUSED.value):
            return {"success": False, "message": f"会议当前状态为 {session.status}，无需终止"}

        # Phase 3: 如果暂停中，先恢复（让 runner 退出等待）
        if session.status == RoundtableStatus.PAUSED.value:
            session.resume()

        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        session.status = RoundtableStatus.ENDED.value
        session.ended_at = datetime.now(timezone.utc).isoformat()
        session.save()

        await session.emit_event({
            "type": "rt_ended",
            "roundtable_id": session_id,
            "total_rounds": session.current_round,
            "transcript_count": len(session.transcript),
        })

        logger.info(f"Roundtable {session_id} 已被手动终止")
        return {"success": True, "message": f"圆桌会议 {session_id} 已终止"}

    # ============ 暂停 / 恢复（Phase 3）============

    async def pause(self, session_id: str) -> dict:
        """暂停正在进行的圆桌会议"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.pause():
            await session.emit_event({
                "type": "rt_paused",
                "roundtable_id": session_id,
                "round": session.current_round,
            })
            session.save()
            return {"success": True, "message": f"圆桌会议 {session_id} 已暂停"}
        return {"success": False, "message": f"会议当前状态为 {session.status}，无法暂停"}

    async def resume(self, session_id: str) -> dict:
        """恢复暂停的圆桌会议"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.resume():
            await session.emit_event({
                "type": "rt_resumed",
                "roundtable_id": session_id,
                "round": session.current_round,
            })
            session.save()
            return {"success": True, "message": f"圆桌会议 {session_id} 已恢复"}
        return {"success": False, "message": f"会议当前状态为 {session.status}，无法恢复"}

    # ============ 用户干预（Phase 3）============

    async def inject(self, session_id: str, content: str) -> dict:
        """用户插话"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.status not in (RoundtableStatus.DISCUSSING.value, RoundtableStatus.PAUSED.value):
            return {"success": False, "message": f"会议状态为 {session.status}，无法插话"}

        await session.intervention_queue.put(
            Intervention(intervention_type="inject", content=content)
        )
        return {"success": True, "message": "插话已提交"}

    async def nominate(self, session_id: str, target_seat_id: str | None = None,
                       target_name: str | None = None, content: str = "") -> dict:
        """点名某个 seat 发言"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.status not in (RoundtableStatus.DISCUSSING.value, RoundtableStatus.PAUSED.value):
            return {"success": False, "message": f"会议状态为 {session.status}，无法点名"}

        # 验证目标 seat 存在
        target = None
        if target_seat_id:
            target = session.get_seat(target_seat_id)
        elif target_name:
            target = session.get_seat_by_name(target_name)

        if not target:
            return {"success": False, "message": f"未找到匹配的席位"}

        await session.intervention_queue.put(
            Intervention(
                intervention_type="nominate",
                content=content,
                target_seat_id=target.seat_id,
            )
        )
        return {"success": True, "message": f"已点名 {target.role_name}"}

    async def add_seat(self, session_id: str, seat_config: dict) -> dict:
        """动态添加席位"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if len(session.seats) >= ROUNDTABLE_MAX_SEATS:
            return {"success": False, "message": f"已达到最大席位数 {ROUNDTABLE_MAX_SEATS}"}

        if session.status in (RoundtableStatus.DISCUSSING.value, RoundtableStatus.PAUSED.value):
            # 运行中通过干预队列添加
            await session.intervention_queue.put(
                Intervention(
                    intervention_type="add_seat",
                    seat_config=seat_config,
                )
            )
            return {"success": True, "message": "席位添加请求已提交"}
        else:
            # 非运行状态直接添加
            new_seat = session.add_seat(seat_config)
            session.save()
            await session.emit_event({
                "type": "rt_seat_added",
                "roundtable_id": session_id,
                "seat": new_seat.to_dict(),
            })
            return {"success": True, "message": f"已添加席位 {new_seat.role_name}", "seat": new_seat.to_dict()}

    async def remove_seat(self, session_id: str, seat_id: str) -> dict:
        """动态移除席位"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if len(session.seats) <= 2:
            return {"success": False, "message": "至少需要保留 2 个席位"}

        target = session.get_seat(seat_id)
        if not target:
            return {"success": False, "message": f"未找到席位 {seat_id}"}

        if target.status == RoundtableStatus.SPEAKING.value:
            return {"success": False, "message": f"不能移除正在发言的席位 {target.role_name}"}

        if session.status in (RoundtableStatus.DISCUSSING.value, RoundtableStatus.PAUSED.value):
            # 运行中通过干预队列移除
            await session.intervention_queue.put(
                Intervention(
                    intervention_type="remove_seat",
                    target_seat_id=seat_id,
                )
            )
            return {"success": True, "message": "席位移除请求已提交"}
        else:
            # 非运行状态直接移除
            removed = session.remove_seat(seat_id)
            if removed:
                session.save()
                await session.emit_event({
                    "type": "rt_seat_removed",
                    "roundtable_id": session_id,
                    "seat_id": seat_id,
                    "role_name": removed.role_name,
                })
                return {"success": True, "message": f"已移除席位 {removed.role_name}"}
            return {"success": False, "message": "移除失败"}

    # ============ 删除 ============

    async def delete(self, session_id: str) -> dict:
        """删除圆桌会议"""
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到圆桌会议 {session_id}"}

        if session.status == RoundtableStatus.DISCUSSING.value:
            return {"success": False, "message": "不能删除正在进行的会议，请先终止"}

        # 清理任务
        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.pop(session_id, None)

        # 通知 SSE 订阅者会话已删除
        await session.emit_event({
            "type": "rt_deleted",
            "roundtable_id": session_id,
        })

        # 从内存中移除
        del self.sessions[session_id]

        # 删除持久化记录
        _store.delete(session_id)

        logger.info(f"Roundtable {session_id} 已删除")
        return {"success": True, "message": f"圆桌会议 {session_id} 已删除"}

    # ============ 查询 ============

    def get(self, session_id: str) -> RoundtableSession | None:
        """获取指定的圆桌会议"""
        return self.sessions.get(session_id)

    def list_all(self) -> list[dict]:
        """列出所有圆桌会议的摘要"""
        return [s.get_summary() for s in self.sessions.values()]

    # ============ 持久化加载 ============

    def load_sessions(self) -> None:
        """从 SQLite 加载所有已保存的 roundtable 会话"""
        for data in _store.load_all():
            try:
                if data.get("session_type") != "roundtable":
                    continue
                session = RoundtableSession.from_dict(data)
                # 恢复时，之前 discussing 的视为异常中断
                if session.status == RoundtableStatus.DISCUSSING.value:
                    session.status = RoundtableStatus.ENDED.value
                    session.ended_at = datetime.now(timezone.utc).isoformat()
                    session.save()
                self.sessions[session.session_id] = session
                logger.info(f"已加载 Roundtable: {session.session_id}")
            except Exception as e:
                logger.error(f"加载 roundtable 失败: {e}")

    # ============ 关闭 ============

    async def shutdown(self) -> None:
        """关闭所有运行中的会议并保存状态"""
        for session_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        for session in self.sessions.values():
            if session.status == RoundtableStatus.DISCUSSING.value:
                session.status = RoundtableStatus.ENDED.value
                session.ended_at = datetime.now(timezone.utc).isoformat()
            session.save()

        self._tasks.clear()
        logger.info("RoundtableManager 已关闭，所有会议状态已保存")
