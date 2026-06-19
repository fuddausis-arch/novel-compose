# 复查修复计划 v2：堵漏洞 + 补未动项

> **For agentic workers:** REQUIRED SUB-TOOL: Use Task subagent with type `general_purpose_task` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复复查发现的问题：write 短路被 audit 覆写（修破了）、S-001 上游未堵（修了一半），并补齐完全没动的清单项。

---

## Fix A: 修复 write 失败短路被 audit 覆写（修破了，最高优先级）

**Files:**
- Modify: `novel_agent/orchestrator/graph.py`
- Modify: `novel_agent/orchestrator/nodes.py`

**Why:** graph 里 write→audit 是直连边，audit_chapter 无条件返回 status="audited"/"needs_rewrite"，覆写掉 write 的 "failed"。到 route_after_audit 时 status 永远不等于 failed，短路分支永不命中。write 失败后仍跑一次 audit 审空草稿（白烧 LLM），然后空转 rewrite 循环。

- [ ] **Step 1: 在 graph.py 中 write 后用条件边，failed 直连 END**

  把 `graph.add_edge("write", "audit")` 改为条件路由：
  ```python
  def route_after_write(state: ChapterGenState) -> str:
      if state.get("status") == "failed":
          return "end_failed"
      return "audit"

  graph.add_conditional_edges(
      "write", route_after_write,
      {"audit": "audit", "end_failed": END},
  )
  ```
  同样把 `rewrite → audit` 也改为条件边（rewrite 也可能 failed）。

- [ ] **Step 2: audit_chapter 不覆写 failed status**

  在 `audit_chapter` 开头检查：
  ```python
  if state.get("status") == "failed" or not state.get("draft", "").strip():
      return {"status": "failed", "audit_report": AuditReport(
          passed=False, overall_score=0, summary="草稿为空或生成失败").model_dump()}
  ```

- [ ] **Step 3: route_after_audit 保留 failed 检查作为双保险**

  保持现有 `if state.get("status") == "failed": return "end_failed"`。

- [ ] **Step 4: 运行测试 + 修复 test_orchestrator_nodes_m3.py**

  可能需要更新测试以适应新的条件边。

- [ ] **Step 5: Commit**

  ```bash
  git add novel_agent/orchestrator/graph.py novel_agent/orchestrator/nodes.py tests/
  git commit -m "fix(orchestrator): write/rewrite failed short-circuits to END, audit skips empty draft"
  ```

---

## Fix B: 修复 S-001 硬编码上游（planning/agents.py）

**Files:**
- Modify: `novel_agent/planning/agents.py`

- [ ] **Step 1: 将 Outliner prompt 的 "id":"S-001" 改为占位符**

  ```python
  # 改前
  "\"foreshadows\":[{{\"id\":\"S-001\","
  # 改后
  "\"foreshadows\":[{{\"id\":\"F-XXX\","
  ```

  并在 prompt 末尾加："伏笔 ID 需项目内唯一（格式 F-001/F-002...），不要照抄示例值。"

- [ ] **Step 2: Commit**

  ```bash
  git add novel_agent/planning/agents.py
  git commit -m "fix(planning): replace S-001 example with F-XXX placeholder in Outliner prompt"
  ```

---

## Fix C: 工程卫生（清单12/13/14）

**Files:**
- Delete: tmp_*.py, tmp-*.html, theme-*.png, design-mockups.png
- Delete: frontend-old-native/
- Modify: .gitignore
- Modify: config.yaml

- [ ] **Step 1: 删除临时文件**

  ```bash
  git rm tmp_adopt_test.py tmp_integration_test.py tmp_mock_llm.py tmp_p0_verify.py tmp-design-mockups.html
  git rm -rf frontend-old-native/
  rm theme-*.png design-mockups.png
  ```

- [ ] **Step 2: 更新 .gitignore**

  添加：
  ```
  .superpowers/
  theme-*.png
  design-mockups.png
  tmp-*.py
  tmp-*.html
  ```

- [ ] **Step 3: 修正 config.yaml 矛盾参数**

  - `max_tokens: 15000`（与 context_length:4096 矛盾，改为 4000）
  - `context_length: 4096` 改为按模型实际值（Doubao-Seed-2.0-pro 应为 128000 或查实际）

- [ ] **Step 4: Commit**

  ```bash
  git add .gitignore config.yaml
  git commit -m "chore(cleanup): remove temp files, fix config contradictions, ignore build artifacts"
  ```

---

## Fix D: Issue.severity 恢复类型约束

**Files:**
- Modify: `novel_agent/audit/schemas.py`

- [ ] **Step 1: severity 恢复为带 fallback 的 Literal**

  用 validator 容错而非降级为 str：
  ```python
  class Issue(BaseModel):
      dimension: str = ""
      severity: Literal["critical", "important", "minor"] = "minor"
      message: str = ""
      location: str = ""

      @field_validator("severity", mode="before")
      @classmethod
      def _coerce_severity(cls, v):
          if isinstance(v, str) and v.lower() in ("critical", "important", "minor"):
              return v.lower()
          return "minor"
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add novel_agent/audit/schemas.py
  git commit -m "fix(audit): restore severity Literal with tolerant validator"
  ```

