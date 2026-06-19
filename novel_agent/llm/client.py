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

    def _build_payload(self, user_content: str, system: str | None = None,
                       images: list[str] | None = None) -> dict[str, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        content: Any = user_content
        if images:
            content = [{"type": "text", "text": user_content}]
            for img_url in images:
                content.append({"type": "image_url", "image_url": {"url": img_url}})

        messages.append({"role": "user", "content": content})
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        return payload

    async def generate(self, user_content: str, system: str | None = None,
                       max_retries: int = 3, images: list[str] | None = None) -> str:
        """生成文本。支持传入图片 URL/base64 data URL 列表进行多模态生成。

        超时/网络错误/429/503 指数退避重试；401/403 等直接报错。
        """
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(user_content, system, images=images)

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
                    await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                body = e.response.text
                # 429 限流 / 503 服务不可用：可重试（退避更久）
                if code in (429, 503) and attempt < max_retries - 1:
                    # 配额超限通常需等很久，重试意义不大，直接友好报错
                    if "quota" in body.lower() or "AccountQuotaExceeded" in body:
                        raise LLMError(self._quota_msg(body)) from e
                    last_err = e
                    await asyncio.sleep(2 ** (attempt + 2))  # 4/8/16 秒
                    continue
                # 401/403 鉴权错误：不重试
                if code in (401, 403):
                    raise LLMError(f"鉴权失败({code})：请检查 config.yaml 的 api_key") from e
                # 其他 HTTP 错误：不重试
                raise LLMError(f"AI 接口 HTTP {code}: {body[:300]}") from e
            except Exception as e:
                raise LLMError(f"AI 生成出错: {e}") from e

        raise LLMError(f"重试 {max_retries} 次后仍失败: {last_err}")

    @staticmethod
    def _quota_msg(body: str) -> str:
        """从 429 响应体提取配额重置时间，给友好提示。"""
        import re
        msg = "LLM 配额超限"
        # 尝试提取重置时间
        m = re.search(r"reset at ([\d\-: +]+)", body)
        if m:
            msg += f"，将于 {m.group(1)} 重置"
        msg += "。请等待重置或更换 LLM 配置。"
        return msg
