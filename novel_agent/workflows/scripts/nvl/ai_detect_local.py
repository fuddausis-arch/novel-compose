#!/usr/bin/env python3
"""本地 AI 味检测脚本（确定性正则，不调用 LLM/Gateway）。

读取章节正文（chapter.md），调用 novel_agent.audit.ai_detect.run() 做词/句/段三级
AI 味分析，把结构化报告写入 ai_detect_report.json 供后续查看/回写。

与 nvl/ai_detect.py 的区别：
- nvl/ai_detect.py 调 humanize-chinese Gateway（外部引擎，网络依赖）
- 本脚本用 audit/ai_detect.py 的确定性正则引擎（离线、快速、可控）

用法:
  python ai_detect_local.py --input story/0001/chapter.md
  python ai_detect_local.py --input story/0001/chapter.md --output story/0001/ai_detect_report.json

作为工作流 script 节点运行时，通过 stdout 的 <WF_VAR> 协议回写 ai_detect_score /
ai_detect_level / ai_detect_total_hits 到变量表，供下游节点消费。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path


def _safe_rel(raw_path: str) -> str:
    """路径安全校验：只允许工作区内相对路径，拒绝绝对路径与 .. 穿越。"""
    p = Path(raw_path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"只允许工作区内相对路径: {raw_path}")
    return raw_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="本地 AI 味检测（确定性正则引擎）"
    )
    parser.add_argument("--input", required=True, help="章节正文文件路径（相对 workspace）")
    parser.add_argument("--output", default=None,
                        help="报告输出路径（默认 story/{章节}/ai_detect_report.json）")
    args = parser.parse_args(argv)

    _safe_rel(args.input)
    if args.output:
        _safe_rel(args.output)

    # 1. 读章节正文
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print(f"（AI 检测跳过：章节文件不存在 {args.input}）")
        return
    except Exception as e:
        print(f"（AI 检测跳过：读取章节文件失败 {e}）")
        return

    if len(text.strip()) < 10:
        print("（AI 检测跳过：文本太短）")
        return

    # 2. 本地确定性引擎检测
    from novel_agent.audit.ai_detect import run as ai_run
    report = ai_run(text)

    # 3. 落盘报告
    if args.output:
        out_path = args.output
    else:
        # 默认写到正文同目录
        out_path = str(Path(args.input).parent / "ai_detect_report.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[OK] AI 率检测完成 → {out_path} "
          f"（score={report['overall_score']}, level={report['ai_level']}, "
          f"total_hits={report['total_hits']}）")

    # 4. WF_VAR 协议：把关键指标回写工作流变量表，供下游节点/前端消费
    print(f"<WF_VAR>ai_detect_score:{report['overall_score']}</WF_VAR>")
    print(f"<WF_VAR>ai_detect_level:{report['ai_level']}</WF_VAR>")
    print(f"<WF_VAR>ai_detect_total_hits:{report['total_hits']}</WF_VAR>")


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
