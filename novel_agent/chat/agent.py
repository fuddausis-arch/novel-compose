"""项目主 Agent：统一对话入口，按对象隔离历史。"""
from __future__ import annotations

import json
import logging
import re

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是本项目的「主 Agent」，用户与系统之间的唯一智能中介。

你的职责：
1. 查项目状态、定位问题、解释决策。
2. 接收用户自然语言指令，转化为结构化动作。
3. 把用户对具体对象的意见落表，供后续生成使用。
4. 回答简洁、准确、以行动为导向。

可用动作（仅在需要时输出 JSON，且只占一行）：
{"type": "rewrite_chapter", "chapter": 3, "feedback": "用户原始意见"}
{"type": "add_chapter_feedback", "chapter": 3, "feedback": "用户原始意见"}
{"type": "generate_outlines", "volume": "第二卷", "chapter_count": 10}
{"type": "query_status"}

规则：
- 如果用户明确说"重写/改写/生成"某章，用 rewrite_chapter。
- 如果只是提意见（如"对话太生硬"），用 add_chapter_feedback 并视情况也 rewrite_chapter。
- 不要编造项目里没有的角色、势力或章节。
- 普通回答不要输出动作 JSON。"""


class ChatAgent:
    """主 Agent 流式回复生成器。"""

    def __init__(self, repo: BibleRepository, cfg: Config):
        self.repo = repo
        self.cfg = cfg
        self.client = LLMClient(cfg.get_agent_llm("orchestrator"))

    async def stream_reply(
        self,
        user_message: str,
        history: list,
        context_text: str,
    ):
        """Async generator yielding dicts: {"type": "text", "content": "..."} or {"type": "action", "action": {...}}."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context_text:
            messages.append({"role": "system", "content": f"【当前上下文】\n{context_text[:2500]}"})
        # 最近 10 轮历史
        for m in history[-20:]:
            role = m.role if m.role in ("user", "assistant", "system") else "user"
            messages.append({"role": role, "content": m.content})
        messages.append({"role": "user", "content": user_message})

        prompt_text = self._messages_to_prompt(messages)
        try:
            raw = await self.client.generate(prompt_text, system=None, max_tokens=2048, temperature=0.7)
        except Exception as e:
            logger.warning("ChatAgent LLM 失败: %s", e)
            yield {"type": "text", "content": f"AI 调用失败：{e}"}
            return
        finally:
            await self.client.close()

        text_part, actions = self._parse_actions(raw)
        # 按句子/短句分块推送，模拟流式
        chunks = re.split(r"(?<=[。！？\n])", text_part)
        for chunk in chunks:
            chunk = chunk.strip()
            if chunk:
                yield {"type": "text", "content": chunk}
        for action in actions:
            yield {"type": "action", "action": action}

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                parts.append(f"[系统]\n{content}")
            elif role == "assistant":
                parts.append(f"[AI]\n{content}")
            else:
                parts.append(f"[用户]\n{content}")
        return "\n\n".join(parts) + "\n\n[AI]\n"

    @staticmethod
    def _parse_actions(text: str) -> tuple[str, list[dict]]:
        """从回复中提取动作 JSON，返回（纯文本，动作列表）。"""
        actions = []
        pattern = re.compile(r"\{\"type\"\s*:\s*\"[^\"]+\".*?\}")
        for match in pattern.finditer(text):
            try:
                action = json.loads(match.group())
                if action.get("type"):
                    actions.append(action)
            except Exception:
                continue
        # 移除原文中的动作 JSON 行
        cleaned = pattern.sub("", text).strip()
        return cleaned, actions
