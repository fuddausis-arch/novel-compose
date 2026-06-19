# 第四轮修复：真接通死代码 + 补长篇承重柱

> 每条修复必须回答：数据从哪进、到哪出、拿什么验证。

## 验证结果（先查实）

### ① 确定性审计 — 用户搜错文件，实际已接通
- `nodes.py:126` 确实调用了 `run_deterministic_checks`
- critical 问题直接返回不调 LLM（line 131-140）
- 非 critical 问题附在 draft 前传给 LLM（line 144-148）
- **结论：这条是真修好了，用户搜 auditor.py 搜错了文件**

### ② 角色状态闭环 — 确认是死代码
- `nodes.py:252-254` 的 prompt JSON 模板没有 `character_states` 字段
- LLM 永远不会返回该字段，line 294 的循环永远空转
- **必须修：把 character_states 加进 prompt 模板**

### ③ S-001 在 outlines.txt — 确认未修
- `templates/prompts/outlines.txt:29` 仍写着 `"foreshadow_id":"S-001"`
- **必须修：改为占位符**

### ④ auditor_llm 默认未配 — 确认
- config.yaml 没有 auditor_llm 段
- **必须修：config.yaml 加默认 auditor_llm（温度更低）**

### ⑤-⑧ 长篇能力缺口 — 确认全部未动
- archival 中文 embedding：未换
- 卷级摘要：return ""
- 角色全量注入：未筛选
- 死 delta target：未实现

---

## Fix 1: 角色状态闭环 — 把 character_states 加进 prompt

**文件:** `novel_agent/orchestrator/nodes.py`

- [ ] Step 1: summarize_chapter 的 prompt JSON 模板增加 `,"character_states":[{"name":"","location":"","emotion":""}]`
- [ ] Step 2: 写测试验证：mock LLM 返回 character_states，断言 repo.get_character(name).current_emotion 更新了
- [ ] Step 3: 运行测试通过

## Fix 2: S-001 占位符

**文件:** `novel_agent/templates/prompts/outlines.txt`

- [ ] Step 1: `"foreshadow_id":"S-001"` 改为 `"foreshadow_id":"<自动生成>"`

## Fix 3: auditor_llm 默认配置

**文件:** `config.yaml`

- [ ] Step 1: 加 auditor_llm 段，temperature: 0.2（比 writer 的 0.5 更严格）

## Fix 4: archival 中文 embedding

**文件:** `novel_agent/memory/archival.py`

- [ ] Step 1: 换 embedding model 为 BAAI/bge-small-zh-v1.5
- [ ] Step 2: 处理模型下载失败时的 fallback

## Fix 5: 卷级摘要

**文件:** `novel_agent/memory/recall.py`

- [ ] Step 1: get_volume_summary 实现：拼接该卷所有章摘要 + 卷主题
- [ ] Step 2: get_full_summary 改为：最近 10 章详细 + 更早的卷级摘要

## Fix 6: 角色按章筛选

**文件:** `novel_agent/memory/core.py`

- [ ] Step 1: assemble 中 list_characters 改为：优先取本章大纲中提到的角色 + 最近 3 章出现的角色
- [ ] Step 2: 总数超 20 时截断到 20

## 执行顺序

1. Fix 1（角色状态 prompt + 测试）
2. Fix 2（S-001 占位符）
3. Fix 3（auditor_llm 默认配置）
4. Fix 4（中文 embedding）
5. Fix 5（卷级摘要）
6. Fix 6（角色筛选）
7. 全量测试 + 提交
