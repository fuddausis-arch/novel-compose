"""扩展 API 契约层。

registrar.py（注册器）已移至 novel_agent/_archive_extensions/（只被已归档的
manager 调用）。本目录仅保留 models.py（扩展数据模型，被 extension_host.manifest 依赖）。
"""
from novel_agent.extension_api.models import *  # noqa: F401,F403
