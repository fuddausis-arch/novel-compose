"""叙事线健康度扫描器：规则通道 + LLM 通道 + 交叉验证（计划书 3.3）。

规则通道：确定性、零成本（伏笔状态/逾期、断线计数）。
LLM 通道：语义判断（每条线是否推进/断线/交汇/暗线铺垫）。
交叉验证：两通道一致 → adopt（自动更新 progress/last_active_chapter + 预警）；
          不一致 → pending（仅展示双方判定，不自动改线状态）。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from novel_agent.bible.models import Foreshadow, Storyline
from novel_agent.utils.json_output import parse_json_safe

logger = logging.getLogger(__name__)

DEFAULT_BREAK_THRESHOLD = 5  # 连续 N 章未推进视为断线


# ── 规则通道 ──────────────────────────────────────────

def rule_scan_chapter(db: Session, project_id: int, chapter: int, text: str,
                      lines: list[Storyline], break_threshold: int = DEFAULT_BREAK_THRESHOLD) -> dict:
    """规则通道：确定性判定 + 预警（不依赖 LLM）。"""
    alerts: list[dict] = []
    line_results: list[dict] = []

    # 1) 伏笔逾期：planned_resolve_chapter < chapter 且未 resolved/abandoned
    overdue = db.query(Foreshadow).filter(
        Foreshadow.project_id == project_id,
        Foreshadow.planned_resolve_chapter > 0,
        Foreshadow.planned_resolve_chapter < chapter,
        Foreshadow.status.in_(["pending", "planted", "developing"]),
    ).all()
    for f in overdue:
        alerts.append({
            "type": "foreshadow_overdue", "severity": "warning",
            "foreshadow_id": f.foreshadow_id,
            "message": f"伏笔 {f.foreshadow_id} 计划第{f.planned_resolve_chapter}章回收，已逾期",
        })

    # 2) 断线：last_active_chapter 与当前章间隔超过阈值
    for l in lines:
        gap = chapter - (l.last_active_chapter or 0)
        stalled = gap >= break_threshold
        line_results.append({
            "storyline_id": l.id, "name": l.name,
            "progressed": False, "stalled": stalled, "gap": gap,
        })
        if stalled:
            alerts.append({
                "type": "line_stalled", "severity": "danger",
                "storyline_id": l.id, "chapter": chapter,
                "message": f"线「{l.name}」连续 {gap} 章未推进",
            })

    return {"alerts": alerts, "line_results": line_results}


def light_scan_chapter(db: Session, project_id: int, chapter: int, text: str,
                       lines: list[Storyline],
                       break_threshold: int = DEFAULT_BREAK_THRESHOLD) -> dict:
    """轻扫（零成本）：写章后自动调用，维护线的推进状态与断线预警。

    - 规则通道照跑（伏笔逾期 / 断线预警，确定性）
    - 线推进判定：线的 tags（角色名/关键词）出现在正文 → 视为本章推进该线，
      更新 last_active_chapter = 本章，progress 少量 +1（不越 100）。
    - LLM 深度语义扫描仍走 /scan（手动），本函数绝不调用 LLM。

    Returns:
        {"updated": 推进线条数, "alerts": [...], "line_results": [...]}
    """
    rule = rule_scan_chapter(db, project_id, chapter, text, lines,
                             break_threshold=break_threshold)
    if not (text or "").strip():
        return {"updated": 0, "alerts": rule["alerts"], "line_results": rule["line_results"]}

    updated = 0
    for l in lines:
        tags = [t for t in (l.tags or []) if t and t.strip()]
        if tags and any(t in text for t in tags):
            # 幂等：同一章多次轻扫（自动保存/重复提交）只 +1 一次，避免推高进度
            if l.last_active_chapter != chapter:
                l.progress = max(0, min(100, l.progress + 1))
            l.last_active_chapter = chapter
            updated += 1
    db.commit()
    return {"updated": updated, "alerts": rule["alerts"], "line_results": rule["line_results"]}


# ── LLM 通道 ──────────────────────────────────────────

_LLM_SCAN_SYSTEM = """你是资深编辑，负责判断一本小说的叙事线推进情况。输入：某一章正文 + 当前所有线的摘要。输出 JSON（只输出 JSON，不要其他文字）：
{
  "line_results": [
    {"storyline_id": 数字, "name": "线名", "progressed": true/false,
     "progress_delta": 建议进度增量 0-100,
     "notes": "本章该线发生了什么", "alert": null 或 "断线/交汇/暗线铺垫不足等提示"}
  ],
  "alerts": [
    {"type": "line_stalled|foreshadow_overdue|merge_missed|dark_underprepared",
     "severity": "info|warning|danger", "storyline_id": 数字, "message": "一句话"}
  ]
}
判断要点：线相关角色/情节是否在本章出现或推进；伏笔是否兑现；是否出现两条线交汇；暗线是否在做铺垫。宁可保守（progressed=false 但 note 说明），不要编造。"""


def _build_llm_user(chapter: int, text: str, lines: list[Storyline]) -> str:
    line_summary = "\n".join(
        f"- {l.id}: {l.name}（{'/'.join(l.tags or [])}）进度{l.progress}% "
        f"最近推进第{l.last_active_chapter}章 摘要:{l.summary}"
        for l in lines
    ) or "（暂无已建线）"
    return (
        f"【第{chapter}章正文】\n{text[:6000]}\n\n"
        f"【当前叙事线】\n{line_summary}\n\n"
        f"请判断本章各线推进情况。"
    )


async def llm_scan_chapter(client: Any, chapter: int, text: str,
                           lines: list[Storyline]) -> dict:
    """LLM 通道：语义判定。单条线失败不影响其他线（计划书风险 #2）。"""
    user = _build_llm_user(chapter, text, lines)
    raw = await client.generate(user, system=_LLM_SCAN_SYSTEM, temperature=0.2)
    data = parse_json_safe(raw) or {}
    line_results = data.get("line_results") or []
    alerts = data.get("alerts") or []
    return {"line_results": line_results, "alerts": alerts}


# ── 交叉验证 ──────────────────────────────────────────

def cross_validate(rule: dict, llm: dict) -> dict:
    """双通道交叉验证（计划书 3.3）：一致 adopt，不一致 pending。"""
    progressed = bool(rule.get("progressed")) == bool(llm.get("progressed"))
    verdict = "adopt" if progressed else "pending"
    return {
        "verdict": verdict,
        "rule": rule,
        "llm": llm,
        "adopted_progressed": bool(llm.get("progressed")) if verdict == "adopt"
        else None,  # adopt 时以 LLM 语义为准（更可靠）
    }
