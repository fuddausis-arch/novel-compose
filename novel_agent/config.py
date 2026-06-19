"""配置加载：env 优先，yaml 补充。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4000
    timeout: float = 180.0
    vision_enabled: bool = False
    context_length: int | None = None


MODEL_CONTEXT_LENGTHS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "deepseek-chat": 65536,
    "deepseek-coder": 65536,
    "qwen-turbo": 8000,
    "qwen-plus": 32000,
    "qwen-max": 32000,
    "kimi": 200000,
    "moonshot-v1": 128000,
    "glm-4": 128000,
    "glm-3-turbo": 128000,
}


def get_model_context_length(model: str) -> int:
    """根据模型名识别最大上下文长度，未知模型返回 4096 作为保守默认值。"""
    name = model.lower().strip()
    for key, length in MODEL_CONTEXT_LENGTHS.items():
        if key in name:
            return length
    return 4096


@dataclass
class Config:
    project_data_dir: Path = Path("project_data")
    llm: LLMConfig = field(default_factory=LLMConfig)
    auditor_llm: LLMConfig | None = None  # None 时回退到 llm

    @property
    def bible_db_path(self) -> Path:
        return self.project_data_dir / "bible.db"

    @property
    def chroma_dir(self) -> Path:
        return self.project_data_dir / "chroma"

    @property
    def chapters_dir(self) -> Path:
        return self.project_data_dir / "chapters"

    def project_dir(self, project_id: int) -> Path:
        return self.project_data_dir / "projects" / str(project_id)

    def project_chapters_dir(self, project_id: int) -> Path:
        return self.project_dir(project_id) / "chapters"

    def project_chroma_dir(self, project_id: int) -> Path:
        return self.project_dir(project_id) / "chroma"


def load_config(yaml_path: Path | None = None) -> Config:
    """加载配置。yaml 文件可选，env 变量覆盖。

    yaml_path 为 None 时，自动检测当前目录下的 config.yaml。
    """
    cfg = Config()
    if yaml_path is None:
        # 自动找当前目录的 config.yaml
        default_path = Path("config.yaml")
        if default_path.exists():
            yaml_path = default_path
    if yaml_path and yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "project_data_dir" in data:
            cfg.project_data_dir = Path(data["project_data_dir"])
        llm_data = data.get("llm", {})
        cfg.llm = LLMConfig(
            base_url=llm_data.get("base_url", cfg.llm.base_url),
            api_key=llm_data.get("api_key", cfg.llm.api_key),
            model=llm_data.get("model", cfg.llm.model),
            temperature=llm_data.get("temperature", cfg.llm.temperature),
            max_tokens=llm_data.get("max_tokens", cfg.llm.max_tokens),
            timeout=llm_data.get("timeout", cfg.llm.timeout),
            vision_enabled=llm_data.get("vision_enabled", cfg.llm.vision_enabled),
            context_length=llm_data.get("context_length", cfg.llm.context_length),
        )
        if cfg.llm.context_length is None:
            cfg.llm.context_length = get_model_context_length(cfg.llm.model)
    # env 覆盖（仅在 env 非空时生效，避免空字符串覆盖 yaml 已保存的配置）
    _env_api_key = os.getenv("NOVEL_LLM_API_KEY", "")
    _env_base_url = os.getenv("NOVEL_LLM_BASE_URL", "")
    _env_model = os.getenv("NOVEL_LLM_MODEL", "")
    if _env_api_key:
        cfg.llm.api_key = _env_api_key
    if _env_base_url:
        cfg.llm.base_url = _env_base_url
    if _env_model:
        cfg.llm.model = _env_model
    _env_vision = os.getenv("NOVEL_LLM_VISION_ENABLED", "")
    if _env_vision:
        cfg.llm.vision_enabled = _env_vision.lower() in ("1", "true", "yes")
    return cfg


def save_config(cfg: Config, yaml_path: Path | None = None) -> Path:
    """保存配置到 yaml 文件。yaml_path 为 None 时保存到当前目录的 config.yaml。"""
    if yaml_path is None:
        yaml_path = Path("config.yaml")
    data: dict = {}
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data["project_data_dir"] = str(cfg.project_data_dir)
    if cfg.llm.context_length is None:
        cfg.llm.context_length = get_model_context_length(cfg.llm.model)
    data["llm"] = {
        "base_url": cfg.llm.base_url,
        "api_key": cfg.llm.api_key,
        "model": cfg.llm.model,
        "temperature": cfg.llm.temperature,
        "max_tokens": cfg.llm.max_tokens,
        "timeout": cfg.llm.timeout,
        "vision_enabled": cfg.llm.vision_enabled,
        "context_length": cfg.llm.context_length,
    }
    if cfg.auditor_llm is not None:
        if cfg.auditor_llm.context_length is None:
            cfg.auditor_llm.context_length = get_model_context_length(cfg.auditor_llm.model)
        data["auditor_llm"] = {
            "base_url": cfg.auditor_llm.base_url,
            "api_key": cfg.auditor_llm.api_key,
            "model": cfg.auditor_llm.model,
            "temperature": cfg.auditor_llm.temperature,
            "max_tokens": cfg.auditor_llm.max_tokens,
            "timeout": cfg.auditor_llm.timeout,
            "vision_enabled": cfg.auditor_llm.vision_enabled,
            "context_length": cfg.auditor_llm.context_length,
        }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return yaml_path
