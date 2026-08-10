"""插件系统模块。

注意：PluginManager / PluginLifecycle（extension_host 宿主生命周期）从未被实例化，
已移至 novel_agent/_archive_extensions/。当前本模块只保留 packaging + assets
（被 routes_plugins.py 调用的活代码，用于插件打包和资产导入导出）。
"""
from __future__ import annotations

from novel_agent.plugin_system.packaging import (
    PackageInfo,
    PackagingError,
    install_package,
    pack_plugin,
    verify_package,
)
from novel_agent.plugin_system.assets import (
    AssetsError,
    export_assets,
    import_assets,
    inspect_assets,
)

__all__ = [
    "PackageInfo",
    "PackagingError",
    "install_package",
    "pack_plugin",
    "verify_package",
    "AssetsError",
    "export_assets",
    "import_assets",
    "inspect_assets",
]

