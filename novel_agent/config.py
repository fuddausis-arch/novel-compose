"""配置加载：env 优先，yaml 补充。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 项目根目录（config.py 的上两级），config.yaml 默认存这里，
# 可通过 NOVEL_CONFIG_PATH 环境变量覆盖，避免测试污染生产配置。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = Path(os.getenv("NOVEL_CONFIG_PATH", _PROJECT_ROOT / "config.yaml"))


def _default_config_path() -> Path:
    """返回当前生效的默认配置路径，优先读取 NOVEL_CONFIG_PATH 环境变量。"""
    return Path(os.getenv("NOVEL_CONFIG_PATH", _DEFAULT_CONFIG_PATH))


def _default_project_data_dir() -> Path:
    """返回默认项目数据目录。

    打包模式：用户可写目录（Windows: %APPDATA%/NovelCompose，macOS: ~/Library/Application Support/NovelCompose）
    开发模式：项目根目录下的 project_data
    """
    import sys as _sys
    if getattr(_sys, "frozen", False):
        # 打包模式：使用用户可写目录，避免 Program Files 权限问题
        if os.name == "nt":  # Windows
            return Path(os.getenv("APPDATA", Path.home())) / "NovelCompose" / "project_data"
        elif _sys.platform == "darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / "NovelCompose" / "project_data"
        else:  # Linux
            return Path.home() / ".novelcompose" / "project_data"
    return _PROJECT_ROOT / "project_data"


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.85  # M9: 提高到0.85增加多样性降AI味
    top_p: float = 0.92  # M9: nucleus采样0.9-0.95
    frequency_penalty: float = 0.4  # M9: 惩罚重复token 0.3-0.6
    presence_penalty: float = 0.3  # M9: 惩罚重复话题 0.3-0.6
    max_tokens: int = 128000
    timeout: float = 2100.0  # 35 分钟，匹配生成类 API 超时保护要求
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
    "deepseek-v4-pro": 1000000,
    "deepseek-v4-flash": 1000000,
    "qwen-turbo": 8000,
    "qwen-plus": 32000,
    "qwen-max": 32000,
    "kimi": 200000,
    "moonshot-v1": 128000,
    "glm-5.2": 1000000,
    "glm-3-turbo": 128000,
}


# 模型预设：客户端选模型时自动填充对应的 base_url。
# api_key 从环境变量读取，避免硬编码在源码中。
# 环境变量：DEEPSEEK_API_KEY、ARK_API_KEY
import os as _os

MODEL_PRESETS: dict[str, dict[str, str]] = {
    "deepseek-v4-flash": {
        "base_url": "https://api.deepseek.com",
        "api_key": _os.environ.get("DEEPSEEK_API_KEY", ""),
    },
    "deepseek-v4-pro": {
        "base_url": "https://api.deepseek.com",
        "api_key": _os.environ.get("DEEPSEEK_API_KEY", ""),
    },
    "glm-5.2": {
        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "api_key": _os.environ.get("ARK_API_KEY", ""),
    },
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
    project_data_dir: Path = field(default_factory=lambda: _default_project_data_dir())
    llm: LLMConfig = field(default_factory=LLMConfig)
    auditor_llm: LLMConfig | None = None  # None 时回退到 llm（向后兼容）
    agent_llm: dict = field(default_factory=dict)  # role -> LLMConfig（通用 per-agent 覆盖）
    # Embedding 配置（方舟 doubao-embedding-vision，OpenAI 兼容协议）
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "doubao-embedding-vision"
    # 语感检索 kill-switch（默认OFF，A/B验证后视情况开）
    enable_genre_rag: bool = False
    # 章纲/细纲内容不足时，允许 AI 自行扩充剧情生成完整章节正文
    allow_auto_expand_chapter: bool = True
    # 角色 -> 采样参数覆盖（借鉴 bishu-novel 温度五级光谱）
    # 在 get_agent_llm 返回前应用，覆盖 base_config 的对应字段
    ROLE_PARAMS: dict[str, dict] = field(default_factory=lambda: {
        "world_engine": {"temperature": 0.3},
        "context_trimmer": {"temperature": 0.3},
        "post_hoc": {"temperature": 0.3},
        "summarizer": {"temperature": 0.3},
        "auditor": {"temperature": 0.4},
        "debater": {"temperature": 0.4},
        "architect": {"temperature": 0.7},
        "writer": {"temperature": 0.8},
        "polisher": {"temperature": 0.8},
        "planner": {"temperature": 0.9},
        "outliner": {"temperature": 0.9},
    })

    def get_agent_llm(self, role: str) -> LLMConfig:
        """按角色获取 LLM 配置，优先级：agent_llm[role] > auditor_llm(仅auditor) > llm。

        agent_llm[role] 的 api_key 为空时，自动回退到 llm.api_key，
        这样用户只需在主 llm 配置里填一次密钥即可（打包分发友好）。

        最后应用 ROLE_PARAMS 覆盖采样参数（温度五级光谱），确保每个角色
        使用适合其任务类型的温度（推演/裁决用低温度，创作用高温度）。
        """
        # ---- 先确定 base_config（不修改原对象） ----
        if role in self.agent_llm:
            ac = self.agent_llm[role]
            if ac.api_key:
                base_config = ac
            else:
                # api_key 为空：复制一份并填入主 llm 的 key，避免修改原对象
                import copy
                filled = copy.copy(ac)
                filled.api_key = self.llm.api_key
                base_config = filled
        elif role == "auditor" and self.auditor_llm:
            ac = self.auditor_llm
            if ac.api_key:
                base_config = ac
            else:
                import copy
                filled = copy.copy(ac)
                filled.api_key = self.llm.api_key
                base_config = filled
        else:
            base_config = self.llm
        # ---- 应用角色参数覆盖（温度五级光谱） ----
        role_params = self.ROLE_PARAMS.get(role, {})
        if role_params:
            import copy
            config = copy.copy(base_config)
            for key, value in role_params.items():
                setattr(config, key, value)
            return config
        return base_config

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


def _str2bool(v) -> bool:
    """把 YAML 中的布尔配置解析为 bool。

    YAML 写 `enable_genre_rag: "false"` 时值是字符串，bool("false") 会误判为 True，
    统一按字符串语义解析：1/true/yes 为 True，其余为 False。
    """
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes")


def _load_env_file(env_path: Path | None = None) -> None:
    """从 .env 文件加载环境变量（不依赖 python-dotenv，零新依赖）。

    格式：KEY=VALUE，忽略 # 注释和空行。值两端引号自动剥离。
    已存在的环境变量不覆盖（系统 env 优先级 > .env，符合 12-Factor 规范）。

    放在 config.py 是为了配合 ${VAR} 占位符：config.yaml 用 ${DEEPSEEK_API_KEY}
    引用，真实 Key 只存在 .env（被 .gitignore 忽略），永不进 git。
    """
    if env_path is None:
        env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_ENV_VAR_RE = None


def _expand_env_vars(text: str) -> str:
    """展开字符串中的 ${VAR} 占位符为环境变量值。

    向后兼容：无 ${ 的字符串原样返回（零性能损耗）。
    变量不存在时返回空字符串（让 LLMConfig 的空 api_key 回退逻辑生效，
    即 agent_llm 里 api_key 为空时会回退到主 llm.api_key）。
    """
    if not isinstance(text, str) or "${" not in text:
        return text
    global _ENV_VAR_RE
    if _ENV_VAR_RE is None:
        import re
        _ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")
    return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), text)


def _expand_env_in_obj(obj):
    """递归展开 dict/list/str 中的 ${VAR} 占位符。

    yaml.safe_load 后一次性处理整个 data，避免在每个字段读取处单独展开。
    """
    if isinstance(obj, str):
        return _expand_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _expand_env_in_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_in_obj(v) for v in obj]
    return obj


def load_config(yaml_path: Path | None = None) -> Config:
    """加载配置。yaml 文件可选，env 变量覆盖。

    yaml_path 为 None 时，使用 NOVEL_CONFIG_PATH 或默认路径。

    Key 管理：真实 API Key 存在 .env（被 .gitignore 忽略），config.yaml 用
    ${DEEPSEEK_API_KEY} / ${ARK_API_KEY} / ${ARK_EMBEDDING_API_KEY} 占位符引用。
    本函数起手加载 .env，然后展开 yaml 中所有 ${VAR} 占位符。
    无占位符的旧 config.yaml 向后兼容，原样工作。
    """
    _load_env_file()  # 从 .env 加载真实 Key 到 os.environ
    cfg = Config()
    # 打包模式：从环境变量读取数据目录
    _env_data_dir = os.getenv("NOVEL_PROJECT_DATA_DIR", "")
    if _env_data_dir:
        cfg.project_data_dir = Path(_env_data_dir)
    if yaml_path is None:
        default_path = _default_config_path()
        if default_path.exists():
            yaml_path = default_path
    if yaml_path and yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # 展开 ${VAR} 占位符（一次性递归处理整个 data，向后兼容）
        data = _expand_env_in_obj(data)
        # 打包模式：忽略 YAML 中的 project_data_dir（防止机器特定路径导致崩溃）
        # 使用 _default_project_data_dir() 的默认值（%APPDATA%/NovelCompose）
        # 开发模式：正常读取 YAML 中的 project_data_dir
        import sys as _sys
        if "project_data_dir" in data and not getattr(_sys, "frozen", False):
            p = Path(data["project_data_dir"])
            # 相对路径基于项目根目录解析，避免依赖 cwd
            cfg.project_data_dir = p if p.is_absolute() else _PROJECT_ROOT / p
        llm_data = data.get("llm", {})
        cfg.llm = LLMConfig(
            base_url=llm_data.get("base_url", cfg.llm.base_url),
            api_key=llm_data.get("api_key", cfg.llm.api_key),
            model=llm_data.get("model", cfg.llm.model),
            temperature=llm_data.get("temperature", cfg.llm.temperature),
            top_p=llm_data.get("top_p", cfg.llm.top_p),
            frequency_penalty=llm_data.get("frequency_penalty", cfg.llm.frequency_penalty),
            presence_penalty=llm_data.get("presence_penalty", cfg.llm.presence_penalty),
            max_tokens=llm_data.get("max_tokens", cfg.llm.max_tokens),
            timeout=llm_data.get("timeout", cfg.llm.timeout),
            vision_enabled=llm_data.get("vision_enabled", cfg.llm.vision_enabled),
            context_length=llm_data.get("context_length", cfg.llm.context_length),
        )
        if cfg.llm.context_length is None:
            cfg.llm.context_length = get_model_context_length(cfg.llm.model)
        # 读取审校独立配置（写审分离铁律）
        auditor_data = data.get("auditor_llm")
        if auditor_data:
            cfg.auditor_llm = LLMConfig(
                base_url=auditor_data.get("base_url", cfg.llm.base_url),
                api_key=auditor_data.get("api_key", cfg.llm.api_key),
                model=auditor_data.get("model", cfg.llm.model),
                temperature=auditor_data.get("temperature", cfg.llm.temperature),
                top_p=auditor_data.get("top_p", cfg.llm.top_p),
                frequency_penalty=auditor_data.get("frequency_penalty", cfg.llm.frequency_penalty),
                presence_penalty=auditor_data.get("presence_penalty", cfg.llm.presence_penalty),
                max_tokens=auditor_data.get("max_tokens", cfg.llm.max_tokens),
                timeout=auditor_data.get("timeout", cfg.llm.timeout),
                vision_enabled=auditor_data.get("vision_enabled", cfg.llm.vision_enabled),
                context_length=auditor_data.get("context_length", cfg.llm.context_length),
            )
        # 读取 embedding 配置
        emb_data = data.get("embedding", {})
        if emb_data:
            cfg.embedding_api_key = emb_data.get("api_key", "")
            cfg.embedding_base_url = emb_data.get("base_url", "")
            cfg.embedding_model = emb_data.get("model", "doubao-embedding-vision")
        # 读取 per-agent 模型覆盖
        agent_data = data.get("agent_llm", {})
        for role, rd in agent_data.items():
            if isinstance(rd, dict):
                cfg.agent_llm[role] = LLMConfig(
                    base_url=rd.get("base_url", cfg.llm.base_url),
                    api_key=rd.get("api_key", cfg.llm.api_key),
                    model=rd.get("model", cfg.llm.model),
                    temperature=rd.get("temperature", cfg.llm.temperature),
                    top_p=rd.get("top_p", cfg.llm.top_p),
                    frequency_penalty=rd.get("frequency_penalty", cfg.llm.frequency_penalty),
                    presence_penalty=rd.get("presence_penalty", cfg.llm.presence_penalty),
                    max_tokens=rd.get("max_tokens", cfg.llm.max_tokens),
                    timeout=rd.get("timeout", cfg.llm.timeout),
                    vision_enabled=rd.get("vision_enabled", cfg.llm.vision_enabled),
                    context_length=rd.get("context_length"),
                )
                if cfg.agent_llm[role].context_length is None:
                    cfg.agent_llm[role].context_length = get_model_context_length(cfg.agent_llm[role].model)
        # 读取语感检索开关（字符串 "false" 需按语义解析，避免 bool("false")==True）
        if "enable_genre_rag" in data:
            cfg.enable_genre_rag = _str2bool(data["enable_genre_rag"])
        # 读取章纲扩充开关
        if "allow_auto_expand_chapter" in data:
            cfg.allow_auto_expand_chapter = _str2bool(data["allow_auto_expand_chapter"])
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
    """保存配置到 yaml 文件。yaml_path 为 None 时使用 NOVEL_CONFIG_PATH 或默认路径。"""
    if yaml_path is None:
        yaml_path = _default_config_path()
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
        "top_p": cfg.llm.top_p,
        "frequency_penalty": cfg.llm.frequency_penalty,
        "presence_penalty": cfg.llm.presence_penalty,
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
            "top_p": cfg.auditor_llm.top_p,
            "frequency_penalty": cfg.auditor_llm.frequency_penalty,
            "presence_penalty": cfg.auditor_llm.presence_penalty,
            "max_tokens": cfg.auditor_llm.max_tokens,
            "timeout": cfg.auditor_llm.timeout,
            "vision_enabled": cfg.auditor_llm.vision_enabled,
            "context_length": cfg.auditor_llm.context_length,
        }
    # 保存 embedding 配置
    if cfg.embedding_api_key:
        data["embedding"] = {
            "api_key": cfg.embedding_api_key,
            "base_url": cfg.embedding_base_url,
            "model": cfg.embedding_model,
        }
    # 保存 per-agent 模型覆盖
    if cfg.agent_llm:
        data["agent_llm"] = {}
        for role, lc in cfg.agent_llm.items():
            if lc.context_length is None:
                lc.context_length = get_model_context_length(lc.model)
            data["agent_llm"][role] = {
                "base_url": lc.base_url,
                "api_key": lc.api_key,
                "model": lc.model,
                "temperature": lc.temperature,
                "max_tokens": lc.max_tokens,
                "timeout": lc.timeout,
                "vision_enabled": lc.vision_enabled,
                "context_length": lc.context_length,
            }
    # 保存语感检索开关
    data["enable_genre_rag"] = cfg.enable_genre_rag
    # 保存章纲扩充开关
    data["allow_auto_expand_chapter"] = cfg.allow_auto_expand_chapter
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return yaml_path
