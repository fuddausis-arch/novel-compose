"""扩展公共数据契约（移植自 DeterminFlow extension_api/models.py）。

三模块架构中的「API 层」：定义插件与宿主之间稳定的公共接口，
插件只依赖本模块，不依赖宿主内部实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

EXTENSION_API_VERSION = "1"


@dataclass(frozen=True)
class ExtensionProcess:
    """插件声明的子进程。"""

    process_id: str
    command: tuple[str, ...]
    working_directory: str = "."
    environment: dict[str, str] = field(default_factory=dict)
    healthcheck_url: str = ""
    start_timeout_seconds: float = 30.0
    stop_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class ExtensionPage:
    """插件附带的轻量静态管理页。"""

    label: str
    static_dir: str
    entrypoint: str = "index.html"


@dataclass(frozen=True)
class ExtensionManifest:
    """插件声明式身份与兼容性元数据（来自 extension.toml）。"""

    extension_id: str
    name: str
    version: str
    api_version: str = EXTENSION_API_VERSION
    description: str = ""
    resource_prefix: str = ""
    dependencies: tuple[str, ...] = ()
    backend: str = ""
    frontend: str = ""
    capabilities: tuple[str, ...] = ()
    base_path: Path | None = field(default=None, compare=False)
    resources: dict[str, Any] = field(default_factory=dict, compare=False)
    requirements: str = ""
    settings_schema: str = ""
    page: ExtensionPage | None = None
    processes: tuple[ExtensionProcess, ...] = ()


@dataclass
class CoreRuntime:
    """宿主初始化完成后传给插件的稳定门面。"""

    app: Any
    session_manager: Any
    workflow_runtime: Any
    tool_registry: Any
    event_publisher: Any
    services: dict[str, Any] = field(default_factory=dict)
    resource_owner: str = ""
    resource_dependencies: tuple[str, ...] = ()
    resource_resolver: Any = None

    def get_service(self, name: str, default: Any = None) -> Any:
        return self.services.get(name, default)

    def resolve_resource(
        self,
        resource_type: str,
        local_id: str,
        *,
        plugin_id: str | None = None,
    ) -> str:
        """把插件局部资源 ID 解析为全局有效 ID（带依赖校验）。"""
        owner = str(plugin_id or self.resource_owner).strip()
        if not owner:
            raise RuntimeError("resolve_resource 缺少 Plugin owner")
        requester = str(self.resource_owner).strip()
        dependencies = {str(d).strip() for d in self.resource_dependencies}
        if requester and owner != requester and owner not in dependencies:
            raise RuntimeError(
                f"Plugin {requester!r} 未声明资源依赖 {owner!r}"
            )
        if self.resource_resolver is None:
            raise RuntimeError("CoreRuntime 未配置 Plugin resource resolver")
        return self.resource_resolver.resolve(owner, resource_type, local_id)


@dataclass(frozen=True)
class PromptContextRequest:
    """主会话/工作流 prompt 构建前的上下文请求。"""

    agent_type: str
    agent_definition: Any = None
    session_type: str = "main"
    workflow_id: str = ""


@dataclass(frozen=True)
class PromptContribution:
    """已启用插件贡献的 prompt 片段。"""

    content: str
    order: int = 100


@dataclass(frozen=True)
class HealthCheckResult:
    """插件健康检查结果。"""

    healthy: bool
    message: str = ""


@runtime_checkable
class Extension(Protocol):
    """插件协议：所有插件必须实现 manifest/register/start/stop。"""

    manifest: ExtensionManifest

    def register(self, registrar: Any) -> None: ...

    async def start(self, runtime: CoreRuntime) -> None: ...

    async def stop(self) -> None: ...


@runtime_checkable
class PromptContextProvider(Protocol):
    async def provide(self, request: PromptContextRequest) -> PromptContribution | None: ...


@runtime_checkable
class SessionLifecycleHook(Protocol):
    async def on_session_end(self, session: Any) -> None: ...
