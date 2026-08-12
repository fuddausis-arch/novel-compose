# NovelCompose · 多 Agent AI 长篇小说创作平台

> 多 Agent 协作的 AI 长篇小说创作平台：**写、审、改分离**，支持浏览器、Windows 桌面、安卓手机。

**技术栈**：FastAPI + React 19 + TypeScript + SQLite + Chroma 向量库 + LangGraph 编排

---

## 架构总览

前端一个"创作工作台"，后端分五层——**创作层、设定层、质量层、记忆层、蒸馏层**。

```
┌─ 前端（React 19 · TypeScript · Vite）──────────────────────────┐
│  对话 · 写作台 · 规划 · 大纲 · 设定库(15类) · 叙事线 · 图谱 ·      │
│  时间线 · 百科 · 圆桌 · 工作流 · 蒸馏 · AI风格 · 设置(12项)       │
└────────────────────┬──────────────────────────────────────────┘
                     ▼ HTTP / SSE 流式
┌─ API 层（FastAPI，30+ 路由模块）───────────────────────────────┐
│  项目/章节/生成/设定/蒸馏/审校/叙事线/时间线/图谱/模型/技能/插件…   │
└──────┬─────────────────┬──────────────────┬───────────────────┘
       ▼                 ▼                  ▼
┌─ 创作层 ─────────┐ ┌─ 设定层 ─────────┐ ┌─ 质量层 ───────────┐
│ 交互式创作(ReAct) │ │ 设定库 15 类     │ │ 三视角审校          │
│ 26智能体流水线    │ │ 标签+权重注入    │ │ AI率检测(本地模型)   │
│ 规划/大纲/写作台  │ │ 叙事线/伏笔/时间线│ │ 事实对账/去重/幻觉过滤│
└──────┬───────────┘ └──────┬──────────┘ └──────┬─────────────┘
       ▼                    ▼                   ▼
┌─ 记忆层（Chroma 向量检索 + 分层摘要树 + 常驻上下文）──────────────┐
┌─ 蒸馏层（拆书 → 19 维蒸馏 → 技能融合 → 按需注入写作）─────────────┐
┌─ 数据层：SQLite 设定库 / 章节 Markdown / Chroma 向量 / 配置+密钥 ─┘
```

---

## 模块

### 1. 创作层 · 两条创作路径，共享一个设定底座

- **交互式创作**（`chat/` + `api/routes_generation.py`）：tool-calling ReAct 循环，真流式输出。问答模式与创作模式分离——日常问答不触发生成，只有明确的创作指令才写正文。支持抽卡（多候选）、人审、润色、重写、提交。
- **正式流水线**（`workflows/definitions/mvp.json`，26 智能体）：世界状态机 → 意图分发 → 大纲导演（全权管伏笔"埋 1 收 2"）→ 骨架写手 → **五科写手并行**（动作/对话/内心/描写/过渡）→ 分镜整合 → AI 味检测 → 人审。4 类网关（并行/汇聚/条件/循环）编排，脚本节点带锁串行防并发污染，支持断点续跑与取消。

### 2. 设定层 · 设定永不崩（`bible/` + `storyline/`）

- **15 类资产**全结构化：角色/势力/怪物/副本/世界设定/伏笔/红线/梗/地点/情感弧线/爽点/记忆精炼/命名覆盖/事件流/导入。
- **标签 + 权重**（对标 NovelAI Lorebook）：正文关键词命中标签 → 100% 注入该标签设定，同标签内按权重降序；高权重伏笔（P0）常驻不衰减；标签命中不到回退向量语义检索（Chroma）兜底。
- **叙事线**（`storyline/`）：明线/暗线 × 主线/支线管理，写作时注入"当前线推进到哪、本章该推什么"。
- **事实级校验**（`audit/fact_reconciliation.py`）：每章写完后提取本章事实与事件流对账，输出矛盾清单。

