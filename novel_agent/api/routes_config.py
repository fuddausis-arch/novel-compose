"""全局配置 API：LLM 接口设置等。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import LLMConfig, load_config, save_config, get_model_context_length

router = APIRouter()


class LLMConfigResponse(BaseModel):
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    timeout: float
    vision_enabled: bool
    context_length: int


class LLMConfigInput(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    vision_enabled: bool | None = None
    context_length: int | None = None


@router.get("/llm")
def get_llm_config():
    cfg = load_config()
    context_length = cfg.llm.context_length
    if context_length is None:
        context_length = get_model_context_length(cfg.llm.model)
    return {
        "base_url": cfg.llm.base_url,
        "api_key": cfg.llm.api_key,
        "model": cfg.llm.model,
        "temperature": cfg.llm.temperature,
        "max_tokens": cfg.llm.max_tokens,
        "timeout": cfg.llm.timeout,
        "vision_enabled": cfg.llm.vision_enabled,
        "context_length": context_length,
    }


@router.put("/llm")
def update_llm_config(data: LLMConfigInput):
    cfg = load_config()
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(cfg.llm, key, value)
    # 模型变更时自动重新识别上下文长度
    if "model" in updates and "context_length" not in updates:
        cfg.llm.context_length = get_model_context_length(cfg.llm.model)
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True, "context_length": cfg.llm.context_length}


@router.post("/llm/test")
async def test_llm_config(data: LLMConfigInput):
    """用当前配置（或传入配置）测试 LLM 连通性。"""
    from novel_agent.llm.client import LLMClient, LLMError

    cfg = load_config()
    updates = data.model_dump(exclude_unset=True)
    base = cfg.llm
    test_model = updates.get("model", base.model)
    test_cfg = LLMConfig(
        base_url=updates.get("base_url", base.base_url),
        api_key=updates.get("api_key", base.api_key),
        model=test_model,
        temperature=updates.get("temperature", base.temperature),
        max_tokens=updates.get("max_tokens", base.max_tokens),
        timeout=updates.get("timeout", base.timeout),
        vision_enabled=updates.get("vision_enabled", base.vision_enabled),
        context_length=updates.get("context_length", base.context_length),
    )
    if test_cfg.context_length is None:
        test_cfg.context_length = get_model_context_length(test_model)
    client = LLMClient(test_cfg)
    try:
        response = await client.generate('请只回复一个单词 "pong"。', system="你是测试助手")
        return {"ok": True, "response": response.strip(), "context_length": test_cfg.context_length}
    except LLMError as e:
        raise HTTPException(502, f"连接失败：{e}")
    except Exception as e:
        raise HTTPException(502, f"连接失败：{e}")
