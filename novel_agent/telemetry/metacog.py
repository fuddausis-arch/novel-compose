"""元认知监控：记录批量生成过程的性能、成本、异常。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from novel_agent.state_common import TaskStatus


@dataclass
class GenerationMetrics:
    project_id: int
    chapter: int
    start_time: float
    end_time: float = 0.0
    status: str = TaskStatus.PENDING.value
    error: str = ""
    word_count: int = 0
    llm_calls: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    human_rating: int = 0  # 人读评分 1-5，0=未评

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class MetacogStore:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = project_dir / "metacog.jsonl"

    def start(self, project_id: int, chapter: int) -> GenerationMetrics:
        return GenerationMetrics(
            project_id=project_id,
            chapter=chapter,
            start_time=time.time(),
        )

    def finish(self, metric: GenerationMetrics) -> None:
        metric.end_time = time.time()
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(metric), ensure_ascii=False) + "\n")

    def rate(self, chapter: int, rating: int) -> bool:
        """人读评分（1-5），更新指定章节的 human_rating。"""
        if not self.log_path.exists():
            return False
        if rating < 1 or rating > 5:
            return False
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        updated = False
        for i in range(len(lines) - 1, -1, -1):
            try:
                m = json.loads(lines[i])
                if m.get("chapter") == chapter:
                    m["human_rating"] = rating
                    lines[i] = json.dumps(m, ensure_ascii=False)
                    updated = True
                    break
            except (json.JSONDecodeError, KeyError):
                continue
        if updated:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        return updated

    def list_metrics(self, limit: int = 100) -> list[dict]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(l) for l in lines[-limit:]]
