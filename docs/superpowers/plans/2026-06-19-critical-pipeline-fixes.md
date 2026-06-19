# 核心生成流程断裂修复计划（P0/P1 + 管线断裂）

> **For agentic workers:** REQUIRED SUB-TOOL: Use Task subagent with type `general_purpose_task` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复核心生成流程的三条致命断裂（生成静默失败、审计 JSON 解析失败导致写审循环永远跑满、章节产出 JSON 垃圾），再补齐规划→生成管线断裂、S-001 硬编码、write 失败空转三个逻辑漏洞。

**根因总结：** 三个 P0 问题的共同根因是"LLM 返回的 JSON 格式和代码期望的 schema 不匹配，但代码没有健壮处理"。mock 测试用预设合法 JSON 全绿，真实 LLM 返回格式千变万化导致全崩。

---

## 文件结构

| 文件 | 责任 |
|------|------|
| `novel_agent/api/routes_generation.py` | generate_world/characters 静默失败修复 |
| `novel_agent/audit/schemas.py` | AuditReport schema 宽容化 |
| `novel_agent/audit/auditor.py` | 审计 JSON 解析健壮性 |
| `novel_agent/orchestrator/nodes.py` | write 失败短路 + 正文校验 + S-001 修复 + 细纲注入 |
| `novel_agent/memory/core.py` | 补全 `_chapter_outline_summary` 方法 |
| `novel_agent/planning/agents.py` | 清理 S-001 硬编码示例 |
| `frontend/src/api.ts` | getChapterText/saveChapterText/deleteChapter 补 project_id |
| `frontend/src/views/ChapterEditorView.tsx` | 适配新 API 签名 |

---

## P0-1: 修复生成世界观/角色静默失败返回 0 items

**Files:**
- Modify: `novel_agent/api/routes_generation.py`

**Why:** `generate_world`/`generate_characters` 调 LLM 后用 `_extract_json` 解析，若 LLM 返回的 JSON key 不匹配（如返回 `worlds` 而非 `world_settings`）或调用失败，静默拿到空列表，用户看到"created: 0"以为成功。

- [ ] **Step 1: 在 generate_world 中增加 LLM 调用错误捕获和 key 兼容**

  在 `routes_generation.py` 的 `generate_world` 中：
  1. 包裹 `client.generate` 调用，失败时 `raise HTTPException(502, f"LLM 调用失败: {e}")`。
  2. `_extract_json` 返回空 dict 时，抛 HTTPException(502, "LLM 返回内容无法解析为 JSON")。
  3. key 兼容：`settings = result.get("world_settings") or result.get("worlds") or result.get("settings") or []`。
  4. 空列表时在 response 中加 `warning` 字段说明"LLM 未返回有效设定项"。

- [ ] **Step 2: 对 generate_characters 做同样处理**

  key 兼容：`characters = result.get("characters") or result.get("chars") or result.get("roles") or []`。

- [ ] **Step 3: 在 Response 模型中增加可选 warning 字段**

  ```python
  class GenerateWorldResponse(BaseModel):
      created: int
      items: list[dict] = []
      warning: str = ""
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add novel_agent/api/routes_generation.py
  git commit -m "fix(generation): surface LLM failures instead of silently returning 0 items"
  ```

---

## P0-2: 修复审计报告 JSON 解析失败

**Files:**
- Modify: `novel_agent/audit/schemas.py`
- Modify: `novel_agent/audit/auditor.py`

**Why:** `AuditReport` 要求 `passed: bool` 和 `overall_score: int(ge=0,le=100)` 必填，LLM 返回的 JSON 常缺字段或类型错误（如 `overall_score: "85"` 字符串），导致 `AuditReport(**data)` 校验失败，审计永远 `passed=False`，写审循环永远跑满 3 次。

- [ ] **Step 1: 让 AuditReport schema 宽容化**

  在 `audit/schemas.py` 中：
  1. `passed` 默认 `False`（已是 bool，但确保 LLM 返回的 "true"/"false" 字符串能转换）。
  2. `overall_score` 改为 `int = Field(default=0, ge=0, le=100)`，加 validator 自动将字符串转 int。
  3. `issues` 中的 `severity` 加默认值 `"minor"`，允许 LLM 返回非枚举值时降级而非报错。

  ```python
  from pydantic import field_validator

  class AuditReport(BaseModel):
      passed: bool = False
      overall_score: int = Field(default=0, ge=0, le=100)
      issues: list[Issue] = Field(default_factory=list)
      summary: str = ""
      suggestions: list[str] = Field(default_factory=list)

      @field_validator("overall_score", mode="before")
      @classmethod
      def _coerce_score(cls, v):
          try:
              return int(v)
          except (TypeError, ValueError):
              return 0

      @field_validator("passed", mode="before")
      @classmethod
      def _coerce_passed(cls, v):
          if isinstance(v, str):
              return v.lower() in ("true", "1", "yes", "通过")
          return bool(v)
  ```

