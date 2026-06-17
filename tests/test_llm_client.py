"""测试 LLM 客户端：用 mock httpx 验证调用逻辑。"""
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


def test_build_request_payload(client):
    payload = client._build_payload("你好", system="你是助手")
    assert payload["model"] == "test-model"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "你是助手"
    assert payload["messages"][1]["content"] == "你好"
    assert payload["temperature"] == 0.7


@pytest.mark.asyncio
async def test_generate_success(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "生成结果"}}]
    }
    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        result = await client.generate("你好")
    assert result == "生成结果"


@pytest.mark.asyncio
async def test_generate_retries_on_timeout(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "成功"}}]
    }
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.TimeoutException("timeout")
        return mock_resp

    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=side_effect)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        result = await client.generate("你好", max_retries=3)
    assert result == "成功"
    assert call_count == 2


@pytest.mark.asyncio
async def test_generate_raises_after_max_retries(client):
    with patch("novel_agent.llm.client.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(LLMError):
            await client.generate("你好", max_retries=2)
