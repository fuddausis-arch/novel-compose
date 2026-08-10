"""插件管理后端：安装/卸载/更新/回滚 + 源管理。

借鉴 DeterminFlow extension_host/ + plugin_system：
- 插件列表（已安装/可用）
- 插件生命周期：install -> enable -> disable -> uninstall
- 源管理：添加/移除插件源（Git URL）
- 插件详情：资源清单（agents/prompts/skills/workflows/scripts）

注意：实际安装/卸载操作做占位实现（返回 501 Not Implemented），重点是 API 设计。
数据存储：project_data/plugins.json。

2026-08-08 更新：extension_host（宿主生命周期）从未被实例化，已移至
novel_agent/_archive_extensions/。本模块调用的 plugin_system.packaging 和
plugin_system.assets 是活代码（插件打包 + 资产导入导出），保留。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from novel_agent.config import load_config

router = APIRouter()


# ---- 默认数据 ----

_DEFAULT_DATA = {
    "installed": [],
    "sources": [],
}


# ---- Pydantic 模型 ----


class SourceInput(BaseModel):
    """插件源添加请求。"""
    url: str


class InstallInput(BaseModel):
    """插件安装请求。"""
    name: str
    source: str | None = None  # 可选：指定从哪个源安装
    version: str | None = None  # 可选：指定版本


# ---- 文件 I/O 辅助 ----


def _plugins_path() -> Path:
    """获取 plugins.json 路径，自动创建目录。"""
    cfg = load_config()
    cfg.project_data_dir.mkdir(parents=True, exist_ok=True)
    return cfg.project_data_dir / "plugins.json"


def _load_data() -> dict:
    """读取插件数据，文件不存在时返回默认结构。"""
    path = _plugins_path()
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT_DATA))  # 深拷贝默认值
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        result = json.loads(json.dumps(_DEFAULT_DATA))
        if isinstance(data, dict):
            result.update(data)
        return result
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_DEFAULT_DATA))


def _save_data(data: dict) -> None:
    """写入 plugins.json。"""
    path = _plugins_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(500, f"保存插件数据失败: {e}")


def _find_plugin(installed: list[dict], name: str) -> dict | None:
    """按 name 查找已安装插件。"""
    for p in installed:
        if p.get("name") == name:
            return p
    return None


# ---- 端点：插件列表 ----


def _manifest_of(plugin_dir: Path):
    """读取插件目录 extension.toml 的 manifest；缺失/非法返回 None。"""
    mf = plugin_dir / "extension.toml"
    if not mf.exists():
        return None
    try:
        from novel_agent.extension_host.manifest import load_manifest
        return load_manifest(mf)
    except Exception:
        return None


def _scan_extensions() -> list[dict]:
    """扫描 extensions 目录下所有插件，返回 [{name, extension_id, version, dir}]。"""
    exts = _extensions_dir()
    out: list[dict] = []
    if not exts.exists():
        return out
    for d in sorted(exts.iterdir()):
        if not d.is_dir():
            continue
        mf = _manifest_of(d)
        out.append({
            "name": mf.name if mf else d.name,
            "extension_id": mf.extension_id if mf else d.name,
            "version": mf.version if mf else "unknown",
            "dir": str(d),
        })
    return out


@router.get("")
def list_plugins():
    """列出已安装插件。"""
    data = _load_data()
    return data


@router.get("/available")
def list_available():
    """列出可用插件：扫描 extensions 目录中尚未安装的插件。"""
    data = _load_data()
    installed_names = {p.get("name") for p in data.get("installed", [])}
    available = [c for c in _scan_extensions() if c["name"] not in installed_names]
    return {
        "available": available,
        "sources": data.get("sources", []),
    }


# ---- 端点：插件生命周期 ----


@router.post("/install")
def install_plugin(body: InstallInput):
    """安装插件。

    支持两种方式：
    1. body.source 传 .napkg 包路径 → 先解包到 extensions 目录再注册；
    2. 仅 name → 从 extensions 目录按 name/extension_id 匹配已存在插件并注册。
    """
    data = _load_data()
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "插件名不能为空")
    if _find_plugin(data["installed"], name):
        raise HTTPException(409, f"插件已安装: {name}")

    # 指定 .napkg 包路径时，先解包到 extensions 目录
    if body.source and body.source.lower().endswith(".napkg"):
        from novel_agent.plugin_system.packaging import PackagingError, install_package
        try:
            install_package(body.source, _extensions_dir(), force=True)
        except PackagingError as e:
            raise HTTPException(400, str(e))

    # 从 extensions 目录按名匹配插件
    hit = None
    for cand in _scan_extensions():
        if cand["name"] == name or cand["extension_id"] == name:
            hit = cand
            break
    if hit is None:
        raise HTTPException(
            404,
            f"未找到插件「{name}」：请先通过 install-package 安装 .napkg 包，"
            "或在 source 传入 .napkg 包路径",
        )

    plugin = {
        "name": hit["name"],
        "extension_id": hit["extension_id"],
        "version": hit["version"],
        "dir": hit["dir"],
        "enabled": True,
    }
    data["installed"].append(plugin)
    _save_data(data)
    return {"installed": True, "plugin": plugin}


@router.delete("/{name}")
def uninstall_plugin(name: str):
    """卸载插件：从已安装列表移除，并清理对应 extensions 目录。"""
    data = _load_data()
    plugin = _find_plugin(data["installed"], name)
    if plugin is None:
        raise HTTPException(404, f"插件不存在: {name}")
    data["installed"] = [p for p in data["installed"] if p.get("name") != name]
    # 清理对应 extensions 目录（仅限位于 extensions 根下的目录，避免误删外部路径）
    pdir = plugin.get("dir")
    if pdir:
        try:
            d = Path(pdir).resolve()
            ext_root = _extensions_dir().resolve()
            if d.is_relative_to(ext_root):
                import shutil
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    _save_data(data)
    return {"uninstalled": True, "name": name}


@router.put("/{name}/enable")
def enable_plugin(name: str):
    """启用插件。"""
    data = _load_data()
    plugin = _find_plugin(data["installed"], name)
    if plugin is None:
        raise HTTPException(404, f"插件不存在: {name}")
    plugin["enabled"] = True
    _save_data(data)
    return {"enabled": True, "name": name}


@router.put("/{name}/disable")
def disable_plugin(name: str):
    """禁用插件。"""
    data = _load_data()
    plugin = _find_plugin(data["installed"], name)
    if plugin is None:
        raise HTTPException(404, f"插件不存在: {name}")
    plugin["enabled"] = False
    _save_data(data)
    return {"disabled": True, "name": name}


# ---- 端点：源管理 ----


@router.get("/sources")
def list_sources():
    """列出插件源。"""
    data = _load_data()
    return {"sources": data.get("sources", [])}


@router.post("/sources")
def add_source(body: SourceInput):
    """添加插件源（Git URL）。"""
    data = _load_data()
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "源 URL 不能为空")
    if url in data["sources"]:
        raise HTTPException(409, f"源已存在: {url}")
    data["sources"].append(url)
    _save_data(data)
    return {"added": True, "url": url}


@router.delete("/sources/{url:path}")
def remove_source(url: str):
    """移除插件源。

    路径参数 url:path 匹配剩余路径，支持含斜杠的 Git URL。
    """
    data = _load_data()
    # url:path 捕获的 URL 可能被 URL 解码过，直接做精确匹配
    sources = data.get("sources", [])
    if url not in sources:
        raise HTTPException(404, f"源不存在: {url}")
    sources.remove(url)
    _save_data(data)
    return {"removed": True, "url": url}


# ---- 端点：Plugin 打包交付（6.12）----


class PackInput(BaseModel):
    """插件打包请求。"""
    plugin_dir: str
    output_path: str | None = None


class InstallPackageInput(BaseModel):
    """插件包安装请求。"""
    package_path: str
    force: bool = False


def _extensions_dir() -> Path:
    """扩展安装根目录。"""
    cfg = load_config()
    d = cfg.project_data_dir / "extensions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/pack")
def pack_plugin_endpoint(body: PackInput):
    """把插件目录打包为 .napkg。"""
    from novel_agent.plugin_system.packaging import PackagingError, pack_plugin
    try:
        return pack_plugin(body.plugin_dir, body.output_path)
    except PackagingError as e:
        raise HTTPException(400, str(e))


@router.post("/verify-package")
def verify_package_endpoint(body: InstallPackageInput):
    """校验 .napkg 包（不安装）。"""
    from novel_agent.plugin_system.packaging import PackagingError, verify_package
    try:
        return verify_package(body.package_path).to_dict()
    except PackagingError as e:
        raise HTTPException(400, str(e))


@router.post("/install-package")
def install_package_endpoint(body: InstallPackageInput):
    """从 .napkg 安装插件到 extensions 目录。"""
    from novel_agent.plugin_system.packaging import PackagingError, install_package
    try:
        return install_package(body.package_path, _extensions_dir(), force=body.force)
    except PackagingError as e:
        raise HTTPException(400, str(e))


# ---- 端点：资产化导出/导入（6.13）----


class ExportAssetsInput(BaseModel):
    """资产导出请求。"""
    output_path: str
    include: list[str] = ["skills", "rules", "preset_phrases"]


class ImportAssetsInput(BaseModel):
    """资产导入请求。"""
    package_path: str
    strategy: str = "merge"  # merge / overwrite


@router.post("/assets/export")
def export_assets_endpoint(body: ExportAssetsInput):
    """导出 Skill/Rule/预设短语为 .naassets 资产包。"""
    from novel_agent.plugin_system.assets import AssetsError, export_assets
    try:
        return export_assets(body.output_path, include=tuple(body.include))
    except AssetsError as e:
        raise HTTPException(400, str(e))


@router.post("/assets/inspect")
def inspect_assets_endpoint(body: ImportAssetsInput):
    """查看资产包内容摘要（不导入）。"""
    from novel_agent.plugin_system.assets import AssetsError, inspect_assets
    try:
        return inspect_assets(body.package_path)
    except AssetsError as e:
        raise HTTPException(400, str(e))


@router.post("/assets/import")
def import_assets_endpoint(body: ImportAssetsInput):
    """导入 .naassets 资产包（merge/overwrite 两种策略）。"""
    from novel_agent.plugin_system.assets import AssetsError, import_assets
    try:
        return import_assets(body.package_path, strategy=body.strategy)
    except AssetsError as e:
        raise HTTPException(400, str(e))
