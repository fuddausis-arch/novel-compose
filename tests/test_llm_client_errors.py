"""测试 LLM 客户端的 429/配额/401 处理（M4 真实验证后新增）。"""
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from novel_agent.config import LLMConfig
from novel_agent.llm.client import LLMClient, LLMError


@pytest.fixture
def client():
    return LLMClient(LLMConfig(
        base_url="https://api.test.com/v1", api_key="sk-test",
        model="test-model", temperature=0.7, max_tokens=1000,
    ))


def _httpx_error(status_code: int, body: str) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.test.com/v1/chat/completions")
    resp = httpx.Response(status_code, request=req, text=body)
    return httpx.HTTPStatusError(f"{status_code}", request=req, response=resp)


@pytest.mark.asyncio
async def test_429_quota_exceeded_no_retry(client):
    """配额超限的 429 直接报错不重试，消息含重置时间。"""
    body = '{"error":{"code":"AccountQuotaExceeded","message":"quota exceeded. reset at 2026-06-18 15:02:18"}}'
    err = _httpx_error(429, body)
    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=err)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(LLMError) as exc:
            await client.generate("x", max_retries=3)
    assert "配额" in str(exc.value) or "quota" in str(exc.value).lower()
    assert "2026-06-18" in str(exc.value)


@pytest.mark.asyncio
async def test_401_auth_error_no_retry(client):
    """401 鉴权失败直接报错，提示检查 key。"""
    err = _httpx_error(401, '{"error":"invalid api key"}')
    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=err)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(LLMError) as exc:
            await client.generate("x")
    assert "鉴权" in str(exc.value) or "api_key" in str(exc.value)


@pytest.mark.asyncio
async def test_429_rate_limit_retries_then_success(client):
    """普通限流 429（非配额超限）应重试后成功。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    rate_err = _httpx_error(429, "too many requests, try later")
    calls = []

    async def side_effect(*a, **kw):
        calls.append(1)
        if len(calls) < 2:
            raise rate_err
        return mock_resp

    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient, \
         patch("novel_agent.llm.client.asyncio.sleep", new=AsyncMock()):
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=side_effect)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        result = await client.generate("x", max_retries=3)
    assert result == "ok"
    assert len(calls) == 2
