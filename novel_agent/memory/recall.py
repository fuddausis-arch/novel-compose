"""Recall memory：全量原文 + 事件时间线查询（不进上下文，供精确回溯）。"""
from __future__ import annotations

import re
from pathlib import Path

from novel_agent.config import Config


class RecallMemory:
    """章节正文文件读写 + 事件流查询入口。"""

    def __init__(self, config: Config, project_id: int | None = None):
        self.config = config
        self.project_id = project_id
        if project_id is not None:
            self.chapters_dir = config.project_chapters_dir(project_id)
        else:
            # 兼容旧调用：无 project_id 时退回到根目录（后续逐步移除）
            self.chapters_dir = config.chapters_dir
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    def save_chapter_text(self, chapter: int, title: str, content: str) -> Path:
        """保存章节正文到 markdown 文件。"""
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
        filename = f"第{chapter:03d}章_{safe_title}.md"
        path = self.chapters_dir / filename
        path.write_text(f"# 第{chapter}章 {title}\n\n{content}", encoding="utf-8")
        return path

    def read_chapter_text(self, chapter: int) -> str:
        """读取章节正文，找不到返回空串。"""
        pattern = f"第{chapter:03d}章_*.md"
        matches = list(self.chapters_dir.glob(pattern))
        if not matches:
            return ""
        return matches[0].read_text(encoding="utf-8")

    def list_chapters(self) -> list[int]:
        """列出所有已写章节号。"""
        chapters = []
        for p in self.chapters_dir.glob("第*章_*.md"):
            m = re.match(r"第(\d+)章_", p.name)
            if m:
                chapters.append(int(m.group(1)))
        return sorted(chapters)
