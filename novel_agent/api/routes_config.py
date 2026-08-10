"""全局配置 API：LLM 接口设置等。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import load_config, save_config, get_model_context_length, MODEL_PRESETS

router = APIRouter()


class LLMConfigResponse(BaseModel):
    base_url: str
    api_key: str
    model: str
    temperature: float
    top_p: float = 0.92
    frequency_penalty: float = 0.4
    presence_penalty: float = 0.3
    max_tokens: int
    timeout: float
    vision_enabled: bool
    context_length: int


class LLMConfigInput(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
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
    # 脱敏：只返回 key 前 8 位
    masked_key = cfg.llm.api_key[:8] + "****" if len(cfg.llm.api_key) > 8 else "****"
    return {
        "base_url": cfg.llm.base_url,
        "api_key": masked_key,
        "model": cfg.llm.model,
        "temperature": cfg.llm.temperature,
        "top_p": cfg.llm.top_p,
        "frequency_penalty": cfg.llm.frequency_penalty,
        "presence_penalty": cfg.llm.presence_penalty,
        "max_tokens": cfg.llm.max_tokens,
        "timeout": cfg.llm.timeout,
        "vision_enabled": cfg.llm.vision_enabled,
        "context_length": context_length,
    }


@router.put("/llm")
def update_llm_config(data: LLMConfigInput):
    cfg = load_config()
    updates = data.model_dump(exclude_unset=True)
    # 脱敏的 api_key（来自 GET 接口）不应覆盖真实密钥
    if "api_key" in updates and updates["api_key"] and updates["api_key"].endswith("****"):
        updates.pop("api_key")
    # 拒绝明显的测试/占位值，防止覆盖真实配置
    fake_markers = ["test.example.com", "test-model", "example.com", "placeholder"]
    for k in list(updates.keys()):
        v = updates[k]
        if v is None or v == "":
            updates.pop(k)
        elif isinstance(v, str) and any(marker in v.lower() for marker in fake_markers):
            updates.pop(k)
    for key, value in updates.items():
        setattr(cfg.llm, key, value)
    # 模型变更时自动重新识别上下文长度
    if "model" in updates and "context_length" not in updates:
        cfg.llm.context_length = get_model_context_length(cfg.llm.model)
    # 模型预设：选 deepseek/glm 系列时自动填充官方 base_url
    # 注意：只在用户未手动传 base_url 时填充预设值；api_key 永不覆盖用户已有配置
    preset = MODEL_PRESETS.get(cfg.llm.model)
    if preset:
        if "base_url" not in updates:
            cfg.llm.base_url = preset["base_url"]
        # api_key 仅在用户当前为空且预设有值时填充（不覆盖用户已配置的密钥）
        if not cfg.llm.api_key and preset.get("api_key"):
            cfg.llm.api_key = preset["api_key"]
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True, "context_length": cfg.llm.context_length}


@router.post("/llm/test")
async def test_llm_config():
    """测试已保存配置的 LLM 连通性（不接受用户传入 base_url/api_key，避免 SSRF 与密钥泄露）。"""
    from novel_agent.llm.client import LLMClient, LLMError

    cfg = load_config()
    context_length = cfg.llm.context_length
    if context_length is None:
        context_length = get_model_context_length(cfg.llm.model)
    client = LLMClient(cfg.llm)
    try:
        response = await client.generate('请只回复一个单词 "pong"。', system="你是测试助手")
        return {"ok": True, "response": response.strip(), "context_length": context_length}
    except LLMError as e:
        raise HTTPException(502, f"连接失败：{e}")
    except Exception as e:
        raise HTTPException(502, f"连接失败：{e}")


@router.get("/auditor-llm")
def get_auditor_llm_config():
    """获取审校独立 LLM 配置（写审分离）。向后兼容，等价于 GET /agent-llm/auditor。"""
    cfg = load_config()
    alc = cfg.get_agent_llm("auditor")
    if not cfg.auditor_llm and "auditor" not in cfg.agent_llm:
        return {"enabled": False, "message": "审校使用与 Writer 相同的模型（未配置独立审校模型）"}
    context_length = alc.context_length
    if context_length is None:
        context_length = get_model_context_length(alc.model)
    masked_key = alc.api_key[:8] + "****" if len(alc.api_key) > 8 else "****"
    return {
        "enabled": True,
        "base_url": alc.base_url,
        "api_key": masked_key,
        "model": alc.model,
        "temperature": alc.temperature,
        "max_tokens": alc.max_tokens,
        "timeout": alc.timeout,
        "context_length": context_length,
    }


@router.put("/auditor-llm")
def update_auditor_llm_config(data: LLMConfigInput):
    """配置审校独立 LLM（写审分离铁律：建议用不同厂商模型）。"""
    from novel_agent.config import LLMConfig
    cfg = load_config()
    updates = data.model_dump(exclude_unset=True)
    if "api_key" in updates and updates["api_key"] and updates["api_key"].endswith("****"):
        updates.pop("api_key")
    fake_markers = ["test.example.com", "test-model", "example.com", "placeholder"]
    for k in list(updates.keys()):
        v = updates[k]
        if v is None or v == "":
            updates.pop(k)
        elif isinstance(v, str) and any(marker in v.lower() for marker in fake_markers):
            updates.pop(k)
    base = cfg.get_agent_llm("auditor")
    model = updates.get("model", base.model)
    preset = MODEL_PRESETS.get(model, {})
    new_cfg = LLMConfig(
        base_url=updates.get("base_url", preset.get("base_url", base.base_url)),
        api_key=updates.get("api_key", preset.get("api_key", base.api_key)),
        model=model,
        temperature=updates.get("temperature", base.temperature),
        max_tokens=updates.get("max_tokens", base.max_tokens),
        timeout=updates.get("timeout", base.timeout),
        vision_enabled=updates.get("vision_enabled", base.vision_enabled),
        context_length=updates.get("context_length"),
    )
    if new_cfg.context_length is None:
        new_cfg.context_length = get_model_context_length(new_cfg.model)
    cfg.agent_llm["auditor"] = new_cfg
    cfg.auditor_llm = new_cfg  # 向后兼容
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True, "context_length": new_cfg.context_length}


@router.delete("/auditor-llm")
def reset_auditor_llm_config():
    """重置审校配置，回退到与 Writer 相同的模型。"""
    cfg = load_config()
    cfg.auditor_llm = None
    cfg.agent_llm.pop("auditor", None)
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True, "message": "审校已回退到 Writer 模型"}


# ---- 通用 per-agent 模型配置 ----

AGENT_ROLES = ["planner", "architect", "outliner", "writer", "auditor", "debater", "polisher", "summarizer"]


@router.get("/agent-llm")
def list_agent_llm_configs():
    """列出所有 agent 的模型配置。"""
    cfg = load_config()
    result = {}
    for role in AGENT_ROLES:
        alc = cfg.get_agent_llm(role)
        is_overridden = role in cfg.agent_llm or (role == "auditor" and cfg.auditor_llm)
        context_length = alc.context_length
        if context_length is None:
            context_length = get_model_context_length(alc.model)
        masked_key = alc.api_key[:8] + "****" if len(alc.api_key) > 8 else "****"
        result[role] = {
            "enabled": is_overridden,
            "base_url": alc.base_url,
            "api_key": masked_key,
            "model": alc.model,
            "temperature": alc.temperature,
            "max_tokens": alc.max_tokens,
            "timeout": alc.timeout,
            "context_length": context_length,
        }
    return result


@router.get("/agent-llm/{role}")
def get_agent_llm_config(role: str):
    """获取指定 agent 的模型配置。"""
    if role not in AGENT_ROLES:
        raise HTTPException(400, f"未知角色：{role}，可选：{AGENT_ROLES}")
    cfg = load_config()
    alc = cfg.get_agent_llm(role)
    is_overridden = role in cfg.agent_llm or (role == "auditor" and cfg.auditor_llm)
    context_length = alc.context_length
    if context_length is None:
        context_length = get_model_context_length(alc.model)
    masked_key = alc.api_key[:8] + "****" if len(alc.api_key) > 8 else "****"
    return {
        "enabled": is_overridden,
        "base_url": alc.base_url,
        "api_key": masked_key,
        "model": alc.model,
        "temperature": alc.temperature,
        "max_tokens": alc.max_tokens,
        "timeout": alc.timeout,
        "context_length": context_length,
    }


@router.put("/agent-llm/{role}")
def update_agent_llm_config(role: str, data: LLMConfigInput):
    """配置指定 agent 的独立模型。"""
    from novel_agent.config import LLMConfig
    if role not in AGENT_ROLES:
        raise HTTPException(400, f"未知角色：{role}，可选：{AGENT_ROLES}")
    cfg = load_config()
    updates = data.model_dump(exclude_unset=True)
    if "api_key" in updates and updates["api_key"] and updates["api_key"].endswith("****"):
        updates.pop("api_key")
    fake_markers = ["test.example.com", "test-model", "example.com", "placeholder"]
    for k in list(updates.keys()):
        v = updates[k]
        if v is None or v == "":
            updates.pop(k)
        elif isinstance(v, str) and any(marker in v.lower() for marker in fake_markers):
            updates.pop(k)
    base = cfg.get_agent_llm(role)
    model = updates.get("model", base.model)
    preset = MODEL_PRESETS.get(model, {})
    new_cfg = LLMConfig(
        base_url=updates.get("base_url", preset.get("base_url", base.base_url)),
        api_key=updates.get("api_key", preset.get("api_key", base.api_key)),
        model=model,
        temperature=updates.get("temperature", base.temperature),
        max_tokens=updates.get("max_tokens", base.max_tokens),
        timeout=updates.get("timeout", base.timeout),
        vision_enabled=updates.get("vision_enabled", base.vision_enabled),
        context_length=updates.get("context_length"),
    )
    if new_cfg.context_length is None:
        new_cfg.context_length = get_model_context_length(new_cfg.model)
    cfg.agent_llm[role] = new_cfg
    if role == "auditor":
        cfg.auditor_llm = new_cfg  # 向后兼容
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True, "context_length": new_cfg.context_length}


@router.delete("/agent-llm/{role}")
def reset_agent_llm_config(role: str):
    """重置指定 agent 配置，回退到默认模型。"""
    if role not in AGENT_ROLES:
        raise HTTPException(400, f"未知角色：{role}，可选：{AGENT_ROLES}")
    cfg = load_config()
    cfg.agent_llm.pop(role, None)
    if role == "auditor":
        cfg.auditor_llm = None
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True, "message": f"{role} 已回退到默认模型"}


# ---- Embedding 配置 ----


class EmbeddingConfigResponse(BaseModel):
    api_key: str
    base_url: str
    model: str


class EmbeddingConfigInput(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


@router.get("/embedding")
def get_embedding_config():
    """获取 Embedding 配置（api_key 脱敏）。"""
    cfg = load_config()
    masked_key = cfg.embedding_api_key[:8] + "****" if len(cfg.embedding_api_key) > 8 else "****"
    return {
        "api_key": masked_key,
        "base_url": cfg.embedding_base_url or cfg.llm.base_url,
        "model": cfg.embedding_model,
    }


@router.put("/embedding")
def update_embedding_config(data: EmbeddingConfigInput):
    """更新 Embedding 配置。"""
    cfg = load_config()
    updates = data.model_dump(exclude_unset=True)
    # 脱敏的 api_key 不应覆盖真实密钥
    if "api_key" in updates and updates["api_key"] and updates["api_key"].endswith("****"):
        updates.pop("api_key")
    fake_markers = ["test.example.com", "test-model", "example.com", "placeholder"]
    for k in list(updates.keys()):
        v = updates[k]
        if v is None or v == "":
            updates.pop(k)
        elif isinstance(v, str) and any(marker in v.lower() for marker in fake_markers):
            updates.pop(k)
    if "api_key" in updates:
        cfg.embedding_api_key = updates["api_key"]
    if "base_url" in updates:
        cfg.embedding_base_url = updates["base_url"]
    if "model" in updates:
        cfg.embedding_model = updates["model"]
    try:
        save_config(cfg)
    except Exception as e:
        raise HTTPException(500, f"保存配置失败：{e}")
    return {"saved": True}


@router.post("/embedding/test")
async def test_embedding_config():
    """测试已保存配置的 Embedding 连通性。"""
    from chromadb.utils import embedding_functions

    cfg = load_config()
    emb_api_key = cfg.embedding_api_key
    if not emb_api_key:
        raise HTTPException(400, "未配置 Embedding API Key")
    emb_base_url = (cfg.embedding_base_url or cfg.llm.base_url).rstrip("/")
    emb_model = cfg.embedding_model or "doubao-embedding-vision"
    try:
        ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=emb_api_key,
            api_base=emb_base_url,
            model_name=emb_model,
        )
        vec = ef(["测试文本"])
        if not vec or len(vec) == 0 or vec[0] is None:
            raise HTTPException(502, "Embedding 返回为空")
        return {"ok": True, "dimensions": len(vec[0])}
    except Exception as e:
        raise HTTPException(502, f"Embedding 连接失败：{e}")
