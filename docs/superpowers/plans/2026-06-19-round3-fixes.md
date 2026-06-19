# 第三轮修复计划：P1 失败反馈 + P2 质量/体验

> **For agentic workers:** REQUIRED SUB-TOOL: Use Task subagent with type `general_purpose_task` to implement this plan task-by-task.

**Goal:** 修复第二轮审查发现的 P1（失败反馈不明确、配额识别、审计 issues 校验）和 P2（垃圾项目、SSE 进度、章节用 brief、dashboard 端点）问题。

---

## P1-1: LLM 失败返回错误码而非 200+created:0

**Files:** `novel_agent/api/routes_generation.py`

- [ ] **Step 1:** generate_world/characters/volumes/arcs/chapters 中，LLM 调用失败时已 raise HTTPException(502)。但 `_extract_json` 返回空 dict 或 key 不匹配导致空列表时，当前返回 200+warning。改为：空列表时返回 `HTTP 422` + warning 文本作为错误详情，让前端明确知道生成失败。

- [ ] **Step 2:** Commit

---

## P1-2: 适配方舟平台配额超限响应

**Files:** `novel_agent/llm/client.py`

- [ ] **Step 1:** 扩展配额检测关键词，匹配方舟/火山引擎平台：
  - `"quota"` / `"AccountQuotaExceeded"`（现有）
  - 增加 `"exceeded"` / `"limit reached"` / `"insufficient"` / `"余额不足"` / `"配额"` / `"rate limit"` 

- [ ] **Step 2:** 429 之外，方舟可能用 400/403 返回配额错误。在 HTTPStatusError 处理中，对 400/403 也检查 body 是否含配额关键词。

- [ ] **Step 3:** Commit

---

## P1-3: 审计 issues 字段宽容补全

**Files:** `novel_agent/audit/auditor.py`

- [ ] **Step 1:** 在 `model_validate` 前，遍历 data["issues"] 补全缺字段：dimension 默认 "未分类"，severity 默认 "minor"，message 默认 "无描述"。

- [ ] **Step 2:** Commit

---

## P2-1: 批量清理垃圾项目

**Files:** `novel_agent/api/routes_projects.py`, `frontend/src/`

- [ ] **Step 1:** 后端新增 `DELETE /api/projects/batch` 端点，接收 id 列表批量删除。

- [ ] **Step 2:** 前端项目列表增加多选+批量删除按钮。

- [ ] **Step 3:** Commit

---

## P2-2: 前端默认用 SSE 端点

**Files:** `frontend/src/`

- [ ] **Step 1:** 检查前端章节生成是否已用 `generateStream`（SSE）。如果用的是同步 `generate`，改为 SSE。

- [ ] **Step 2:** Commit

---

## P2-3: 章节生成接入 MemoryPack + brief

**Files:** `novel_agent/orchestrator/nodes.py`, `novel_agent/orchestrator/runner.py`

- [ ] **Step 1:** 在 write_chapter 节点中，先调 chapter/brief 逻辑生成任务书，注入 prompt。

- [ ] **Step 2:** Commit

---

## P2-4: 验证 consistency-dashboard 端点

**Files:** `novel_agent/api/routes_bible.py`

- [ ] **Step 1:** 确认端点存在且正常工作，如有 bug 修复。

- [ ] **Step 2:** Commit

---

## Q1: 增强 JSON 检测

**Files:** `novel_agent/orchestrator/nodes.py`

- [ ] **Step 1:** `_looks_like_json_not_prose` 增加更多检测：`{"chapter"` / `{"error"` / try json.loads 成功且不含中文标点。

---

## Q3: config.yaml 参数澄清

已在上一轮修复（max_tokens:4000, context_length:128000）。确认无矛盾。

---

## 执行顺序

1. P1-1 + P1-2 + P1-3（失败反馈三连，根因关联）
2. P2-4（验证 dashboard，快速）
3. Q1（JSON 检测增强）
4. P2-1（批量清理）
5. P2-2（SSE 默认）
6. P2-3（brief 接入，改动最大）
7. 全量测试 + 提交
