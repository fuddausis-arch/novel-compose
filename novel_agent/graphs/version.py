"""图谱脏标记：内容版本计数，判断"剧情数据是否比图谱新"。

原理：
- 写章入口（RecallMemory.save_chapter_text / commit / postprocess / bridge）
  调用 bump_content()，项目内容版本 +1。
- 图谱保存/生成入口调用 mark_graph_generated()，记录该图生成时的内容版本。
- dirty = content_version > graph_version（内容变过、图谱没重新生成过）。

数据存 project_data/projects/{id}/graph_version.json：
    {"content": N, "graphs": {graph_id: N}}

无数据库依赖、无状态冲突；文件不存在时默认 content=0。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _version_path(project_id: int) -> Path:
    from novel_agent.config import load_config
    cfg = load_config()
    return cfg.project_data_dir / "projects" / str(project_id) / "graph_version.json"


def _load(project_id: int) -> dict:
    path = _version_path(project_id)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取图谱版本文件失败（将重建）: %s", e)
    return {"content": 0, "graphs": {}}


def _save(project_id: int, data: dict) -> None:
    path = _version_path(project_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("写入图谱版本文件失败: %s", e)


def bump_content(project_id: int) -> int:
    """内容变更：写章/大纲等剧情数据更新后调用，返回新的内容版本号。

    测试内存库（NOVEL_TEST_DB=memory）下跳过文件副作用，避免污染真实数据目录。
    """
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return 0
    with _lock:
        data = _load(project_id)
        data["content"] = int(data.get("content", 0)) + 1
        _save(project_id, data)
        return data["content"]


def mark_graph_generated(project_id: int, graph_id: int | None) -> None:
    """图谱生成/保存后调用：记录该图的内容版本（graph_id=None 表示整类图谱全部刷新）。"""
    if graph_id is None:
        return
    if os.getenv("NOVEL_TEST_DB") == "memory":
        return
    with _lock:
        data = _load(project_id)
        graphs = data.setdefault("graphs", {})
        if isinstance(graphs, dict):
            graphs[str(graph_id)] = int(data.get("content", 0))
            _save(project_id, data)


def is_graph_dirty(project_id: int, graph_id: int) -> bool:
    """该图谱是否需要刷新：内容版本 > 图谱生成时版本。"""
    data = _load(project_id)
    content = int(data.get("content", 0))
    graphs = data.get("graphs", {}) if isinstance(data.get("graphs", {}), dict) else {}
    graph_ver = int(graphs.get(str(graph_id), -1))
    return content > graph_ver


def get_content_version(project_id: int) -> int:
    return int(_load(project_id).get("content", 0))
