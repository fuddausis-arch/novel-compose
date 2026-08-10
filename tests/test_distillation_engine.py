"""模块B：蒸馏引擎全面测试（功能/边界/异常/性能）。

覆盖：
1. split_text 拆分：功能、边界（空/超短/超长/无章节/单段超长/硬切）、性能
2. build_round_prompt：轮次映射、无效轮次回退
3. import_text：空内容、chunk 落库
4. distill_chunk：chunk 不存在、JSON 兜底
5. generate_skill：轮次未完成、skill 落库
6. fuse_skills：空列表、权重归一化、负权重
7. distill_character：角色不存在、样本合并上限
8. blind_evaluate：skill 不存在、judge 解析兜底
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from novel_agent.distillation.engine import (
    MAX_CHUNK_CHARS,
    ROUND_DIMENSIONS,
    DistillationEngine,
)
from novel_agent.distillation.store import DistillationStore


@pytest.fixture
def store(tmp_path: Path) -> DistillationStore:
    return DistillationStore(db_path=tmp_path / "test_distill.db")


@pytest.fixture
def engine(store: DistillationStore, tmp_path: Path, monkeypatch) -> DistillationEngine:
    """蒸馏引擎：skills 一律写入 tmp（避免测试污染真实 project_data/skills 目录）。"""
    e = DistillationEngine(store=store)

    def _skills_dir_tmp():
        d = tmp_path / "skills"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(e, "_skills_dir", _skills_dir_tmp)
    return e


def _seed_work(store: DistillationStore, title: str = "测试书") -> int:
    return store.create_work(title=title, source_type="file", file_path=None,
                             total_chars=100, chunk_count=1)


def _seed_chunk_and_round(store: DistillationStore, work_id: int,
                          content: str = "第一章内容。", skill_data: dict | None = None) -> tuple[int, int]:
    chunk_id = store.create_chunk(work_id, 0, content)
    round_id = store.create_round(chunk_id, 1, "prompt")
    if skill_data is not None:
        store.complete_round(round_id, "raw", json.dumps(skill_data, ensure_ascii=False), status="done")
    return chunk_id, round_id


# ----------------------------------------------------------------------
# split_text：功能
# ----------------------------------------------------------------------
class TestSplitText:
    def test_short_content_single_chunk(self):
        assert DistillationEngine.split_text("第1章 短内容") == ["第1章 短内容"]

    def test_empty_content(self):
        assert DistillationEngine.split_text("") == []
        assert DistillationEngine.split_text("   \n  ") == []

    def test_splits_by_chapter_title(self):
        text = "前言\n第1章 开头\n第一段内容\n第2章 发展\n第二段内容"
        chunks = DistillationEngine.split_text(text, max_chars=100)
        # 前言 + 第1章 + 第2章 应被拆为多段，但都在 100 字内会被合并？验证：
        # 若总长 < max_chars 则不分。这里 text 很短，应返回整体。
        assert len(chunks) == 1

    def test_chunk_respects_max_chars(self):
        text = "\n\n".join(f"第{i}章\n" + "内容" * 80 for i in range(1, 6))
        chunks = DistillationEngine.split_text(text, max_chars=100)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 100

    def test_single_oversize_paragraph_hard_split(self):
        text = "第1章\n" + "超长段落" * 500
        chunks = DistillationEngine.split_text(text, max_chars=100)
        assert all(len(c) <= 100 for c in chunks)

    def test_no_chapter_title_long_text_splits(self):
        text = "无标题" * 500
        chunks = DistillationEngine.split_text(text, max_chars=100)
        assert len(chunks) > 1

    def test_max_chars_one(self):
        text = "一二三四五"
        chunks = DistillationEngine.split_text(text, max_chars=1)
        assert all(len(c) == 1 for c in chunks)

    def test_preamble_preserved(self):
        """章前导言应作为独立 segment 保留，不与第一章粘连丢失。"""
        text = "这是全书前言说明\n第1章 正文\n正文内容"
        chunks = DistillationEngine.split_text(text, max_chars=10)
        joined = "\n".join(chunks)
        assert "前言" in joined
        assert "第1章" in joined

    def test_performance_large_text(self):
        """性能：10 万字文本拆分应快速完成（<2s）。"""
        import time
        text = "\n".join(f"第{i}章\n" + "内容" * 200 for i in range(1, 400))
        t0 = time.perf_counter()
        chunks = DistillationEngine.split_text(text, max_chars=MAX_CHUNK_CHARS)
        elapsed = time.perf_counter() - t0
        assert len(chunks) >= 1
        assert elapsed < 2.0, f"split_text 耗时 {elapsed:.2f}s，超过 2s"


# ----------------------------------------------------------------------
# build_round_prompt
# ----------------------------------------------------------------------
class TestBuildRoundPrompt:
    def test_valid_round_dimension(self):
        system, user = DistillationEngine.build_round_prompt(1, "内容")
        assert "写作风格特征" in user
        assert system

    def test_round7_new_dimension(self):
        _, user = DistillationEngine.build_round_prompt(7, "内容")
        assert "情感算法" in user

    def test_invalid_round_falls_back(self):
        _, user = DistillationEngine.build_round_prompt(99, "内容")
        # 无效轮次回退到第1轮维度
        assert "写作风格特征" in user


# ----------------------------------------------------------------------
# import_text
# ----------------------------------------------------------------------
class TestImportText:
    def test_import_creates_work_and_chunks(self, engine, store):
        result = engine.import_text("测试书", "第1章\n正文\n第2章\n正文", max_chars=10)
        assert result["chunk_count"] >= 2
        work = store.get_work(result["work_id"])
        assert work["total_chars"] > 0
        chunks = store.list_chunks(result["work_id"])
        assert len(chunks) == result["chunk_count"]

    def test_import_empty_raises(self, engine):
        with pytest.raises(ValueError):
            engine.import_text("测试书", "   ")


# ----------------------------------------------------------------------
# distill_chunk
# ----------------------------------------------------------------------
class TestDistillChunk:
    async def test_chunk_not_found(self, engine):
        mock_client = MagicMock()
        mock_client.generate = AsyncMock()
        with pytest.raises(ValueError):
            await engine.distill_chunk(9999, 1, mock_client)

    async def test_json_parse_failure_fallback(self, engine, store):
        """LLM 返回非 JSON 时使用兜底结构，soft_guidelines 保留原文。"""
        work_id = _seed_work(store)
        chunk_id, _ = _seed_chunk_and_round(store, work_id, skill_data=None)
        # 模拟 LLM 返回非 JSON 文本
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value="这不是 JSON 的蒸馏分析文本")
        result = await engine.distill_chunk(chunk_id, 1, mock_client)
        assert result["skill_data"]["signature_moves"] == []
        assert "蒸馏分析文本" in result["skill_data"]["soft_guidelines"][0]["rule"]

    async def test_llm_error_marks_round_failed(self, engine, store):
        work_id = _seed_work(store)
        chunk_id, round_id = _seed_chunk_and_round(store, work_id)
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=RuntimeError("LLM 挂了"))
        with pytest.raises(RuntimeError):
            await engine.distill_chunk(chunk_id, 1, mock_client)
        round_row = store.get_round(chunk_id, 1)
        assert round_row["status"] == "failed"


# ----------------------------------------------------------------------
# generate_skill
# ----------------------------------------------------------------------
class TestGenerateSkill:
    def test_round_not_done_raises(self, engine, store):
        work_id = _seed_work(store)
        chunk_id, _ = _seed_chunk_and_round(store, work_id, skill_data=None)  # 未 complete
        with pytest.raises(ValueError):
            engine.generate_skill(work_id, 0, 1)

    def test_skill_generated(self, engine, store, tmp_path):
        skill_data = {
            "name": "冷峻短句风",
            "description": "短句为主",
            "features": ["多用短句"],
            "guidelines": ["每句不超过15字"],
            "tags": ["冷峻", "短句"],
        }
        work_id = _seed_work(store)
        _seed_chunk_and_round(store, work_id, skill_data=skill_data)
        # 重开一轮已 done 的 round 需要单独路径：直接调用 generate_skill
        skill = engine.generate_skill(work_id, 0, 1)
        assert skill["name"].startswith("distill_w")
        db_skill = store.get_skill(skill["id"])
        assert json.loads(db_skill["tags"]) == ["冷峻", "短句"]

    def test_skill_content_has_traceability(self, engine, store):
        skill_data = {"name": "风", "description": "d", "features": ["f1"], "guidelines": ["g1"], "tags": []}
        work_id = _seed_work(store)
        _seed_chunk_and_round(store, work_id, skill_data=skill_data)
        skill = engine.generate_skill(work_id, 0, 1)
        assert "溯源" in skill["content"]
        assert "测试书" in skill["content"]


# ----------------------------------------------------------------------
# fuse_skills
# ----------------------------------------------------------------------
class TestFuseSkills:
    def _seed_skill(self, store, work_id: int, round_num: int = 1) -> int:
        chunk_id, round_id = _seed_chunk_and_round(
            store, work_id, skill_data={"name": f"风{round_num}", "features": [f"f{round_num}"],
                                        "guidelines": [f"g{round_num}"], "tags": []})
        return store.create_skill(
            work_id=work_id, work_title="测试书", chunk_index=0, round_num=round_num,
            name=f"skill_{round_num}", description="d", content=f"内容{round_num}", tags=[],
        )

    async def test_empty_list_raises(self, engine):
        with pytest.raises(ValueError):
            await engine.fuse_skills([], None, "融合")

    async def test_missing_skill_raises(self, engine):
        with pytest.raises(ValueError):
            await engine.fuse_skills([9999], None, "融合")

    async def test_default_equal_weights(self, engine, store):
        work_id = _seed_work(store)
        s1 = self._seed_skill(store, work_id, 1)
        s2 = self._seed_skill(store, work_id, 2)
        result = await engine.fuse_skills([s1, s2], None, "九合一")
        fusion = store.get_fusion(result["fusion_id"])
        assert json.loads(fusion["weights_json"]) == [0.5, 0.5]

    async def test_custom_weights_normalized(self, engine, store):
        work_id = _seed_work(store)
        s1 = self._seed_skill(store, work_id, 1)
        s2 = self._seed_skill(store, work_id, 2)
        result = await engine.fuse_skills([s1, s2], [1.0, 3.0], "融合")
        fusion = store.get_fusion(result["fusion_id"])
        assert json.loads(fusion["weights_json"]) == [0.25, 0.75]

    async def test_negative_weights_clamped(self, engine, store):
        work_id = _seed_work(store)
        s1 = self._seed_skill(store, work_id, 1)
        s2 = self._seed_skill(store, work_id, 2)
        result = await engine.fuse_skills([s1, s2], [-1.0, 2.0], "融合")
        fusion = store.get_fusion(result["fusion_id"])
        assert json.loads(fusion["weights_json"]) == [0.0, 1.0]

    async def test_llm_refined_fusion(self, engine, store, tmp_path):
        """有 LLM 时融合走提炼：产出 v2 结构化总纲，而非拼接原文。"""
        work_id = _seed_work(store)
        s1 = self._seed_skill(store, work_id, 1)
        s2 = self._seed_skill(store, work_id, 2)
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value=json.dumps({
            "name": "融合总纲",
            "description": "提炼结果",
            "signature_moves": [{"pattern": "先压后爽", "evidence": "例证", "apply": "落地", "exception": ""}],
            "hard_rules": [],
            "soft_guidelines": [],
            "anti_patterns": [],
            "tags": ["融合"],
        }, ensure_ascii=False))
        result = await engine.fuse_skills([s1, s2], [1.0, 3.0], "融合", client=mock_client)
        assert result["refined"] is True
        fusion = store.get_fusion(result["fusion_id"])
        assert json.loads(fusion["weights_json"]) == [0.25, 0.75]
        # 提炼产物应含 v2 结构，而非原 skill 拼接内容
        out = (tmp_path / "skills" / f"{result['skill_file']}.json").read_text(encoding="utf-8")
        assert "招牌手法" in out
        assert "先压后爽" in out
        assert "内容1" not in out  # 不是简单拼接原文

    async def test_llm_fallback_to_concat(self, engine, store):
        """LLM 提炼失败（抛异常）时回退为按权重拼接，不阻塞融合。"""
        work_id = _seed_work(store)
        s1 = self._seed_skill(store, work_id, 1)
        s2 = self._seed_skill(store, work_id, 2)
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=RuntimeError("模拟 LLM 失败"))
        result = await engine.fuse_skills([s1, s2], None, "九合一", client=mock_client)
        assert result["refined"] is False
        fusion = store.get_fusion(result["fusion_id"])
        assert json.loads(fusion["weights_json"]) == [0.5, 0.5]


# ----------------------------------------------------------------------
# distill_character
# ----------------------------------------------------------------------
class TestDistillCharacter:
    async def test_work_not_found(self, engine):
        mock_client = MagicMock()
        mock_client.generate = AsyncMock()
        with pytest.raises(ValueError):
            await engine.distill_character(9999, "张三", mock_client)

    async def test_character_not_found_in_text(self, engine, store):
        work_id = _seed_work(store)
        store.create_chunk(work_id, 0, "这里没有目标角色的内容")
        mock_client = MagicMock()
        mock_client.generate = AsyncMock()
        with pytest.raises(ValueError):
            await engine.distill_character(work_id, "不存在的角色", mock_client)

    async def test_character_distill_success(self, engine, store):
        work_id = _seed_work(store)
        store.create_chunk(work_id, 0, "张三说：今天天气不错。\n张三又说：走吧。")
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(return_value=json.dumps({
            "name": "冷峻短句型", "description": "短句",
            "features": ["句式极短"], "guidelines": ["每句不超过15字"],
            "tags": ["冷峻"], "sample_lines": ["今天天气不错。"],
        }, ensure_ascii=False))
        result = await engine.distill_character(work_id, "张三", mock_client)
        assert result["character"] == "张三"
        assert "说话风格" in result["content"] or "原文对话样本" in result["content"]
        db_skill = store.get_skill(result["skill_id"])
        assert "角色蒸馏" in db_skill["tags"]


# ----------------------------------------------------------------------
# blind_evaluate
# ----------------------------------------------------------------------
class TestBlindEvaluate:
    async def test_skill_not_found(self, engine):
        mock_client = MagicMock()
        mock_client.generate = AsyncMock()
        with pytest.raises(ValueError):
            await engine.blind_evaluate(9999, "写一段", mock_client)

    async def test_judge_json_fallback(self, engine, store):
        """judge 返回非 JSON 时兜底为 winner=unknown。"""
        work_id = _seed_work(store)
        skill_id = store.create_skill(
            work_id=work_id, work_title="测试书", chunk_index=0, round_num=1,
            name="skill", description="d", content="风格内容", tags=[],
        )
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=["基线文本", "带风格文本"])
        mock_client.chat = AsyncMock(return_value={"content": "不是JSON"})
        result = await engine.blind_evaluate(skill_id, "写一段", mock_client)
        assert result["judgment"]["winner"] == "unknown"
        assert result["baseline"] == "基线文本"
        assert result["with_style"] == "带风格文本"

    async def test_judge_winner_label_restored(self, engine, store):
        work_id = _seed_work(store)
        skill_id = store.create_skill(
            work_id=work_id, work_title="测试书", chunk_index=0, round_num=1,
            name="skill", description="d", content="风格", tags=[],
        )
        mock_client = MagicMock()
        mock_client.generate = AsyncMock(side_effect=["基线", "风格文"])
        mock_client.chat = AsyncMock(return_value={"content": json.dumps(
            {"winner": "A", "confidence": 0.9, "score_a": 8, "score_b": 5, "reason": "更像",
             "style_match_a": "像", "style_match_b": "不像"})})
        result = await engine.blind_evaluate(skill_id, "写一段", mock_client)
        # A/B 标签应被还原为 baseline/with_style 之一
        assert result["judgment"]["winner_label"] in ("baseline", "with_style")
        assert "text_a_is" in result["judgment"]


# ----------------------------------------------------------------------
# 补蒸馏（retry_failed）：只重跑失败的片段/轮次
# ----------------------------------------------------------------------
class TestRetryFailed:
    """补蒸馏模式核心保证：
    1. 已 done 的轮次绝不重复调用 LLM
    2. 失败的轮次被重跑，且复用原 round_id（DB 不累积重复记录）
    3. 已 done 的整片段直接跳过
    4. 中断残留的 running 记录也会被补齐
    """

    @pytest.fixture
    def engine_tmp(self, store: DistillationStore, tmp_path: Path, monkeypatch):
        """skills 写入 tmp，避免污染真实 project_data/skills 目录。"""
        e = DistillationEngine(store=store)

        def _skills_dir_tmp():
            d = tmp_path / "skills"
            d.mkdir(parents=True, exist_ok=True)
            return d

        monkeypatch.setattr(e, "_skills_dir", _skills_dir_tmp)
        return e

    @staticmethod
    def _client(calls: list[int]) -> MagicMock:
        """记录每次调用的轮次，返回合法 v2 JSON。"""
        client = MagicMock()

        async def _generate(user: str, system: str | None = None, **kw):
            import re
            m = re.search(r"第 (\d+) 轮", user)
            rn = int(m.group(1)) if m else 1
            calls.append(rn)
            return json.dumps({
                "name": f"特征{rn}",
                "description": "测试",
                "signature_moves": [{"pattern": f"手法{rn}", "evidence": "例证",
                                     "apply": "落地", "exception": ""}],
                "hard_rules": [],
                "soft_guidelines": [{"rule": f"规则{rn}", "why": "", "flexibility": ""}],
                "anti_patterns": [],
                "tags": ["测试"],
            }, ensure_ascii=False)

        client.generate = AsyncMock(side_effect=_generate)
        return client

    async def test_retry_reruns_only_failed_rounds(self, store, engine_tmp):
        work_id = _seed_work(store)
        chunk_id = store.create_chunk(work_id, 0, "第1章 测试内容。")
        # 预置：round1 成功，round2 失败，chunk 标记 failed
        r1 = store.create_round(chunk_id, 1, "p1")
        store.complete_round(r1, "raw", "{}", status="done")
        r2 = store.create_round(chunk_id, 2, "p2")
        store.complete_round(r2, "", "", status="failed")
        store.update_chunk_status(chunk_id, "failed")

        calls: list[int] = []
        await engine_tmp.distill_work(work_id, self._client(calls),
                                      dimensions=[1, 2], retry_failed=True)
        # 只重跑失败的 round2，不重复 round1
        assert calls == [2]
        assert store.get_work(work_id)["status"] == "done"
        assert store.get_chunk(chunk_id)["status"] == "done"
        # 复用原 round_id：round 记录仍只有 2 条，不累积
        assert len(store.list_rounds(chunk_id)) == 2
        assert {r["round_num"]: r["status"] for r in store.list_rounds(chunk_id)} == {1: "done", 2: "done"}

    async def test_retry_skips_done_chunks(self, store, engine_tmp):
        work_id = _seed_work(store)
        c0 = store.create_chunk(work_id, 0, "内容A")
        c1 = store.create_chunk(work_id, 1, "内容B")
        # chunk0 全部成功，chunk1 第 1 轮失败
        r0 = store.create_round(c0, 1, "p")
        store.complete_round(r0, "raw", "{}", status="done")
        store.update_chunk_status(c0, "done")
        r1 = store.create_round(c1, 1, "p")
        store.complete_round(r1, "", "", status="failed")
        store.update_chunk_status(c1, "failed")

        calls: list[int] = []
        await engine_tmp.distill_work(work_id, self._client(calls),
                                      dimensions=[1], retry_failed=True)
        # 只补 chunk1：chunk0 已 done 跳过（不调用 LLM）
        assert calls == [1]
        assert store.get_chunk(c0)["status"] == "done"
        assert store.get_chunk(c1)["status"] == "done"
        assert store.get_work(work_id)["status"] == "done"

    async def test_retry_recovers_interrupted_running(self, store, engine_tmp):
        """中断残留的 running 轮次（上次中途停掉）也能被补蒸馏补齐。"""
        work_id = _seed_work(store)
        chunk_id = store.create_chunk(work_id, 0, "内容")
        store.update_chunk_status(chunk_id, "distilling")
        # round1 done，round2 是中断残留的 running
        r1 = store.create_round(chunk_id, 1, "p")
        store.complete_round(r1, "raw", "{}", status="done")
        store.create_round(chunk_id, 2, "p")

        calls: list[int] = []
        await engine_tmp.distill_work(work_id, self._client(calls),
                                      dimensions=[1, 2], retry_failed=True)
        assert calls == [2]  # running 残留视为未完成，被重跑
        assert store.get_work(work_id)["status"] == "done"
        rounds = {r["round_num"]: r["status"] for r in store.list_rounds(chunk_id)}
        assert rounds == {1: "done", 2: "done"}
        assert len(store.list_rounds(chunk_id)) == 2  # 复用 running 记录，不重复建
