"""工作流定义加载器 + 执行器。

加载 bishu-novel 移植的 7 条工作流定义（definitions/*.json，共 83 节点），
用 NovelAgent 的 LLMClient 与 nvl 脚本库驱动执行。

支持能力（对齐 DeterminFlow Core）：
- agent / script 两类节点
- condition / parallel / converge / loop 四种网关
- {{var}} 模板渲染（first_message 与 script_args）
- output_variable 写回变量表
- save_output_to_file 产物落盘（相对 workspace，防路径穿越）
- 节点尝试历史记录（node_runs）
- fail_auto_skip / enable_reject_upstream 字段识别
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from novel_agent.state_common import TaskStatus, WorkflowNodeStatus

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFINITIONS_DIR = _PACKAGE_DIR / "definitions"
RESOURCES_DIR = _PACKAGE_DIR / "resources"

# 7 条移植工作流
WORKFLOW_IDS = ["build", "character", "story-plan", "outline", "mvp", "post-hoc", "polish"]

# bishu-novel agent_type → NovelAgent config role 映射
# 让 26+ 个细粒度 agent 各自映射到 config.yaml 的 11 个角色模型配置，
# 解锁跨模型审校（如 observer 用便宜模型、writer 用强模型）。
# 未列出的 agent_type 回退到传入的默认 llm_client（req.agent_role）。
AGENT_TYPE_TO_ROLE: dict[str, str] = {
    # 大纲系 → outliner（高温度，规划创作）
    "novel-volume-outliner": "outliner",
    "novel-director": "outliner",
    "novel-outliner": "outliner",
    # 写手系 → writer（高温度，正文创作）
    "novel-writer": "writer",
    "novel-storyboard-integrator": "writer",
    "novel-dialogue-writer": "writer",
    "novel-action-writer": "writer",
    "novel-internal-writer": "writer",
    "novel-description-writer": "writer",
    "novel-single-writer": "writer",
    "novel-transition-writer": "writer",
    # 世界系 → world_engine（低温度，冷静推演）
    "novel-observer": "world_engine",
    "novel-worldbuilder-corelaws": "world_engine",
    "novel-worldbuilder-spacetime": "world_engine",
    "novel-worldbuilder-society": "world_engine",
    "novel-worldbuilder-historyculture": "world_engine",
    "novel-worldbuilder-existence": "world_engine",
    "novel-worldbuilder-information": "world_engine",
    # 角色系 → architect（中高温度，角色建设）
    "novel-character-skeleton": "architect",
    "novel-character-belief": "architect",
    "novel-character-deep": "architect",
    "novel-character-voice": "architect",
    "novel-character-maintainer": "architect",
    # 规划系 → planner（高温度，意图分发）
    "novel-story-planner": "planner",
    "novel-settler": "planner",
    "novel-intent-distributor": "planner",
    # 审校系 → auditor（低温度，严谨裁决）
    "novel-self-critic": "auditor",
    "novel-arbiter": "auditor",
    "novel-chapter-observer": "auditor",
    "novel-voice-critic": "auditor",
    "novel-palette-critic": "auditor",
    # 润色系 → polisher（高温度，文笔打磨）
    "novel-polisher": "polisher",
    "novel-professional-polisher": "polisher",
    # 风格/裁剪 → summarizer/context_trimmer（低温度，提炼压缩）
    "novel-style-profiler": "summarizer",
    "novel-world-context-trimmer": "context_trimmer",
}

# 蒸馏维度 → 适用 agent 的映射（DIMENSION_AGENTS）中出现的全部 agent 集合。
# 这些 agent 参与「按维度注入」：执行时只注入通用 skill + 自己维度的蒸馏 skill。
# 未覆盖的 agent（observer/settler/intent-distributor/审校系等）保持原行为（不注入）。
_DIMENSION_AGENT_TYPES: set[str] | None = None


def _dimension_agent_types() -> set[str]:
    """惰性加载蒸馏维度映射覆盖的 agent 集合（含写手系/世界观系/角色系/大纲系等）。"""
    global _DIMENSION_AGENT_TYPES
    if _DIMENSION_AGENT_TYPES is None:
        try:
            from novel_agent.distillation.engine import DIMENSION_AGENTS
            _DIMENSION_AGENT_TYPES = {
                a for roles in DIMENSION_AGENTS.values() for a in roles
            }
        except Exception as e:
            logger.warning("加载蒸馏维度映射失败: %s", e)
            _DIMENSION_AGENT_TYPES = set()
    return _DIMENSION_AGENT_TYPES


# ── 资源加载 ──────────────────────────────────────────────────

def load_definition(workflow_id: str, project_id: int | None = None) -> dict[str, Any]:
    """加载工作流定义 JSON。

    优先从内置 definitions/ 加载；若不存在且 project_id 给定，
    则从数据库 custom_workflows 表加载用户自定义工作流。
    """
    # 1. 内置工作流
    path = DEFINITIONS_DIR / f"{workflow_id}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # 2. 数据库自定义工作流
    if project_id is not None:
        try:
            from novel_agent.bible.database import SessionLocal, set_config
            from novel_agent.bible.models import Base, CustomWorkflow
            from novel_agent.config import load_config as _load_config
            set_config(_load_config())
            from novel_agent.bible import database as db_mod
            Base.metadata.create_all(bind=db_mod.engine)
            db = SessionLocal()
            try:
                w = db.query(CustomWorkflow).filter(
                    CustomWorkflow.project_id == project_id,
                    CustomWorkflow.workflow_id == workflow_id,
                ).first()
                if w and w.workflow_json:
                    data = dict(w.workflow_json)
                    # 补全元信息
                    data.setdefault("workflow_id", w.workflow_id)
                    data.setdefault("name", w.name)
                    data.setdefault("description", w.description or "")
                    data.setdefault("is_custom", True)
                    data.setdefault("custom_id", w.id)
                    return data
            finally:
                db.close()
        except Exception as e:
            logger.warning("加载自定义工作流失败 %s: %s", workflow_id, e)

    raise FileNotFoundError(f"工作流定义不存在: {workflow_id}")


def list_workflows(project_id: int | None = None) -> list[dict[str, Any]]:
    """列出所有可用工作流（内置 7 条 + 项目自定义）。

    Args:
        project_id: 若给定，合并该项目的自定义工作流
    """
    out = []
    # 1. 内置工作流
    for wid in WORKFLOW_IDS:
        try:
            d = load_definition(wid)
            out.append({
                "workflow_id": wid,
                "name": d.get("name", wid),
                "version": d.get("version", 1),
                "node_count": len(d.get("nodes", [])),
                "variables": [
                    {"key": v.get("key"), "name": v.get("name"),
                     "type": v.get("type"), "required": v.get("required", False)}
                    for v in d.get("variables", [])
                ],
                "is_custom": False,
            })
        except Exception as e:
            logger.warning("加载工作流定义失败 %s: %s", wid, e)

    # 2. 项目自定义工作流
    if project_id is not None:
        try:
            from novel_agent.bible.database import SessionLocal, set_config
            from novel_agent.bible.models import Base, CustomWorkflow
            from novel_agent.config import load_config as _load_config
            set_config(_load_config())
            from novel_agent.bible import database as db_mod
            Base.metadata.create_all(bind=db_mod.engine)
            db = SessionLocal()
            try:
                items = db.query(CustomWorkflow).filter(
                    CustomWorkflow.project_id == project_id,
                ).order_by(CustomWorkflow.updated_at.desc()).all()
                for w in items:
                    wf_data = w.workflow_json or {}
                    out.append({
                        "workflow_id": w.workflow_id,
                        "name": w.name,
                        "version": 1,
                        "node_count": len(wf_data.get("nodes", [])),
                        "variables": [
                            {"key": v.get("key"), "name": v.get("name"),
                             "type": v.get("type"), "required": v.get("required", False)}
                            for v in wf_data.get("variables", [])
                        ],
                        "is_custom": True,
                        "description": w.description or "",
                    })
            finally:
                db.close()
        except Exception as e:
            logger.warning("加载自定义工作流列表失败: %s", e)

    return out


class WorkflowResources:
    """agents.json + prompts.json 资源访问。"""

    def __init__(self) -> None:
        with open(RESOURCES_DIR / "agents.json", encoding="utf-8") as f:
            self._agents: dict[str, Any] = json.load(f).get("agents", {})
        with open(RESOURCES_DIR / "prompts.json", encoding="utf-8") as f:
            self._prompts: dict[str, Any] = json.load(f).get("agents", {})

    def agent_def(self, agent_type: str) -> dict[str, Any]:
        return self._agents.get(agent_type, {})

    def system_prompt(self, agent_type: str) -> str:
        """拼接 agent 的完整 system prompt（sections 按序拼接）。"""
        entry = self._prompts.get(agent_type, {})
        sections = entry.get("sections", [])
        parts = [s.get("content", "") for s in sections if s.get("content")]
        return "\n\n".join(parts)

    def model_params(self, agent_type: str) -> dict[str, Any]:
        return self.agent_def(agent_type).get("model_params", {}) or {}

    def agent_types(self) -> list[str]:
        return list(self._agents.keys())


# ── 模板渲染 ──────────────────────────────────────────────────

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_template(text: str, variables: dict[str, Any]) -> str:
    """{{var}} 模板渲染。变量不存在时保留原样（不炸）。"""
    if not text:
        return ""
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        val = variables.get(key)
        if val is None:
            return m.group(0)
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False, indent=2)
        return str(val)
    return _TEMPLATE_RE.sub(_sub, text)


def _strip_code_fence(text: str) -> str:
    """剥离 LLM 输出常见的 markdown 代码块围栏。

    bishu-novel 的 agent 节点 prompt 要求"直接输出纯 JSON"，
    但 LLM 经常仍会包裹 ```json ... ``` 围栏，导致后续后处理脚本
    json.load 失败。此处统一在 agent 输出落盘前清理。

    处理三种形态：
    - ```json\\n{...}\\n``` （标准围栏）
    - ```\\n{...}\\n``` （无语言标记围栏）
    - ```{...}``` （单行围栏，少见）

    只剥离首尾围栏，不动 JSON 内部的 ``` 字符串。
    """
    if not text:
        return text
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text  # 无围栏，原样返回
    # 去掉首行 fence（```json 或 ```）
    first_nl = stripped.find("\n")
    if first_nl == -1:
        # 单行 ```{...}``` 的情况
        if stripped.endswith("```") and len(stripped) > 6:
            return stripped[3:-3].strip()
        return stripped
    inner = stripped[first_nl + 1:]
    # 去掉结尾 fence（允许尾部有空白）
    rstripped = inner.rstrip()
    if rstripped.endswith("```"):
        inner = rstripped[:-3].rstrip()
    return inner


