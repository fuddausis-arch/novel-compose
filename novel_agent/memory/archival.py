"""Archival memory：向量库，按需检索章节/设定切片。

spec 2.1：Chroma 存全章节切块 + 设定条目；
检索用 recency × importance × relevance 三因子（M1 简化为 relevance）。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import chromadb

from novel_agent.config import Config

logger = logging.getLogger(__name__)

# 中文 embedding 模型，中文语义检索效果远优于默认的 all-MiniLM-L6-v2
_ZH_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
_FALLBACK_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _build_embedding_function():
    """构建 embedding 函数。

    优先使用 BAAI/bge-small-zh-v1.5（中文 embedding 模型）；
    若 sentence_transformers 未安装或模型下载失败，回退到 chromadb 默认
    all-MiniLM-L6-v2 并打印 warning，中文语义检索效果会偏弱。
    """
    try:
        from chromadb.utils import embedding_functions
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=_ZH_EMBEDDING_MODEL
        )
        logger.info("archival memory 使用中文 embedding 模型 %s", _ZH_EMBEDDING_MODEL)
        return ef
    except Exception as e:  # ImportError / 模型下载失败等
        logger.warning(
            "加载中文 embedding 模型 %s 失败（%s），回退到默认 %s，"
            "中文语义检索效果可能较弱",
            _ZH_EMBEDDING_MODEL, e, _FALLBACK_EMBEDDING_MODEL,
        )
        return None


class ArchivalMemory:
    """Chroma 向量检索。"""

    def __init__(self, config: Config, project_id: int | None = None):
        self.config = config
        self.project_id = project_id
        if project_id is not None:
            chroma_dir = config.project_chroma_dir(project_id)
        else:
            # 兼容旧调用
            chroma_dir = config.chroma_dir
        chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(chroma_dir))
        # 显式指定中文 embedding 模型；不可用时回退到 chromadb 默认
        # all-MiniLM-L6-v2（embedding_function 为 None 时 chromadb 用默认）
        self._embedding_function = _build_embedding_function()
        self._collection = self._client.get_or_create_collection(
            name="novel_archive",
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_function,
        )

    def index_chapter(self, chapter: int, title: str, content: str) -> None:
        doc_id = f"ch{chapter}_{uuid.uuid4().hex[:8]}"
        self._collection.add(
            ids=[doc_id],
            documents=[f"第{chapter}章《{title}》\n{content}"],
            metadatas=[{"type": "chapter", "chapter": chapter, "title": title}],
        )

    def index_setting(self, category: str, title: str, content: str) -> None:
        doc_id = f"set_{uuid.uuid4().hex[:8]}"
        self._collection.add(
            ids=[doc_id],
            documents=[f"【{category}：{title}】\n{content}"],
            metadatas=[{"type": "setting", "category": category, "title": title}],
        )

    def retrieve(self, query: str, top_k: int = 4,
                 chapter_filter: int | None = None) -> list[dict[str, Any]]:
        if self._collection.count() == 0:
            return []
        where = None
        if chapter_filter is not None:
            where = {"chapter": chapter_filter}
        res = self._collection.query(
            query_texts=[query], n_results=top_k, where=where,
        )
        results = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i, doc in enumerate(docs):
            results.append({
                "id": ids[i],
                "content": doc,
                "metadata": metas[i],
                "distance": dists[i],
                "chapter": metas[i].get("chapter"),
            })
        return results

    def reset(self) -> None:
        self._client.delete_collection("novel_archive")
        self._collection = self._client.get_or_create_collection(
            name="novel_archive",
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_function,
        )
