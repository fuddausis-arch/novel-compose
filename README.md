# NovelCompose（织谱）· 多 Agent AI 小说创作平台

> 多 Agent 协作的 AI 长篇小说创作平台：**写、审、改分离**，你负责想法和判断，AI 负责规划和写作。支持浏览器、Windows 桌面、安卓手机。

**技术栈**：FastAPI + React 19 + TypeScript + SQLite + LangGraph

## 亮点

- **多 Agent 分工**：规划、写正文、审校、润色由不同角色协作完成，写审使用**不同模型**，避免"自己写自己审"
- **设定库驱动**：角色 / 势力 / 世界观 / 伏笔 / 大纲结构化存储，正文生成自动带上，长篇小说不写崩设定
- **质量闭环**：三视角审校 → 人审确认 → 润色 → 设定回写，每一章的质量大权始终在你手里
- **越用越懂你**：导入参考作品可蒸馏出写作风格技能（7 维蒸馏 / 拆书），写作时自动按需注入

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

## 使用文档

📖 完整的功能清单、使用指南、页面导览、技术架构与 FAQ 见 **[docs/README.md](docs/README.md)**

## 开源协议

**GNU AGPL v3**（详见 [LICENSE](LICENSE)）。
