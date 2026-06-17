# 多 Agent 自动小说生成系统

基于 LangGraph 的多 agent 网文自动生成系统，目标 200 万字长篇。

## 开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## 文档

- 设计 spec: `docs/superpowers/specs/2026-06-17-multi-agent-novel-generator-design.md`
- M1 实现计划: `docs/superpowers/plans/2026-06-17-m1-foundation-and-memory.md`
