"""26-Agent 整合质量验收脚本（验收工程师自用，不依赖用户提供样本）。

背景：26-Agent 工作流（mvp.json）中，5 个分科写手（动作/对话/内心/描写/过渡）并行产出，
再由 novel-storyboard-integrator（分镜整合器）统一成稿。本脚本在每次跑完后自动验收：

1. 齐全性    —— 6 个写手产出 + 终稿是否都在
2. 重复检测  —— 各写手内部/写手之间段落重复
3. 拼接痕迹  —— 终稿是否残留 JSON 转义/标记/异常空段
4. 角色名一致 —— 写手提名的角色是否被终稿统一（粗查）
5. AI 味     —— 复用 novel_agent.audit.stat_signal 统计信号给终稿打分

用法：
    python tools/verify_mvp_integration.py            # 扫描全部项目
    python tools/verify_mvp_integration.py 3730       # 只查指定项目

退出码：0=全部 PASS 或未找到产物；1=存在 WARN/FAIL 项。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

def _project_data_dir() -> Path:
    """优先用 novel_agent.config 的权威数据目录（可能被 config.yaml/.env 覆盖）。"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from novel_agent.config import load_config
        return load_config().project_data_dir
    except Exception:
        return Path(__file__).resolve().parent.parent / "project_data"


# 项目数据目录（与 novel_agent.config 保持一致）
PROJECTS_DIR = _project_data_dir() / "projects"

# 写手产出文件名（对应 mvp.json 的 save_output_to_file 路径）
WRITER_FILES = {
    "framework": "cache/writer/framework_writer.json",   # 主写手（骨架）
    "dialogue": "cache/writer/dialogue_writer.json",     # 对话写手
    "action": "cache/writer/action_writer.json",         # 动作写手
    "internal": "cache/writer/internal_writer.json",     # 内心写手
    "description": "cache/writer/description_writer.json",  # 描写写手
    "transition": "cache/writer/transition_writer.json",    # 过渡写手
}
FINAL_FILE = "cache/si/chapter.json"                     # 分镜整合器终稿


def _extract_body(payload: dict | None) -> str:
    """从节点 JSON 输出里尽量提取正文文本（容错多字段）。"""
    if not isinstance(payload, dict):
        return ""
    for key in ("body", "content", "text", "draft", "chapter"):
        val = payload.get(key)
        if isinstance(val, str):
            return val
    # 兜底：把所有字符串字段拼起来
    parts = [str(v) for v in payload.values() if isinstance(v, str)]
    return "\n".join(parts)


def load_text(path: Path) -> str:
    """读节点产物，容错 JSON 解析；非 JSON 按纯文本返回。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return _extract_body(payload)


def _paragraphs(text: str) -> list[str]:
    """按空行/换行切段落，去掉空段。
    保留 ≥2 字段落：网文对白段常只有几个字，阈值过高会漏检短段重复。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    return [p for p in paras if len(p) >= 2]


def check_completeness(ws: Path) -> tuple[bool, list[str]]:
    """1. 齐全性：6 写手 + 终稿文件是否存在。"""
    missing = []
    for name, rel in WRITER_FILES.items():
        if not (ws / rel).exists():
            missing.append(f"写手[{name}] 缺失: {rel}")
    if not (ws / FINAL_FILE).exists():
        missing.append(f"终稿缺失: {FINAL_FILE}")
    return (not missing), missing


def check_empty(ws: Path) -> list[str]:
    """1.5 空产出：写手/终稿提取后正文过短（<10 字）说明该写手空转，白花一次 LLM 调用。"""
    warns = []
    for name, rel in WRITER_FILES.items():
        p = ws / rel
        if not p.exists():
            continue
        text = load_text(p).strip()
        if len(text) < 10:
            warns.append(f"写手[{name}] 空产出（{len(text)} 字）——该写手空转，LLM 调用白费；若正文仍需该内容，由整合器兜底")
    final_path = ws / FINAL_FILE
    if final_path.exists():
        final_text = load_text(final_path).strip()
        if len(final_text) < 100:
            warns.append(f"终稿过短（{len(final_text)} 字），疑似生成失败")
    return warns


