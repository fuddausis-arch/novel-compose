"""Archival memory：向量库，按需检索章节/设定切片。

spec 2.1：Chroma 存全章节切块 + 设定条目；
检索用 recency × importance × relevance 三因子（M1 简化为 relevance）。
"""
from __future__ import annotations

import uuid
from typing import Any

import chromadb

from novel_agent.config import Config


class ArchivalMemory:
    """Chroma 向量检索。"""

    def __init__(self, config: Config):
        self.config = config
        config.chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(config.chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name="novel_archive",
            metadata={"hnsw:space": "cosine"},
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
        # M1 用 chromadb 默认 all-MiniLM-L6-v2（中文支持弱）；M2 换 bge-small-zh
        # 等中文 embedding 模型提升召回准确性。
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
            name="novel_archive", metadata={"hnsw:space": "cosine"},
        )
