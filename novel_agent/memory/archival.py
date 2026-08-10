"""Archival memory：向量库，按需检索章节/设定切片。

spec 2.1：Chroma 存全章节切块 + 设定条目；
检索用 recency × importance × relevance 三因子（M1 简化为 relevance）。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from novel_agent.config import Config

logger = logging.getLogger(__name__)


def _build_embedding_function(config: Config):
    """构建 embedding 函数。

    优先使用方舟 doubao-embedding-vision API（云端推理，无需本地模型）；
    若未配置 embedding API key，回退到本地 BAAI/bge-small-zh-v1.5。
    """
    from chromadb.utils import embedding_functions

    # 优先：方舟 embedding API（OpenAI 兼容协议）
    emb_api_key = getattr(config, "embedding_api_key", "") or ""
    if emb_api_key:
        emb_base_url = getattr(config, "embedding_base_url", "") or config.llm.base_url
        emb_model = getattr(config, "embedding_model", "") or "doubao-embedding-vision"
        try:
            ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=emb_api_key,
                api_base=emb_base_url.rstrip("/"),
                model_name=emb_model,
            )
            logger.info("archival memory 使用方舟 embedding API: %s (base=%s)", emb_model, emb_base_url)
            return ef
        except Exception as e:
            logger.warning("方舟 embedding API 初始化失败(%s)，回退到本地模型", e)

    # 回退：本地中文 embedding 模型
    zh_model = "BAAI/bge-small-zh-v1.5"
    try:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=zh_model)
        logger.info("archival memory 使用本地中文 embedding 模型 %s", zh_model)
        return ef
    except Exception as e:
        logger.warning("加载本地 embedding 模型 %s 失败(%s)，回退到 chromadb 默认", zh_model, e)
        return None


class ArchivalMemory:
    """Chroma 向量检索。"""

    def __init__(self, config: Config, project_id: int | None = None):
        self.config = config
        self.project_id = project_id
        self._client = None
        self._collection = None
        self._embedding_function = None
        if project_id is not None:
            chroma_dir = config.project_chroma_dir(project_id)
        else:
            # 兼容旧调用
            chroma_dir = config.chroma_dir
        # 延迟 import chromadb，避免启动期加载触发模型下载或卡死；
        # chroma 数据损坏/锁/依赖缺失时初始化失败 → 降级为不可用，不抛异常崩溃
        try:
            chroma_dir.mkdir(parents=True, exist_ok=True)
            import chromadb
            self._client = chromadb.PersistentClient(path=str(chroma_dir))
            # 显式指定 embedding 模型；不可用时回退到 chromadb 默认
            # all-MiniLM-L6-v2（embedding_function 为 None 时 chromadb 用默认）
            self._embedding_function = _build_embedding_function(config)
            self._collection = self._client.get_or_create_collection(
                name="novel_archive",
                metadata={"hnsw:space": "cosine"},
                embedding_function=self._embedding_function,
            )
            # 检测embedding维度是否匹配（旧collection可能是384维本地模型建的）
            self._ensure_dimension_compat()
        except Exception as e:
            self._client = None
            self._collection = None
            self._embedding_function = None
            logger.warning("ArchivalMemory 初始化失败，向量记忆降级为不可用: %s", e)

    def is_available(self) -> bool:
        """向量库是否可用（初始化失败时返回 False，调用方走降级路径）。"""
        return self._client is not None

    def _ensure_dimension_compat(self):
        """检测collection的embedding维度是否和当前模型匹配，不匹配则重建。"""
        if self._collection.count() == 0:
            return  # 空collection不需要检测
        try:
            self._collection.query(query_texts=["test"], n_results=1)
        except Exception as e:
            if "dimension" in str(e).lower() or "384" in str(e):
                logger.warning("embedding维度不匹配，删除旧collection重建: %s", e)
                self._client.delete_collection("novel_archive")
                self._collection = self._client.get_or_create_collection(
                    name="novel_archive",
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=self._embedding_function,
                )
                logger.info("novel_archive collection已重建（旧数据需要重新索引）")

    def _get_collection(self, name: str):
        """按名获取/创建 collection。

        chapters 映射到主 collection（index_chapter 写入处）；
        references 为独立 collection 供 index_reference 使用。
        """
        if name == "chapters":
            return self._collection
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_function,
        )

    def index_chapter(self, chapter: int, title: str, content: str) -> None:
        if self._client is None:
            return
        # 先清理该章旧切片，避免章节重写后旧版本永久残留、检索召回过期内容
        try:
            self._collection.delete(where={"chapter": chapter, "type": "chapter"})
        except Exception:
            pass  # 空 collection 或 where 无匹配时容忍
        doc_id = f"ch{chapter}_{uuid.uuid4().hex[:8]}"
        self._collection.add(
            ids=[doc_id],
            documents=[f"第{chapter}章《{title}》\n{content}"],
            metadatas=[{"type": "chapter", "chapter": chapter, "title": title}],
        )

    def index_setting(self, category: str, title: str, content: str) -> None:
        if self._client is None:
            return
        # 先按 category+title 清理旧条目，避免同名设定重写后旧版本残留
        try:
            self._collection.delete(where={"category": category, "title": title, "type": "setting"})
        except Exception:
            pass
        doc_id = f"set_{uuid.uuid4().hex[:8]}"
        self._collection.add(
            ids=[doc_id],
            documents=[f"【{category}：{title}】\n{content}"],
            metadatas=[{"type": "setting", "category": category, "title": title}],
        )

    def index_reference(self, filename: str, content: str, source: str = "user_upload"):
        """索引用户上传的参考文档（切片后入库）。

        简单切片：按段落（双换行）切，每片最多 1000 字。
        """
        try:
            if self._client is None:
                return
            coll = self._get_collection("references")
            # 先清理同名旧文档：ids 固定为 ref_{filename}_{i}，重复上传同名文件 add 会因
            # id 已存在抛异常被吞，且旧内容会残留
            try:
                coll.delete(where={"filename": filename})
            except Exception:
                pass  # 无同名旧文档时容忍
            # 按段落切片
            chunks = []
            for para in content.split("\n\n"):
                para = para.strip()
                if not para:
                    continue
                # 长段落再按句号切
                if len(para) > 1000:
                    sentences = para.replace("。", "。\n").split("\n")
                    buf = ""
                    for s in sentences:
                        if len(buf) + len(s) > 1000:
                            if buf:
                                chunks.append(buf)
                            buf = s
                        else:
                            buf += s
                    if buf:
                        chunks.append(buf)
                else:
                    chunks.append(para)
            if not chunks:
                return
            ids = [f"ref_{filename}_{i}" for i in range(len(chunks))]
            metadatas = [{"filename": filename, "source": source, "chapter": -1} for _ in chunks]
            coll.add(documents=chunks, ids=ids, metadatas=metadatas)
            logger.info("参考文档已索引: %s (%d 片段)", filename, len(chunks))
        except Exception as e:
            logger.warning("index_reference 失败: %s", e)

    def retrieve(self, query: str, top_k: int = 4,
                 chapter_filter: int | None = None) -> dict:
        """语义检索 chapters + references 两个 collection，合并后按距离排序取 top_k。

        Returns:
            dict 格式：{"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        """
        results = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        if self._client is None:
            return results
        for coll_name in ["chapters", "references"]:
            try:
                coll = self._get_collection(coll_name)
                if coll.count() == 0:
                    continue
                where = None
                if chapter_filter is not None and coll_name == "chapters":
                    where = {"chapter": {"$lte": chapter_filter}}
                kwargs = {"query_texts": [query], "n_results": top_k}
                if where:
                    kwargs["where"] = where
                r = coll.query(**kwargs)
                if r and r.get("documents") and r["documents"][0]:
                    results["ids"][0].extend(r["ids"][0])
                    results["documents"][0].extend(r["documents"][0])
                    results["metadatas"][0].extend(r["metadatas"][0])
                    results["distances"][0].extend(r["distances"][0])
            except Exception as e:
                logger.warning("retrieve from %s 失败: %s", coll_name, e)
        # 按距离排序取 top_k
        if results["documents"][0]:
            paired = list(zip(
                results["distances"][0], results["documents"][0],
                results["metadatas"][0], results["ids"][0],
            ))
            paired.sort(key=lambda x: x[0])
            paired = paired[:top_k]
            results["distances"][0] = [p[0] for p in paired]
            results["documents"][0] = [p[1] for p in paired]
            results["metadatas"][0] = [p[2] for p in paired]
            results["ids"][0] = [p[3] for p in paired]
        return results

    def reset(self) -> None:
        if self._client is None:
            return
        self._client.delete_collection("novel_archive")
        self._collection = self._client.get_or_create_collection(
            name="novel_archive",
            metadata={"hnsw:space": "cosine"},
            embedding_function=self._embedding_function,
        )
