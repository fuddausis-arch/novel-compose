# 系统性批量修复执行计划

> 基于「审查.txt」多 Agent 对抗性审查报告 + 六轮迭代修复经验沉淀。
> 制定日期：2026-06-21  
> 适用范围：novel_agent 多 Agent 自动小说生成系统  
> 当前基线：commit `2af0e51`（123 passed）

---

## 0. 修复范围总览

### 已修复（26 项，无需再动）
C1-C5、H4-H8、M1-M8/M10/M11/M14/M15、P0 伏笔反向惩罚、P0 auditor_llm、Q2/Q3/Q4

### 未修复（20 项，本计划覆盖）
- 🔴 可立即修（7 项，低风险）
- 🟡 需决策（4 项，中等改动）
- 🔵 架构重构（9 项，大改）

---

## Phase 1: 准备阶段

### 1.1 明确修复范围

| 批次 | 编号 | 问题 | 优先级 | 预计改动 |
|------|------|------|--------|----------|
| **B1** | H1 | checkpoints.db 跨项目共享无 WAL | P0 | ~10 行 |
| **B1** | A3-池 | LLMClient 每次新建 httpx 客户端 | P1 | ~15 行 |
| **B1** | A3-SSE | SSE 长任务无心跳 | P1 | ~10 行 |
| **B1** | A3-熔断 | 单章最坏 1 小时无超时 | P1 | ~5 行 |
| **B1** | A3-emb | bge 回退无记录 | P2 | ~3 行 |
| **B1** | A5-优先 | 细纲被角色列表挤掉 | P1 | ~5 行 |
| **B1** | A4-残留 | 脚手架 counter.ts/svg 残留 | P3 | 0 行（删除） |
| **B2** | H9/A1 | 零鉴权 + CORS* + SSE GET | P0 | 中 |
| **B2** | M9 | 生成直接写入圣经 | P2 | 中 |
| **B2** | A5-卷摘 | 卷级摘要机械截断非 LLM 压缩 | P2 | 大 |
| **B2** | A5-伏笔 | 伏笔逾期悬挂无巡检 | P2 | 中 |
| **B3** | H2 | 两套记忆系统不一致 | P1 | 大 |
| **B3** | H3 | 事件流残缺 | P1 | 大 |
| **B3** | M12 | 前端 dist 未 git track | P3 | 小 |
| **B3** | M13 | 测试全 mock | P2 | 大 |
| **B3** | A5-题材 | 题材检索关键词匹配不准 | P3 | 中 |
| **B3** | A6-上帝 | routes_bible 1319 行 | P3 | 大 |
| **B3** | A6-nodes | nodes.py 338 行混 4 关注点 | P3 | 大 |
| **B3** | A6-props | 前端 40+ props 半 store | P3 | 大 |
| **B3** | A3-退避 | SSE 退避 16 秒断连策略 | P3 | 中 |

### 1.2 收集相关文档

- [x] 审查.txt（多 Agent 对抗性审查报告）
- [x] docs/superpowers/plans/ 历史修复计划（4 份）
- [ ] spec.md（原系统规格）— 需确认 H2/H3 的设计意图
- [ ] README.md — 需更新依赖说明（sentence-transformers）
- [ ] config.yaml — 当前配置基线

### 1.3 配置开发环境

| 任务 | 命令 | 验证 |
|------|------|------|
| 安装中文 embedding 依赖 | `pip install sentence-transformers>=2.7` | `python -c "import sentence_transformers"` |
| 安装限流中间件（B2） | `pip install slowapi` | `python -c "import slowapi"` |
| 确认测试基线 | `python -m pytest tests/ -q` | 123 passed |
| 确认前端基线 | `cd frontend && npx tsc --noEmit` | 0 errors |

### 1.4 责任分工

| 角色 | 职责 |
|------|------|
| **执行者**（AI agent） | 代码实现、测试编写、文档更新 |
| **决策者**（用户） | 架构方向决策、优先级调整、验收 |
| **审查者**（对抗性 agent） | 每批完成后交叉验证 |

