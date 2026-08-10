"""Auditor agent：多维度独立审校，产出结构化审计报告。

写审分离铁律：Auditor 与 Writer 必须使用不同模型配置。
三视角审查：用户视角 + 专业视角 + 编辑视角。
审查不通过时触发对抗性讨论。
"""
from __future__ import annotations

import json
import logging
import re

from novel_agent.audit.dimensions import DIMENSIONS, CRITICAL_DIMENSIONS
from novel_agent.audit.schemas import AuditReport, Issue, PerspectiveScore
from novel_agent.bible.repository import BibleRepository
from novel_agent.llm.client import LLMClient

logger = logging.getLogger(__name__)

# 三视角 system prompt
USER_AUDITOR_SYSTEM = (
    "你是一个普通的网文读者，用手机看免费小说打发时间。"
    "你的标准很简单：这段文字会不会让你划走？有没有让你想看下一章的冲动？"
    "你不在乎写作技巧，你只在乎：好不好看、有不有趣、能不能看懂。"
    "你的弃书标准：连续2章无新信息/无爽点/看不懂设定/主角无主动决策。"
    "通过标准：有至少1个让你想看下一章的点。"
    "如果无聊或看不懂，就标不通过。"
)

EXPERT_AUDITOR_SYSTEM = (
    "你是网文行业的资深内容分析师，精通叙事结构和世界观构建。"
    "你从专业角度评估：设定是否准确一致、异能体系是否有逻辑、"
    "人物行为是否符合人设、伏笔是否合理、剧情是否有技术深度。"
    "额外判定：本章爽点是否服务于全书立意（核心爽点类型）。"
    "如果爽点偏离立意、存在设定矛盾或逻辑硬伤，就标不通过。"
)

EDITOR_AUDITOR_SYSTEM = (
    "你是出版社的资深文字编辑，负责把关语言质量。"
    "你评估：结构完整性、逻辑连贯性、语言规范性、段落节奏、"
    "对话自然度、是否有AI味。"
    "AI味检测参照完整黑名单：深吸一口气/心跳如擂鼓/嘴角上扬/瞳孔一缩/"
    "后背发凉/像被定格的照片/系统提示音/连续忽然突然猛地(一章>2次)。"
    "如果语言质量不达标或AI味明显，就标不通过。"
)

# 对抗讨论中的 Writer 辩护 prompt
WRITER_DEBATE_SYSTEM = (
    "你是章节的作者。审查方提出了批评，你需要认真考虑他们的意见。"
    "如果你认同批评，承认问题并说明你会怎么改。"
    "如果你认为批评有误，可以据理力争，但必须有具体理由。"
    "不要无脑认错，也不要无脑反驳。"
)


def _build_dimensions_text() -> str:
    lines = []
    for d in DIMENSIONS:
        tag = "【关键】" if d.critical else ""
        lines.append(f"- {tag}{d.name}（{d.category.value}）：{d.check}")
    return "\n".join(lines)


from novel_agent.utils.json_parser import parse_json_strict


def _extract_json(text: str) -> dict | None:
    result = parse_json_strict(text)
    return result if result else None