### 3. 质量层 · 质量闸门（`audit/` + `orchestrator/post_commit.py`）

- **三视角审校**：读者/专业/编辑三路并行独立打分（并行网关），不通过触发对抗性讨论。
- **AI 率检测三层融合**：规则层 + 统计层 + **本地深度模型**（AIGC_detector_zhv3）按 30%/20%/50% 加权；模型未就绪自动降级不阻塞。给出具体问题与改法。
- **提交后闭环**（`post_commit.py`）：伏笔自动埋设、红线检测、命名归一化（别名回写正名）、审校结论回写设定库、圆桌结论落库，五子项各自容错。

### 4. 记忆层 · 长篇小说不忘前情（`memory/`）

- 常驻上下文（最近 N 章）+ **向量语义检索**（`archival.py`，Chroma；embedding API 优先、本地模型兜底）+ 分层摘要树（`summary_tree.py`）+ 记忆精炼（`refine.py`）。

### 5. 蒸馏层 · 风格学习（`skills/` + `distillation/`）

- **拆书**（`skills/book_to_skill.py`）：上传 EPUB/PDF/DOCX/TXT，自动识别章节、逐章提炼技法，只存摘要不存原文。
- **19 维蒸馏**（`distillation/engine.py`）：风格/语言/结构/叙事引擎/信息控制/人物塑造/情感算法/人味指纹等 19 个维度多轮提炼，生成技能卡；多技能按权重融合；盲评对比验证。
- **按需注入**：技能通过索引检索相关片段注入，不浪费上下文。

### 6. 配置与安全（`config.py`）

- **BYOK**：多模型供应商自由添加（OpenAI 兼容协议），写/审/规划可分配不同模型。
- **密钥安全**：API Key 只放 `.env`，`config.yaml` 用 `${VAR}` 占位引用，密钥永不进 git。
- **红线开关**：`content_redline_enabled`（默认放开内容题材）；设定级红线永远生效，不受开关影响。

---

## 快速开始

环境要求：Python 3.11+、Node.js 18+

```bash
# 1. 后端依赖
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. 前端依赖
cd frontend && npm install && cd ..

# 3. 配置密钥
copy config.yaml.example config.yaml   # 复制配置模板
# 在项目根目录创建 .env，填入你的密钥（.env 永不进 git）：
#   DEEPSEEK_API_KEY=sk-xxx
#   ARK_API_KEY=ark-xxx

# 4. 启动（终端 1 后端，终端 2 前端）
# 默认只监听本机 127.0.0.1（安全，仅本机/桌面客户端可访问）
python -m uvicorn novel_agent.api.app:app --host 127.0.0.1 --port 8000 --reload
cd frontend && npm run dev
```

浏览器访问 **http://localhost:5173** 即可使用。

> 也支持命令行：`novel-compose init` / `generate` / `plan` / `resume` / `serve`

## 远程/局域网访问（可选）

默认后端只监听 `127.0.0.1`。如需手机 App（Capacitor）或局域网访问：

1. 启动时指定 `--host 0.0.0.0`，并设置一个随机 token 启用鉴权：
   ```bash
   # PowerShell: $env:NOVEL_API_TOKEN="<随机长串>"    bash: export NOVEL_API_TOKEN="<随机长串>"
   python -m uvicorn novel_agent.api.app:app --host 0.0.0.0 --port 8000
   ```
2. 客户端访问时，在浏览器/App 的 localStorage 写入同一个 token（键名 `novel_api_token`），
   前端会自动附在 `X-API-Token` 请求头；或直接用 `Authorization: Bearer <token>`。

未设置 `NOVEL_API_TOKEN` 时 API 不鉴权（仅适合本机单机使用）。

## 文档

📘 页面导览、项目结构、数据存储、模型分配、配置与 FAQ：**[docs/README.md](docs/README.md)**

## 开源协议

**GNU AGPL v3**（详见 [LICENSE](LICENSE)）。
