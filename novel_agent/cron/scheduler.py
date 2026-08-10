"""Cron 定时任务调度器。

借鉴 DeterminFlow cron/ 模块：
- 支持 cron 表达式调度
- 支持手动触发
- 任务类型：批量生成、后验裁决、状态快照

APScheduler 可能未安装（requirements.txt 未声明），用 try/import 处理：
- 已安装：使用 APScheduler BackgroundScheduler
- 未安装：降级为 daemon 线程轮询 CronStore 的简易调度器（精度 30 秒），
  保证 start/stop/定时触发整体可用，不因缺少第三方依赖而完全失效。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 尝试导入 APScheduler，未安装时降级为线程轮询调度器
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _HAS_APSCHEDULER = True
except ImportError:  # pragma: no cover - 依赖未安装时的降级路径
    _HAS_APSCHEDULER = False
    BackgroundScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 简化 cron 表达式匹配（5 字段：分 时 日 月 周），供降级调度器使用
# ---------------------------------------------------------------------------
def _cron_field_set(field: str, values: range) -> set[int]:
    """解析单个 cron 字段，返回匹配值集合。

    支持：*、*/N、N/M、A-B、逗号列表、单值。
    """
    field = field.strip()
    if field == "*":
        return set(values)
    if "," in field:
        out: set[int] = set()
        for part in field.split(","):
            out |= _cron_field_set(part, values)
        return out
    if "/" in field:
        base, step_s = field.split("/")
        step = int(step_s)
        if base == "*":
            return set(range(values.start, values.stop, step))
        start = int(base)
        return set(range(start, values.stop, step))
    if "-" in field:
        a, b = (int(x) for x in field.split("-"))
        return set(range(a, b + 1))
    try:
        return {int(field)}
    except ValueError:
        return set()


def cron_matches(expr: str, dt: datetime) -> bool:
    """判断 dt 是否匹配简化 cron 表达式（5 字段）。"""
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, day, month, weekday = parts
    if dt.minute not in _cron_field_set(minute, range(60)):
        return False
    if dt.hour not in _cron_field_set(hour, range(24)):
        return False
    if dt.day not in _cron_field_set(day, range(1, 32)):
        return False
    if dt.month not in _cron_field_set(month, range(1, 13)):
        return False
    # 周字段：cron 用 0/7=周日，Python weekday() 0=周一
    wd = dt.weekday() + 1  # 1-7，7=周日
    if wd == 7:
        wd = 0
    if weekday != "*" and wd not in _cron_field_set(weekday, range(7)):
        return False
    return True


def next_cron_run(expr: str, after: datetime | None = None) -> datetime | None:
    """计算下一个匹配 cron 表达式的时间（逐分钟推进，最多查 24 小时）。

    仅用于展示 next_run，实际触发以轮询匹配为准。
    """
    cursor = (after or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    cursor += timedelta(minutes=1)
    for _ in range(1440):
        if cron_matches(expr, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    return None


class _FallbackScheduler:
    """APScheduler 未安装时的降级调度器：daemon 线程轮询 CronStore。

    每 30 秒扫描一次已启用任务，cron 表达式命中当前分钟则触发一次；
    同一任务在同一分钟内最多触发一次（内存去重，防止轮询周期内重复触发）。
    """

    def __init__(self, owner: "CronScheduler"):
        self._owner = owner
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_fired: dict[str, str] = {}  # job_id -> "YYYY-MM-DDTHH:MM"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="cron-fallback", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread = None

    def remove_job(self, job_id: str) -> None:
        self._last_fired.pop(job_id, None)

    def _loop(self) -> None:
        while not self._stop_event.wait(30):
            try:
                now = datetime.now(timezone.utc)
                jobs = self._owner.list_jobs()
            except Exception:
                logger.exception("cron 降级调度器读取任务失败")
                continue
            for job in jobs:
                if not job.enabled or not job.schedule:
                    continue
                try:
                    if not cron_matches(job.schedule, now):
                        continue
                except Exception:
                    continue
                minute_key = now.strftime("%Y-%m-%dT%H:%M")
                if self._last_fired.get(job.id) == minute_key:
                    continue
                self._last_fired[job.id] = minute_key
                try:
                    self._owner._dispatch(job.id)
                except Exception:
                    logger.exception("Cron job %s 定时执行失败", job.id)


@dataclass
class CronJob:
    """定时任务定义。

    Attributes:
        id: 任务唯一 id
        name: 任务名称
        schedule: cron 表达式（如 "0 */6 * * *"，6 小时一次）
        workflow_type: 任务类型（batch_generate / post_hoc / snapshot）
        parameters: 任务参数，传给 runner 回调
        enabled: 是否启用
        last_run: 上次执行时间（ISO 字符串）
        next_run: 下次执行时间（ISO 字符串）
    """

    id: str
    name: str
    schedule: str  # cron 表达式
    workflow_type: str  # 任务类型：batch_generate / post_hoc / snapshot
    parameters: dict = field(default_factory=dict)
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的 dict。"""
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule,
            "workflow_type": self.workflow_type,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        """从 dict 反序列化。"""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            schedule=data.get("schedule", ""),
            workflow_type=data.get("workflow_type", ""),
            parameters=data.get("parameters", {}) or {},
            enabled=data.get("enabled", True),
            last_run=data.get("last_run"),
            next_run=data.get("next_run"),
        )