def _eval_condition(expr: str, variables: dict[str, Any]) -> bool:
    """评估条件边表达式。支持格式：{{var}}==value / {{var}}!=value。"""
    if not expr:
        return False
    m = re.match(r"\{\{\s*(\w+)\s*\}\}\s*(==|!=)\s*(.+)", expr.strip())
    if not m:
        return False
    var, op, raw = m.group(1), m.group(2), m.group(3).strip().strip("'\"")
    val = str(variables.get(var, ""))
    return (val == raw) if op == "==" else (val != raw)


_LOOP_RE = re.compile(r"for\s+(\w+)\s+in\s+(\w+)")

# 脚本 stdout 变量回写协议（对齐 DeterminFlow src/workflow/nodes/script.py）
# 格式：<WF_VAR>key:value</WF_VAR>，value 尝试 json.loads，失败按字符串
_WF_VAR_RE = re.compile(r"<WF_VAR>([a-zA-Z_][a-zA-Z0-9_]*):(.*?)</WF_VAR>", re.DOTALL)


def _parse_wf_vars(stdout: str) -> dict[str, Any]:
    """从脚本 stdout 提取 WF_VAR 变量。"""
    out: dict[str, Any] = {}
    for m in _WF_VAR_RE.finditer(stdout or ""):
        key, raw = m.group(1), m.group(2).strip()
        try:
            out[key] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            out[key] = raw
    return out