### 1.5 时间节点

| 阶段 | 内容 | 预计节点 |
|------|------|----------|
| Phase 1 | 准备 | T+0（已完成） |
| Phase 2 | 分析 | T+1 |
| Phase 3-B1 | 第一批修复（7 项） | T+2 |
| Phase 3-B2 | 第二批修复（4 项，需决策） | T+4 |
| Phase 3-B3 | 第三批架构重构（9 项） | T+8 |
| Phase 4 | 测试 | 每批后 |
| Phase 5 | 部署 | T+10 |
| Phase 6 | 总结 | T+11 |

---

## Phase 2: 分析阶段

### 2.1 问题分类与优先级排序

**按影响维度分类：**

| 维度 | 编号 | 数量 |
|------|------|------|
| 数据完整性 | H1, H3 | 2 |
| 安全 | H9/A1 | 1 |
| 性能/可靠性 | A3-池, A3-SSE, A3-熔断, A3-退避 | 4 |
| 可观测性 | A3-emb | 1 |
| 长篇质量 | A5-优先, A5-卷摘, A5-伏笔, A5-题材, H2 | 5 |
| 代码质量 | A4-残留, A6-上帝, A6-nodes, A6-props, M12 | 5 |
| 用户体验 | M9 | 1 |
| 测试 | M13 | 1 |

**优先级矩阵：**

```
        高影响
          │
   H9    │  H1  H2  H3
   A3-池 │  A3-熔断
   A3-SSE│  A5-优先
          │
 ─────────┼─────────
          │  A3-emb
   M9    │  A4-残留  M12
   A5-题材│  A6-*  M13
          │
        低影响
   低复杂度    高复杂度
```

### 2.2 修复标准（每条必须满足）

1. **数据流闭环**：数据从哪进、到哪出、拿什么验证——三问必须明确
2. **无死代码**：写了的必须被调用，调用的必须被测试覆盖
3. **不破坏隔离**：审计隔离、事务原子性、写审分离铁律不破
4. **可观测**：降级/回退有日志，不静默
5. **回归通过**：123 passed 不退化，新增测试覆盖新行为

### 2.3 各批修复方案

#### B1 方案（7 项，低风险）

| # | 方案 | 文件 | 验证方式 |
|---|------|------|----------|
| H1 | 每项目独立 checkpoints.db + WAL | `runner.py` | 并发 2 项目生成不报 locked |
| A3-池 | `__init__` 创建持久 httpx.AsyncClient，`generate` 复用 | `llm/client.py` | 单元测试 mock 验证复用 |
| A3-SSE | event_generator 中加 heartbeat 协程 | `routes_chapters.py` | 手动 SSE 连接验证 |
| A3-熔断 | `runner.run` 外包 `asyncio.wait_for(timeout=600)` | `orchestrator/runner.py` | 超时测试 |
| A3-emb | `_build_embedding_function` 成功/失败 logger.info | `memory/archival.py` | 日志含模型名 |
| A5-优先 | assemble 中细纲移到 sections 末尾拼接 | `memory/core.py` | 长角色列表不截断细纲 |
| A4-残留 | 删除 counter.ts/vite.svg/typescript.svg | `frontend/src/` | tsc 无报错 |

#### B2 方案（4 项，需决策）

| # | 决策点 | 选项 | 推荐 |
|---|--------|------|------|
| H9/A1 | 鉴权程度 | A. slowapi 限流+CORS localhost<br>B. 完整用户体系<br>C. 仅 SSE 改 POST | **A**（单机桌面应用场景） |
| M9 | 预览模式 | A. 改为预览不写库<br>B. 保持当前删除兜底 | **B**（改动小，边缘可接受） |
| A5-卷摘 | LLM 压缩 | A. 加 Summarizer agent<br>B. 保持机械截断+接进 core memory | **A**（长篇质量核心） |
| A5-伏笔 | 逾期巡检 | A. 加 get_overdue_foreshadows + 注入提示<br>B. 定时告警 | **A**（注入提示即可） |

