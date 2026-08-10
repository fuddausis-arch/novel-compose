"""Recall memory：全量原文 + 事件时间线查询（不进上下文，供精确回溯）。"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from novel_agent.config import Config

logger = logging.getLogger(__name__)


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
        """保存章节正文到 markdown 文件。重生成时覆盖同章号旧文件。"""
        # sanitize 标题：去除控制字符 + 截断到 50 字 + 替换文件名非法字符
        clean_title = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', title).strip()
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", clean_title)[:50]
        if not safe_title:
            safe_title = "untitled"
        filename = f"第{chapter:03d}章_{safe_title}.md"
        path = self.chapters_dir / filename
        # 删除同章号的旧文件（标题可能已改，文件名不同）
        for old in self.chapters_dir.glob(f"第{chapter:03d}章_*.md"):
            if old != path:
                old.unlink()
        path.write_text(f"# 第{chapter}章 {clean_title or 'untitled'}\n\n{content}", encoding="utf-8")
        # 图谱脏标记：正文变更 → 内容版本 +1（图谱页据此提示"有更新，可刷新"）
        try:
            from novel_agent.graphs.version import bump_content
            bump_content(self.project_id)
        except Exception:
            pass  # 脏标记失败不阻塞保存
        # 断链①③：写章即更新——补写出场记录 + 叙事线规则通道轻扫。
        # 所有正文落盘路径（手动保存/标准生成/交互式创作/工作流）都经 save_chapter_text，
        # 在此统一挂钩，避免各入口重复代码且不漏写；失败不阻塞保存。
        self._post_save_sync(chapter, content)
        return path

    def _post_save_sync(self, chapter: int, content: str) -> None:
        """写章后同步（断链①③）：出场记录（文本匹配）+ 叙事线轻扫（规则通道，零成本）。

        出场记录供人物/势力图谱过滤"未出场实体"与时间线角色泳道；
        叙事线轻扫维护线进度/最近推进章/断线预警（LLM 深度语义扫描仍由叙事线页手动触发）。
        """
        try:
            from novel_agent.bible import database as db_mod
            from novel_agent.bible.models import Base, Storyline
            from novel_agent.bible.repository import BibleRepository
            from novel_agent.storyline.scanner import light_scan_chapter
            db_mod.set_config(self.config)
            Base.metadata.create_all(bind=db_mod.engine)
            db = db_mod.SessionLocal()
            try:
                repo = BibleRepository(db, project_id=self.project_id)
                n_app = repo.record_appearances_from_text(chapter, content or "")
                lines = db.query(Storyline).filter_by(project_id=self.project_id).all()
                light_scan_chapter(db, self.project_id, chapter, content or "", lines)
                if n_app:
                    logger.info("第%d章出场记录（文本匹配）写入 %d 条", chapter, n_app)
            finally:
                db.close()
        except Exception as e:
            logger.warning("写章后同步出场/叙事线失败（不阻塞保存）: %s", e)

    def read_chapter_text(self, chapter: int) -> str:
        """读取章节正文，找不到返回空串。"""
        pattern = f"第{chapter:03d}章_*.md"
        matches = list(self.chapters_dir.glob(pattern))
        if not matches:
            return ""
        return matches[0].read_text(encoding="utf-8")

    def read_chapter_preview(self, chapter: int, max_chars: int = 200) -> str:
        """只读文件头部获取预览，避免读取完整大文件。"""
        pattern = f"第{chapter:03d}章_*.md"
        matches = list(self.chapters_dir.glob(pattern))
        if not matches:
            return ""
        # 只读前 max_chars 个字符（Python 按字符读），避免全量读取
        with open(matches[0], "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)

    def list_chapters(self) -> list[int]:
        """列出所有已写章节号。"""
        chapters = []
        for p in self.chapters_dir.glob("第*章_*.md"):
            m = re.match(r"第(\d+)章_", p.name)
            if m:
                chapters.append(int(m.group(1)))
        return sorted(chapters)

    def list_chapters_with_titles(self) -> list[dict]:
        """列出所有已写章节，含章号和标题（从文件名解析）。"""
        results = []
        for p in sorted(self.chapters_dir.glob("第*章_*.md")):
            m = re.match(r"第(\d+)章_(.+)\.md", p.name)
            if m:
                ch = int(m.group(1))
                title = m.group(2).replace("_", "").strip()
                results.append({"chapter": ch, "title": title})
        return results
