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


@dataclass
class Config:
    project_data_dir: Path = Path("project_data")
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def bible_db_path(self) -> Path:
        return self.project_data_dir / "bible.db"

    @property
    def chroma_dir(self) -> Path:
        return self.project_data_dir / "chroma"

    @property
    def chapters_dir(self) -> Path:
        return self.project_data_dir / "chapters"


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
        )
    # env 覆盖
    cfg.llm.api_key = os.getenv("NOVEL_LLM_API_KEY", cfg.llm.api_key)
    cfg.llm.base_url = os.getenv("NOVEL_LLM_BASE_URL", cfg.llm.base_url)
    cfg.llm.model = os.getenv("NOVEL_LLM_MODEL", cfg.llm.model)
    return cfg
