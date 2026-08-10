"""测试地图布局引擎（P3：LLM 语义 + 引擎布局）。

覆盖：
1. parse_semantic_hints 解析 LLM 返回的语义 JSON
2. layout_map 布局结果满足：方位语义生效、父子靠近、不重叠
3. 无语义提示时纯算法也能出结果
"""
from __future__ import annotations

from novel_agent.geo.map_layout import DIRECTION_HINTS, LAYER_BAND, layout_map, parse_semantic_hints


def _sample_locations():
    return [
        {"id": 1, "name": "天界", "type": "continent", "layer": "celestial", "parent_name": "", "importance": "核心"},
        {"id": 2, "name": "大唐帝国", "type": "kingdom", "layer": "surface", "parent_name": "", "importance": "核心"},
        {"id": 3, "name": "幽冥界", "type": "continent", "layer": "underworld", "parent_name": "", "importance": "重要"},
        {"id": 4, "name": "苏城", "type": "city", "layer": "surface", "parent_name": "大唐帝国", "importance": "普通"},
        {"id": 5, "name": "龙宫", "type": "site", "layer": "underwater", "parent_name": "", "importance": "次要"},
        {"id": 6, "name": "黑市", "type": "site", "layer": "surface", "parent_name": "苏城", "importance": "次要"},
    ]


def _sample_rels():
    return [
        {"source": "大唐帝国", "target": "天界", "relation_type": "portal"},
        {"source": "大唐帝国", "target": "幽冥界", "relation_type": "portal"},
        {"source": "大唐帝国", "target": "苏城", "relation_type": "contains"},
        {"source": "苏城", "target": "黑市", "relation_type": "contains"},
        {"source": "大唐帝国", "target": "龙宫", "relation_type": "road"},
        {"source": "苏城", "target": "龙宫", "relation_type": "adjacent"},
    ]


class TestParseSemanticHints:
    def test_parse_valid(self):
        raw = '[{"name": "天界", "direction": "north"}, {"name": "苏城", "direction": "center", "relative_to": "大唐帝国"}]'
        hints = parse_semantic_hints(raw)
        assert hints["天界"]["direction"] == "north"
        assert hints["苏城"]["relative_to"] == "大唐帝国"

    def test_parse_with_codeblock(self):
        raw = '```json\n[{"name": "幽冥界", "direction": "south"}]\n```'
        hints = parse_semantic_hints(raw)
        assert hints["幽冥界"]["direction"] == "south"

    def test_parse_invalid_returns_empty(self):
        assert parse_semantic_hints("出错了，无法解析") == {}
        assert parse_semantic_hints("") == {}
        assert parse_semantic_hints(None) == {}

    def test_parse_ignores_unknown_direction(self):
        raw = '[{"name": "黑市", "direction": "sideways"}]'
        hints = parse_semantic_hints(raw)
        assert "黑市" not in hints or "direction" not in hints["黑市"]


class TestLayoutEngine:
    def test_layout_returns_all_locations(self):
        pos = layout_map(_sample_locations(), _sample_rels())
        assert len(pos) == 6

    def test_direction_semantics_respected(self):
        """天界(北)应在幽冥界(南)上方"""
        hints = parse_semantic_hints(
            '[{"name": "天界", "direction": "north"}, {"name": "幽冥界", "direction": "south"}]')
        pos = layout_map(_sample_locations(), _sample_rels(), hints=hints)
        assert pos[1]["y"] < pos[3]["y"], "天界应在幽冥界上方"

    def test_parent_child_close(self):
        """苏城(父：大唐帝国)应靠近大唐帝国"""
        pos = layout_map(_sample_locations(), _sample_rels())
        d = ((pos[4]["x"] - pos[2]["x"]) ** 2 + (pos[4]["y"] - pos[2]["y"]) ** 2) ** 0.5
        assert d < 500, f"父子地点距离过大: {d}"

    def test_no_overlap(self):
        """任意两点最小距离应大于 40（避免完全重叠）"""
        pos = layout_map(_sample_locations(), _sample_rels())
        items = list(pos.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (_, a), (_, b) = items[i], items[j]
                d = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
                assert d > 40, f"地点 {a} {b} 距离过近: {d:.1f}"

    def test_without_hints_still_works(self):
        """无语义提示时纯算法也应出结果"""
        pos = layout_map(_sample_locations(), _sample_rels())
        assert len(pos) == 6

    def test_layer_banding(self):
        """layer 带应有不同垂直基准：天界基准在幽冥之上"""
        assert LAYER_BAND["celestial"] < LAYER_BAND["underworld"]
        assert LAYER_BAND["underworld"] < LAYER_BAND["underwater"]


# ── 深度测试 d4: 布局边界场景 ─────────────────────────


def _many_isolated(n: int):
    """构造 n 个无父子关系的孤立地点。"""
    return [
        {"id": i, "name": f"地点{i}", "type": "city", "layer": "surface",
         "parent_name": "", "importance": "普通"}
        for i in range(1, n + 1)
    ]


class TestLayoutBoundary:
    def test_empty(self):
        assert layout_map([], []) == {}

    def test_single(self):
        pos = layout_map(_many_isolated(1), [])
        assert len(pos) == 1
        assert pos[1]["x"] > 0 and pos[1]["y"] > 0

    def test_two_spread(self):
        pos = layout_map(_many_isolated(2), [])
        p1, p2 = pos[1], pos[2]
        d = ((p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2) ** 0.5
        assert d > 200, f"两个孤立地点应分散: {d:.0f}"

    def test_61_isolated_no_overlap(self):
        """61 个孤立地点（对应打包版真实数据规模）：碰撞消除后无重叠。"""
        pos = layout_map(_many_isolated(61), [], width=2560, height=1400)
        items = list(pos.items())
        min_d = 1e9
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (_, a), (_, b) = items[i], items[j]
                d = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
                min_d = min(min_d, d)
        assert min_d >= 200, f"61 地点最小间距应 ≥200（物理空间上限约242）: {min_d:.0f}"

    def test_parent_edges_keep_children_close(self):
        """有父子关系的子地点应环绕父地点（间距在合理范围）。"""
        locs = [
            {"id": 1, "name": "主城", "type": "city", "layer": "surface",
             "parent_name": "", "importance": "核心"},
            {"id": 2, "name": "东区", "type": "city", "layer": "surface",
             "parent_name": "主城", "importance": "普通"},
            {"id": 3, "name": "西区", "type": "city", "layer": "surface",
             "parent_name": "主城", "importance": "普通"},
        ]
        rels = [{"source": "东区", "target": "主城", "relation_type": "contains"},
                {"source": "西区", "target": "主城", "relation_type": "contains"}]
        pos = layout_map(locs, rels)
        for child in (2, 3):
            d = ((pos[child]["x"] - pos[1]["x"]) ** 2 + (pos[child]["y"] - pos[1]["y"]) ** 2) ** 0.5
            assert 150 < d < 700, f"子地点距父地点应适中: {d:.0f}"
        d_cc = ((pos[2]["x"] - pos[3]["x"]) ** 2 + (pos[2]["y"] - pos[3]["y"]) ** 2) ** 0.5
        assert d_cc > 200, f"两个子地点应分开: {d_cc:.0f}"

    def test_iterations_tolerant(self):
        """迭代次数过少/过多都不应崩溃。"""
        for it in (1, 5, 300):
            pos = layout_map(_many_isolated(10), [], iterations=it)
            assert len(pos) == 10
