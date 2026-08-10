"""extension.toml 清单加载与校验（移植自 DeterminFlow extension_host/manifest.py）。

从 extension.toml 解析出 ExtensionManifest，校验 api_version 兼容性、
字段完整性与 capability 声明合法性。
"""
from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from novel_agent.extension_api.models import (
    EXTENSION_API_VERSION,
    ExtensionManifest,
    ExtensionPage,
    ExtensionProcess,
)

logger = logging.getLogger(__name__)

_EXTENSION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

# 合法 capability 声明（与 fusion-plan 6.37 extension.toml 能力声明对应）
KNOWN_CAPABILITIES = frozenset({
    "workflows",       # 提供工作流定义
    "agents",          # 提供 Agent 定义
    "prompts",         # 提供 Prompt section
    "skills",          # 提供 Skill
    "rules",           # 提供 Rule
    "preset_phrases",  # 提供预设短语
    "scripts",         # 提供脚本库
    "api",             # 提供 HTTP API（router）
    "processes",       # 声明子进程
    "pages",           # 提供静态管理页
    "cron",            # 提供定时任务
    "tools",           # 提供工具
})


class ManifestError(ValueError):
    """extension.toml 解析/校验失败。"""


def _require_str(data: dict, key: str, *, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context}: 字段 {key!r} 必须是非空字符串")
    return value.strip()


def _parse_processes(raw: Any) -> tuple[ExtensionProcess, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestError("[[processes]] 必须是数组")
    processes: list[ExtensionProcess] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(f"processes[{i}] 必须是 table")
        process_id = _require_str(item, "process_id", context=f"processes[{i}]")
        command = item.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(c, str) or not c for c in command)
        ):
            raise ManifestError(f"processes[{i}].command 必须是非空字符串数组")
        processes.append(ExtensionProcess(
            process_id=process_id,
            command=tuple(command),
            working_directory=str(item.get("working_directory", ".")),
            environment={str(k): str(v) for k, v in (item.get("environment") or {}).items()},
            healthcheck_url=str(item.get("healthcheck_url", "")),
            start_timeout_seconds=float(item.get("start_timeout_seconds", 30.0)),
            stop_timeout_seconds=float(item.get("stop_timeout_seconds", 10.0)),
        ))
    return tuple(processes)


def _parse_page(raw: Any) -> ExtensionPage | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError("[page] 必须是 table")
    return ExtensionPage(
        label=_require_str(raw, "label", context="page"),
        static_dir=_require_str(raw, "static_dir", context="page"),
        entrypoint=str(raw.get("entrypoint", "index.html")),
    )


def parse_manifest(data: dict[str, Any], base_path: Path | None = None) -> ExtensionManifest:
    """从 extension.toml 解析出的 dict 构建 ExtensionManifest 并校验。"""
    if not isinstance(data, dict):
        raise ManifestError("extension.toml 顶层必须是 table")

    ext = data.get("extension")
    if not isinstance(ext, dict):
        raise ManifestError("缺少 [extension] table")

    extension_id = _require_str(ext, "id", context="extension")
    if not _EXTENSION_ID_RE.fullmatch(extension_id):
        raise ManifestError(
            f"extension.id {extension_id!r} 不合法：必须小写字母开头，"
            f"仅含小写字母/数字/_/-，长度 2-64")

    name = _require_str(ext, "name", context="extension")
    version = _require_str(ext, "version", context="extension")
    if not _VERSION_RE.fullmatch(version):
        raise ManifestError(f"extension.version {version!r} 不合法：需符合 semver（如 1.0.0）")

    api_version = str(ext.get("api_version", EXTENSION_API_VERSION))
    if api_version != EXTENSION_API_VERSION:
        raise ManifestError(
            f"extension.api_version {api_version!r} 与宿主支持的 {EXTENSION_API_VERSION!r} 不兼容")

    capabilities = tuple(str(c) for c in (ext.get("capabilities") or []))
    unknown_caps = sorted(set(capabilities) - KNOWN_CAPABILITIES)
    if unknown_caps:
        raise ManifestError(f"未知 capabilities: {', '.join(unknown_caps)}")

    dependencies = tuple(str(d) for d in (ext.get("dependencies") or []))

    return ExtensionManifest(
        extension_id=extension_id,
        name=name,
        version=version,
        api_version=api_version,
        description=str(ext.get("description", "")),
        resource_prefix=str(ext.get("resource_prefix", "")),
        dependencies=dependencies,
        backend=str(ext.get("backend", "")),
        frontend=str(ext.get("frontend", "")),
        capabilities=capabilities,
        base_path=base_path,
        resources=dict(data.get("resources") or {}),
        requirements=str(data.get("requirements", "")),
        settings_schema=str(data.get("settings_schema", "")),
        page=_parse_page(data.get("page")),
        processes=_parse_processes(data.get("processes")),
    )


def load_manifest(manifest_path: str | Path) -> ExtensionManifest:
    """从 extension.toml 文件加载并校验清单。"""
    path = Path(manifest_path).resolve()
    if not path.exists():
        raise ManifestError(f"extension.toml 不存在: {path}")
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"extension.toml 解析失败: {e}") from e
    return parse_manifest(data, base_path=path.parent)
