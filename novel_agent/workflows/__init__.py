"""工作流引擎相关模块。

- loader: 7 条 bishu-novel 移植工作流的加载与执行（83 节点）
- scripts.nvl: 15 个确定性脚本库（local_archive/json_to_md/vo_post 等）
- definitions/: 7 条工作流定义 JSON
- resources/: 33 个 Agent 定义 + prompt 模板
"""
from novel_agent.workflows.loader import (
    WORKFLOW_IDS,
    WorkflowResources,
    WorkflowRunner,
    list_workflows,
    load_definition,
    render_template,
    run_workflow,
)

__all__ = [
    "WORKFLOW_IDS",
    "WorkflowResources",
    "WorkflowRunner",
    "list_workflows",
    "load_definition",
    "render_template",
    "run_workflow",
]