class Auditor:
    """多维度独立审校 agent。

    使用独立 LLM 配置（与 Writer 不同模型），三视角并行审查。
    审查不通过时可触发对抗性讨论。
    """

    def __init__(self, llm_client: LLMClient, writer_client: LLMClient | None = None,
                 debater_client: LLMClient | None = None):
        """Args:
            llm_client: 审查用 LLM（必须与 Writer 不同配置）
            writer_client: 对抗讨论时 Writer 侧用的 LLM（可选，None 时用 llm_client）
            debater_client: 辩论专用 LLM（可选，优先于 writer_client）
        """
        self.llm_client = llm_client
        self._debater_client = debater_client
        self.writer_client = debater_client or writer_client or llm_client

    async def _audit_single_perspective(
        self, system_prompt: str, perspective_name: str,
        chapter: int, title: str, draft: str,
        char_text: str, foreshadow_text: str,
        project_constraints_text: str = "",
        world_settings_text: str = "",
    ) -> PerspectiveScore:
        """单视角审查。"""
        prompt_parts = [
            f"从【{perspective_name}】审阅第{chapter}章《{title}》草稿。\n\n",
            f"【角色状态】\n{char_text}\n\n",
        ]
        if project_constraints_text:
            prompt_parts.append(f"{project_constraints_text}\n\n")
        if world_settings_text:
            prompt_parts.append(f"{world_settings_text}\n\n")
        prompt_parts.append(f"【伏笔要求】\n{foreshadow_text or '无'}\n\n")
        prompt_parts.append(f"【审计维度参考】\n{_build_dimensions_text()}\n\n")
        prompt_parts.append(f"【草稿正文】\n{draft}\n\n")
        prompt_parts.append(
            f"【硬规则】如果本章草稿违反了上述【全书铁律】/【立意禁忌】/【角色绝对禁令】/【世界设定】中的任一条，"
            f"直接 passed=false，且 issues 中必须列出具体违反项及证据，severity=\"critical\"。\n\n"
        )
        prompt_parts.append(
            f"要求：从{perspective_name}评估，输出 JSON：\n"
            f'{{"score": 0-100, "passed": bool, "issues": ["问题1","问题2"], '
            f'"summary": "评价摘要"}}\n'
            f"score<70 则 passed=false。只输出 JSON。"
        )
        prompt = "".join(prompt_parts)
        try:
            raw = await self.llm_client.generate(prompt, system=system_prompt)
            data = _extract_json(raw)
            if data is None:
                return PerspectiveScore(score=0, passed=False, summary=f"{perspective_name}审查解析失败")
            # 健壮处理：score/passed 原样传给 PerspectiveScore，
            # 由 schemas 的 _coerce_score（int(float)）与 _coerce_passed（字符串 false→False）统一解析。
            # 这里不再提前 int()/bool()，避免把 "false"、"72.5" 等 LLM 常见输出解析错。
            raw_score = data.get("score", 0)
            try:
                score = int(float(raw_score)) if raw_score not in (None, "") else 0
            except (ValueError, TypeError):
                score = 0
            passed = data.get("passed", False)
            if passed is None:
                passed = score >= 70
            issues = data.get("issues", []) or []
            if isinstance(issues, dict):
                # C10：LLM 返回 dict 时取 values（顺序无关），避免 PerspectiveScore 校验失败
                issues = list(issues.values())
            if isinstance(issues, str):
                issues = [issues]
            return PerspectiveScore(
                score=score,
                passed=passed,
                issues=issues,
                summary=data.get("summary", "") or "",
            )
        except Exception as e:
            logger.warning("%s审查失败: %s", perspective_name, e)
            return PerspectiveScore(score=0, passed=False, summary=f"{perspective_name}审查异常: {e}")

    async def audit(self, chapter: int, title: str, draft: str,
                    repo: BibleRepository) -> AuditReport:
        """三视角并行审查，返回结构化审计报告。"""
        chars = repo.list_characters()
        # char_text 补全：name/role/personality/motivation/absolute_taboos/core_contradiction
        char_lines = []
        for c in chars:
            line = f"- {c.name}（{c.role or '角色'}）"
            if getattr(c, 'personality', ''):
                line += f" / 性格：{c.personality}"
            if getattr(c, 'motivation', ''):
                line += f" / 动机：{c.motivation}"
            if getattr(c, 'absolute_taboos', ''):
                line += f" / 绝对禁令（违反则废稿）：{c.absolute_taboos}"
            if getattr(c, 'core_contradiction', ''):
                line += f" / 承重矛盾：{c.core_contradiction}"
            char_lines.append(line)
        char_text = "\n".join(char_lines) or "无角色记录"

        # project_constraints_text：constitution/golden_finger/central_concept/genre
        project_constraints_text = ""
        project = repo.get_project()
        if project:
            parts = []
            if getattr(project, 'constitution', ''):
                parts.append(f"【全书铁律（违反任一条直接 passed=false）】\n{project.constitution}")
            if getattr(project, 'golden_finger', ''):
                try:
                    gf = json.loads(project.golden_finger) if isinstance(project.golden_finger, str) else project.golden_finger
                    gf_text = gf if isinstance(gf, str) else json.dumps(gf, ensure_ascii=False)
                    parts.append(f"【金手指设定（必须遵守其机制/限制/代价）】\n{gf_text}")
                except Exception:
                    parts.append(f"【金手指设定（必须遵守其机制/限制/代价）】\n{project.golden_finger}")
            if getattr(project, 'central_concept', ''):
                try:
                    concept = json.loads(project.central_concept) if isinstance(project.central_concept, str) else project.central_concept
                    taboos = concept.get('taboos', []) if isinstance(concept, dict) else []
                    taboos_list = taboos if isinstance(taboos, list) else ([taboos] if taboos else [])
                    taboos_text = ', '.join(str(t) for t in taboos_list) if taboos_list else '无'
                    parts.append(
                        f"【立意（违反【立意禁忌】则废稿）】\n核心爽点：{concept.get('core_hook', '')}\n"
                        f"主角目标：{concept.get('protagonist_goal', '')}\n"
                        f"立意禁忌（违反则废稿）：{taboos_text}"
                    )
                except Exception:
                    parts.append(f"【立意】\n{project.central_concept}")
            if project.genre:
                parts.append(f"【题材】{project.genre}")
            project_constraints_text = "\n\n".join(parts)

        # world_settings_text：每条最多 300 字
        world_settings = repo.list_world_settings()
        if world_settings:
            world_lines = ["【世界设定（不得违反）】"]
            for w in world_settings:
                content = (w.content or "")
                world_lines.append(f"- [{w.category}] {w.title}：{content}")
            world_settings_text = "\n".join(world_lines)
        else:
            world_settings_text = ""

        to_plant = repo.get_foreshadows_to_plant(chapter)
        to_resolve = repo.get_foreshadows_to_resolve(chapter)
        foreshadow_text = ""
        if to_plant:
            foreshadow_text += "应埋：" + "；".join(f"{f.foreshadow_id}:{f.description}" for f in to_plant)
        if to_resolve:
            foreshadow_text += "应回收：" + "；".join(f"{f.foreshadow_id}:{f.description}" for f in to_resolve)

        # 三视角并行审查
        import asyncio
        user_result, expert_result, editor_result = await asyncio.gather(
            self._audit_single_perspective(
                USER_AUDITOR_SYSTEM, "普通用户视角",
                chapter, title, draft, char_text, foreshadow_text,
                project_constraints_text, world_settings_text),
            self._audit_single_perspective(
                EXPERT_AUDITOR_SYSTEM, "专业人员视角",
                chapter, title, draft, char_text, foreshadow_text,
                project_constraints_text, world_settings_text),
            self._audit_single_perspective(
                EDITOR_AUDITOR_SYSTEM, "编辑视角",
                chapter, title, draft, char_text, foreshadow_text,
                project_constraints_text, world_settings_text),
        )

        # 汇总
        all_passed = user_result.passed and expert_result.passed and editor_result.passed
        overall_score = (user_result.score + expert_result.score + editor_result.score) // 3

        # 收集 issues
        issues = []
        for perspective, result in [("用户视角", user_result), ("专业视角", expert_result), ("编辑视角", editor_result)]:
            for issue_text in result.issues:
                severity = "critical" if not result.passed else "important"
                issues.append(Issue(
                    dimension=perspective,
                    severity=severity,
                    message=issue_text,
                ))

        # 收集建议
        suggestions = []
        for result in [user_result, expert_result, editor_result]:
            if result.issues:
                suggestions.extend(result.issues)

        summary = f"用户{user_result.score}分({('通过' if user_result.passed else '不通过')})，" \
                  f"专业{expert_result.score}分({('通过' if expert_result.passed else '不通过')})，" \
                  f"编辑{editor_result.score}分({('通过' if editor_result.passed else '不通过')})"

        return AuditReport(
            passed=all_passed,
            overall_score=overall_score,
            user_perspective=user_result,
            expert_perspective=expert_result,
            editor_perspective=editor_result,
            issues=issues,
            summary=summary,
            suggestions=suggestions,
        )

    async def debate(self, chapter: int, title: str, draft: str,
                     report: AuditReport, max_rounds: int = 2) -> AuditReport:
        """对抗性讨论：审查不通过时，Writer 和 Auditor 多轮辩论。

        每轮：
        1. Auditor 提出具体批评
        2. Writer 回应（认错或反驳）
        3. 如果 Writer 反驳有理，Auditor 重新评估
        4. 如果 Writer 认错，生成修订建议
        """
        debate_rounds = []
        issues_text = "\n".join(f"- {i.dimension}: {i.message}" for i in report.issues) or "无具体问题"

        for round_num in range(1, max_rounds + 1):
            # Auditor 提出批评
            auditor_prompt = (
                f"你是审查方。第{chapter}章审查未通过（综合{report.overall_score}分）。\n"
                f"当前问题：\n{issues_text}\n\n"
                f"【草稿正文】\n{draft}\n\n"
                f"请提出你最核心的 1-3 个问题，要具体，引用原文。"
                f"输出 JSON：{{\"criticisms\": [\"问题1\",\"问题2\"], \"must_fix\": [\"必须修改的点\"]}}"
            )
            try:
                auditor_raw = await self.llm_client.generate(auditor_prompt, system=EDITOR_AUDITOR_SYSTEM)
                auditor_data = _extract_json(auditor_raw) or {"criticisms": [], "must_fix": []}
            except Exception:
                auditor_data = {"criticisms": [], "must_fix": []}

            criticisms = auditor_data.get("criticisms", [])
            must_fix = auditor_data.get("must_fix", [])

            # Writer 回应
            writer_prompt = (
                f"你是作者。审查方对第{chapter}章提出以下批评：\n"
                + "\n".join(f"- {c}" for c in criticisms) + "\n\n"
                f"【你的草稿】\n{draft}\n\n"
                f"请逐条回应：认同还是反驳？如果认同，说明怎么改。"
                f"输出 JSON：{{\"responses\": [{{\"criticism\":\"\",\"agree\":false,\"reason\":\"\",\"fix\":\"\"}}]}}"
            )
            try:
                writer_raw = await self.writer_client.generate(writer_prompt, system=WRITER_DEBATE_SYSTEM)
                writer_data = _extract_json(writer_raw) or {"responses": []}
            except Exception:
                writer_data = {"responses": []}

            responses = writer_data.get("responses", [])

            # 记录本轮讨论
            round_record = {
                "round": round_num,
                "auditor_criticisms": criticisms,
                "must_fix": must_fix,
                "writer_responses": responses,
            }
            debate_rounds.append(round_record)

            # 如果 Writer 全部认同且有 must_fix，生成修订建议
            agreed_fixes = [r.get("fix", "") for r in responses if r.get("agree") and r.get("fix")]
            if agreed_fixes:
                report.suggestions.extend(agreed_fixes)

            # 如果 Writer 反驳且有理，重新评估
            disagreed = [r for r in responses if not r.get("agree")]
            if disagreed and len(disagreed) == len(responses):
                # Writer 全部反驳，Auditor 重新考虑
                reconsider_prompt = (
                    f"作者对您的批评做了以下回应：\n"
                    + json.dumps(responses, ensure_ascii=False, indent=2) + "\n\n"
                    f"请重新评估：作者的反驳是否有道理？是否需要调整评分？\n"
                    f'输出 JSON：{{"reconsidered": bool, "new_score": 0-100, "new_passed": bool, "reason": ""}}'
                )
                try:
                    recon_raw = await self.llm_client.generate(reconsider_prompt, system=EDITOR_AUDITOR_SYSTEM)
                    recon_data = _extract_json(recon_raw) or {}
                    if recon_data.get("reconsidered"):
                        report.overall_score = recon_data.get("new_score", report.overall_score)
                        # 如果重新评估通过，结束讨论
                        if recon_data.get("new_passed"):
                            report.passed = True
                            report.summary += f"\n对抗讨论第{round_num}轮：审查方接受作者反驳，改为通过。"
                            break
                except Exception:
                    pass

            # 如果没有 must_fix 且 Writer 全部认同，结束
            if not must_fix and agreed_fixes:
                break

        report.debate_rounds = debate_rounds
        return report
