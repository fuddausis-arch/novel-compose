"""测试卷级 graph 结构。"""
from unittest.mock import MagicMock
from novel_agent.planning.graph import build_volume_graph


def _mock_deps():
    return {
        "planner": MagicMock(), "architect": MagicMock(), "outliner": MagicMock(),
        "repo": MagicMock(), "applier": MagicMock(),
    }


def test_graph_has_five_nodes():
    graph = build_volume_graph(_mock_deps())
    node_ids = set(graph.nodes.keys())
    for name in ["plan", "design", "outline", "review", "apply"]:
        assert name in node_ids, f"缺失节点 {name}"
