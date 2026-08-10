"""子 agent：上下文隔离的迷你研究 agent。

主 agent 通过 delegate_research 工具调用，子 agent 用独立上下文
查多个设定并综合，只把最终摘要返回给主 agent（不污染主 agent 历史）。

设计参考 Claude Code 子 agent：
- 上下文隔离：子 agent 的工具调用不进主 agent 历史，只返回最终摘要
- 父只收子摘要：主 agent 只拿到一段文字，看不到子的推理过程
- 限层防失控：子 agent 工具集只含只读工具，不含 delegate_research，天然不会递归

成本提示（来自 Claude Code 经验）：子 agent 会显著增加 token 消耗，
只在需要查多个对象、避免主上下文被撑爆时才用。
"""
from __future__ import annotations

import json
import logging

from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient
from novel_agent.chat.tools import READONLY_TOOLS_SCHEMA, dispatch_tool
from novel_agent.chat.executor import ActionExecutor
from novel_agent.chat.context_manager import compact_if_needed, truncate_tool_result

logger = logging.getLogger(__name__)


class ResearchSubAgent:
    """迷你研究子 agent：独立上下文 + 只读工具 + 最多 N 轮。

    用非流式 chat（输出不需要流式给用户，只返回摘要给主 agent）。
    """

    MAX_ROUNDS = 4

    SUB_SYSTEM_PROMPT = """你是项目的研究子 agent，负责用工具查资料并综合成简洁摘要。

规则：
- 只能调用查询类工具（查角色/章纲/摘要/伏笔/进度）
- 不要编造，查不到就说查不到
- 用最少的工具调用完成任务，不要重复查同一个
- 最后输出一段中文摘要，直接给上层 agent 使用，不要加“好的”“以下是”等废话"""


    def __init__(self, repo: BibleRepository, llm_client: LLMClient, executor: ActionExecutor):
        self.repo = repo
        self.client = llm_client
        self.executor = executor

    async def run(self, task: str) -> str:
        """执行研究任务，返回摘要文本。"""
        messages: list[dict] = [
            {"role": "system", "content": self.SUB_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        try:
            for _ in range(self.MAX_ROUNDS):
                resp = await self.client.chat(
                    messages, tools=READONLY_TOOLS_SCHEMA, tool_choice="auto"
                )
                content = resp.get("content") or ""
                tool_calls = resp.get("tool_calls")
                if not tool_calls:
                    return content or "（子 agent 无输出）"
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    logger.info("ResearchSubAgent 调用工具 %s(%s)", name, args)
                    dispatched = await dispatch_tool(
                        name, args, self.repo, self.executor, llm_client=None
                    )
                    # 轻微: 子 agent 也截断长工具结果，和主 agent 一致
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": truncate_tool_result(dispatched["result"]),
                    })
                # 工具结果可能很长，压缩上下文避免爆 token
                messages = await compact_if_needed(messages, self.client)
            # 超轮数：让 LLM 不带工具收尾
            messages.append({
                "role": "system",
                "content": "已达工具调用上限，请基于已查到的信息直接输出摘要。",
            })
            resp = await self.client.chat(messages, tools=None)
            return resp.get("content") or "（子 agent 无输出）"
        except Exception as e:
            logger.warning("ResearchSubAgent 失败: %s", e)
            return f"（子 agent 出错: {e}）"