def check_repeat(ws: Path) -> list[str]:
    """2. 重复检测：跨写手段落重复（≥4 字完全相同的段落对）。"""
    warns = []
    texts = {}
    for name, rel in WRITER_FILES.items():
        p = ws / rel
        if p.exists():
            texts[name] = _paragraphs(load_text(p))
    final_paras = _paragraphs(load_text(ws / FINAL_FILE)) if (ws / FINAL_FILE).exists() else []
    # 2a. 写手之间重复
    names = list(texts.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = set(texts[names[i]]), set(texts[names[j]])
            dup = a & b
            if dup:
                sample = sorted(dup)[:2]
                warns.append(f"跨写手重复: [{names[i]}]×[{names[j]}] {len(dup)} 段，如「{sample[0][:30]}…」")
    # 2b. 写手内部重复（同一段落出现 ≥2 次）
    for name, paras in texts.items():
        seen = {}
        for p in paras:
            seen[p] = seen.get(p, 0) + 1
        dup = {p: c for p, c in seen.items() if c >= 2}
        if dup:
            sample = next(iter(dup))
            warns.append(f"写手[{name}]内部重复 {len(dup)} 段，如「{sample[:30]}…」")
    # 2c. 终稿相对写手没有覆盖（终稿段落 ≈ 写手段落合集的比例，衡量整合器是否真加工）
    if final_paras:
        all_writer = set()
        for paras in texts.values():
            all_writer |= set(paras)
        final_set = set(final_paras)
        overlap = len(final_set & all_writer)
        if len(final_set) and overlap / len(final_set) > 0.9:
            warns.append(
                f"终稿与写手原文重合度 {overlap/len(final_set):.0%}（>90%）"
                "——整合器疑似直接拼接未加工，需人工确认"
            )
    return warns


def check_seam(ws: Path) -> list[str]:
    """3. 拼接痕迹：终稿里残留 JSON 转义、缓存标记、异常空段。"""
    warns = []
    final_path = ws / FINAL_FILE
    if not final_path.exists():
        return warns
    text = load_text(final_path)
    # 3a. 残留 JSON 转义
    for pat, label in [
        (r"\\n", "未处理的 \\n 转义"),
        (r"\\\"", "未处理的 \\\" 转义"),
        (r"\{[^{}\n]{0,60}\}", "疑似残留 JSON 对象"),
    ]:
        hits = re.findall(pat, text)
        if hits:
            warns.append(f"拼接痕迹: {label} {len(hits)} 处，如「{hits[0][:40]}」")
    # 3b. 缓存文件名/标记残留
    for token in ("framework_writer", "dialogue_writer", "action_writer",
                  "internal_writer", "description_writer", "transition_writer", "```"):
        if token in text:
            warns.append(f"拼接痕迹: 终稿含缓存标记「{token}」")
    # 3c. 异常空段落（超过 4 个连续换行）
    if re.search(r"\n{5,}", text):
        warns.append("拼接痕迹: 存在连续 5 行以上空白（段落拼接粗糙）")
    return warns


def check_names(ws: Path) -> list[str]:
    """4. 角色名一致性（粗查）：终稿中高频出现的「」引号词，
    若只出现在终稿而 6 个写手都没提过，提示可能的命名漂移。"""
    warns = []
    final_text = load_text(ws / FINAL_FILE) if (ws / FINAL_FILE).exists() else ""
    if not final_text:
        return warns
    writer_text = ""
    for name, rel in WRITER_FILES.items():
        p = ws / rel
        if p.exists():
            writer_text += load_text(p)
    # 提取「」/""/《》里的词做名字候选
    final_names = re.findall(r"[「“]([^」”]{1,8})[」”]", final_text)
    writer_names = set(re.findall(r"[「“]([^」”]{1,8})[」”]", writer_text))
    from collections import Counter
    freq = Counter(final_names)
    for name, cnt in freq.most_common(8):
        if cnt >= 2 and name not in writer_names:
            warns.append(f"命名漂移? 终稿出现「{name}」{cnt} 次，但 6 个写手都没提过（可能整合器/写手改名）")
    return warns


def check_ai_style(ws: Path) -> list[str]:
    """5. AI 味：复用 novel_agent.audit.stat_signal 对终稿打分。"""
    final_text = load_text(ws / FINAL_FILE) if (ws / FINAL_FILE).exists() else ""
    if len(final_text) < 300:
        return []
    try:
        from novel_agent.audit.stat_signal import (
            signal_burstiness, signal_adj_density,
            signal_dash_density, signal_connector_density,
        )
    except ImportError:
        return ["[跳过] stat_signal 不可用（novel_agent 未在 sys.path）"]
    warns = []
    for sig in (signal_burstiness, signal_adj_density, signal_dash_density, signal_connector_density):
        try:
            r = sig(final_text)
            if isinstance(r, dict) and r.get("score", 100) < 60:
                warns.append(f"AI味[{sig.__name__.replace('signal_','')}] 得分 {r['score']} < 60: {r.get('suggestion','')}")
        except Exception as e:  # 信号函数容错，不因检测异常中断验收
            warns.append(f"[跳过] {sig.__name__} 异常: {e}")
    return warns


# 6. 矛盾检测：同角色同部位互斥状态（规则层抽查，WARN 级提示人工复核）。
# 每个互斥对是"同一瞬间的身体状态"——同章同时出现大概率是并行写手矛盾残留。
# 刻意避开"先握拳后松手"这类连贯动作（跨部位/跨时刻不误报）。
_MUTEX_STATE_PAIRS = [
    (("瞳孔放大", "瞳孔骤然放大"), ("瞳孔收缩", "瞳孔缩小", "瞳孔骤缩")),
    (("脸色煞白", "脸色发白", "脸白得", "脸色惨白"), ("脸色涨红", "脸色通红", "脸涨得通红")),
    (("手在抖", "手抖得", "指节发白", "手不停发抖"), ("手很稳", "手纹丝不动")),
    (("冷汗直冒", "冷汗涔涔"), ("浑身发热", "燥热难耐")),
    (("呼吸困难", "喘不上气"), ("呼吸平稳", "气息平稳")),
]


def _mutex_hits(text: str) -> list[str]:
    """扫描文本中的同部位互斥状态对，返回描述列表（供测试与 check_contradiction 共用）。"""
    hits = []
    for group_a, group_b in _MUTEX_STATE_PAIRS:
        hit_a = next((w for w in group_a if w in text), None)
        hit_b = next((w for w in group_b if w in text), None)
        if hit_a and hit_b:
            hits.append(f"「{hit_a}」与「{hit_b}」")
    return hits


def check_contradiction(ws: Path) -> list[str]:
    """6. 事中仲裁残留（补充 3）：终稿中同部位互斥状态同时出现 → 提示人工复核。"""
    warns = []
    final_text = load_text(ws / FINAL_FILE) if (ws / FINAL_FILE).exists() else ""
    if len(final_text) < 100:
        return warns
    for desc in _mutex_hits(final_text):
        warns.append(
            f"可能矛盾: 终稿同时出现{desc}——"
            f"并行写手各自描写同一部位时打架，整合器未完全消除（补充3事中仲裁残留）"
        )
    return warns


def verify_project(project_id: str) -> tuple[str, list[str]]:
    """验收单个项目，返回 (状态, 问题列表)。"""
    ws = PROJECTS_DIR / project_id
    problems: list[str] = []
    ok, missing = check_completeness(ws)
    if not ok:
        return "NO_PRODUCT", missing  # 无产物（或产物不全），不算失败

    problems += check_empty(ws)
    problems += check_repeat(ws)
    problems += check_seam(ws)
    problems += check_names(ws)
    problems += check_ai_style(ws)
    problems += check_contradiction(ws)  # 补充3：事中仲裁残留
    status = "PASS" if not problems else "FAIL"
    return status, problems


def main() -> int:
    targets = sys.argv[1:] or [d.name for d in sorted(PROJECTS_DIR.iterdir())
                               if d.is_dir() and d.name.isdigit()]
    if not PROJECTS_DIR.exists():
        print(f"未找到项目数据目录: {PROJECTS_DIR}")
        return 0
    any_fail = False
    found_product = False
    for pid in targets:
        ws = PROJECTS_DIR / pid
        if not ws.is_dir():
            print(f"项目 {pid} 不存在，跳过")
            continue
        status, problems = verify_project(pid)
        if status == "NO_PRODUCT":
            print(f"[项目 {pid}] 无 26-Agent 产物（{len(problems)} 个文件缺失），跳过")
            continue
        found_product = True
        print(f"\n===== 项目 {pid} 整合质量验收 =====")
        if problems:
            for p in problems:
                print(f"  ⚠ {p}")
            any_fail = True
        else:
            print("  ✅ 全部通过：无重复、无拼接痕迹、角色名一致、AI 味信号正常")
    if not found_product:
        print("\n未找到任何 26-Agent 运行产物。")
        print("运行 26-Agent 写章后，再执行本脚本即可自动验收。")
        print(f"产物查找路径: {PROJECTS_DIR}/<project_id>/cache/writer/*.json")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