# ── 工作流执行器 ──────────────────────────────────────────────

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _has_transition_slots(skeleton_raw: str) -> bool:
    """P1-1：判断骨架 JSON 是否含过渡槽（[SLOT_TRANSITION_ 文本标记 或 slots.TRANSITION 非空）。

    过渡写手只填骨架中的过渡槽；骨架无槽时跳过 LLM 调用（杜绝空转浪费 token）。
    """
    raw = skeleton_raw or ""
    if "[SLOT_TRANSITION_" in raw:
        return True
    try:
        data = json.loads(raw)
        slots = (data or {}).get("slots", {}) if isinstance(data, dict) else {}
        return bool(isinstance(slots, dict) and slots.get("TRANSITION"))
    except Exception:
        return False


# P1-3：mvp 依赖的上游核心产物（相对 workspace）。volume_outline 首章可能不存在，
# 不作为硬前置；story_plan 与 world_foundation 是 story-plan / build 的必要产物。
_MVP_REQUIRED_PRODUCTS = (
    ("meta/story_plan.md", "story-plan（故事规划）"),
    ("meta/world_foundation.md", "build（世界观总纲）"),
)


def _mvp_precheck_missing(workspace: Path) -> list[str]:
    """P1-3：返回 mvp 缺失的上游产物描述列表（空 = 前置满足，可运行）。"""
    missing = []
    for rel, step in _MVP_REQUIRED_PRODUCTS:
        if not (Path(workspace) / rel).exists():
            missing.append(f"{step}（{rel}）")
    return missing


