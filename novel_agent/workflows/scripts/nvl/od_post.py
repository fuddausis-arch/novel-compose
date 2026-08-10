#!/usr/bin/env python3
"""OD 后处理：把小说导演（od）输出拆分为确定性的下游产物
guide.json + hooks.json + debts.json。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/script-library/nvl/od_post/od_post.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
from typing import Any


def _safe_rel(raw_path: str) -> str:
    """路径安全校验：只允许工作区内相对路径，拒绝绝对路径与 .. 穿越。"""
    p = Path(raw_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    return raw_path


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return data


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)

    _safe_rel(str(args.input))

    data = _read_json(args.input)
    guide = data.get("guide", {})
    hooks = data.get("hooks", [])
    debts = data.get("debts", [])
    if not isinstance(guide, dict):
        raise ValueError("guide 必须是对象")
    if not isinstance(hooks, list):
        raise ValueError("hooks 必须是数组")
    if not isinstance(debts, list):
        raise ValueError("debts 必须是数组")

    output_root = Path("cache/od")
    _write_json(output_root / "guide.json", guide)
    _write_json(output_root / "hooks.json", hooks)
    _write_json(output_root / "debts.json", debts)
    print(
        "[OK] guide.json + hooks.json "
        f"({len(hooks)}条) + debts.json ({len(debts)}条) → cache/od/"
    )


def run(args: list[str] | None = None, workspace: Path | None = None) -> dict:
    """工作流引擎进程内调用入口。返回 {"status": "ok"/"failed", ...}"""
    ws = Path(workspace).resolve() if workspace else Path(os.getcwd()).resolve()
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    prev_cwd = os.getcwd()
    exit_code = 0
    error = ""
    try:
        os.chdir(ws)
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            main(args)
    except SystemExit as exc:  # argparse 或显式 sys.exit
        exit_code = exc.code if isinstance(exc.code, int) else 1
        if exc.code and not isinstance(exc.code, int):
            error = str(exc.code)
    except Exception as exc:  # 确定性脚本需把异常转为失败状态
        exit_code = 1
        error = str(exc)
    finally:
        os.chdir(prev_cwd)
    result: dict = {
        "status": "ok" if exit_code == 0 else "failed",
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
    }
    if exit_code:
        result["exit_code"] = exit_code
    if error:
        result["error"] = error
    return result


if __name__ == "__main__":
    main()
