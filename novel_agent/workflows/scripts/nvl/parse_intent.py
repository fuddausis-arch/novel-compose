#!/usr/bin/env python3
"""意图分发器后处理：cache/intent.json → od_intent + se_intent 工作流变量。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/script-library/nvl/parse_intent/parse_intent.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path


def _safe_rel(raw_path: str) -> str:
    """路径安全校验：只允许工作区内相对路径，拒绝绝对路径与 .. 穿越。"""
    p = Path(raw_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    return raw_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="意图分发器输出的 JSON 文件路径")
    args = parser.parse_args(argv)

    _safe_rel(args.input)

    try:
        data = json.load(open(args.input, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        print("<WF_VAR>od_intent:（空）</WF_VAR>")
        print("<WF_VAR>se_intent:（空）</WF_VAR>")
        return

    od = data.get("od_intent", "（空）") or "（空）"
    se = data.get("se_intent", "（空）") or "（空）"

    print(f"<WF_VAR>od_intent:{od}</WF_VAR>")
    print(f"<WF_VAR>se_intent:{se}</WF_VAR>")


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