class CronStore:
    """SQLite 持久化 cron 任务（在 project_data 目录下 cron.db）。

    表结构极简：id (PK) + data_json（整条 CronJob 序列化），
    避免表结构随 dataclass 演进反复迁移。
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            # 默认放到 project_data 目录下
            from novel_agent.config import Config

            db_path = str(Config().project_data_dir / "cron.db")
        self._db_path = str(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保 cron_jobs 表存在。"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def save_job(self, job: CronJob) -> None:
        """新增或更新一条任务（按 id upsert）。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cron_jobs (id, data_json) VALUES (?, ?)",
                (job.id, json.dumps(job.to_dict(), ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_job(self, job_id: str) -> None:
        """删除一条任务。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
            conn.commit()
        finally:
            conn.close()

    def load_job(self, job_id: str) -> CronJob | None:
        """按 id 加载单条任务。"""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT data_json FROM cron_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            return CronJob.from_dict(json.loads(row[0]))
        finally:
            conn.close()

    def load_jobs(self) -> list[CronJob]:
        """加载全部任务（按 id 排序）。"""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT data_json FROM cron_jobs ORDER BY id"
            ).fetchall()
            return [CronJob.from_dict(json.loads(r[0])) for r in rows]
        except Exception as e:
            logger.warning("加载 cron jobs 失败: %s", e)
            return []
        finally:
            conn.close()


class CronScheduler:
    """定时任务调度器。

    APScheduler 已安装时使用 BackgroundScheduler；
    未安装时降级为 daemon 线程轮询调度器（_FallbackScheduler），
    保证 start/stop/定时触发整体可用。持久化（CronStore）与
    list_jobs/trigger_job 不依赖任何调度后端，始终正常工作。
    """

    def __init__(self, store: CronStore | None = None):
        self._store = store or CronStore()
        # workflow_type -> 回调，trigger_job / 定时触发时按此分发
        self._runners: dict[str, Callable[[dict], Any]] = {}
        self._scheduler: Any = None
        if _HAS_APSCHEDULER:
            try:
                self._scheduler = BackgroundScheduler()
            except Exception as e:
                logger.warning("初始化 BackgroundScheduler 失败: %s", e)
                self._scheduler = None
        else:
            # APScheduler 未安装：降级为线程轮询调度器，保证 cron 整体可用
            self._scheduler = _FallbackScheduler(self)

    def register_runner(self, workflow_type: str, callback: Callable[[dict], Any]) -> None:
        """注册某类 workflow_type 的执行回调。

        Args:
            workflow_type: 任务类型（与 CronJob.workflow_type 对应）
            callback: 接收 parameters dict 的可调用对象
        """
        self._runners[workflow_type] = callback
        logger.info("已注册 cron runner: %s", workflow_type)

    def add_job(self, job: CronJob) -> None:
        """添加定时任务：持久化 + 注册到调度后端。"""
        self._store.save_job(job)
        if self._scheduler is not None and job.enabled and job.schedule:
            try:
                if _HAS_APSCHEDULER:
                    trigger = CronTrigger.from_crontab(job.schedule)
                    self._scheduler.add_job(
                        self._dispatch,
                        trigger=trigger,
                        args=[job.id],
                        id=job.id,
                        replace_existing=True,
                    )
                    # 用 APScheduler 计算出的下次运行时间回写持久化
                    ap_job = self._scheduler.get_job(job.id)
                    if ap_job is not None and ap_job.next_run_time is not None:
                        job.next_run = ap_job.next_run_time.isoformat()
                        self._store.save_job(job)
                else:
                    # 降级调度器：轮询时从 store 读取，无需预注册；
                    # 计算 next_run 近似值用于展示
                    next_run = next_cron_run(job.schedule)
                    if next_run is not None:
                        job.next_run = next_run.isoformat()
                        self._store.save_job(job)
            except Exception as e:
                logger.warning("注册 cron job %s 失败: %s", job.id, e)
        logger.info("已添加 cron job: %s (%s)", job.id, job.name)

    def remove_job(self, job_id: str) -> None:
        """移除任务：从持久化与调度后端中同时删除。"""
        self._store.delete_job(job_id)
        if self._scheduler is not None:
            try:
                if _HAS_APSCHEDULER:
                    self._scheduler.remove_job(job_id)
                else:
                    self._scheduler.remove_job(job_id)
            except Exception:
                # 调度后端中可能不存在该 job，忽略
                pass
        logger.info("已移除 cron job: %s", job_id)

    def list_jobs(self) -> list[CronJob]:
        """列出所有任务。"""
        return self._store.load_jobs()

    def trigger_job(self, job_id: str) -> dict:
        """手动触发一次任务执行。

        不依赖 APScheduler 是否启动，直接调用已注册的 runner。
        """
        job = self._store.load_job(job_id)
        if job is None:
            return {"ok": False, "error": f"未找到 job: {job_id}"}
        if not job.enabled:
            return {"ok": False, "error": f"job {job_id} 已禁用"}
        runner = self._runners.get(job.workflow_type)
        if runner is None:
            return {
                "ok": False,
                "error": f"未注册 workflow_type={job.workflow_type} 的 runner",
            }
        try:
            result = runner(job.parameters)
            job.last_run = datetime.now(timezone.utc).isoformat()
            self._store.save_job(job)
            return {"ok": True, "result": result}
        except Exception as e:
            logger.exception("手动触发 cron job %s 失败", job_id)
            return {"ok": False, "error": str(e)}

    def start(self) -> None:
        """启动调度器（APScheduler 或降级线程调度器）。"""
        if self._scheduler is None:
            logger.warning("调度器不可用，CronScheduler.start() 降级为 no-op")
            return
        try:
            if not self._scheduler.running:
                self._scheduler.start()
                logger.info("CronScheduler 已启动（%s）",
                            "APScheduler" if _HAS_APSCHEDULER else "降级线程调度器")
        except Exception as e:
            logger.warning("启动 CronScheduler 失败: %s", e)

    def stop(self) -> None:
        """停止调度器（APScheduler 或降级线程调度器）。"""
        if self._scheduler is None:
            logger.warning("调度器不可用，CronScheduler.stop() 降级为 no-op")
            return
        try:
            if self._scheduler.running:
                if _HAS_APSCHEDULER:
                    self._scheduler.shutdown(wait=False)
                else:
                    self._scheduler.stop()
                logger.info("CronScheduler 已停止")
        except Exception as e:
            logger.warning("停止 CronScheduler 失败: %s", e)

    def _dispatch(self, job_id: str) -> None:
        """调度后端定时触发的回调，按 job_id 分发到 runner。"""
        try:
            self.trigger_job(job_id)
        except Exception:
            logger.exception("Cron job %s 定时执行失败", job_id)
