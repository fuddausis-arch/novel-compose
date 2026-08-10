"""跨章语义去重扫描器：用方舟 Embedding 检测重复场景。

冷路径运行，不进写作热路径。
调用时机：审计阶段（audit节点后），作为软信号注入audit_report。不阻塞生成。
"""
from __future__ import annotations

import logging
from typing import Any

from novel_agent.config import Config

logger = logging.getLogger(__name__)


class DedupScanner:
    """跨章语义去重扫描器。"""

    def __init__(self, config: Config, project_id: int | None = None):
        self._config = config
        self._project_id = project_id
        self._archival = None

    def _get_archival(self):
        """延迟初始化 ArchivalMemory（避免启动时加载 embedding 模型）。"""
        if self._archival is None:
            try:
                from novel_agent.memory.archival import ArchivalMemory
                self._archival = ArchivalMemory(self._config, project_id=self._project_id)
            except Exception as e:
                logger.warning("DedupScanner: ArchivalMemory 初始化失败: %s", e)
                return None
        return self._archival

    def scan_chapter(self, chapter: int, draft_text: str,
                     top_k: int = 5) -> list[dict]:
        """扫描本章正文是否和已有章节语义重复。

        Returns:
            重复项列表，每项含 chapter/similarity/matched_content。
            空列表=无重复。
        """
        archival = self._get_archival()
        if not archival:
            return []

        # 用正文检索历史章节
        query_text = draft_text
        try:
            results = archival.retrieve(query=query_text, top_k=top_k)
        except Exception as e:
            logger.warning("DedupScanner scan_chapter 检索失败: %s", e)
            return []

        duplicates = []
        if results and results.get("documents") and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0], results["metadatas"][0], results["distances"][0]
            ):
                # 排除当前章
                ch = meta.get("chapter") if meta else None
                if ch == chapter:
                    continue
                if dist < 0.3:  # 余弦距离<0.3=高度相似
                    duplicates.append({
                        "chapter": ch,
                        "similarity": round(1 - dist, 2),
                        "matched_content": (doc or "")[:80],
                    })
        return duplicates

    def check_beat_freshness(self, chapter: int, beat_type: str,
                             beat_desc: str) -> bool:
        """检查这个爽点类型最近有没有写过相似的。

        Returns:
            True=新鲜（可写），False=最近写过相似的（不新鲜）。
        """
        archival = self._get_archival()
        if not archival:
            return True  # 无法检测时默认新鲜

        query = f"{beat_type} {beat_desc}"
        try:
            results = archival.retrieve(query=query, top_k=3)
        except Exception as e:
            logger.warning("DedupScanner check_beat_freshness 检索失败: %s", e)
            return True

        if results and results.get("documents") and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0], results["metadatas"][0], results["distances"][0]
            ):
                ch = meta.get("chapter") if meta else None
                if ch == chapter:
                    continue
                if dist < 0.25:
                    logger.info("beat_freshness: %s 与第%d章相似(distance=%.3f)",
                                beat_type, ch, dist)
                    return False
        return True