#### B3 方案（9 项，架构重构，需独立 spec）

| # | 方案方向 | spec 要求 |
|---|----------|-----------|
| H2 | CoreMemoryAssembler 统一，MemoryPackBuilder 改为薄包装 | 上下文装配契约 |
| H3 | commit_chapter 走 applier，CRUD 补 append_event | 事件流覆盖矩阵 |
| M12 | 前端 CI 构建 + dist 进 git 或 release artifact | 部署流程 |
| M13 | 补 round-trip/行为测试，覆盖 P0 逻辑路径 | 测试矩阵 |
| A5-题材 | 改 embedding 检索或精确多标签匹配 | 检索策略 |
| A6-上帝 | routes_bible 按资源拆 10 个文件 | 文件拆分映射 |
| A6-nodes | nodes.py 拆 audit/summary/clean/route 模块 | 模块边界 |
| A6-props | Workspace 改从 store 读，去掉手传 props | 前端状态流 |
| A3-退避 | SSE 单独超时策略（短退避+心跳保活） | SSE 协议 |

### 2.4 风险应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| B1 改动引入回归 | 低 | 中 | 每项改完立即跑 123 测试 |
| B2 鉴权改 SSE POST 破前端 | 中 | 高 | 前后端同步改，加集成测试 |
| B3 重构破坏现有流程 | 高 | 高 | 分 spec 评审 → 灰度 → 回归 |
| LLM 依赖不稳定 | 中 | 中 | 超时熔断 + fallback |
| sentence-transformers 下载失败 | 中 | 低 | 已有 MiniLM fallback |
| 数据库迁移破坏存量 | 低 | 高 | 加迁移脚本 + 备份 |

---

## Phase 3: 执行阶段

### 3.1 B1 批次实施（7 项）

**执行顺序（按依赖关系）：**

```
A4-残留（无依赖，先清环境）
  ↓
H1（checkpoints 独立 db）
  ↓
A3-池 → A3-SSE → A3-熔断（LLM 可靠性三连，有依赖）
  ↓
A3-emb（可观测，独立）
  ↓
A5-优先（core memory 调整，独立）
```

**每项实施流程：**
1. 读取相关文件确认当前代码
2. 实施修改
3. 运行 `python -m pytest tests/ -q`（123 passed）
4. 运行 `npx tsc --noEmit`（如涉及前端）
5. 记录修改到 commit message

**质量控制：**
- 每项独立 commit，message 格式：`fix(B1): <编号> <描述>`
- 全部完成后跑一次全量测试
- 交叉验证：用对抗性 agent 视角检查"是否真的接通了"

### 3.2 B2 批次实施（4 项，需决策）

**前置：决策者确认 2.3 表中推荐选项**

| # | 实施 | 验证 |
|---|------|------|
| H9/A1 | slowapi 限流（10次/分钟）+ CORS 限制 localhost + SSE 改 POST | curl 测试限流 + 前端 SSE 适配 |
| M9 | 不改（决策 B） | — |
| A5-卷摘 | 新增 Summarizer agent + 卷摘要存储 + core memory 消费 | 50 章后上下文含卷摘要 |
| A5-伏笔 | get_overdue_foreshadows + assemble 注入提示 | 逾期伏笔出现在生成上下文 |

**风险控制：**
- H9 的 SSE POST 改动必须前后端同步
- A5-卷摘涉及 LLM 调用，加超时+fallback

### 3.3 B3 批次实施（9 项，架构重构）

**每个独立 spec → 评审 → 实施 → 验收**

**执行顺序（按依赖）：**
```
H2（记忆统一）→ H3（事件流统一）  # 数据层基础
  ↓
A6-nodes（拆模块）→ A6-上帝（拆路由）  # 代码组织
  ↓
A6-props（前端状态）  # 前端独立
  ↓
M13（补测试）→ M12（部署）→ A5-题材 → A3-退避  # 收尾
```

