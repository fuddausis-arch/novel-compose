"""OpenAI 兼容客户端：重试/降级/超时。

spec 1.1：不绑死厂商；多模型分层降成本。
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from novel_agent.config import LLMConfig


class LLMError(Exception):
    """LLM 调用失败。"""


class LLMClient:
    """OpenAI 兼容 chat/completions 客户端。"""

    def __init__(self, config: LLMConfig):
        self.config = config

    def _build_payload(self, user_content: str, system: str | None = None) -> dict[str, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        return {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    async def generate(self, user_content: str, system: str | None = None,
                       max_retries: int = 3) -> str:
        """生成文本，超时/网络错误指数退避重试。"""
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(user_content, system)

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
            except httpx.HTTPStatusError as e:
                raise LLMError(f"AI 接口 HTTP 错误: {e.response.text}") from e
            except Exception as e:
                raise LLMError(f"AI 生成出错: {e}") from e

        raise LLMError(f"重试 {max_retries} 次后仍失败: {last_err}")
