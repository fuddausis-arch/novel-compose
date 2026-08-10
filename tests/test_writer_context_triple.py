"""测试写手上下文三合一（P0）：实体历史提及提取与格式化。

覆盖：
1. _extract_chapter_entities：从大纲约束 + 最近章节正文提取本章实体
2. _format_entity_history_for_prompt：mention/久远实体重点提示，普通实体不刷屏
3. _format_volume_summary_for_prompt：最近章节摘要注入
"""
from __future__ import annotations

import json

from novel_agent.api.routes_generation import (
    _extract_chapter_entities,
    _format_entity_history_for_prompt,
    _format_volume_summary_for_prompt,
)


class _Outline:
    def __init__(self, constraints_json: str | None):
        self.character_constraints = constraints_json


class _Char:
    def __init__(self, name):
        self.name = name


class _Appearance:
    def __init__(self, chapter, role, snippet, entity_id="张三"):
        self.chapter = chapter
        self.role_in_chapter = role
        self.context_snippet = snippet
        self.entity_id = entity_id


class _Summary:
    def __init__(self, chapter, events):
        self.chapter = chapter
        self.core_events = events


class _FakeRepo:
    def __init__(self, chars=None, outline=None, appearances=None, summaries=None):
        self._chars = chars or []
        self._outline = outline
        self._appearances = appearances or []
        self._summaries = summaries or []

    def get_outline_by_chapter(self, chapter):
        return self._outline

    def list_characters(self):
        return self._chars

    def list_entity_appearances(self, entity_type=None, entity_id=None, chapter=None):
        apps = [a for a in self._appearances if a.chapter < 9999]
        if entity_id is not None:
            apps = [a for a in apps if a.entity_id == entity_id]
        return apps


class TestExtractChapterEntities:
    def test_from_outline_constraints(self):
        """大纲 character_constraints 的 key（且是已知角色）应被提取"""
        outline = _Outline(json.dumps({"林晚": {"location": "苏城"}, "张三": {"emotion": "愤怒"}}))
        repo = _FakeRepo(chars=[_Char("林晚"), _Char("张三")], outline=outline)
        assert set(_extract_chapter_entities(repo, 40, [])) == {"林晚", "张三"}

    def test_structured_fields_filtered(self):
        """大纲回退到 arc/volume 级时，character_focus 等结构化字段不得被当角色名"""
        outline = _Outline(json.dumps({
            "character_focus": ["林晚"],
            "emotion_arc": "压抑",
            "pacing_intent": "紧张",
            "林晚": {"location": "苏城"},
        }))
        repo = _FakeRepo(chars=[_Char("林晚"), _Char("张三")], outline=outline)
        assert _extract_chapter_entities(repo, 40, []) == ["林晚"]

    def test_from_recent_text(self):
        """最近章节正文中出现的已知角色应被提取"""
        chars = [_Char("林晚"), _Char("苏瑶"), _Char("萧云")]
        repo = _FakeRepo(chars=chars)
        names = _extract_chapter_entities(repo, 40, ["林晚推开门，苏瑶跟在后面。"])
        assert "林晚" in names and "苏瑶" in names
        assert "萧云" not in names

    def test_outline_failure_ignored(self):
        """大纲无约束时应回退到正文提取，不抛错"""
        repo = _FakeRepo(chars=[_Char("林晚")], outline=None)
        names = _extract_chapter_entities(repo, 40, ["林晚走向城门。"])
        assert names == ["林晚"]


class TestFormatEntityHistory:
    def test_mention_highlighted(self):
        """role=mention 的实体应被重点提示（含最早章节与上下文）"""
        apps = [
            _Appearance(3, "mention", "新闻里提到杀人犯张三的名字"),
            _Appearance(40, "lead", "张三出现了"),
        ]
        repo = _FakeRepo(appearances=apps)
        text = _format_entity_history_for_prompt(repo, 41, ["张三"])
        assert "张三" in text
        assert "第3章" in text
        assert "提及" in text
        assert "新闻里提到杀人犯张三" in text[:200]

    def test_ancient_entity_highlighted(self):
        """最早出场距今 >= 10 章的实体应提示"""
        apps = [_Appearance(3, "participant", "张三与人同行")]
        repo = _FakeRepo(appearances=apps)
        text = _format_entity_history_for_prompt(repo, 40, ["张三"])
        assert "张三" in text
        assert "第3章" in text

    def test_recent_participant_not_flagged(self):
        """最近刚出场且 role 非 mention 的实体不应刷屏"""
        apps = [_Appearance(39, "participant", "张三与人同行")]
        repo = _FakeRepo(appearances=apps)
        assert _format_entity_history_for_prompt(repo, 40, ["张三"]) == ""

    def test_empty_input(self):
        repo = _FakeRepo()
        assert _format_entity_history_for_prompt(repo, 40, []) == ""


class TestFormatVolumeSummary:
    def test_last_10_summaries(self):
        summaries = [_Summary(i, f"第{i}章核心事件") for i in range(1, 15)]
        repo = _FakeRepo(summaries=summaries)
        text = _format_volume_summary_for_prompt(repo, 15, summaries)
        assert "第14章" in text
        assert "第1章" not in text  # 只取最近10章
        assert text.startswith("【近期剧情摘要")

    def test_empty(self):
        assert _format_volume_summary_for_prompt(_FakeRepo(), 1, []) == ""
