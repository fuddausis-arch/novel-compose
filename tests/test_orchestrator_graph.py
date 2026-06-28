"""测试 StateGraph 结构与节点连接。"""
from unittest.mock import MagicMock
from novel_agent.orchestrator.graph import build_graph, NODE_NAMES


def _mock_deps():
    return {
        "repo": MagicMock(),
        "llm_client": MagicMock(),
        "recall": MagicMock(),
        "applier": MagicMock(),
        "auditor": MagicMock(),
    }


def test_graph_has_all_nodes():
    graph = build_graph(_mock_deps())
    node_ids = set(graph.nodes.keys())
    for name in NODE_NAMES:
        assert name in node_ids, f"缺失节点 {name}"


def test_node_names_complete():
    assert NODE_NAMES == ["assemble", "analyze_style", "write", "audit", "rewrite", "human_review", "style_refine", "save_text", "summarize"]
