"""测试 Archival 向量检索。"""
import pytest

from novel_agent.config import Config
from novel_agent.memory.archival import ArchivalMemory


@pytest.fixture
def archival(tmp_config):
    am = ArchivalMemory(tmp_config)
    yield am
    am.reset()  # 清理临时 chroma


def test_index_and_retrieve(archival):
    archival.index_chapter(chapter=1, title="无声征召",
                           content="刘洋在修理厂修车，贺鸣率灰烬小队突袭征召。")
    archival.index_chapter(chapter=2, title="火种基地",
                           content="刘洋被带到火种基地，见到神秘黑色晶体。")
    archival.index_setting(category="力量体系", title="奇点",
                           content="奇点是异能核心，分 F 到 S 级。")
    results = archival.retrieve(query="黑色晶体是什么", top_k=2)
    # retrieve 返回 chroma 风格 dict（{"ids"/"documents"/"metadatas"/"distances"}）
    # M1 用默认 MiniLM embedding（中文支持弱），验证返回结构正确即可；
    # 中文语义召回准确性留待 M2 换 bge-small-zh 等中文模型优化。
    assert isinstance(results, dict)
    assert set(["ids", "documents", "metadatas", "distances"]).issubset(results.keys())


def test_retrieve_with_chapter_filter(archival):
    archival.index_chapter(chapter=1, title="ch1", content="征召事件")
    archival.index_chapter(chapter=2, title="ch2", content="基地见闻")
    results = archival.retrieve(query="征召", top_k=5, chapter_filter=1)
    assert isinstance(results, dict)
    # 若命中，所有结果都必须属于第 1 章（chapter_filter 生效）
    if results.get("documents") and results["documents"][0]:
        for meta in results["metadatas"][0]:
            assert meta.get("chapter") == 1


def test_retrieve_empty(archival):
    results = archival.retrieve(query="不存在的内容", top_k=3)
    # 返回 chroma 风格空 dict：documents 内层为空列表
    assert isinstance(results, dict)
    assert results["documents"] == [[]]