- [ ] **Step 2: 在 auditor.py 解析时做字段补全**

  在 `auditor.py` 的 `AuditReport(**data)` 之前：
  1. 若 data 缺 `passed`，从 issues 推断：有 critical issue 则 `passed=False`，否则 `True`。
  2. 若 data 缺 `overall_score`，默认 60。
  3. issues 列表中每项补全缺字段。
  4. 用 `model_validate` 替代直接 `**data` 构造，让 validator 生效。

- [ ] **Step 3: Commit**

  ```bash
  git add novel_agent/audit/schemas.py novel_agent/audit/auditor.py
  git commit -m "fix(audit): tolerant JSON parsing so audit loop doesn't always fail"
  ```

---

## P0-3: 修复章节生成产出 JSON 垃圾而非正文

**Files:**
- Modify: `novel_agent/orchestrator/nodes.py`

**Why:** 审计永远失败导致写审循环跑满 3 次，Writer 在 rewrite 时 prompt 被污染产出建议 JSON 而非正文。根因在 P0-2（审计），但 write 节点也需增加正文校验。

- [ ] **Step 1: 在 write_chapter/rewrite_chapter 增加正文校验**

  LLM 返回后检测：若 draft 以 `{` 开头或包含 `"suggestions"` / `"title"` / `"summary"` 等 JSON 结构特征，判定为非正文，返回 `status: "failed"`。

  ```python
  def _looks_like_json_not_prose(text: str) -> bool:
      s = text.strip()
      if s.startswith("{") and s.endswith("}"):
          return True
      if '"suggestions"' in s or '"payload"' in s:
          return True
      return False
  ```

  在 write_chapter 和 rewrite_chapter 的 `clean_chapter_text` 后调用此检查。

- [ ] **Step 2: 在 route_after_audit 增加 failed 短路（原 Task 3）**

  ```python
  def route_after_audit(state: ChapterGenState) -> str:
      if state.get("status") == "failed" or not state.get("draft", "").strip():
          return "end_failed"
      report = AuditReport(**state.get("audit_report", {}))
      if report.passed:
          return "polish"
      if state.get("review_iterations", 0) >= 3:
          return "end_failed"
      return "rewrite"
  ```

- [ ] **Step 3: 增加日志**

  write 失败和 route 进入 end_failed 时 `logger.warning`。

- [ ] **Step 4: Commit**

  ```bash
  git add novel_agent/orchestrator/nodes.py
  git commit -m "fix(orchestrator): validate prose output + short-circuit failed writes"
  ```

---

