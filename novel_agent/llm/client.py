"""OpenAI 兼容客户端：重试/降级/超时。

spec 1.1：不绑死厂商；多模型分层降成本。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import httpx

from novel_agent.config import LLMConfig
from novel_agent.utils.token_usage import ledger as _token_ledger

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败。"""


class LLMClient:
    """OpenAI 兼容 chat/completions 客户端。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    @staticmethod
    def _is_deepseek(model: str) -> bool:
        return "deepseek" in model.lower()

    def _apply_thinking_params(self, payload: dict[str, Any], enable_thinking: bool = True) -> dict[str, Any]:
        """仅对 DeepSeek 模型开启思考模式 + reasoning_effort=max。

        非 DeepSeek 模型保留用户配置的采样参数（temperature/top_p 等），
        不注入 thinking/reasoning_effort（避免 API 报错或被忽略）。

        enable_thinking=False 时关闭思考模式（用于审校等结构化输出场景）。
        """
        if not self._is_deepseek(self.config.model):
            return payload  # 非 DeepSeek：保留采样参数，不注入思考模式
        if enable_thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max"
            # DeepSeek 思考模式下采样参数不生效，不传
            payload.pop("temperature", None)
            payload.pop("top_p", None)
            payload.pop("frequency_penalty", None)
            payload.pop("presence_penalty", None)
        else:
            payload["thinking"] = {"type": "disabled"}
        return payload

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建持久 httpx 连接，复用 TCP 连接池。

        用 asyncio.Lock 防止多协程首次并发调用时重复创建 AsyncClient 导致连接池泄漏。
        """
        if self._client is not None and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            # 双重检查：等待锁期间可能已被其他协程创建
            if self._client is not None and not self._client.is_closed:
                return self._client
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=self.config.timeout,
                    write=30.0,
                    pool=10.0,
                ),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self):
        """关闭底层 httpx 连接池。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_payload(self, user_content: str, system: str | None = None,
                       images: list[str] | None = None,
                       max_tokens: int | None = None,
                       temperature: float | None = None) -> dict[str, Any]:
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
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "frequency_penalty": self.config.frequency_penalty,
            "presence_penalty": self.config.presence_penalty,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        return payload

    async def generate(self, user_content: str, system: str | None = None,
                       max_retries: int = 3, images: list[str] | None = None,
                       max_tokens: int | None = None,
                       temperature: float | None = None,
                       thinking: bool = True,
                       node_name: str = "default") -> str:
        """生成文本。支持传入图片 URL/base64 data URL 列表进行多模态生成。
        超时/网络错误/429/503 指数退避重试；401/403 等直接报错。
        max_tokens 可覆盖 config 默认值（用于解析长文档等需要更大输出的场景）。
        temperature 可覆盖 config 默认值（用于按任务类型动态调整创意度）。
        thinking=False 关闭 DeepSeek 思考模式（用于审校等结构化输出场景）。
        node_name 标记调用来源节点，用于 token 账本按节点统计。
        """
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(user_content, system, images=images,
                                     max_tokens=max_tokens,
                                     temperature=temperature)
        self._apply_thinking_params(payload, enable_thinking=thinking)

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                # 检查响应体是否包含 choices（方舟可能返回 200 + 错误 JSON）
                if "choices" not in data or not data["choices"]:
                    body = resp.text
                    body_lower = body.lower()
                    quota_keywords = ["quota", "exceeded", "limit reached",
                                      "insufficient", "余额不足", "配额", "rate limit"]
                    if any(kw in body_lower or kw in body for kw in quota_keywords):
                        raise LLMError(self._quota_msg(body))
                    raise LLMError(f"AI 接口返回异常（无 choices 字段）: {body[:300]}")
                choice = data["choices"][0]
                content = choice.get("message", {}).get("content", "")
                finish_reason = choice.get("finish_reason", "")
                # 检测空响应：部分模型偶尔返回空 content
                if not content or not content.strip():
                    usage = data.get("usage", {})
                    logger.warning(
                        "LLM 返回空内容 (finish_reason=%s, usage=%s, model=%s, prompt_len≈%d)",
                        finish_reason, usage, self.config.model, len(user_content),
                    )
                    # content_filter 触发：不重试，直接报错
                    if finish_reason == "content_filter":
                        raise LLMError(
                            "AI 内容审核拦截（content_filter），请修改提示词后重试。"
                        )
                    # 其他原因的空响应：重试
                    if attempt < max_retries - 1:
                        logger.warning("LLM 空响应，重试 (尝试%d/%d)", attempt + 1, max_retries)
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise LLMError(
                        f"AI 返回空内容（finish_reason={finish_reason}），"
                        f"可能是模型 {self.config.model} 无法处理该请求，请重试或更换模型。"
                    )
                # 记录 token 用量到全局账本（如果 API 返回了 usage）
                self._record_usage(data.get("usage"), node_name, finish_reason)
                return content
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                logger.warning("LLM 请求超时/网络错误(尝试%d/%d): %s: %s", attempt+1, max_retries, type(e).__name__, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                body = e.response.text
                body_lower = body.lower()
                # 配额超限检测（适配多平台）：仅语义明确为配额耗尽（不含 rate-limit 语义）才不重试
                quota_keywords = ["quota", "insufficient", "余额不足", "配额", "account quota"]
                rate_limit_keywords = ["rate limit", "ratelimit", "too many requests", "throttl"]
                is_quota = (
                    any(kw in body_lower for kw in quota_keywords)
                    and not any(rk in body_lower for rk in rate_limit_keywords)
                )
                if is_quota:
                    raise LLMError(self._quota_msg(body)) from e
                # 429 限流 / 503 服务不可用：可重试
                if code in (429, 503) and attempt < max_retries - 1:
                    last_err = e
                    logger.warning("LLM 限流/不可用 HTTP %d(尝试%d/%d): %s", code, attempt+1, max_retries, body[:200])
                    await asyncio.sleep(min(2 ** (attempt + 2), 8))  # 最多8秒，配合SSE心跳
                    continue
                # 401/403 鉴权错误：不重试
                if code in (401, 403):
                    raise LLMError(f"鉴权失败({code})：请检查 config.yaml 的 api_key") from e
                # 其他 HTTP 错误：不重试
                raise LLMError(f"AI 接口 HTTP {code}: {body[:300]}") from e
            except LLMError:
                raise
            except Exception as e:
                logger.warning("LLM 生成异常(尝试%d/%d): %s: %s", attempt+1, max_retries, type(e).__name__, e)
                raise LLMError(f"AI 生成出错: {e}") from e

        raise LLMError(f"重试 {max_retries} 次后仍失败: {type(last_err).__name__ if last_err else 'Unknown'}: {last_err}")

    async def chat(self, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]] | None = None,
                   tool_choice: str | dict[str, Any] = "auto",
                   max_tokens: int | None = None,
                   temperature: float | None = None,
                   max_retries: int = 3) -> dict[str, Any]:
        """OpenAI 兼容 chat/completions，支持 function calling。

        与 generate 不同：接收完整 messages 数组（可含历史/工具消息），
        返回完整 assistant message（含 content 和 tool_calls）。

        Returns:
            {"content": str, "tool_calls": list[dict] | None, "finish_reason": str, "usage": dict}
        """
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "frequency_penalty": self.config.frequency_penalty,
            "presence_penalty": self.config.presence_penalty,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        self._apply_thinking_params(payload)

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if "choices" not in data or not data["choices"]:
                    body = resp.text
                    body_lower = body.lower()
                    quota_keywords = ["quota", "exceeded", "limit reached",
                                      "insufficient", "余额不足", "配额", "rate limit"]
                    if any(kw in body_lower or kw in body for kw in quota_keywords):
                        raise LLMError(self._quota_msg(body))
                    raise LLMError(f"AI 接口返回异常（无 choices 字段）: {body[:300]}")
                choice = data["choices"][0]
                message = choice.get("message", {})
                content = message.get("content") or ""
                tool_calls = message.get("tool_calls")
                finish_reason = choice.get("finish_reason", "")
                # tool_calls 模式下 content 可能为空，这是正常的，不重试
                if not content and not tool_calls:
                    if finish_reason == "content_filter":
                        raise LLMError("AI 内容审核拦截（content_filter），请修改提示词后重试。")
                    if attempt < max_retries - 1:
                        logger.warning("chat 空响应，重试 (尝试%d/%d)", attempt + 1, max_retries)
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise LLMError(f"AI 返回空内容（finish_reason={finish_reason}）")
                return {
                    "content": content,
                    "tool_calls": tool_calls,
                    "finish_reason": finish_reason,
                    "usage": data.get("usage", {}),
                }
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                logger.warning("chat 请求超时/网络错误(尝试%d/%d): %s: %s", attempt + 1, max_retries, type(e).__name__, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                body = e.response.text
                body_lower = body.lower()
                # 配额超限检测（适配多平台）：仅语义明确为配额耗尽（不含 rate-limit 语义）才不重试
                quota_keywords = ["quota", "insufficient", "余额不足", "配额", "account quota"]
                rate_limit_keywords = ["rate limit", "ratelimit", "too many requests", "throttl"]
                is_quota = (
                    any(kw in body_lower for kw in quota_keywords)
                    and not any(rk in body_lower for rk in rate_limit_keywords)
                )
                if is_quota:
                    raise LLMError(self._quota_msg(body)) from e
                if code in (429, 503) and attempt < max_retries - 1:
                    last_err = e
                    logger.warning("chat 限流/不可用 HTTP %d(尝试%d/%d): %s", code, attempt + 1, max_retries, body[:200])
                    await asyncio.sleep(min(2 ** (attempt + 2), 8))
                    continue
                if code in (401, 403):
                    raise LLMError(f"鉴权失败({code})：请检查 config.yaml 的 api_key") from e
                raise LLMError(f"AI 接口 HTTP {code}: {body[:300]}") from e
            except LLMError:
                raise
            except Exception as e:
                logger.warning("chat 生成异常(尝试%d/%d): %s: %s", attempt + 1, max_retries, type(e).__name__, e)
                raise LLMError(f"AI 生成出错: {e}") from e

        raise LLMError(f"重试 {max_retries} 次后仍失败: {type(last_err).__name__ if last_err else 'Unknown'}: {last_err}")

    async def chat_stream(self, messages: list[dict[str, Any]],
                          tools: list[dict[str, Any]] | None = None,
                          tool_choice: str | dict[str, Any] = "auto",
                          max_tokens: int | None = None,
                          temperature: float | None = None,
                          cancel_event: asyncio.Event | None = None,
                          node_name: str = "default") -> AsyncGenerator[dict[str, Any], None]:
        """流式 chat/completions，支持 function calling。边收边 yield。

        yield 事件：
        - {"type": "text_delta", "content": "..."}  文本增量（实时推送）
        - {"type": "tool_calls", "tool_calls": [...]}  完整工具调用（流结束后一次给出）
        - {"type": "done", "finish_reason": "..."}  结束标记

        tool_calls 增量按 index 累积拼接，流结束后一次性产出。
        不做重试（流式重试复杂），出错直接 raise。
        node_name 标记调用来源节点，用于 token 账本按节点统计。
        """
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "frequency_penalty": self.config.frequency_penalty,
            "presence_penalty": self.config.presence_penalty,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        self._apply_thinking_params(payload)

        accumulated: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        stream_started = False  # 是否已开始接收数据（用于决定是否重试）
        stream_usage: dict[str, Any] | None = None  # 流式 usage（部分 API 在末尾 chunk 返回）

        client = await self._get_client()
        for attempt in range(3):
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        stream_started = True  # 已开始接收数据
                        if cancel_event is not None and cancel_event.is_set():
                            logger.info("chat_stream 检测到取消令牌，提前终止流式")
                            yield {"type": "done", "finish_reason": "cancelled"}
                            return
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        # 捕获流式 usage（部分 API 在最后一个 chunk 返回，choices 可能为空）
                        chunk_usage = chunk.get("usage")
                        if chunk_usage:
                            stream_usage = chunk_usage
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        # 思考链增量（DeepSeek 思考模式）：yield 给上层展示/回传
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            yield {"type": "reasoning_delta", "content": reasoning}
                        # 文本增量：实时 yield
                        content = delta.get("content")
                        if content:
                            yield {"type": "text_delta", "content": content}
                        # 工具调用增量：按 index 累积拼接
                        tcs = delta.get("tool_calls")
                        if tcs:
                            for tc in tcs:
                                if not isinstance(tc, dict):
                                    continue
                                idx = tc.get("index", 0)
                                if idx not in accumulated:
                                    accumulated[idx] = {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                if tc.get("id"):
                                    accumulated[idx]["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    accumulated[idx]["function"]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    accumulated[idx]["function"]["arguments"] += fn["arguments"]
                        fr = choices[0].get("finish_reason")
                        if fr:
                            finish_reason = fr
                break  # 成功完成，退出重试循环
            except asyncio.CancelledError:
                logger.info("chat_stream 被取消，已关闭流式连接")
                raise
            except httpx.HTTPStatusError as e:
                if stream_started or attempt >= 2:
                    body = e.response.text if e.response else ""
                    raise LLMError(f"AI 流式接口 HTTP {e.response.status_code}: {body[:300]}") from e
                logger.warning("chat_stream 连接失败 (attempt %d)，%d秒后重试", attempt + 1, 2 ** attempt)
                await asyncio.sleep(2 ** attempt)
                stream_started = False
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if stream_started or attempt >= 2:
                    raise LLMError(f"AI 流式请求网络错误: {type(e).__name__}: {e}") from e
                logger.warning("chat_stream 网络错误 (attempt %d)：%s，%d秒后重试", attempt + 1, e, 2 ** attempt)
                await asyncio.sleep(2 ** attempt)
                stream_started = False

        if accumulated:
            tool_calls_list = [accumulated[i] for i in sorted(accumulated)]
            yield {"type": "tool_calls", "tool_calls": tool_calls_list}
        # 流结束后记录 token 用量到全局账本
        self._record_usage(stream_usage, node_name, finish_reason)
        yield {"type": "done", "finish_reason": finish_reason}

    async def stream_generate(self, user_content: str, system: str | None = None,
                              max_tokens: int | None = None,
                              temperature: float | None = None) -> AsyncGenerator[str, None]:
        """流式生成文本。逐 token yield content delta。

        使用 OpenAI 兼容的 SSE 流式接口（stream=true）。
        不做重试（流式重试复杂），出错直接 raise。
        """
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(user_content, system, images=None,
                                     max_tokens=max_tokens,
                                     temperature=temperature)
        payload["stream"] = True

        client = await self._get_client()
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response else ""
            raise LLMError(f"AI 流式接口 HTTP {e.response.status_code}: {body[:300]}") from e
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise LLMError(f"AI 流式请求网络错误: {type(e).__name__}: {e}") from e

    def _record_usage(self, usage: dict[str, Any] | None, node_name: str, finish_reason: str = "") -> None:
        """从 API 响应的 usage 字段记录 token 用量到全局账本。

        兼容 OpenAI / DeepSeek 格式：
        - prompt_tokens / completion_tokens 为标准字段
        - DeepSeek 思考模式的 reasoning_tokens 在 completion_tokens_details 下
        - prompt 缓存命中在 prompt_tokens_details.cached_tokens（DeepSeek/OpenAI）
        - finish_reason 用于统计截断率（length = 输出被 max_tokens 截断）
        缺失字段记 0，不阻塞主流程。
        """
        if not usage or not isinstance(usage, dict):
            return
        try:
            input_tokens = int(usage.get("prompt_tokens", 0) or 0)
            output_tokens = int(usage.get("completion_tokens", 0) or 0)
            # DeepSeek 把推理 token 放在 completion_tokens_details.reasoning_tokens
            details = usage.get("completion_tokens_details") or {}
            reasoning_tokens = int(details.get("reasoning_tokens", 0) or 0)
            # prompt 缓存命中：OpenAI/DeepSeek 都在 prompt_tokens_details.cached_tokens
            pdetails = usage.get("prompt_tokens_details") or {}
            cache_hit = int(pdetails.get("cached_tokens", 0) or 0)
            if input_tokens or output_tokens:
                _token_ledger.record(
                    node_name=node_name,
                    model=self.config.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reasoning_tokens=reasoning_tokens,
                    finish_reason=finish_reason,
                    cache_hit_tokens=cache_hit,
                )
        except (TypeError, ValueError) as e:
            logger.debug("记录 token usage 失败（忽略）: %s", e)

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
