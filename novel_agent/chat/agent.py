"""项目主 Agent：基于 tool-calling 的 ReAct 循环（真流式 + 压缩 + 并发 + 子 agent + steer）。

设计参考（照搬 Codex 开源源码架构，Apache-2.0）：
- session/mod.rs submission_loop：Op 分发（由 Session 调用本 agent）
- session/input_queue.rs Steer：工具间隙注入用户补充输入（steer_callback）
- client.rs CancellationToken：cancel_event 显式取消
- codex_delegate.rs：子 agent 上下文隔离
- Claude Code（学设计）：5 级渐进压缩（简化为 L1 截断 + L2 摘要）、per-call 并发安全

写审分离铁律仍保留：禁止在聊天里直接生成章节正文，正文必须走后端 graph 流水线。
"""
from __future__ import annotations

import asyncio
import json
import logging

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.chat.executor import ActionExecutor
from novel_agent.chat.tools import TOOLS_SCHEMA, dispatch_tool, READONLY_TOOL_NAMES as READONLY_TOOLS
from novel_agent.chat.context_manager import truncate_tool_result, compact_if_needed
from novel_agent.chat.context_window import context_window_status

logger = logging.getLogger(__name__)

# 只读工具集合从 tools.py 统一导入（READONLY_TOOL_NAMES），消除重复定义


SYSTEM_PROMPT = """你是本项目的「主 Agent」，用户与系统之间的唯一智能中介。

你的职责：
1. 查项目状态、定位问题、解释决策。
2. 接收用户自然语言指令，转化为结构化动作。
3. 把用户对具体对象的意见落表，供后续生成使用。
4. 回答简洁、准确、以行动为导向。

【铁律：禁止在聊天里直接生成章节正文】
正文必须由后端 graph 流水线生成（含 audit/人审/字数控制）。
用户说“重写/改写/生成某章”时，你必须调用 rewrite_chapter 工具，由后端启动重写流程。
如果你直接写正文，会绕过字数控制和人审环节，这是严重错误。
讨论重写方案（如“应该砍掉铺垫”“放大对峙”）是允许的，但一旦用户确认要执行，必须调用 rewrite_chapter 工具。

你有工具可用：
- 查询类：get_character / list_characters（分页 limit/offset）/ get_outline / list_chapter_summaries（分页）/ list_foreshadows / query_status / list_factions（势力）/ search（跨对象全文检索）/ get_character_appearances（查角色出场章节）/ read_reference_files（读取项目参考文件/设定总纲，可传 keyword 过滤）
- 质量检查类：check_red_line（检查红线违规）/ check_ai_style（检测AI味浓度）/ check_excitement（检测爽点密度）
- 动作类：rewrite_chapter（启动重写）/ add_chapter_feedback（给某章追加意见，不重写）
- 写库类：create_character / update_character / create_outline / update_outline（用 chapter 定位）/ create_foreshadow / update_foreshadow / update_foreshadow_status（pending->planted->developing->resolved/abandoned）/ create_world_setting / create_faction / update_faction（势力，用 faction_id 或 name 定位）
- 交互类：present_options（【必须用此工具提问】当你想问用户问题、给方向让用户选时，必须调用此工具弹出选项按钮。【绝对禁止】在文本里直接提问或写"请选择A或B"。调用后不要继续生成文本，等用户点击）
- 委托类：delegate_research（委托子 agent 做深度研究，查多个设定并综合，避免主对话被工具调用撑爆；只用于复杂核对场景）
- Skill 管理类：list_skills（列出所有技能）/ get_skill（看某技能内容）/ create_skill（创建技能，用户要求"做一个 skill 帮助写XXX文"时调用，name 用 kebab-case，content 填完整写作方法）/ update_skill / delete_skill / search_skills（跨技能搜索）
- 记忆类：read_chapter_file（读某章正文）/ list_chapter_files（列出已写章节）/ memory_search（向量语义检索已写章节与设定，按主题找回相关内容）
- 网络类：web_fetch（抓取指定 URL 网页正文，用于获取参考资料）
- 文件/命令类：read_file / write_to_file / replace_in_file / apply_diff（读写编辑项目文件，路径相对工作区，沙箱保护）/ search_files（按内容正则搜索）/ search_file（按文件名 glob 搜索）/ list_files（列目录）/ list_code_definitions（列代码定义）/ execute_command（执行终端命令，高风险命令需审批，慎用）/ ask_user（向用户提问）

规则：
- 不确定的事实，先调用查询工具核对，不要凭空编造角色、势力或章节。
- 章节号一律用阿拉伯数字。
- 用户只是提意见（如“对话太生硬”）且没要求重写，用 add_chapter_feedback。
- 用户提意见并要求重写，先 add_chapter_feedback 落意见，再 rewrite_chapter 启动重写。
- 普通问答/解释/讨论方案时，不要调用工具，直接回答。
- 工具调用要有的放矢，不要重复调用同一个工具。
- 需要查多个对象且会撑爆对话时，用 delegate_research 委托子 agent，不要自己连续调十几次查询工具。
- execute_command 会执行真实命令，除非用户明确要求否则不要调用；写文件用 write_to_file/replace_in_file 即可。
- 如果收到【用户补充】标记的消息，那是用户在你工作时的补充指示，请纳入当前任务的考虑。"""


