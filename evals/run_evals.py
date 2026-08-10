"""evals 评测运行器。

两种模式：
1. static：不调用 LLM，直接用 static_checks 验证 writing-assistant 的
   select_workflow / parse_user_intent 决策是否符合预期（CI 可跑）。
2. llm：调用 LLM 按 expectations 逐条评分（需配置可用模型，默认关闭）。

用法：
    python evals/run_evals.py            # static 模式
    python evals/run_evals.py --llm      # llm 模式（需有效 LLM 配置）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVALS_PATH = Path(__file__).parent / "evals.json"


def load_evals() -> dict:
    with open(EVALS_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_static_checks(ev: dict) -> list[str]:
    """执行 static_checks，返回失败信息列表（空 = 全部通过）。"""
    from novel_agent.skills.writing_assistant import (
        parse_user_intent,
        select_workflow,
    )

    failures: list[str] = []
    checks = ev.get("static_checks", {})
    if not checks:
        return failures

    if "select_workflow_input" in checks:
        actual = select_workflow(checks["select_workflow_input"])
        expected = checks.get("select_workflow_expected")
        if actual != expected:
            failures.append(
                f"select_workflow({checks['select_workflow_input']}) "
                f"= {actual!r}，期望 {expected!r}")

    if "parse_intent_expected_workflow" in checks:
        result = parse_user_intent(ev["prompt"])
        expected_wf = checks["parse_intent_expected_workflow"]
        if result.get("workflow") != expected_wf:
            failures.append(
                f"parse_user_intent 工作流 = {result.get('workflow')!r}，"
                f"期望 {expected_wf!r}")

    return failures


def run_llm_eval(ev: dict) -> dict:
    """LLM 评分模式：让模型按 expectations 逐条判断（pass/fail + 理由）。"""
    from novel_agent.config import load_config
    from novel_agent.llm.client import LLMClient

    cfg = load_config()
    client = LLMClient(cfg)

    expectations_text = "\n".join(
        f"{i + 1}. {e}" for i, e in enumerate(ev.get("expectations", [])))
    judge_prompt = f"""你是评测裁判。下面给出一个写作助手的用户输入、期望输出和逐条期望。
请你扮演该写作助手，先给出你的实际回复，然后逐条判定是否满足期望。

【用户输入】
{ev["prompt"]}

【期望输出】
{ev.get("expected_output", "")}

【逐条期望】
{expectations_text}

输出 JSON（不要输出其他内容）：
{{
  "assistant_reply": "你的实际回复（简要）",
  "results": [{{"expectation": "...", "pass": true/false, "reason": "..."}}]
}}"""

    raw = client.complete(
        messages=[{"role": "user", "content": judge_prompt}],
        temperature=0.0,
        max_tokens=4096,
    )
    from novel_agent.utils.json_parser import parse_json_safe
    parsed = parse_json_safe(raw)
    if not isinstance(parsed, dict) or "results" not in parsed:
        return {"error": "裁判输出解析失败", "raw": raw[:500]}
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="启用 LLM 评分模式")
    args = parser.parse_args()

    data = load_evals()
    evals = data.get("evals", [])
    print(f"加载 {len(evals)} 条评测用例（skill: {data.get('skill_name')}）")

    total_fail = 0
    for ev in evals:
        print(f"\n[{ev['id']}] {ev.get('name', '')}")
        failures = run_static_checks(ev)
        if failures:
            total_fail += len(failures)
            for f in failures:
                print(f"  ✗ static: {f}")
        else:
            print("  ✓ static checks 全部通过")

        if args.llm:
            result = run_llm_eval(ev)
            if "error" in result:
                print(f"  ✗ llm: {result['error']}")
                total_fail += 1
            else:
                for r in result.get("results", []):
                    mark = "✓" if r.get("pass") else "✗"
                    print(f"  {mark} {r.get('expectation', '')[:60]}: {r.get('reason', '')[:80]}")
                    if not r.get("pass"):
                        total_fail += 1

    print(f"\n{'=' * 50}")
    if total_fail:
        print(f"FAILED: {total_fail} 项未通过")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