**每项 spec 需包含：**
- 现状分析（当前代码结构+问题）
- 目标设计（拆分后结构+接口契约）
- 迁移路径（增量改动步骤）
- 回归测试方案
- 回滚预案

---

## Phase 4: 测试阶段

### 4.1 测试策略

| 层级 | 范围 | 工具 | 通过标准 |
|------|------|------|----------|
| 单元测试 | 每个修改的函数/方法 | pytest | 100% 新代码覆盖 |
| 集成测试 | 端到端生成流程 | pytest + TestClient | 生成→审计→保存→摘要 全通 |
| 回归测试 | 全量 123 测试 | pytest | 0 退化 |
| 行为测试 | P0 逻辑路径 | pytest（新增） | 伏笔/短路/配置 round-trip |
| 前端类型 | TypeScript | tsc | 0 errors |
| 前端构建 | 生产构建 | vite build | 成功 |

### 4.2 B1 测试用例（新增）

```python
# test_h1_checkpoints_isolated
def test_checkpoints_db_per_project(tmp_path):
    """每个项目用独立 checkpoints.db，并发不锁死。"""
    # 两个项目同时生成，不报 database is locked

# test_a3_client_reuse
def test_llm_client_reuses_connection():
    """LLMClient 复用 httpx 连接，不每次新建。"""

# test_a3_sse_heartbeat
def test_sse_yields_heartbeat_on_long_wait():
    """SSE 长等待时发心跳，不断连。"""

# test_a3_timeout_circuit
def test_graph_timeout_circuits():
    """graph 整体超时 600 秒后熔断。"""

# test_a5_outline_not_truncated
def test_outline_not_truncated_by_characters():
    """角色列表超长时，细纲不被截断。"""
```

### 4.3 B2 测试用例（新增）

```python
# test_h9_rate_limit
def test_generate_rate_limited():
    """超过 10 次/分钟返回 429。"""

# test_a5_volume_summary_llm
def test_volume_summary_is_llm_compressed():
    """卷摘要由 LLM 压缩生成，非机械截断。"""

# test_a5_overdue_foreshadow
def test_overdue_foreshadow_injected():
    """逾期伏笔出现在生成上下文。"""
```

### 4.4 B3 测试矩阵

| spec | 必须覆盖的行为 |
|------|---------------|
| H2 | 同一章走两条路径上下文一致 |
| H3 | commit_chapter/CRUD 都写事件流 |
| A6-nodes | 拆分后各模块独立可测 |
| A6-props | Workspace 从 store 读，props 减少 |
| M13 | config round-trip、validator 行为、graph 真实路径 |

---

## Phase 5: 部署阶段

### 5.1 环境准备

| 环境 | 用途 | 配置 |
|------|------|------|
| 本地开发 | B1/B2 开发测试 | `python -m novel_agent.cli serve` + `npm run dev` |
| Electron 打包 | 桌面应用验证 | `npm run electron:dev` |
| 灰度环境 | B3 重构验证 | 独立项目目录 + 真实 LLM |

### 5.2 灰度发布

**B1（低风险）：直接合并**
- 全量测试通过 → commit → 部署

**B2（中风险）：分项灰度**
- H9 限流：先只加 CORS localhost，不加限流，验证不破坏现有功能
- A5-卷摘：单个项目测试卷摘要效果
- A5-伏笔：单个项目测试逾期提示

**B3（高风险）：逐 spec 灰度**
- 每个 spec 独立分支
- 在灰度项目上跑 50 章生成验证
- 对比重构前后生成质量

### 5.3 监控与回滚

| 监控项 | 方式 | 告警阈值 |
|--------|------|----------|
| 测试通过率 | pytest CI | < 100% |
| 生成成功率 | SSE done 事件 status | failed 率 > 20% |
| LLM 调用延迟 | client.py 日志 | 单次 > 60s |
| SQLite locked | 异常日志 | 出现即告警 |
| 前端构建 | tsc + build | 失败即阻断 |

