"""bishu-novel 插件确定性脚本移植集（NVL 系列）。

每个子模块暴露：
- main(argv=None)：原有 CLI 入口；
- run(args=None, workspace=None)：工作流引擎进程内调用入口，
  返回 {"status": "ok"/"failed", "stdout": ..., "stderr": ...}。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from . import (
    ai_detect,
    ai_detect_local,
    bridge,
    cm_post,
    db_export_chapter,
    extract_names,
    json_to_md,
    local_archive,
    no_post,
    od_post,
    parse_intent,
    polish_post,
    render_worldview,
    se_post,
    si_post,
    trimmer_post,
    vo_post,
    we_post,
)

# 脚本名 → 进程内入口，供工作流引擎按名调用
SCRIPTS = {
    "ai_detect": ai_detect.run,
    "ai_detect_local": ai_detect_local.run,
    "bridge": bridge.run,
    "cm_post": cm_post.run,
    "db_export_chapter": db_export_chapter.run,
    "extract_names": extract_names.run,
    "json_to_md": json_to_md.run,
    "local_archive": local_archive.run,
    "no_post": no_post.run,
    "od_post": od_post.run,
    "parse_intent": parse_intent.run,
    "polish_post": polish_post.run,
    "render_worldview": render_worldview.run,
    "se_post": se_post.run,
    "si_post": si_post.run,
    "trimmer_post": trimmer_post.run,
    "vo_post": vo_post.run,
    "we_post": we_post.run,
}

# 进程级锁：脚本的 run() 内部会 os.chdir(workspace)，chdir 是进程级状态。
# 并发执行脚本（两个工作流/两个项目同时跑）会互相切走 CWD，导致跨项目文件污染
# 并使 local_archive 以 Path.cwd() 为基准的路径安全校验失效（TOCTOU）。
# 所有脚本调用必须经此锁串行化。
_SCRIPT_LOCK = threading.Lock()
# 标记锁是否被一个可能已卡死的线程持有（超时后置 True，锁释放后置 False）
_SCRIPT_LOCK_STUCK = False


async def run_script(name: str, args: list[str] | None,
                     workspace: Path | str,
                     timeout: float = 120.0) -> dict[str, Any]:
    """按名执行 nvl 脚本（进程级锁串行 + 线程池卸载 + 超时保护）。

    锁获取与脚本执行分离：
    - 先用 to_thread + acquire(timeout=5) 获取锁，避免卡死时永久阻塞
    - 获取锁后在主 async 上下文持有锁，再 to_thread 执行脚本
    - 脚本超时后，锁可能仍被卡死线程持有（因 os.chdir 不可中断），
      但 _SCRIPT_LOCK_STUCK 标记会让后续请求快速失败而非无限等待

    Args:
        timeout: 脚本执行超时秒数。
    Raises:
        RuntimeError: 脚本名未注册
    Returns:
        {"status": "ok"/"failed", "stdout": ..., "stderr": ..., ...}
    """
    global _SCRIPT_LOCK_STUCK
    entry = SCRIPTS.get(name)
    if entry is None:
        raise RuntimeError(f"未注册的脚本: {name}")

    # 快速失败：如果锁被卡死线程持有，直接返回错误
    if _SCRIPT_LOCK_STUCK:
        return {
            "status": "failed",
            "stdout": "",
            "stderr": "脚本锁被前一个超时脚本持有，请重启服务后重试",
            "error": "lock_stuck",
        }

    # 带超时获取锁（5 秒内拿不到说明有其他脚本在跑）
    acquired = await asyncio.to_thread(_SCRIPT_LOCK.acquire, True, 5.0)
    if not acquired:
        return {
            "status": "failed",
            "stdout": "",
            "stderr": f"脚本锁繁忙（另一个脚本正在执行），请稍后重试",
            "error": "lock_busy",
        }

    # 能成功获取锁说明锁已空闲（之前的 stuck 线程已结束），复位 stuck 标记
    _SCRIPT_LOCK_STUCK = False

    try:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(entry, args, Path(workspace)),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # 脚本超时：底层线程仍在跑且已 os.chdir，不能释放锁
            # （否则新脚本 chdir 会导致卡死线程在错误 CWD 下操作文件）
            # 标记为 stuck，后续请求快速失败，避免永久阻塞
            _SCRIPT_LOCK_STUCK = True
            logger.error("脚本 %s 执行超时（%ss），锁被标记为 stuck", name, timeout)
            return {
                "status": "failed",
                "stdout": "",
                "stderr": f"脚本 {name} 执行超时（{timeout}s），可能需要重启服务",
                "error": "timeout",
            }
        # 正常完成：释放锁
        _SCRIPT_LOCK.release()
        return result
    except Exception as e:
        # 脚本执行异常：必须释放锁，否则全局锁永久泄漏会拖垮整个工作流引擎
        _SCRIPT_LOCK.release()
        logger.error("脚本 %s 执行异常，已释放脚本锁：%s", name, e)
        return {
            "status": "failed",
            "stdout": "",
            "stderr": f"脚本 {name} 执行异常：{e}",
            "error": "exception",
        }


__all__ = [
    "ai_detect",
    "ai_detect_local",
    "bridge",
    "cm_post",
    "db_export_chapter",
    "extract_names",
    "json_to_md",
    "local_archive",
    "no_post",
    "od_post",
    "parse_intent",
    "polish_post",
    "render_worldview",
    "se_post",
    "si_post",
    "trimmer_post",
    "vo_post",
    "we_post",
    "SCRIPTS",
    "run_script",
]