class ChatAgent:
    """主 Agent：基于 tool-calling 的 ReAct 循环（真流式 + 压缩 + 并发 + 子 agent + steer）。

    被 Session 调用（照搬 Codex Session -> turn loop）。
    文本增量实时 yield；工具调用在文本流结束后执行，结果喂回 LLM 继续下一轮。
    支持 steer（工具间隙注入用户输入，照搬 Codex InputQueue.Steer）+
    cancel_event（显式取消，照搬 Codex CancellationToken）。
    """

    MAX_TOOL_ROUNDS = 4  # 最多工具往返次数，防失控（从6降到4，减少重复输出）

    def __init__(self, repo: BibleRepository, cfg: Config, executor: ActionExecutor | None = None, llm_client: LLMClient | None = None):
        self.repo = repo
        self.cfg = cfg
        self.client = llm_client or LLMClient(cfg.get_agent_llm("orchestrator"))
        self.executor = executor or ActionExecutor(repo, cfg)
        # 显式取消令牌（对齐项目 runner.py 的 _cancel_tokens 模式 + Codex CancellationToken）
        self._cancel_event = asyncio.Event()

    def cancel(self):
        """请求取消当前生成。chat_stream 会在下一个 chunk 检查点退出。"""
        self._cancel_event.set()
        logger.info("ChatAgent 收到取消请求")

    async def stream_reply(
        self,
        user_message: str,
        history: list,
        context_text: str,
        cancel_event: asyncio.Event | None = None,
        steer_callback=None,
    ):
        """Async generator yielding dicts:
        {"type": "text", "content": "..."}（文本增量，实时）
        {"type": "action", "action": {...}}（动作事件，工具执行后）

        cancel_event: 外部取消令牌（Session 传入，照搬 Codex CancellationToken）。
                      None 时用 self._cancel_event（向后兼容直接调用）。
        steer_callback: 照搬 Codex InputQueue.Steer--返回待注入的用户补充输入列表，
                        在工具调用间隙注入 messages，不中断生成。
        """
        ce = cancel_event or self._cancel_event
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context_text:
            messages.append({"role": "system", "content": f"【当前上下文】\n{context_text}"})
        # 最近历史
        for m in history[-20:]:
            role = m.role if m.role in ("user", "assistant", "system") else "user"
            messages.append({"role": role, "content": m.content})
        messages.append({"role": "user", "content": user_message})

        try:
            prev_content = ""  # 上一轮的文本，用于重复检测
            loop_cancel = asyncio.Event()  # 轮内局部中断标记（不要设置会话级 ce，否则后续所有轮次都会误判"已取消"）
            for _ in range(self.MAX_TOOL_ROUNDS):
                if ce.is_set():
                    yield {"type": "text", "content": "（已取消）"}
                    return
                if loop_cancel.is_set():
                    break
                # 照搬 Codex steer：工具间隙检查用户补充输入，有则注入
                if steer_callback:
                    for s in steer_callback():
                        messages.append({"role": "user", "content": f"【用户补充】{s}"})
                        logger.info("steer 注入: %s", s[:50])
                accumulated_content = ""
                accumulated_reasoning = ""  # DeepSeek 思考链内容，工具调用时必须回传
                tool_calls = None
                # 真流式：边收文本边推送，工具调用增量累积
                async for event in self.client.chat_stream(
                    messages, tools=TOOLS_SCHEMA, tool_choice="auto",
                    cancel_event=loop_cancel,
                ):
                    etype = event["type"]
                    if etype == "reasoning_delta":
                        accumulated_reasoning += event["content"]
                        # 推送思考链给前端展示（像 Trae/Codex 那样）
                        yield {"type": "reasoning", "content": event["content"]}
                    elif etype == "text_delta":
                        accumulated_content += event["content"]
                        # 单轮内重复检测：如果最新 15 字在累积文本中出现超过 3 次，LLM 陷入循环，中断
                        if len(accumulated_content) >= 30:
                            tail = accumulated_content[-15:]
                            if accumulated_content.count(tail) > 3:
                                logger.warning("检测到单轮内重复循环（'%s' 出现 >3 次），中断 LLM", tail[:30])
                                yield {"type": "text", "content": "\n\n（检测到输出循环，已自动中断）"}
                                loop_cancel.set()  # 只中断本轮，不影响会话后续轮次
                                break
                        # 跨轮重复检测：如果本轮最新 20 字在上一轮文本中出现过，跳过推送
                        if prev_content and len(accumulated_content) >= 20:
                            tail = accumulated_content[-20:]
                            if tail in prev_content:
                                continue  # 跳过重复文本的推送
                        yield {"type": "text", "content": event["content"]}
                    elif etype == "tool_calls":
                        tool_calls = event["tool_calls"]
                    elif etype == "done":
                        pass

                # 没有 tool_calls：最终回复已流式推完，结束
                if not tool_calls:
                    # Bug 9: 如果是取消导致的提前结束，补提示
                    if ce.is_set():
                        yield {"type": "text", "content": "（已取消）"}
                    return

                # 有 tool_calls：先把 assistant 消息（含 tool_calls + reasoning_content）入历史
                # DeepSeek 思考模式：工具调用轮次的 reasoning_content 必须回传，否则 API 400
                assistant_msg = {
                    "role": "assistant",
                    "content": accumulated_content,
                    "tool_calls": tool_calls,
                }
                if accumulated_reasoning:
                    assistant_msg["reasoning_content"] = accumulated_reasoning
                messages.append(assistant_msg)

                # 重复检测：如果本轮文本与上一轮高度相似，注入提示或提前终止
                if prev_content and accumulated_content:
                    # 检测重复程度：本轮文本的末尾 20 字是否在上一轮中出现过
                    is_duplicate = len(accumulated_content) >= 20 and accumulated_content[-20:] in prev_content
                    if is_duplicate:
                        repeat_count = getattr(self, "_repeat_count", 0) + 1
                        self._repeat_count = repeat_count
                        if repeat_count >= 2:
                            # 连续 2 轮重复，提前终止
                            logger.warning("检测到连续 %d 轮重复输出，提前终止工具循环", repeat_count)
                            yield {"type": "text", "content": "\n\n（检测到重复输出，已自动停止）"}
                            return
                        # 注入提示，让 LLM 不要重复
                        messages.append({
                            "role": "system",
                            "content": "你刚才输出的文本与上一轮重复。请不要重复相同的文字，直接调用工具或给出新内容。"
                        })
                    else:
                        self._repeat_count = 0
                prev_content = accumulated_content  # 记录本轮文本，供下轮重复检测

                # 工具执行：全部只读则并发，否则串行（保动作类顺序与安全）
                dispatched_list = await self._execute_tool_calls(tool_calls)
                for tc, dispatched in zip(tool_calls, dispatched_list):
                    if not isinstance(dispatched, dict):
                        messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                         "content": "工具执行异常（返回格式错误）"})
                        continue
                    # 动作类：给前端推 action 事件（已含 status/result）
                    if dispatched.get("action"):
                        yield {"type": "action", "action": dispatched["action"]}
                    # 工具结果喂回 LLM（超长截断）
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": truncate_tool_result(dispatched["result"]),
                    })

                # present_options 是终止性工具：调用后直接结束，等用户点击选项
                if any(isinstance(d, dict) and (d.get("action") or {}).get("type") == "present_options" for d in dispatched_list):
                    return

                # 上下文监控 + 压缩（照搬 Codex context_window.rs + auto_compact）
                cw = context_window_status(messages)
                if cw.limit_reached:
                    logger.info("上下文达限 %d/%d 字符，触发压缩",
                                cw.active_chars, cw.auto_compact_limit)
                messages = await compact_if_needed(messages, self.client)
                # 继续循环，让 LLM 看到工具结果后决定下一步

            # 超过最大轮数仍未结束：让 LLM 不带工具收尾
            messages.append({
                "role": "system",
                "content": "已达到工具调用上限，请基于已有信息直接回答用户，不要再调用工具。",
            })
            async for event in self.client.chat_stream(messages, tools=None, cancel_event=ce):
                if event["type"] == "text_delta":
                    yield {"type": "text", "content": event["content"]}
        except Exception as e:
            logger.warning("ChatAgent 失败: %s", e, exc_info=True)
            yield {"type": "text", "content": f"AI 调用失败：{e}"}

    async def _execute_tool_calls(self, tool_calls: list[dict]) -> list[dict]:
        """执行工具调用列表。全部只读则并发，否则串行。

        返回与 tool_calls 同序的 dispatched 结果列表。
        并发只用于只读工具（无副作用）；动作类和委托类必须串行避免状态竞争/递归。
        注意：delegate_research 不是只读工具，会走串行分支。
        """
        # 防御：过滤掉 None 或格式错误的 tool_call（某些模型返回的 tool_calls 可能含空元素）
        tool_calls = [tc for tc in tool_calls if isinstance(tc, dict) and isinstance(tc.get("function"), dict)]
        if not tool_calls:
            return []

        async def run_one(tc: dict) -> dict:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            logger.info("ChatAgent 调用工具 %s(%s)", name, args)
            try:
                return await dispatch_tool(
                    name, args, self.repo, self.executor, llm_client=self.client
                )
            except Exception as e:
                logger.warning("工具 %s 执行异常: %s", name, e, exc_info=True)
                return {"result": f"工具执行异常: {e}", "action": None}

        names = [tc.get("function", {}).get("name", "") for tc in tool_calls]
        all_readonly = all(n in READONLY_TOOLS for n in names)

        if all_readonly and len(tool_calls) > 1:
            logger.info("并发执行 %d 个只读工具: %s", len(tool_calls), names)
            results = await asyncio.gather(*(run_one(tc) for tc in tool_calls), return_exceptions=True)
            return [r if isinstance(r, dict) else {"result": f"工具异常: {r}", "action": None} for r in results]
        # 串行（含动作类/委托类/单个调用）
        return [await run_one(tc) for tc in tool_calls]

    async def close(self):
        """关闭 LLM 客户端连接池。"""
        await self.client.close()
