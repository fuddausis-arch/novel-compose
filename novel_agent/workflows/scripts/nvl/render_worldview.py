#!/usr/bin/env python3
"""世界观 JSON → Markdown 专用渲染脚本。

读取 world/ 目录下 6 个维度 JSON，按维度 schema 渲染为层级清晰的 Markdown。
每种字段类型（prose/table/list）有独立的渲染方式。

移植自 DeterminFlow-Plugins/plugins/bishu-novel/resources/workflows/build/script/render_worldview.py
（确定性脚本，核心逻辑逐行保留；新增 run() 进程内入口与工作区路径校验。）
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


# ═══════════════════════════════════════════════════════════
#  维度 Schema：定义每个维度的中文标题 + 字段映射
# ═══════════════════════════════════════════════════════════

DIMENSION_ORDER = [
    "core_laws",
    "space_time",
    "society",
    "history_culture",
    "existence",
    "information",
]

DIMENSION_SCHEMA = {
    "core_laws": {
        "title": "一、核心法则",
        "fields": [
            {"key": "power_system",       "label": "力量体系", "type": "prose"},
            {"key": "axioms",             "label": "公理铁律", "type": "table",
             "headers": ["名称", "陈述", "代价", "边界", "执行"],
             "cols":   ["name", "statement", "cost", "boundary", "enforcement"]},
            {"key": "taboos",             "label": "禁忌",     "type": "list"},
            {"key": "power_manifestation","label": "力量显化", "type": "prose"},
        ],
    },
    "space_time": {
        "title": "二、时空地理",
        "fields": [
            {"key": "world_layout",       "label": "世界格局", "type": "prose"},
            {"key": "key_locations",      "label": "关键地点", "type": "table",
             "headers": ["名称", "地形", "特征", "风险", "控制势力"],
             "cols":   ["name", "terrain", "feature", "risk", "controlling_force"]},
            {"key": "ecology",            "label": "生态",     "type": "prose"},
            {"key": "era",                "label": "时代",     "type": "prose"},
            {"key": "environment_texture","label": "环境质感", "type": "prose"},
        ],
    },
    "society": {
        "title": "三、社会权力",
        "fields": [
            {"key": "races",              "label": "种族",             "type": "table",
             "headers": ["名称", "特征", "人口", "社会地位"],
             "cols":   ["name", "traits", "population", "social_status"]},
            {"key": "class_structure",    "label": "阶层结构",         "type": "prose"},
            {"key": "political_system",   "label": "政治制度",         "type": "prose"},
            {"key": "forces",             "label": "势力",             "type": "table",
             "headers": ["名称", "类型", "权力根基", "目标", "手段"],
             "cols":   ["name", "type", "base_of_power", "goals", "methods"]},
            {"key": "force_relations",    "label": "势力关系",         "type": "table",
             "headers": ["来源", "目标", "关系", "张力点"],
             "cols":   ["source", "target", "relation", "tension_point"]},
            {"key": "power_visibility",   "label": "权力的日常可见性", "type": "prose"},
        ],
    },
    "history_culture": {
        "title": "四、历史文化",
        "fields": [
            {"key": "major_events",       "label": "重大事件", "type": "table",
             "headers": ["事件", "时代", "持久影响"],
             "cols":   ["event", "era", "lasting_impact"]},
            {"key": "religions",          "label": "宗教",     "type": "table",
             "headers": ["名称", "核心信条", "信徒范围"],
             "cols":   ["name", "core_belief", "follower_scope"]},
            {"key": "customs",            "label": "风俗习惯", "type": "prose"},
            {"key": "economy",            "label": "经济",     "type": "prose"},
            {"key": "daily_slice",        "label": "日常切片", "type": "prose"},
        ],
    },
    "existence": {
        "title": "五、存在基础",
        "fields": [
            {"key": "calendar",           "label": "历法",         "type": "prose"},
            {"key": "lifespan",           "label": "寿命与衰老",   "type": "prose"},
            {"key": "death",              "label": "死亡",         "type": "prose"},
            {"key": "disease_and_birth",  "label": "疾病与生育",   "type": "prose"},
        ],
    },
    "information": {
        "title": "六、信息传播",
        "fields": [
            {"key": "info_speed",         "label": "信息流速",     "type": "prose"},
            {"key": "knowledge_medium",   "label": "知识媒介",     "type": "prose"},
            {"key": "info_barriers",      "label": "信息壁垒",     "type": "prose"},
            {"key": "rumor_and_truth",    "label": "谣言与真相",   "type": "prose"},
        ],
    },
}


# ═══════════════════════════════════════════════════════════
#  渲染函数
# ═══════════════════════════════════════════════════════════

def render_table(rows: list[dict], headers: list[str], cols: list[str]) -> str:
    """将 list[dict] 渲染为 Markdown 表格。"""
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["------"] * len(headers)) + "|"]
    for row in rows:
        cells = []
        for col in cols:
            val = row.get(col, "")
            if isinstance(val, list):
                val = "；".join(str(v) for v in val)
            cells.append(str(val).replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_list(items: list) -> str:
    """将 list[str] 渲染为 Markdown 无序列表。"""
    return "\n".join(f"- {item}" for item in items)


def render_dimension(data: dict) -> str:
    """渲染单个维度的完整 Markdown section。"""
    # 每个 JSON 文件只有一个顶层 key（维度名）
    dim_key = list(data.keys())[0]
    inner = data[dim_key]
    schema = DIMENSION_SCHEMA.get(dim_key)
    if not schema:
        # 退化：未知维度，用简单标题
        return f"## {dim_key.replace('_', ' ').title()}\n\n{json.dumps(inner, ensure_ascii=False, indent=2)}"

    parts = [f"## {schema['title']}"]

    # essence 定调句
    essence = inner.get("essence", "").strip()
    if essence:
        parts.append(f"> {essence}")

    for field in schema["fields"]:
        key = field["key"]
        value = inner.get(key)
        if value is None or value == "" or (isinstance(value, list) and len(value) == 0):
            continue  # 跳过空字段

        parts.append(f"### {field['label']}")

        if field["type"] == "prose":
            parts.append(str(value).strip())

        elif field["type"] == "table":
            parts.append(render_table(value, field["headers"], field["cols"]))

        elif field["type"] == "list":
            parts.append(render_list(value))

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="世界观 JSON → Markdown 专用渲染")
    parser.add_argument("--input-dir", required=True, help="world/ JSON 目录")
    parser.add_argument("--output", required=True, help="输出 Markdown 文件路径")
    parser.add_argument("--title", default="世界观基础", help="一级标题")
    args = parser.parse_args(argv)

    _safe_rel(args.input_dir)
    _safe_rel(args.output)

    if not os.path.isdir(args.input_dir):
        print(f"[render_worldview] 错误：目录不存在 {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    sections = []
    for dim_key in DIMENSION_ORDER:
        fpath = os.path.join(args.input_dir, f"{dim_key}.json")
        if not os.path.exists(fpath):
            print(f"[render_worldview] 警告：缺少 {dim_key}.json，跳过", file=sys.stderr)
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            sections.append(render_dimension(data))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"[render_worldview] 跳过 {dim_key}.json: {e}", file=sys.stderr)

    if not sections:
        print("[render_worldview] 错误：没有可渲染的维度", file=sys.stderr)
        sys.exit(1)

    output_md = f"# {args.title}\n\n" + "\n\n---\n\n".join(sections) + "\n"

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output_md)

    print(f"[render_worldview] 已生成：{args.output}，共 {len(sections)} 个维度", file=sys.stderr)


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
