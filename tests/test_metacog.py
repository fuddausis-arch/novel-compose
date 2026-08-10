"""元认知监控 MetacogStore 测试。"""
from __future__ import annotations

from pathlib import Path

from novel_agent.telemetry.metacog import GenerationMetrics, MetacogStore


def test_metacog_store_records_completed_and_failed_metrics(tmp_path: Path):
    store = MetacogStore(tmp_path / "projects" / "1")

    completed = store.start(project_id=1, chapter=1)
    completed.status = "completed"
    completed.word_count = 2500
    completed.llm_calls = 5
    completed.tokens_prompt = 1000
    completed.tokens_completion = 500
    store.finish(completed)

    failed = store.start(project_id=1, chapter=2)
    failed.status = "failed"
    failed.error = "生成超时"
    failed.word_count = 0
    store.finish(failed)

    metrics = store.list_metrics(limit=100)
    assert len(metrics) == 2

    assert metrics[0]["project_id"] == 1
    assert metrics[0]["chapter"] == 1
    assert metrics[0]["status"] == "completed"
    assert metrics[0]["word_count"] == 2500
    assert metrics[0]["llm_calls"] == 5
    assert metrics[0]["tokens_prompt"] == 1000
    assert metrics[0]["tokens_completion"] == 500
    assert metrics[0]["error"] == ""
    assert metrics[0]["end_time"] >= metrics[0]["start_time"]

    assert metrics[1]["project_id"] == 1
    assert metrics[1]["chapter"] == 2
    assert metrics[1]["status"] == "failed"
    assert metrics[1]["error"] == "生成超时"
    assert metrics[1]["word_count"] == 0


def test_list_metrics_limit_returns_most_recent(tmp_path: Path):
    store = MetacogStore(tmp_path / "projects" / "2")

    for chapter in range(1, 5):
        m = store.start(project_id=2, chapter=chapter)
        m.status = "completed"
        m.word_count = chapter * 100
        store.finish(m)

    metrics = store.list_metrics(limit=2)
    assert len(metrics) == 2
    assert metrics[0]["chapter"] == 3
    assert metrics[1]["chapter"] == 4


def test_list_metrics_empty_when_file_missing(tmp_path: Path):
    store = MetacogStore(tmp_path / "projects" / "3")
    assert store.list_metrics() == []
