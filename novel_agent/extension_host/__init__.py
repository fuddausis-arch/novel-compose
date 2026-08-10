"""扩展宿主层。

manager.py（ExtensionHostManager）和 lifecycle.py（8 状态生命周期）从未被实例化，
已移至 novel_agent/_archive_extensions/。本目录仅保留 manifest.py（扩展清单解析，
被 plugin_system.packaging 依赖）。
"""
from novel_agent.extension_host.manifest import *  # noqa: F401,F403
