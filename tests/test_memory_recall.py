"""测试 Recall：全量原文 + 事件时间线查询。"""
import pytest
from pathlib import Path

from novel_agent.config import Config
from novel_agent.memory.recall import RecallMemory


@pytest.fixture
def recall(tmp_config):
    recall = RecallMemory(tmp_config)
    # 写一章正文
    recall.save_chapter_text(chapter=1, title="无声征召",
                             content="刘洋在修理厂修车……（正文）")
    yield recall


def test_save_and_read_chapter_text(recall):
    text = recall.read_chapter_text(chapter=1)
    assert "刘洋" in text
    assert "无声征召" in text


def test_read_nonexistent_chapter(recall):
    text = recall.read_chapter_text(chapter=999)
    assert text == ""


def test_list_chapters(recall):
    recall.save_chapter_text(chapter=2, title="火种", content="第二章正文")
    chapters = recall.list_chapters()
    assert 1 in chapters
    assert 2 in chapters