## P1-1: 修复章节正文 API 缺 project_id

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/views/ChapterEditorView.tsx`（及所有调用方）

**Why:** 后端 `GET /api/chapters/{chapter}/text` 需要 `project_id` query 参数，前端 `getChapterText(chapter)` 没传，导致 422。同样影响 `saveChapterText` 和 `deleteChapter`。

- [ ] **Step 1: 修改 api.ts 三个方法签名**

  ```typescript
  getChapterText: (projectId: number, chapter: number) =>
    request<ChapterText>(`/api/chapters/${chapter}/text?project_id=${projectId}`),
  saveChapterText: (projectId: number, chapter: number, title: string, content: string) =>
    request<void>(`/api/chapters/${chapter}/text?project_id=${projectId}`, { method: "PUT", body: JSON.stringify({ title, content }) }),
  deleteChapter: (projectId: number, chapter: number) =>
    request<void>(`/api/chapters/${chapter}?project_id=${projectId}`, { method: "DELETE" }),
  ```

- [ ] **Step 2: 更新所有调用方传入 projectId**

  搜索 `getChapterText` / `saveChapterText` / `deleteChapter` 的调用处，补上 projectId 参数。

- [ ] **Step 3: 类型检查与构建**

  ```bash
  cd frontend && npx tsc --noEmit && npm run build
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/api.ts frontend/src/views/ChapterEditorView.tsx
  git commit -m "fix(frontend): pass project_id to chapter text APIs"
  ```

---

## P1-2: 生成失败增加可操作反馈

**Files:**
- Modify: `novel_agent/api/routes_generation.py`

**Why:** 生成返回 0 items 时 UI 只显示"创建了 0 个"，用户不知道原因。

- [ ] **Step 1: 在 generate_world/characters 的空结果分支返回 warning**

  当 LLM 调用成功但解析出空列表时，response 中 `warning` 字段填入：
  - "LLM 返回了内容但格式不匹配，未提取到有效项。原始返回前200字：{raw[:200]}"
  - 或 "LLM 返回了空结果，可能是 prompt 不够明确或模型能力不足。"

- [ ] **Step 2: Commit**

  ```bash
  git add novel_agent/api/routes_generation.py
  git commit -m "feat(generation): add warning field for empty results with diagnostic info"
  ```

---

## Task 1: 补全规划→生成断裂修复

**Files:**
- Modify: `novel_agent/memory/core.py`

**Why:** core.py 已注入 `chapter_outline` 但缺少 `_chapter_outline_summary` 方法定义，运行时会 AttributeError。

- [ ] **Step 1: 实现 `_chapter_outline_summary` 方法**

  ```python
  def _chapter_outline_summary(self, chapter: int) -> str:
      outlines = self.repo.list_outlines(level="chapter")
      match = next((o for o in outlines if o.order == chapter), None)
      if not match:
          return ""
      lines = [f"【本章细纲】"]
      lines.append(f"标题：{match.title}")
      lines.append(f"概要：{match.summary}")
      if match.act:
          lines.append(f"节奏：{match.act}")
      if match.strand:
          lines.append(f"故事线：{match.strand}")
      return "\n".join(lines)
  ```

- [ ] **Step 2: 在 write_chapter prompt 中强化细纲约束（与 P0-3 合并）**

  nodes.py 的 write_chapter prompt 已有 context（含 chapter_outline），增加显式约束行。

- [ ] **Step 3: 运行测试**

  ```bash
  python -m pytest tests/ -q
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add novel_agent/memory/core.py novel_agent/orchestrator/nodes.py
  git commit -m "fix(pipeline): complete chapter outline injection into writer context"
  ```

---

## Task 2: 修复 S-001 硬编码污染伏笔系统

**Files:**
- Modify: `novel_agent/orchestrator/nodes.py`
- Modify: `novel_agent/planning/agents.py`

- [ ] **Step 1: 将 summarize prompt 中的 `["S-001"]` 改为 `[]`**

  nodes.py:168 `fs_instruction = ',"resolved_foreshadows":["S-001"]'` → `fs_instruction = ',"resolved_foreshadows":[]'`

- [ ] **Step 2: 清理 planning/agents.py 中的 S-001 示例**

  搜索 `"S-001"` 或 `"id":"S-001"`，改为占位符 `"F-XXX"`，prompt 中说明"ID 需项目内唯一，勿照抄示例"。

- [ ] **Step 3: Commit**

  ```bash
  git add novel_agent/orchestrator/nodes.py novel_agent/planning/agents.py
  git commit -m "fix(foreshadows): remove hardcoded S-001 example from prompts"
  ```

---

## 执行顺序

1. **P0-1 + P0-2 + P0-3**（三个 P0 一起修，因为根因关联）→ 让核心生成流程能跑通
2. **P1-1**（章节正文 API）→ 让阅读功能能用
3. **Task 1**（补全 chapter_outline 方法）→ 修复 core.py 的 AttributeError
4. **Task 2**（S-001 硬编码）→ 修复伏笔数据正确性
5. **P1-2**（生成失败反馈）→ 提升体验
6. 全量测试 + 提交

---

## 自检

1. **P0 覆盖：**
   - 生成静默失败 → P0-1（错误捕获 + key 兼容 + warning）
   - 审计 JSON 解析失败 → P0-2（schema 宽容 + 字段补全）
   - 章节产出 JSON 垃圾 → P0-3（正文校验 + failed 短路）

2. **P1 覆盖：**
   - 章节正文 API 422 → P1-1（补 project_id）
   - 生成失败无反馈 → P1-2（warning 字段）

3. **管线修复：**
   - 规划→生成断裂 → Task 1（补全 _chapter_outline_summary）
   - S-001 污染 → Task 2（改空数组）

4. **安全：** 不引入新的静默 except，所有失败路径有明确错误信息或 warning。
