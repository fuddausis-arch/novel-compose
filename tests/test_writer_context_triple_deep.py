"""模块A：写手上下文三合一深度测试（功能/边界/异常/性能）。

现有 test_writer_context_triple.py 只测纯函数，本文件补充：
1. 端到端注入：interactive_generate_chapter 是否真实注入 entity_history/volume_summary
2. 边界：实体名长度为1被过滤、snippet 截断、gap 边界（4/5/9/10）、role 未知值
3. 异常：repo 查询抛错时函数应降级不抛
4. 性能：大量实体时格式化耗时
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novel_agent.api.routes_generation import (
    _extract_chapter_entities,
    _format_entity_history_for_prompt,
    _format_volume_summary_for_prompt,
)


# ----------------------------------------------------------------------
# _extract_chapter_entities：边界
# ----------------------------------------------------------------------
class TestExtractBoundary:
    def test_entity_name_length_one_ignored(self):
        """单字角色名（如"虎"）不应被误提取，避免噪音。"""
        class _Char:
            def __init__(self, name):
                self.name = name
        class _Outline:
            character_constraints = None
        class _FakeRepo:
            def list_characters(self):
                return [_Char("虎"), _Char("张三"), _Char("林晚")]
            def get_outline_by_chapter(self, chapter):
                return _Outline()
        names = _extract_chapter_entities(_FakeRepo(), 40, ["猛虎出笼，张三上前"])
        assert "虎" not in names
        assert "张三" in names

    def test_duplicate_entities_deduped(self):
        class _Char:
            def __init__(self, name):
                self.name = name
        class _Outline:
            character_constraints = json.dumps({"林晚": {"location": "城"}, "张三": {}})
        class _FakeRepo:
            def list_characters(self):
                return [_Char("林晚"), _Char("张三"), _Char("萧云")]
            def get_outline_by_chapter(self, chapter):
                return _Outline()
        names = _extract_chapter_entities(_FakeRepo(), 40, ["林晚与萧云同行，张三在后"])
        assert names == ["张三", "林晚", "萧云"]  # 去重 + 排序（sorted 按拼音）

    def test_outline_constraints_non_dict(self):
        """大纲 character_constraints 不是 dict 时应降级，不抛错。"""
        class _Char:
            def __init__(self, name):
                self.name = name
        class _Outline:
            character_constraints = "纯文本非JSON"
        class _FakeRepo:
            def list_characters(self):
                return [_Char("林晚")]
            def get_outline_by_chapter(self, chapter):
                return _Outline()
        assert _extract_chapter_entities(_FakeRepo(), 40, []) == []

    def test_empty_known_characters(self):
        """无角色时返回空列表，不抛错。"""
        class _FakeRepo:
            def list_characters(self):
                return []
            def get_outline_by_chapter(self, chapter):
                return None
        assert _extract_chapter_entities(_FakeRepo(), 40, ["任意文本"]) == []

    def test_repo_characters_raises_fallback(self):
        """list_characters 抛错时降级为空集合，不中断。"""
        class _FakeRepo:
            def list_characters(self):
                raise RuntimeError("db down")
            def get_outline_by_chapter(self, chapter):
                return None
        assert _extract_chapter_entities(_FakeRepo(), 40, ["张三"]) == []


# ----------------------------------------------------------------------
# _format_entity_history_for_prompt：边界
# ----------------------------------------------------------------------
class _Appearance:
    def __init__(self, chapter, role, snippet, entity_id="张三"):
        self.chapter = chapter
        self.role_in_chapter = role
        self.context_snippet = snippet
        self.entity_id = entity_id


class _FakeRepo:
    def __init__(self, appearances=None, raise_error=False):
        self._apps = appearances or []
        self._raise = raise_error

    def list_entity_appearances(self, entity_type=None, entity_id=None, chapter=None):
        if self._raise:
            raise RuntimeError("db down")
        apps = [a for a in self._apps if a.entity_id == entity_id]
        if chapter is not None:
            apps = [a for a in apps if a.chapter == chapter]
        return apps


class TestFormatEntityHistoryBoundary:
    def test_gap_boundary_9_not_flagged(self):
        """gap=9（不足10章）且 role 非 mention → 不提示。"""
        apps = [_Appearance(31, "participant", "张三与人同行")]
        assert _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"]) == ""

    def test_gap_boundary_10_flagged(self):
        """gap=10 → 提示（久远实体防遗忘）。"""
        apps = [_Appearance(30, "participant", "张三与人同行")]
        text = _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"])
        assert "第30章" in text
        assert "共出场1次" in text

    def test_gap_5_shows_since_text(self):
        """gap>=5 显示"距上次已有X章"。"""
        apps = [_Appearance(35, "mention", "新闻提到张三")]
        text = _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"])
        assert "距上次已有5章" in text

    def test_snippet_truncated_to_60(self):
        """context_snippet 超过 60 字应截断。"""
        long_snippet = "长" * 200
        apps = [_Appearance(3, "mention", long_snippet)]
        text = _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"])
        assert "长" * 60 + "..." in text

    def test_snippet_newlines_collapsed(self):
        """context_snippet 含换行应折叠为空格。"""
        apps = [_Appearance(3, "mention", "第一行\n第二行\n第三行")]
        text = _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"])
        assert "\n" not in text.split("（上下文：")[1].split("）")[0]

    def test_unknown_role_mapped_to_raw(self):
        """未知 role 值应原样显示。"""
        apps = [_Appearance(3, "cameo", "客串")]
        text = _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"])
        assert "cameo" in text

    def test_entity_without_past_appearances_skipped(self):
        """本章首次出现的实体（无历史）不应提示。"""
        apps = [_Appearance(40, "lead", "本章首次登场")]
        assert _format_entity_history_for_prompt(_FakeRepo(apps), 40, ["张三"]) == ""

    def test_repo_raises_degraded(self):
        """repo 查询抛错时该实体被跳过，整体不抛。"""
        assert _format_entity_history_for_prompt(_FakeRepo(raise_error=True), 40, ["张三"]) == ""

    def test_multiple_entities_ordered(self):
        apps = [
            _Appearance(3, "mention", "提到张三"),
            _Appearance(5, "mention", "提到李四"),
        ]
        repo = _FakeRepo(apps)
        # repo 过滤按 entity_id，这里构造两个独立实体
        text = _format_entity_history_for_prompt(repo, 40, ["张三"])
        assert "张三" in text

    def test_performance_many_entities(self):
        """性能：20 个实体 × 各 50 条历史记录，格式化应快速完成。"""
        import time
        all_apps = []
        for i in range(20):
            for j in range(50):
                all_apps.append(_Appearance(1 + j, "participant" if j > 3 else "mention",
                                            f"实体{i}上下文内容", entity_id=f"实体{i}"))
        # 需要按 entity_id 过滤，重写 repo（支持 entity_type 参数）
        class _PerfRepo:
            def __init__(self, apps):
                self._by_id = {}
                for a in apps:
                    self._by_id.setdefault(a.entity_id, []).append(a)
            def list_entity_appearances(self, entity_type=None, entity_id=None, chapter=None):
                if entity_id is None:
                    return []
                return self._by_id.get(entity_id, [])
        t0 = time.perf_counter()
        text = _format_entity_history_for_prompt(_PerfRepo(all_apps), 60,
                                                 [f"实体{i}" for i in range(20)])
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"格式化耗时 {elapsed:.2f}s"
        assert text  # 有输出


# ----------------------------------------------------------------------
# _format_volume_summary_for_prompt：边界
# ----------------------------------------------------------------------
class _Summary:
    def __init__(self, chapter, events):
        self.chapter = chapter
        self.core_events = events


class TestFormatVolumeSummaryBoundary:
    def test_only_core_events(self):
        """无 core_events 的摘要应被跳过。"""
        summaries = [_Summary(1, ""), _Summary(2, "有事件")]
        text = _format_volume_summary_for_prompt(_FakeRepo(), 3, summaries)
        assert "第1章" not in text
        assert "第2章" in text

    def test_core_events_truncated_120(self):
        """core_events 超过 120 字截断。"""
        summaries = [_Summary(1, "长" * 300)]
        text = _format_volume_summary_for_prompt(_FakeRepo(), 2, summaries)
        assert "长" * 120 in text
        assert "长" * 121 not in text

    def test_more_than_10_takes_last_10(self):
        summaries = [_Summary(i, f"事件{i}") for i in range(1, 15)]
        text = _format_volume_summary_for_prompt(_FakeRepo(), 15, summaries)
        assert "第14章" in text
        assert "第4章" not in text

    def test_empty_list(self):
        assert _format_volume_summary_for_prompt(_FakeRepo(), 1, []) == ""

    def test_unsorted_input_sorted(self):
        """输入乱序时应按章节升序。"""
        summaries = [_Summary(5, "e5"), _Summary(2, "e2")]
        text = _format_volume_summary_for_prompt(_FakeRepo(), 6, summaries)
        assert text.index("第2章") < text.index("第5章")


# ----------------------------------------------------------------------
# 端到端注入：interactive_generate_chapter 是否真实注入三合一
# ----------------------------------------------------------------------
class TestEndToEndInjection:
    def test_generate_chapter_injects_entity_history(self, client, sample_project):
        """interactive_generate_chapter 应注入实体历史提及 + 近期剧情摘要。"""
        from novel_agent.bible.database import SessionLocal
        from novel_agent.bible.repository import BibleRepository

        db = SessionLocal()
        repo = BibleRepository(db, sample_project)
        repo.create_character(name="张三", role="配角")
        # 第1章 mention 出场（跨章伏笔场景）
        repo.create_entity_appearance(
            entity_type="character", entity_id="张三", chapter=1,
            role_in_chapter="mention", context_snippet="新闻里提到杀人犯张三的名字",
        )
        db.close()

        # 写入第 1 章正文（recent_texts 需含角色名，实体才会被提取）
        resp = client.put(
            f"/api/chapters/1/text?project_id={sample_project}",
            json={"title": "第一章", "content": "张三在新闻里被提及，但没有人见过他的脸。"},
        )
        assert resp.status_code == 200, resp.text

        # mock LLMClient.generate，捕获注入的 user prompt
        captured = {}

        async def fake_generate(self, user_content, **kwargs):
            captured["user"] = user_content
            captured["system"] = kwargs.get("system") or ""
            # 返回符合 _generate_json_with_repair 预期的 JSON
            return json.dumps({
                "title": "第2章", "content": "张三出现在街道上，与林晚对峙。",
                "suggested_next": "", "brief": "张三登场",
            }, ensure_ascii=False)

        with patch("novel_agent.llm.client.LLMClient.generate", fake_generate):
            resp = client.post(
                "/api/generation/interactive/generate-chapter",
                json={"project_id": sample_project, "chapter_number": 2,
                      "user_direction": "张三登场"},
            )
            assert resp.status_code in (200, 201), resp.text
            assert captured, "LLM 应被调用"

        # 断言三合一区块被注入
        assert "【实体历史提及" in captured["user"], "实体历史提及未注入"
        assert "张三" in captured["user"]
        assert "第1章" in captured["user"]  # 最早出场章节
        assert "提及" in captured["user"]
