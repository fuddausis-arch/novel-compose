"""模型管理后端：供应商 CRUD + 模型发现 + 优先级/默认设置。

借鉴 DeterminFlow core/model_manager.py：
- 供应商管理：base_url, api_key, name
- 模型发现：调用 /models 端点获取可用模型列表
- 优先级和默认设置

复用 config.py 的 MODEL_PRESETS。
供应商数据存储：project_data/model_providers.json。
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import load_config, MODEL_PRESETS, get_model_context_length

router = APIRouter()


# ---- Pydantic 模型 ----


class ProviderInput(BaseModel):
    """供应商创建/更新字段。"""
    name: str
    base_url: str = ""
    api_key: str = ""
    models: list[str] = []
    priority: int = 0
    is_default: bool = False


class ProviderUpdate(BaseModel):
    """供应商更新字段（全部可选，name 不可变）。"""
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    priority: int | None = None
    is_default: bool | None = None


# ---- 文件 I/O 辅助 ----


def _providers_path() -> Path:
    """获取 model_providers.json 路径，自动创建目录。"""
    cfg = load_config()
    cfg.project_data_dir.mkdir(parents=True, exist_ok=True)
    return cfg.project_data_dir / "model_providers.json"


def _load_providers() -> list[dict]:
    """读取所有供应商，文件不存在时返回空列表。"""
    path = _providers_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_providers(providers: list[dict]) -> None:
    """写入 model_providers.json。"""
    path = _providers_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(providers, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存供应商失败: {e}")


def _find_provider(providers: list[dict], name: str) -> dict | None:
    """按 name 查找供应商。"""
    for p in providers:
        if p.get("name") == name:
            return p
    return None


def _mask_api_key(key: str) -> str:
    """脱敏 API Key：只返回前 8 位。"""
    if len(key) > 8:
        return key[:8] + "****"
    return "****" if key else ""


# ---- 端点 ----


@router.get("/presets")
def get_presets():
    """获取 MODEL_PRESETS（含上下文长度信息）。"""
    result = {}
    for model_name, preset in MODEL_PRESETS.items():
        result[model_name] = {
            "base_url": preset.get("base_url", ""),
            "context_length": get_model_context_length(model_name),
        }
    return {"presets": result}


@router.get("/providers")
def list_providers():
    """列出所有供应商（api_key 脱敏）。"""
    providers = _load_providers()
    for p in providers:
        p["api_key"] = _mask_api_key(p.get("api_key", ""))
    return {"providers": providers}


@router.post("/providers")
def create_provider(provider: ProviderInput):
    """添加供应商。"""
    providers = _load_providers()
    if _find_provider(providers, provider.name):
        raise HTTPException(409, f"供应商已存在: {provider.name}")
    data = provider.model_dump()
    # 设为默认时，取消其他供应商的默认标记
    if data.get("is_default"):
        for p in providers:
            p["is_default"] = False
    providers.append(data)
    _save_providers(providers)
    result = dict(data)
    result["api_key"] = _mask_api_key(data["api_key"])
    return {"created": True, "provider": result}


@router.put("/providers/{name}")
def update_provider(name: str, updates: ProviderUpdate):
    """更新供应商。"""
    providers = _load_providers()
    target = _find_provider(providers, name)
    if target is None:
        raise HTTPException(404, f"供应商不存在: {name}")
    update_data = updates.model_dump(exclude_unset=True)
    # 脱敏的 api_key（来自 GET 接口）不应覆盖真实密钥
    if "api_key" in update_data and update_data["api_key"] and update_data["api_key"].endswith("****"):
        update_data.pop("api_key")
    target.update(update_data)
    # 设为默认时，取消其他供应商的默认标记
    if update_data.get("is_default"):
        for p in providers:
            if p is not target:
                p["is_default"] = False
    _save_providers(providers)
    result = dict(target)
    result["api_key"] = _mask_api_key(target.get("api_key", ""))
    return {"updated": True, "provider": result}


@router.delete("/providers/{name}")
def delete_provider(name: str):
    """删除供应商。"""
    providers = _load_providers()
    target = _find_provider(providers, name)
    if target is None:
        raise HTTPException(404, f"供应商不存在: {name}")
    providers.remove(target)
    _save_providers(providers)
    return {"deleted": True, "name": name}


@router.get("/discover")
async def discover_models(provider: str | None = None, base_url: str | None = None, api_key: str | None = None):
    """发现可用模型（调用 /v1/models 端点）。

    可指定 provider 名称（从已存储的供应商中读取 base_url/api_key），
    也可直接传 base_url 和 api_key 进行临时发现。
    """
    # 确定请求参数
    if provider:
        providers = _load_providers()
        p = _find_provider(providers, provider)
        if p is None:
            raise HTTPException(404, f"供应商不存在: {provider}")
        url = (base_url or p.get("base_url", "")).rstrip("/")
        key = api_key or p.get("api_key", "")
    else:
        url = (base_url or "").rstrip("/")
        key = api_key or ""

    if not url:
        raise HTTPException(400, "缺少 base_url：请通过 provider 参数指定已存储供应商，或直接传 base_url")

    models_url = f"{url}/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(models_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"模型发现请求失败 ({e.response.status_code}): {e}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"模型发现连接失败: {e}")
    except Exception as e:
        raise HTTPException(500, f"模型发现异常: {e}")

    # 兼容 OpenAI /v1/models 响应格式：{"data": [{"id": "model-name", ...}]}
    models = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(models, list):
        models = []
    result = []
    for m in models:
        if isinstance(m, dict):
            model_id = m.get("id", m.get("name", ""))
            result.append({
                "id": model_id,
                "context_length": get_model_context_length(model_id),
                "owned_by": m.get("owned_by", ""),
            })
        elif isinstance(m, str):
            result.append({"id": m, "context_length": get_model_context_length(m), "owned_by": ""})
    return {"models": result, "source": provider or base_url or "custom"}