**回滚机制：**
- 每个 commit 可独立 revert
- B3 重构保留旧代码路径作为 fallback（feature flag）
- 数据库迁移脚本可逆（downgrade）

---

## Phase 6: 总结阶段

### 6.1 修复效果评估

| 指标 | 基线（当前） | 目标 |
|------|-------------|------|
| 审查项修复率 | 26/46 (56%) | 46/46 (100%) |
| 测试通过数 | 123 | 140+（新增行为测试） |
| 测试覆盖 P0 路径 | 0 | 100% |
| 静默降级项 | 5+ | 0 |
| 死代码项 | 0（已清） | 0 |
| 单章生成超时上限 | 无限 | 600s |

### 6.2 经验沉淀

**已识别的系统性病灶（需写入开发规范）：**

1. **契约失配** → 新增规则：save/load 必须对称，加 round-trip 测试
2. **静默降级** → 新增规则：所有 except 必须有 logger.warning
3. **死代码** → 新增规则：新增 import 必须在 30 行内有调用
4. **应试修补** → 新增规则：修复必须回答"数据从哪进、到哪出、拿什么验证"

**写入位置：**
- `.trae/rules/project_rules.md`（开发规范）
- `docs/superpowers/specs/`（架构决策记录）

### 6.3 文档更新

| 文档 | 更新内容 |
|------|----------|
| README.md | 加 sentence-transformers 依赖说明 |
| config.yaml | 加 auditor_llm 段说明 |
| .trae/rules/project_rules.md | 新增 4 条开发规范 |
| docs/superpowers/plans/ | 本计划 + 各 B3 spec |
| 审查.txt | 标注各条最终状态 |

---

## 附录 A: 资源需求

| 资源 | 需求 | 备注 |
|------|------|------|
| 开发环境 | Python 3.11+ / Node 18+ | 已有 |
| 依赖 | sentence-transformers, slowapi | B1/B2 新增 |
| LLM 配额 | 灰度测试用 | 50 章约 300 次调用 |
| 存储 | 灰度项目数据 | ~500MB |
| 时间 | B1: 1 天 / B2: 2 天 / B3: 5 天 | 含测试 |

## 附录 B: 批次依赖图

```
B1（7项，无依赖）
  ├── A4-残留 ──────────── 独立
  ├── H1 ────────────────── 独立
  ├── A3-池 → A3-SSE → A3-熔断 → A3-退避  LLM可靠性链
  ├── A3-emb ────────────── 独立
  └── A5-优先 ───────────── 独立

B2（4项，需决策）
  ├── H9/A1 ─────────────── 独立（前后端同步）
  ├── M9 ────────────────── 不改
  ├── A5-卷摘 ───────────── 依赖 A5-优先（core memory）
  └── A5-伏笔 ───────────── 独立

B3（9项，架构重构，需 spec）
  H2 → H3 → A6-nodes → A6-上帝 → A6-props
                                    ↓
                          M13 → M12 → A5-题材 → A3-退避
```

## 附录 C: 风险登记册

| ID | 风险 | 概率 | 影响 | 应对 | 状态 |
|----|------|------|------|------|------|
| R1 | B1 改动引入回归 | 低 | 中 | 每项改完跑 123 测试 | 待执行 |
| R2 | B2 SSE POST 破前端 | 中 | 高 | 前后端同步改 | 待决策 |
| R3 | B3 重构破坏流程 | 高 | 高 | spec 评审+灰度 | 待 spec |
| R4 | LLM 不稳定 | 中 | 中 | 超时熔断+fallback | 已有 |
| R5 | embedding 下载失败 | 中 | 低 | MiniLM fallback | 已有 |
| R6 | DB 迁移破坏存量 | 低 | 高 | 备份+可逆迁移 | 待执行 |
| R7 | 时间超期 | 中 | 中 | B3 可延后，B1/B2 先行 | 监控中 |

---

**计划版本**: v1.0  
**制定者**: AI agent  
**审批者**: 用户（决策者）  
**下次评审**: B1 完成后
