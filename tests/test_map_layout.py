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