class WorkflowRunner:
    """单条工作流定义的执行器。

    从 __start__ 沿 edges 走到 __end__，途中执行 agent/script 节点，
    处理 4 种网关。变量表 variables 在节点间传递（output_variable 写回）。
    """

    def __init__(
        self,
        definition: dict[str, Any],
        llm_client: Any,
        workspace: Path,
        resources: WorkflowResources | None = None,
        on_event: EventCallback | None = None,
        cfg: Any = None,
        project_id: int | None = None,
    ) -> None:
        self.defn = definition
        self.llm = llm_client  # 默认 client（兜底，未映射的 agent_type 用）
        self.workspace = Path(workspace)
        self.res = resources or WorkflowResources()
        self.on_event = on_event
        self.project_id = project_id  # 项目参考书单查询用（注入蒸馏 skill 时按书过滤）
        # 模型按 agent_type 分配：cfg 给定时，按 AGENT_TYPE_TO_ROLE 映射
        # 为每个 role 创建独立 LLMClient 并缓存，解锁跨模型审校。
        self._cfg = cfg
        self._client_cache: dict[str, Any] = {}  # role → LLMClient
        self._skills_text: dict[str, str] = {}  # agent_type → 注入文本缓存（按 agent 过滤）

        self.nodes: dict[str, dict[str, Any]] = {
            n["id"]: n for n in definition.get("nodes", [])
        }
        self.gateways: dict[str, dict[str, Any]] = {
            g["id"]: g for g in definition.get("gateways", [])
        }
        # source -> [edge]
        self.edges_from: dict[str, list[dict[str, Any]]] = {}
        for e in definition.get("edges", []):
            self.edges_from.setdefault(e["source"], []).append(e)

        self.variables: dict[str, Any] = {}
        self.node_runs: list[dict[str, Any]] = []
        self.status = TaskStatus.PENDING.value

    # ── 事件与历史 ────────────────────────────────────────────

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            try:
                await self.on_event(event)
            except Exception as e:
                logger.warning("事件回调失败: %s", e)

    def _record(self, node_id: str, status: str, elapsed: float,
                error: str = "", output_preview: str = "") -> None:
        self.node_runs.append({
            "node_id": node_id,
            "status": status,
            "elapsed_s": round(elapsed, 2),
            "error": error,
            "output_preview": output_preview[:500],
            "ts": time.time(),
        })

    # ── 安全路径 ──────────────────────────────────────────────

    def _safe_path(self, rel: str) -> Path:
        """相对 workspace 的安全路径（拒绝绝对路径与 ..）。"""
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"非法工作区路径: {rel}")
        return self.workspace / p

    # ── 变量解析（B2 修复）────────────────────────────────────

    def _resolve_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """合并输入与定义默认值，并把 file 类型变量读文件注入内容。

        对齐 DeterminFlow variable_resolution.py 的语义：
        1. 文本变量：inputs 优先，缺失时用定义 default（两轮嵌套渲染，
           支持 default 中引用其他变量，如 story/{{prev_chapter}}/world_state.md）
        2. file 变量：渲染路径 → 读 workspace 内文件内容注入；
           文件不存在且非 required → 置空字符串（源行为：可选文件缺失置空）
        """
        variables: dict[str, Any] = dict(inputs)
        var_defs = self.defn.get("variables", [])

        # 第一轮：文本变量默认值（两轮渲染支持嵌套引用）
        for _ in range(2):
            for v in var_defs:
                key = v.get("key")
                if not key or v.get("type") == "file":
                    continue
                if variables.get(key) is not None and variables.get(key) != "":
                    continue
                default = v.get("default")
                if default is not None:
                    variables[key] = render_template(str(default), variables)

        # 第二轮：file 变量读文件内容
        for v in var_defs:
            key = v.get("key")
            if not key or v.get("type") != "file":
                continue
            existing = variables.get(key)
            # 已有值且看起来是内容（含换行或长度超限）则视为已注入，跳过
            if isinstance(existing, str) and ("\n" in existing or len(existing) > 300):
                continue
            raw_path = existing or v.get("default") or ""
            if not raw_path:
                if not v.get("required", False):
                    variables[key] = ""
                continue
            rel = render_template(str(raw_path), variables)
            try:
                path = self._safe_path(rel)
            except ValueError:
                logger.warning("file 变量 %s 路径非法: %s", key, rel)
                variables[key] = ""
                continue
            if path.exists() and path.is_file():
                try:
                    variables[key] = path.read_text(encoding="utf-8")
                    logger.info("file 变量 %s 已注入: %s（%d 字符）",
                                key, rel, len(variables[key]))
                except OSError as e:
                    logger.warning("file 变量 %s 读取失败: %s", key, e)
                    variables[key] = ""
            else:
                if v.get("required", False):
                    logger.warning("required file 变量 %s 缺失: %s", key, rel)
                variables[key] = ""

        # 第三轮：文件变量注入后再渲染一遍文本变量，解析嵌套引用。
        # 文本变量（如 wroter_context）的 default 引用了 style_guide_file/guide_file 等
        # 文件变量，而这些文件变量要到第二轮才注入；若不在注入后重渲染，
        # wroter_context 里会残留 {{style_guide_file}} 等占位符原样进 LLM，
        # 导致并行写手拿不到真实上下文、正文跑偏。故文件注入完成后统一重渲染一次。
        for v in var_defs:
            key = v.get("key")
            if not key or v.get("type") == "file":
                continue
            cur = variables.get(key)
            if isinstance(cur, str):
                variables[key] = render_template(cur, variables)

        # 会话元信息（E7：26 个 agent 的 system prompt 含 {{session_meta}}）
        # 注入本次创作的关键上下文，让每个 agent 知道"我在为哪一章、什么意图创作"
        _wf_id = self.defn.get('workflow_id', '?')
        _wf_name = self.defn.get('name', '')
        _chapter = variables.get("chapter_number", "未指定")
        _prev = variables.get("prev_chapter", "无")
        _intent = (variables.get("human_intent", "") or "").strip()
        if _intent:
            # 创作意图全量注入：截断会丢后半段创作要求（"看全"原则）
            _intent_short = _intent
        else:
            _intent_short = "（无特定意图，自主推进）"
        _writer = variables.get("writer_type", "single")
        _lang = variables.get("language", "中文")
        variables.setdefault(
            "session_meta",
            f"工作流: {_wf_id}（{_wf_name}）\n"
            f"引擎: NovelCompose 工作流引擎\n"
            f"当前章节: 第{_chapter}章（上一章: 第{_prev}章）\n"
            f"创作意图: {_intent_short}\n"
            f"写手模式: {_writer} | 语言: {_lang}",
        )
        return variables

    # ── 节点执行 ──────────────────────────────────────────────

    def _get_client_for_agent(self, agent_type: str) -> Any:
        """按 agent_type 取对应 LLMClient。

        优先级：AGENT_TYPE_TO_ROLE 映射 + cfg 可用 → 按 role 创建/取缓存 client；
        否则回退到默认 self.llm（外部传入的 req.agent_role client）。

        这样 26+ 个 agent 各自用 config.yaml 里配的角色模型，
        解锁跨模型审校（observer 便宜/writer 强模型）。
        """
        role = AGENT_TYPE_TO_ROLE.get(agent_type)
        if not role or self._cfg is None:
            return self.llm  # 兜底：用默认 client
        if role not in self._client_cache:
            from novel_agent.llm.client import LLMClient
            llm_config = self._cfg.get_agent_llm(role)
            self._client_cache[role] = LLMClient(llm_config)
            logger.info("为 agent_type=%s 创建 role=%s 的 LLMClient", agent_type, role)
        return self._client_cache[role]

    async def close_clients(self) -> None:
        """关闭按 role 缓存的 LLMClient（默认 self.llm 由调用方关闭）。"""
        for role, client in self._client_cache.items():
            try:
                await client.close()
            except Exception:
                pass
        self._client_cache.clear()

    def _enabled_skills_text(self, agent_type: str = "") -> str:
        """加载当前 agent 适用的启用 Skills 注入文本（按 agent_type 缓存）。

        复用 routes_skills.load_enabled_skills_for_injection，保证工作流路径与
        单 Agent 直生成路径（正式写作页/交互式创作）注入逻辑一致，不分叉。
        排除 source=corpus 的语料型 skill：内容庞大且需按上下文检索，工作流
        路径不做检索，全量注入会严重膨胀 token。

        蒸馏-Agent 对齐：传入 agent_type 后，注入侧按 skill 的 agent_roles 过滤，
        每个 agent 只拿到自己负责维度的蒸馏 skill + 全部通用 skill。
        参考书单：项目选了参考书时，只注入选中书的蒸馏 skill（非蒸馏 skill 不受限）。
        """
        if agent_type not in self._skills_text:
            book_ids = self._project_book_ids()
            try:
                from novel_agent.api.routes_skills import load_enabled_skills_for_injection
                self._skills_text[agent_type] = load_enabled_skills_for_injection(
                    exclude_sources=("corpus",), agent_type=agent_type or None,
                    book_ids=book_ids)
            except Exception as e:
                logger.warning("Skills 注入加载失败（工作流路径，agent=%s）: %s",
                               agent_type or "-", e)
                self._skills_text[agent_type] = ""
        return self._skills_text[agent_type]

    def _project_book_ids(self) -> list[int]:
        """项目参考书单（distill_works.id 列表）；无 project_id 或读取失败返回空（不过滤）。"""
        if not self.project_id:
            return []
        try:
            from novel_agent.bible.models import Project
            from novel_agent.config import load_config
            cfg = load_config()
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            engine = create_engine(cfg.database_path)
            Session = sessionmaker(bind=engine)
            s = Session()
            try:
                p = s.query(Project).filter(Project.id == self.project_id).first()
                return (p.style_books or []) if p else []
            finally:
                s.close()
        except Exception as e:
            logger.warning("读取项目参考书单失败（按书过滤降级为不过滤）: %s", e)
            return []

    def _refresh_file_variables(self, *texts: str) -> None:
        """渲染前刷新文本引用的 file 变量：从磁盘现读最新内容并级联重渲染文本变量。

        file 变量在 _resolve_variables 启动时一次性缓存；但流程中动态生成的文件
        （如并行写手运行中写入 cache/writer/*.json）要到下游节点执行时才存在，
        启动时读到的是旧值/空值。故在每个 agent 节点渲染 first_message 前，
        扫描模板里引用的 file 变量、按当前文件内容刷新 self.variables，
        再重渲染一遍文本变量（使 wroter_context 这类内嵌文件内容的文本变量也随新值更新）。
        """
        refs: set[str] = set()
        for text in texts:
            for m in _TEMPLATE_RE.finditer(text or ""):
                refs.add(m.group(1))
        var_defs = self.defn.get("variables", []) or []
        file_keys = {v.get("key") for v in var_defs if v.get("type") == "file"}
        for key in refs & file_keys:
            raw_path = next((v.get("default") for v in var_defs if v.get("key") == key), None)
            if not raw_path:
                continue
            rel = render_template(str(raw_path), self.variables)
            path = self._safe_path(rel)
            if path.exists():
                self.variables[key] = path.read_text(encoding="utf-8")
            else:
                # 文件尚未生成：保持现值（可能为启动时空值），不覆盖为破坏性内容
                self.variables.setdefault(key, "")
        # 级联重渲染文本变量：从其 default 模板重渲染（而非当前值），
        # 使 wroter_context 这类内嵌文件内容的模板变量随文件新值更新。
        # 必须用 default 模板：当前值在 init 时已被解析、占位符已被消费，
        # 再渲染当前值无意义；只有 default 里仍保留 {{file_var}} 占位符。
        # 仅当 default 含占位符时重渲染，避免覆盖 output_variable 写入的运行时值。
        for v in var_defs:
            key = v.get("key")
            if not key or v.get("type") == "file":
                continue
            tpl = str(v.get("default") or "")
            if "{{" in tpl:
                self.variables[key] = render_template(tpl, self.variables)

    async def _exec_agent(self, node: dict[str, Any]) -> str:
        """执行 agent 节点：拼 prompt → 调 LLM → 写回 output_variable。"""
        node_id = node["id"]
        agent_type = node.get("agent_type", "")
        agent_def = self.res.agent_def(agent_type)
        if not agent_def:
            raise RuntimeError(f"未注册的 agent_type: {agent_type}")

        # 渲染前刷新模板引用的 file 变量（并行写手等上游运行中才生成的文件，
        # 让下游 agent 拿到本轮的新值，而不是启动时缓存的旧值）
        node_sys_tpl = node.get("system_prompt_template") or ""
        first_tpl = node.get("first_message", "")
        self._refresh_file_variables(
            self.res.system_prompt(agent_type), node_sys_tpl, first_tpl)

        # P1-1：过渡写手无过渡槽时跳过 LLM 调用（杜绝空转浪费 token）。
        # 骨架 JSON 的 slots.TRANSITION 为空且 skeleton 文本无 [SLOT_TRANSITION_
        # 标记时，过渡写手无槽可填（历史实测产出空 {} 全靠整合器兜底），
        # 直接落盘空 {} 并跳过 LLM 调用。
        if agent_type == "novel-transition-writer":
            try:
                skeleton_raw = self.variables.get("framework_writer_cache", "") or ""
                if not _has_transition_slots(skeleton_raw):
                    logger.info(
                        "过渡写手（%s）：骨架无 TRANSITION 槽，跳过 LLM 调用，产物为空 {}",
                        node_id)
                    if node.get("save_output_to_file") and node.get("output_file_path"):
                        rel = render_template(node["output_file_path"], self.variables)
                        path = self._safe_path(rel)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("{}", encoding="utf-8")
                    return "{}"
            except Exception as e:
                logger.warning("过渡写手槽检查失败（仍走 LLM）: %s", e)

        # system prompt 也需要模板渲染（{{session_meta}}/{{genre}} 等占位符）
        system = render_template(self.res.system_prompt(agent_type), self.variables)
        # node 级 system_prompt_template 覆盖（定义里通常为空）
        if node_sys_tpl:
            system = render_template(node_sys_tpl, self.variables) + "\n\n" + system

        # 蒸馏/启用 Skills 注入：
        # - 写手系（role==writer）注入文风约束（原有行为）；
        # - 蒸馏维度映射覆盖的 agent（世界观/角色/大纲/润色等）按自身维度注入
        #   （agent_roles 过滤，每个 agent 只拿自己负责维度的蒸馏 skill + 通用 skill）。
        # 对应蒸馏-Agent 对齐：每个 agent 只学习自己负责的技能，避免上下文爆炸。
        role = AGENT_TYPE_TO_ROLE.get(agent_type)
        if role == "writer" or agent_type in _dimension_agent_types():
            skills_text = self._enabled_skills_text(agent_type)
            if skills_text:
                if role == "writer":
                    system = f"{system}\n\n【写作风格要求】\n{skills_text}"
                else:
                    system = f"{system}\n\n【专业技能注入--当前维度方法论，创作时遵循】\n{skills_text}"

        first_message = render_template(first_tpl, self.variables)
        params = self.res.model_params(agent_type)
        temperature = params.get("temperature")
        thinking = bool(params.get("thinking_enabled", True))

        # 按 agent_type 取对应 LLMClient（模型分配，解锁跨模型审校）
        client = self._get_client_for_agent(agent_type)
        content = await client.generate(
            first_message,
            system=system or None,
            temperature=temperature,
            thinking=thinking,
            node_name=node_id,
        )

        # 清理 LLM 输出常见的 markdown 代码块围栏（```json ... ```）
        # bishu-novel 的后处理脚本用 json.load 直接读产物文件，围栏会导致解析失败。
        # 此处统一在 agent 输出落盘前清理，避免逐个修 17 个 post 脚本。
        content = _strip_code_fence(content)

        out_var = node.get("output_variable") or ""
        if out_var:
            self.variables[out_var] = content

        # 产物落盘
        if node.get("save_output_to_file") and node.get("output_file_path"):
            rel = render_template(node["output_file_path"], self.variables)
            path = self._safe_path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            logger.info("节点 %s 产物已落盘: %s", node_id, path)

        return content

    async def _exec_script(self, node: dict[str, Any]) -> str:
        """执行 script 节点：调 nvl 脚本库（进程级锁串行，防 chdir 竞态）。"""
        from novel_agent.workflows.scripts import nvl

        node_id = node["id"]
        params = node.get("node_params", {}) or {}
        script_name = params.get("script_name", "")

        raw_args = render_template(params.get("script_args", ""), self.variables)
        args = shlex.split(raw_args) if raw_args else []

        result = await nvl.run_script(script_name, args, self.workspace)
        if isinstance(result, dict) and result.get("status") == "failed":
            raise RuntimeError(f"脚本 {script_name} 失败: {result.get('error', 'unknown')}")

        # WF_VAR 协议：脚本 stdout 中的 <WF_VAR>key:value</WF_VAR> 回写变量表
        # （parse_intent → od_intent/se_intent；extract_names → character_names）
        if isinstance(result, dict):
            wf_vars = _parse_wf_vars(str(result.get("stdout", "")))
            if wf_vars:
                self.variables.update(wf_vars)
                logger.info("节点 %s 回写变量: %s", node_id, list(wf_vars))

        out_text = (json.dumps(result, ensure_ascii=False)[:2000]
                    if isinstance(result, dict) else str(result))
        # script 节点 output_variable 对称支持（当前定义该字段均空，防御性）
        out_var = node.get("output_variable") or ""
        if out_var:
            self.variables[out_var] = out_text
        return out_text

    async def _run_node(self, node_id: str) -> bool:
        """执行单个节点（带失败策略）。返回是否成功。"""
        node = self.nodes[node_id]
        node_type = node.get("node_type", "")
        t0 = time.time()
        await self._emit({"type": "node_start", "node": node_id,
                          "label": node.get("label", node_id)})
        try:
            if node_type == "agent":
                output = await self._exec_agent(node)
            elif node_type == "script":
                output = await self._exec_script(node)
            else:
                raise RuntimeError(f"未知节点类型: {node_type}")
            self._record(node_id, WorkflowNodeStatus.OK.value, time.time() - t0, output_preview=output)
            await self._emit({"type": "node_done", "node": node_id,
                              "elapsed_s": round(time.time() - t0, 2)})
            return True
        except Exception as e:
            self._record(node_id, WorkflowNodeStatus.FAILED.value, time.time() - t0, error=str(e))
            await self._emit({"type": "node_failed", "node": node_id, "error": str(e)})
            if node.get("fail_auto_skip"):
                logger.warning("节点 %s 失败，按 fail_auto_skip 跳过: %s", node_id, e)
                return True
            logger.error("节点 %s 执行失败: %s", node_id, e)
            return False

    # ── 网关处理 ──────────────────────────────────────────────

    def _next_edges(self, node_id: str) -> list[dict[str, Any]]:
        return self.edges_from.get(node_id, [])

    def _pick_condition_edge(self, gw_id: str) -> str | None:
        """条件网关：取表达式为真的边，否则取默认边。"""
        edges = self._next_edges(gw_id)
        default_target: str | None = None
        for e in edges:
            cond = e.get("condition") or {}
            if cond.get("is_default"):
                default_target = e["target"]
                continue
            expr = cond.get("expression", "")
            if expr and _eval_condition(expr, self.variables):
                return e["target"]
        return default_target

    async def _walk_until(self, start_id: str, stop_ids: set[str]) -> bool:
        """从 start_id 顺序执行，直到遇到 stop_ids 中的节点或 __end__。

        用于并行分支与循环体的局部行走。不进入嵌套网关（嵌套网关由主循环处理）。
        """
        current = start_id
        while current and current not in stop_ids:
            if current == "__end__":
                return True
            if current in self.gateways:
                # 分支内部遇到网关：交给主流程处理逻辑过于复杂，
                # 目前移植定义中并行分支均为纯线性链，遇到网关即停。
                return current in stop_ids
            if not await self._run_node(current):
                return False
            edges = self._next_edges(current)
            if not edges:
                return True
            current = edges[0]["target"]
        return True

    async def _exec_parallel(self, gw: dict[str, Any]) -> str | None:
        """并行网关：分支 asyncio.gather 并发执行，汇聚后继续。"""
        gw_id = gw["id"]
        converge_id = gw.get("converge_gateway_id")
        branches = [e["target"] for e in self._next_edges(gw_id)]
        stop = {converge_id} if converge_id else {"__end__"}
        logger.info("并行网关 %s: %d 个分支，汇聚于 %s", gw_id, len(branches), converge_id)
        results = await asyncio.gather(
            *[self._walk_until(b, stop) for b in branches],
            return_exceptions=True,
        )
        for b, r in zip(branches, results):
            if isinstance(r, Exception):
                logger.error("并行分支 %s 异常: %s", b, r)
                return None
            if r is False:
                logger.error("并行分支 %s 执行失败", b)
                return None
        return converge_id

    async def _exec_loop(self, gw_id: str) -> str | None:
        """循环网关：对列表变量逐项迭代循环体，完成后走退出边。"""
        edges = self._next_edges(gw_id)
        body_edge: dict[str, Any] | None = None
        exit_edge: dict[str, Any] | None = None
        for e in edges:
            cond = e.get("condition") or {}
            expr = cond.get("expression", "")
            if _LOOP_RE.search(expr):
                body_edge = e
            elif cond.get("is_default"):
                exit_edge = e
        if body_edge is None or exit_edge is None:
            logger.error("循环网关 %s 缺少循环体或退出边", gw_id)
            return None

        m = _LOOP_RE.search(body_edge["condition"]["expression"])
        item_var, list_var = m.group(1), m.group(2)
        items = self.variables.get(list_var) or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [s.strip() for s in items.split(",") if s.strip()]
        if not isinstance(items, list):
            logger.error("循环变量 %s 不是列表: %r", list_var, items)
            return None

        logger.info("循环网关 %s: %s 共 %d 项", gw_id, list_var, len(items))
        # 记录循环开始前的变量快照，循环结束后清理循环体产生的临时变量
        pre_loop_keys = set(self.variables.keys())
        for item in items:
            self.variables[item_var] = item
            ok = await self._walk_until(body_edge["target"], {gw_id, "__end__"})
            if not ok:
                logger.error("循环体在 %s=%r 时失败", item_var, item)
                return None
            # 循环体内 _refresh_file_variables 可能将大文件内容读入 self.variables，
            # 清理本轮新增的 file 类型变量以降低内存峰值（下一轮会重新读取）
            var_defs = self.defn.get("variables", []) or []
            file_keys = {v.get("key") for v in var_defs if v.get("type") == "file"}
            for key in list(self.variables.keys()):
                if key in file_keys and key not in pre_loop_keys and key != item_var:
                    val = self.variables[key]
                    if isinstance(val, str) and len(val) > 10000:
                        self.variables[key] = ""  # 清空大文件缓存，下次 _refresh_file_variables 会重读
        return exit_edge["target"]

    # ── 主循环 ────────────────────────────────────────────────

    async def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """执行工作流。inputs 为 variables 的初始值。"""
        self.variables = self._resolve_variables(inputs)
        self.status = TaskStatus.RUNNING.value
        self.workspace.mkdir(parents=True, exist_ok=True)

        current = "__start__"
        start_edges = self._next_edges("__start__")
        if not start_edges:
            self.status = TaskStatus.FAILED.value
            return {"status": TaskStatus.FAILED.value, "error": "工作流无起始边"}
        current = start_edges[0]["target"]

        while current and current != "__end__":
            if current in self.gateways:
                gw = self.gateways[current]
                gtype = gw.get("gateway_type")
                if gtype == "condition":
                    current = self._pick_condition_edge(current)
                elif gtype == "parallel":
                    current = await self._exec_parallel(gw)
                elif gtype == "converge":
                    edges = self._next_edges(current)
                    current = edges[0]["target"] if edges else "__end__"
                elif gtype == "loop":
                    current = await self._exec_loop(current)
                else:
                    logger.error("未知网关类型: %s", gtype)
                    self.status = TaskStatus.FAILED.value
                    break
                continue

            if not await self._run_node(current):
                self.status = TaskStatus.FAILED.value
                break

            edges = self._next_edges(current)
            if not edges:
                current = "__end__"
            else:
                current = edges[0]["target"]

        if current == "__end__" and self.status == TaskStatus.RUNNING.value:
            self.status = TaskStatus.COMPLETED.value
        elif self.status == TaskStatus.RUNNING.value:
            self.status = TaskStatus.FAILED.value

        await self._emit({"type": "workflow_done", "status": self.status})
        return {
            "status": self.status,
            "variables": self.variables,
            "node_runs": self.node_runs,
        }


