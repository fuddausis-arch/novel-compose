"""BookRunner：跨卷编排 + 卷摘要激活 + 完本保障。

批量生成多章，每卷完成后生成卷摘要注入下一卷上下文。
异常时不 break，记录失败章节跳过继续（防太监）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from novel_agent.bible.repository import BibleRepository
from novel_agent.config import Config
from novel_agent.llm.client import LLMClient
from novel_agent.memory.summary_tree import SummaryTree
from novel_agent.orchestrator.runner import ChapterRunner
from novel_agent.state_common import TaskStatus, ReviewStatus, ChapterGenStatus
from novel_agent.telemetry.metacog import MetacogStore

logger = logging.getLogger(__name__)


class BookRunner:
    """批量章节生成运行器：跨卷编排 + 卷摘要 + 异常恢复。"""

    def __init__(self, config: Config, repo: BibleRepository,
                 llm_client: LLMClient | None = None):
        self.config = config
        self.repo = repo
        # C5：不传 llm_client 时按 summarizer 角色创建真实 client，避免卷摘要机械拼接
        if llm_client is None:
            llm_client = LLMClient(config.get_agent_llm("summarizer"))
        self.llm_client = llm_client  # 保留用于兼容，但不传给 ChapterRunner
        self.summary_tree = SummaryTree(repo)
        self.metacog = MetacogStore(config.project_dir(repo.project_id))
        self._failed_chapters: list[dict] = []
        self._completed_chapters: list[int] = []
        self._pending_review: list[dict] = []      # C4：需人工确认（human_review 中断）的章节
        self._new_completed_chapters: list[int] = []  # C6：本次运行新增完成的章节

    async def run_volume(self, start_chapter: int, end_chapter: int,
                         titles: dict[int, str] | None = None,
                         resume: bool = False) -> dict:
        """生成一卷的章节（start_chapter 到 end_chapter）。

        Args:
            start_chapter: 起始章号
            end_chapter: 结束章号
            titles: {chapter: title} 映射，未提供则从大纲读取
            resume: 为 True 时读取 checkpoint，跳过已完成章节

        Returns:
            {"completed": [...], "failed": [...], "volume_summary": "..."}
        """
        titles = titles or {}
        runner = ChapterRunner(self.config, self.repo)

        # resume 模式：从 checkpoint 恢复已完成/失败/待确认状态
        if resume:
            ck = self.repo.get_generation_checkpoint()
            if ck and ck.get("start_chapter") == start_chapter and ck.get("end_chapter") == end_chapter:
                self._completed_chapters = list(ck.get("completed", []))
                self._failed_chapters = list(ck.get("failed", []))
                self._pending_review = list(ck.get("pending_review", []))  # C4
                self._new_completed_chapters = []  # C6：本次运行新增完成章从零计
                logger.info("BookRunner: 从 checkpoint 恢复，已完成 %d 章，失败 %d 章，待人工确认 %d 章",
                           len(self._completed_chapters), len(self._failed_chapters),
                           len(self._pending_review))

        try:
            for chapter in range(start_chapter, end_chapter + 1):
                # resume 时跳过已完成的章节 / 已进入人工确认的章节
                # （C4：固定 thread_id 残留中断 checkpoint，跳过避免反复挂起）
                if resume and (chapter in self._completed_chapters
                               or any(p.get("chapter") == chapter for p in self._pending_review)):
                    logger.info("BookRunner: 第%d章已存在或待人工确认，跳过", chapter)
                    continue

                # 从大纲读取标题
                title = titles.get(chapter, "")
                if not title:
                    outline = self.repo.get_outline_by_chapter(chapter)
                    title = outline.title if outline else f"第{chapter}章"

                # 断点续跑：thread_id 必须稳定（project_id + chapter）
                thread_id = f"project_{self.repo.project_id}_ch{chapter}"

                logger.info("BookRunner: 生成第%d章《%s》", chapter, title)
                metric = self.metacog.start(self.repo.project_id, chapter)
                try:
                    result = await runner.run(chapter, title, thread_id=thread_id)
                    if result.get("status") == TaskStatus.COMPLETED.value:
                        metric.status = TaskStatus.COMPLETED.value
                        metric.word_count = result.get("word_count", 0)
                        self._completed_chapters.append(chapter)
                        self._new_completed_chapters.append(chapter)  # C6：记录本次新增完成章
                        logger.info("BookRunner: 第%d章完成", chapter)
                    elif "__interrupt__" in result or result.get("status") in (ReviewStatus.AUDITED.value, ChapterGenStatus.REVIEW_PENDING.value):
                        # C4：中低置信度章节进入 human_review 中断（status=audited + __interrupt__）。
                        # 视为"待人工确认"，不判 failed、不阻塞其他章节继续。
                        metric.status = TaskStatus.PENDING_REVIEW.value
                        metric.word_count = result.get("word_count", 0)
                        self._pending_review.append({
                            "chapter": chapter,
                            "title": title,
                            "error": "需人工确认（human_review 中断）",
                        })
                        logger.warning("BookRunner: 第%d章需人工确认（人审中断），跳过继续", chapter)
                    else:
                        metric.status = TaskStatus.FAILED.value
                        metric.error = result.get("error", "未知错误")
                        metric.word_count = result.get("word_count", 0)
                        self._failed_chapters.append({
                            "chapter": chapter,
                            "title": title,
                            "error": result.get("error", "未知错误"),
                        })
                        logger.warning("BookRunner: 第%d章失败：%s，跳过继续",
                                      chapter, result.get("error"))
                except Exception as e:
                    # 异常不 break，记录失败章节跳过继续（防太监）
                    metric.status = TaskStatus.FAILED.value
                    metric.error = str(e)
                    self._failed_chapters.append({
                        "chapter": chapter,
                        "title": title,
                        "error": str(e),
                    })
                    logger.warning("BookRunner: 第%d章异常：%s，跳过继续", chapter, e)
                    continue
                finally:
                    # 每章后保存 checkpoint 与元认知监控
                    self.metacog.finish(metric)
                    self._save_checkpoint(start_chapter, end_chapter)

            # 卷完成后生成卷摘要
            volume_num = (start_chapter - 1) // 30 + 1
            volume_summary = ""
            if self._completed_chapters:
                # C6：幂等——该卷 Outline 已有 LLM 摘要且本次无新增完成章时跳过，避免重复追加
                if self._volume_has_summary(volume_num) and not self._new_completed_chapters:
                    logger.info("BookRunner: 第%d卷已有摘要且本次无新增完成章，跳过生成", volume_num)
                else:
                    try:
                        volume_summary = await self.summary_tree.generate_volume_summary(
                            volume_num, self.llm_client)
                        # 存入卷级大纲的 summary 字段
                        if volume_summary:
                            self._store_volume_summary(volume_num, volume_summary)
                        logger.info("BookRunner: 第%d卷摘要已生成并存库", volume_num)
                    except Exception as e:
                        logger.warning("BookRunner: 卷摘要生成失败：%s", e)
                        volume_summary = ""

            # 卷完成，清空 checkpoint 或标记完成
            self._save_checkpoint(start_chapter, end_chapter, finished=True)

            return {
                "completed": list(self._completed_chapters),
                "failed": list(self._failed_chapters),
                "pending_review": list(self._pending_review),  # C4
                "volume_summary": volume_summary,
            }
        finally:
            await runner.close()

    async def run_single(self, chapter: int, runner: ChapterRunner,
                         checkpoint_start: int | None = None,
                         checkpoint_end: int | None = None) -> dict:
        """生成单章并返回结果（供 SSE 端点逐章推送进度）。

        与 run_volume 内部的逐章逻辑一致：标题查找、稳定 thread_id、
        元认知监控、checkpoint 保存。异常不 break，返回 failed 状态。

        Args:
            chapter: 章节号
            runner: 复用的 ChapterRunner 实例（调用方负责 close）
            checkpoint_start/checkpoint_end: checkpoint 记录范围，默认仅本章

        Returns:
            {"status": "completed"/"failed"/"pending_review",
             "title": str, "word_count": int, "error": str}
        """
        sc = checkpoint_start if checkpoint_start is not None else chapter
        ec = checkpoint_end if checkpoint_end is not None else chapter

        # 从大纲读取标题
        outline = self.repo.get_outline_by_chapter(chapter)
        title = outline.title if outline else f"第{chapter}章"

        thread_id = f"project_{self.repo.project_id}_ch{chapter}"
        logger.info("BookRunner: 生成第%d章《%s》", chapter, title)
        metric = self.metacog.start(self.repo.project_id, chapter)
        try:
            result = await runner.run(chapter, title, thread_id=thread_id)
            if result.get("status") == TaskStatus.COMPLETED.value:
                metric.status = TaskStatus.COMPLETED.value
                metric.word_count = result.get("word_count", 0)
                self._completed_chapters.append(chapter)
                self._new_completed_chapters.append(chapter)
                logger.info("BookRunner: 第%d章完成", chapter)
                return {"status": TaskStatus.COMPLETED.value, "title": title,
                        "word_count": result.get("word_count", 0)}
            elif "__interrupt__" in result or result.get("status") in (ReviewStatus.AUDITED.value, ChapterGenStatus.REVIEW_PENDING.value):
                metric.status = TaskStatus.PENDING_REVIEW.value
                metric.word_count = result.get("word_count", 0)
                self._pending_review.append({
                    "chapter": chapter, "title": title,
                    "error": "需人工确认（human_review 中断）",
                })
                logger.warning("BookRunner: 第%d章需人工确认（人审中断），跳过继续", chapter)
                return {"status": TaskStatus.PENDING_REVIEW.value, "title": title,
                        "word_count": result.get("word_count", 0)}
            else:
                metric.status = TaskStatus.FAILED.value
                metric.error = result.get("error", "未知错误")
                metric.word_count = result.get("word_count", 0)
                self._failed_chapters.append({
                    "chapter": chapter, "title": title,
                    "error": result.get("error", "未知错误"),
                })
                logger.warning("BookRunner: 第%d章失败：%s，跳过继续",
                              chapter, result.get("error"))
                return {"status": TaskStatus.FAILED.value, "title": title,
                        "error": result.get("error", "未知错误")}
        except Exception as e:
            metric.status = TaskStatus.FAILED.value
            metric.error = str(e)
            self._failed_chapters.append({
                "chapter": chapter, "title": title, "error": str(e),
            })
            logger.warning("BookRunner: 第%d章异常：%s，跳过继续", chapter, e)
            return {"status": TaskStatus.FAILED.value, "title": title, "error": str(e)}
        finally:
            self.metacog.finish(metric)
            self._save_checkpoint(sc, ec)

    def _save_checkpoint(self, start_chapter: int, end_chapter: int,
                         finished: bool = False) -> None:
        """保存元认知 checkpoint，供 resume 端点恢复。"""
        try:
            checkpoint = {
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "completed": list(self._completed_chapters),
                "failed": list(self._failed_chapters),
                "pending_review": list(self._pending_review),  # C4
                "finished": finished,
            }
            self.repo.save_generation_checkpoint(checkpoint)
            logger.debug("BookRunner checkpoint 已保存：ch%d-%d", start_chapter, end_chapter)
        except Exception as e:
            logger.warning("BookRunner checkpoint 保存失败：%s", e)

    async def run_book(self, total_chapters: int,
                       chapters_per_volume: int = 30) -> dict:
        """生成全书（分卷执行）。

        Args:
            total_chapters: 总章数
            chapters_per_volume: 每卷章数（默认30）

        Returns:
            {"completed": [...], "failed": [...], "volumes_completed": int}
        """
        all_completed: list[int] = []
        all_failed: list[dict] = []
        all_pending_review: list[dict] = []  # C4
        volumes_completed = 0

        for vol_start in range(1, total_chapters + 1, chapters_per_volume):
            vol_end = min(vol_start + chapters_per_volume - 1, total_chapters)
            logger.info("BookRunner: 开始生成第%d卷（第%d章-第%d章）",
                       (vol_start - 1) // chapters_per_volume + 1,
                       vol_start, vol_end)

            # 重置本卷统计
            self._completed_chapters = []
            self._failed_chapters = []
            self._pending_review = []
            self._new_completed_chapters = []  # C6

            result = await self.run_volume(vol_start, vol_end)
            all_completed.extend(result["completed"])
            all_failed.extend(result["failed"])
            all_pending_review.extend(result.get("pending_review", []))  # C4
            if result["volume_summary"]:
                volumes_completed += 1

        return {
            "completed": all_completed,
            "failed": all_failed,
            "pending_review": all_pending_review,  # C4
            "volumes_completed": volumes_completed,
            "total_chapters": total_chapters,
        }

    def _store_volume_summary(self, volume_num: int, summary: str) -> None:
        """将卷摘要存入卷级大纲的 summary 字段。"""
        from novel_agent.bible.models import Outline

        # 查找卷级大纲
        vol_outline = self.repo.db.query(Outline).filter(
            Outline.project_id == self.repo.project_id,
            Outline.level == "volume",
            Outline.order == volume_num,
        ).first()

        if vol_outline:
            # 追加卷摘要到现有 summary
            existing = vol_outline.summary or ""
            vol_outline.summary = f"{existing}\n\n{summary}" if existing else summary
        else:
            # 创建卷级大纲记录
            self.repo.create_outline(
                level="volume",
                order=volume_num,
                title=f"第{volume_num}卷",
                summary=summary,
                act="已生成",
            )

        self.repo.db.commit()

    def _volume_has_summary(self, volume_num: int) -> bool:
        """该卷级大纲是否已有 LLM 摘要（C6 幂等判断）。"""
        from novel_agent.bible.models import Outline
        try:
            vol = self.repo.db.query(Outline).filter(
                Outline.project_id == self.repo.project_id,
                Outline.level == "volume",
                Outline.order == volume_num,
            ).first()
            return bool(vol and (vol.summary or "").strip())
        except Exception:
            return False

    async def close(self):
        if self.llm_client is not None:
            await self.llm_client.close()