---

## Fix E: 确定性审计（清单6）

**Files:**
- Create: `novel_agent/audit/validator.py`
- Modify: `novel_agent/orchestrator/nodes.py`

- [ ] **Step 1: 创建 validator.py 硬检查器**

  ```python
  import re

  FORBIDDEN_WORDS = ["忽然", "竟然", "不禁", "赫然", "蓦然", "陡然"]

  def check_word_count(draft: str, min_w: int = 1500, max_w: int = 5000) -> tuple[bool, str]:
      count = len(re.findall(r'[\u4e00-\u9fff]', draft))
      if count < min_w:
          return False, f"字数不足：{count} < {min_w}"
      if count > max_w:
          return False, f"字数超限：{count} > {max_w}"
      return True, f"字数达标：{count}"

  def check_forbidden_words(draft: str, max_count: int = 3) -> tuple[bool, list[str]]:
      hits = [w for w in FORBIDDEN_WORDS if draft.count(w) > 0]
      return len(hits) <= max_count, hits

  def check_foreshadows_planted(draft: str, foreshadow_ids: list[str]) -> tuple[bool, list[str]]:
      missing = [fid for fid in foreshadow_ids if fid not in draft and fid.split(":")[-1] not in draft]
      return len(missing) == 0, missing
  ```

- [ ] **Step 2: 在 audit_chapter 中先跑硬检查**

  硬检查失败直接 passed=False，并把结果喂给 LLM 审计 prompt。

- [ ] **Step 3: Commit**

  ```bash
  git add novel_agent/audit/validator.py novel_agent/orchestrator/nodes.py
  git commit -m "feat(audit): add deterministic checks for wordcount/forbiddenwords/foreshadows"
  ```

---

## Fix F: 写审分离（清单7）

**Files:**
- Modify: `novel_agent/config.py`
- Modify: `novel_agent/orchestrator/runner.py`
- Modify: `config.yaml`

- [ ] **Step 1: Config 新增 auditor_llm 字段**

  ```python
  @dataclass
  class Config:
      ...
      auditor_llm: LLMConfig | None = None  # None 时回退到 llm
  ```

  `load_config` 中读取 `auditor_llm` 段，为空则回退。

- [ ] **Step 2: runner.py 使用独立 client**

  ```python
  writer_client = LLMClient(config.llm)
  auditor_client = LLMClient(config.auditor_llm or config.llm)
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add novel_agent/config.py novel_agent/orchestrator/runner.py config.yaml
  git commit -m "feat(config): allow independent auditor_llm configuration"
  ```

---

## Fix G: 角色状态闭环（清单2）

**Files:**
- Modify: `novel_agent/orchestrator/nodes.py`
- Modify: `novel_agent/bible/models.py`
- Modify: `novel_agent/bible/repository.py`

- [ ] **Step 1: Character 模型增加 state 字段（若不存在）**

  检查 Character 是否有 current_location/current_emotion/known_facts，没有则添加。

- [ ] **Step 2: summarize_chapter prompt 增加角色状态提取**

  prompt 要求 LLM 输出 `character_states: [{name, location, emotion, new_info}]`。

- [ ] **Step 3: summarize_chapter 解析后更新角色状态**

  ```python
  for cs in data.get("character_states", []):
      repo.update_character(cs["name"],
          current_location=cs.get("location", ""),
          current_emotion=cs.get("emotion", ""))
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add novel_agent/orchestrator/nodes.py novel_agent/bible/models.py novel_agent/bible/repository.py
  git commit -m "feat(pipeline): character state update after each chapter summarize"
  ```

---

## Fix H: archival 中文 embedding（清单3）

**Files:**
- Modify: `novel_agent/memory/archival.py`

- [ ] **Step 1: 替换 embedding model 为 bge-small-zh-v1.5**

- [ ] **Step 2: Commit**

---

## Fix I: 卷级摘要（清单4）

**Files:**
- Modify: `novel_agent/memory/recall.py`

- [ ] **Step 1: 实现 get_volume_summary**

- [ ] **Step 2: Commit**

---

## 执行顺序

1. **Fix A**（write 短路，修破了，最高优先级）
2. **Fix B**（S-001 上游）
3. **Fix C**（工程卫生）
4. **Fix D**（severity 类型恢复）
5. **Fix E**（确定性审计）
6. **Fix F**（写审分离）
7. **Fix G**（角色状态闭环）
8. **Fix H + I**（中文 embedding + 卷级摘要）
9. 全量测试 + 提交

---

## 自检

1. **修破了** → Fix A（条件边绕过 audit）
2. **修了一半** → Fix B（planning/agents.py S-001）
3. **完全没动** → Fix C-I
4. **安全**：config.yaml 矛盾参数修复，临时文件清理
