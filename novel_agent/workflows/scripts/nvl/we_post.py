#!/usr/bin/env python3
"""WE 后处理：we_output.json → world_state.json + world_events.json。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/script-library/nvl/we_post/we_post.py
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


def _load_we_input(path: Path) -> dict:
    """读取 we_output.json，容忍 LLM 输出格式漂移。

    需求：agent（LLM）输出偶发会在 JSON 对象后附带多余文本（如把 prompt 指令
    原样复读），直接 json.load 会抛 "Extra data"。这里用 raw_decode 只提取
    第一个 JSON 对象，忽略尾部多余内容，避免整条工作流因格式漂移而 failed。
    """
    text = path.read_text(encoding="utf-8").strip()
    decoder = json.JSONDecoder()
    idx = text.find("{")
    if idx == -1:
        raise ValueError(f"未找到 JSON 对象: {path}")
    obj, _ = decoder.raw_decode(text[idx:])
    if not isinstance(obj, dict):
        raise ValueError(f"首个 JSON 不是对象: {path}")
    return obj


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)

    _safe_rel(args.input)

    data = _load_we_input(Path(args.input))

    state = {
        "world_time": data.get("world_time", ""),
        "time_advanced_days": data.get("time_advanced_days", 0),
        "forces": data.get("forces", []),
        "undercurrents": data.get("undercurrents", []),
    }
    events = {
        "world_time": data.get("world_time", ""),
        "time_advanced_days": data.get("time_advanced_days", 0),
        "on_camera_events": data.get("on_camera_events", []),
        "off_camera_events": data.get("off_camera_events", []),
        "undercurrent_progress": data.get("undercurrent_progress", []),
        "power_shift": data.get("power_shift", ""),
    }

    os.makedirs("cache/we", exist_ok=True)
    json.dump(state, open("cache/we/world_state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(events, open("cache/we/world_events.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[OK] world_state.json + world_events.json → cache/we/")


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
