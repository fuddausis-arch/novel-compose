"""Plugin 打包交付（移植自 DeterminFlow plugin_system/release.py + store.py 概念）。

能力：
- pack_plugin: 把插件目录（含 extension.toml）打包为 .napkg（zip 格式）
- install_package: 从 .napkg 安装到 extensions 目录
- verify_package: 安装前校验（manifest 合法性、路径安全、版本冲突）

打包格式 .napkg = zip，根目录必须含 extension.toml。
安全措施：
- 解压时拒绝绝对路径与 .. 路径穿越（zip slip 防护）
- 单文件与总大小上限
- 覆盖安装需显式 force=True
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from novel_agent.extension_host.manifest import ManifestError, load_manifest

logger = logging.getLogger(__name__)

PACKAGE_SUFFIX = ".napkg"
_MAX_PACKAGE_BYTES = 64 * 1024 * 1024       # 包总大小 64MB
_MAX_FILE_BYTES = 8 * 1024 * 1024           # 单文件 8MB
_MAX_FILE_COUNT = 2000


class PackagingError(RuntimeError):
    """打包/安装失败。"""


@dataclass
class PackageInfo:
    """包内清单摘要。"""

    extension_id: str
    name: str
    version: str
    file_count: int
    total_bytes: int
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "name": self.name,
            "version": self.version,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "capabilities": self.capabilities,
        }


def _iter_plugin_files(plugin_dir: Path):
    """遍历插件目录文件（跳过缓存/虚拟环境）。"""
    skip_dirs = {"__pycache__", ".git", ".venv", "node_modules", ".pytest_cache"}
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_dir)
        if any(part in skip_dirs for part in rel.parts):
            continue
        yield rel, path


def pack_plugin(plugin_dir: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    """把插件目录打包为 .napkg。

    Args:
        plugin_dir: 插件根目录（必须含 extension.toml）
        output_path: 输出文件路径，缺省为 <plugin_dir 父目录>/<extension_id>-<version>.napkg

    Returns:
        {"status": "packed", "package": ..., "info": ...}
    """
    plugin_dir = Path(plugin_dir).resolve()
    if not plugin_dir.is_dir():
        raise PackagingError(f"插件目录不存在: {plugin_dir}")
    manifest_path = plugin_dir / "extension.toml"
    if not manifest_path.exists():
        raise PackagingError(f"插件目录缺少 extension.toml: {plugin_dir}")

    # 打包前先校验清单
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as e:
        raise PackagingError(f"extension.toml 校验失败，拒绝打包: {e}") from e

    if output_path is None:
        safe_name = f"{manifest.extension_id}-{manifest.version}{PACKAGE_SUFFIX}"
        output_path = plugin_dir.parent / safe_name
    output_path = Path(output_path).resolve()

    file_count = 0
    total_bytes = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, path in _iter_plugin_files(plugin_dir):
            size = path.stat().st_size
            if size > _MAX_FILE_BYTES:
                raise PackagingError(f"文件超过单文件上限 {_MAX_FILE_BYTES}: {rel}")
            file_count += 1
            total_bytes += size
            if file_count > _MAX_FILE_COUNT:
                raise PackagingError(f"文件数超过上限 {_MAX_FILE_COUNT}")
            if total_bytes > _MAX_PACKAGE_BYTES:
                raise PackagingError(f"包总大小超过上限 {_MAX_PACKAGE_BYTES}")
            zf.write(path, rel.as_posix())

    info = PackageInfo(
        extension_id=manifest.extension_id,
        name=manifest.name,
        version=manifest.version,
        file_count=file_count,
        total_bytes=total_bytes,
        capabilities=list(manifest.capabilities),
    )
    logger.info("插件已打包: %s -> %s (%d 文件, %d bytes)",
                plugin_dir, output_path, file_count, total_bytes)
    return {"status": "packed", "package": str(output_path), "info": info.to_dict()}


def _safe_member_path(name: str) -> PurePosixPath:
    """校验 zip 成员路径，防 zip slip。"""
    if name.startswith("/") or name.startswith("\\"):
        raise PackagingError(f"包内含绝对路径，拒绝安装: {name}")
    rel = PurePosixPath(name.replace("\\", "/"))
    if any(part in ("", ".", "..") for part in rel.parts):
        raise PackagingError(f"包内含路径穿越，拒绝安装: {name}")
    return rel


def verify_package(package_path: str | Path) -> PackageInfo:
    """校验 .napkg 包：格式、路径安全、manifest 合法性。"""
    package_path = Path(package_path).resolve()
    if not package_path.exists():
        raise PackagingError(f"包不存在: {package_path}")
    if package_path.stat().st_size > _MAX_PACKAGE_BYTES:
        raise PackagingError(f"包大小超过上限 {_MAX_PACKAGE_BYTES}")

    try:
        zf = zipfile.ZipFile(package_path)
    except zipfile.BadZipFile as e:
        raise PackagingError(f"不是合法的 zip 包: {e}") from e

    with zf:
        names = zf.namelist()
        if "extension.toml" not in names:
            raise PackagingError("包根目录缺少 extension.toml")
        file_count = 0
        total_bytes = 0
        for name in names:
            if name.endswith("/"):
                continue
            _safe_member_path(name)
            info = zf.getinfo(name)
            if info.file_size > _MAX_FILE_BYTES:
                raise PackagingError(f"包内文件超过单文件上限: {name}")
            file_count += 1
            total_bytes += info.file_size
        if file_count > _MAX_FILE_COUNT:
            raise PackagingError(f"包内文件数超过上限 {_MAX_FILE_COUNT}")

        # 解析 manifest（不解压到磁盘）
        with zf.open("extension.toml") as f:
            import tomllib
            try:
                data = tomllib.load(io.BytesIO(f.read()))
            except tomllib.TOMLDecodeError as e:
                raise PackagingError(f"包内 extension.toml 解析失败: {e}") from e
        from novel_agent.extension_host.manifest import parse_manifest
        try:
            manifest = parse_manifest(data)
        except ManifestError as e:
            raise PackagingError(f"包内 extension.toml 校验失败: {e}") from e

    return PackageInfo(
        extension_id=manifest.extension_id,
        name=manifest.name,
        version=manifest.version,
        file_count=file_count,
        total_bytes=total_bytes,
        capabilities=list(manifest.capabilities),
    )


def install_package(
    package_path: str | Path,
    extensions_dir: str | Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """从 .napkg 安装到 extensions 目录。

    Args:
        package_path: .napkg 包路径
        extensions_dir: 扩展安装根目录
        force: 已存在同 id 扩展时是否覆盖

    Returns:
        {"status": "installed", "extension_id": ..., "dir": ..., "info": ...}
    """
    info = verify_package(package_path)
    extensions_dir = Path(extensions_dir).resolve()
    extensions_dir.mkdir(parents=True, exist_ok=True)

    target_dir = extensions_dir / info.extension_id
    if target_dir.exists():
        if not force:
            raise PackagingError(
                f"扩展 {info.extension_id} 已存在，需 force=True 覆盖安装")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    with zipfile.ZipFile(Path(package_path).resolve()) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            rel = _safe_member_path(name)
            dest = target_dir.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)

    logger.info("插件包已安装: %s -> %s", package_path, target_dir)
    return {
        "status": "installed",
        "extension_id": info.extension_id,
        "dir": str(target_dir),
        "info": info.to_dict(),
    }