# ── 顶层入口 ──────────────────────────────────────────────────

async def run_workflow(
    workflow_id: str,
    inputs: dict[str, Any],
    llm_client: Any,
    workspace: Path | str,
    on_event: EventCallback | None = None,
    project_id: int | None = None,
    cfg: Any = None,
) -> dict[str, Any]:
    """加载并执行一条工作流。

    Args:
        workflow_id: build/character/story-plan/outline/mvp/post-hoc/polish 或自定义 workflow_id
        inputs: 工作流变量初始值（对应定义中的 variables）
        llm_client: NovelAgent LLMClient 实例（默认兜底 client）
        workspace: 项目工作区目录（通常 Config().project_dir(project_id)）
        on_event: 可选异步事件回调（node_start/node_done/node_failed/workflow_done）
        project_id: 项目 ID（用于加载自定义工作流；内置工作流可省略）
        cfg: Config 实例，给定时按 AGENT_TYPE_TO_ROLE 为每个 agent 创建独立模型 client

    Returns:
        {"status": "completed"/"failed", "variables": ..., "node_runs": [...]}
    """
    definition = load_definition(workflow_id, project_id=project_id)

    # P1-3：mvp 前置依赖友好报错——没跑过上游工作流直接跑 mvp 时，
    # 缺产物给中文友好提示（替代底层"缺少本地存档文件"的报错）
    if workflow_id == "mvp":
        missing = _mvp_precheck_missing(Path(workspace))
        if missing:
            return {
                "status": "failed",
                "error": (
                    "缺少上游产物，无法运行 mvp：\n- "
                    + "\n- ".join(missing)
                    + "\n请先在「工作流」页按顺序运行：build → story-plan → outline → mvp。"
                ),
                "variables": {},
                "node_runs": [],
            }

    runner = WorkflowRunner(definition, llm_client, Path(workspace),
                            on_event=on_event, cfg=cfg, project_id=project_id)
    try:
        return await runner.run(inputs)
    finally:
        # 关闭按 role 缓存的 client（默认 llm_client 由调用方关闭）
        await runner.close_clients()
