"""测试幻觉过滤（P5）：过滤正文从未出场的实体，防图谱污染。

覆盖：
1. filter_appeared：有出场记录的实体被保留，无出场记录的被过滤
2. 保护机制：某类实体完全没有出场记录时不过滤（新项目不空图）
"""
from __future__ import annotations

from novel_agent.audit.hallucination_filter import appeared_entity_ids, filter_appeared


class _FakeEntity:
    def __init__(self, name, eid):
        self.name = name
        self.id = eid


class _FakeAppearance:
    def __init__(self, entity_id):
        self.entity_id = entity_id


class _FakeDB:
    """最小 DB 桩：只实现 filter_appeared 需要的查询。"""

    def __init__(self, appearance_rows):
        self._rows = appearance_rows

    def query(self, col):
        return _FakeQuery(self._rows)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def filter(self, *args):
        return self

    def distinct(self):
        return self

    def all(self):
        return [(r.entity_id,) for r in self._rows]


def _sample_entities():
    return [
        _FakeEntity("林晚", 1),
        _FakeEntity("苏瑶", 2),
        _FakeEntity("萧云", 3),
    ]


class TestFilterAppeared:
    def test_only_appeared_kept(self):
        """只有出场记录的角色被保留"""
        db = _FakeDB([_FakeAppearance("林晚"), _FakeAppearance("林晚")])
        result = filter_appeared(db, 1, "character", _sample_entities(), id_fn=lambda e: e.name)
        assert [e.name for e in result] == ["林晚"]

    def test_fresh_project_keeps_all(self):
        """某类实体完全无出场记录 → 不过滤（新项目不空图）"""
        db = _FakeDB([])
        result = filter_appeared(db, 1, "character", _sample_entities(), id_fn=lambda e: e.name)
        assert len(result) == 3

    def test_empty_input(self):
        """空列表直接返回"""
        db = _FakeDB([])
        assert filter_appeared(db, 1, "character", [], id_fn=lambda e: e.name) == []

    def test_faction_by_id(self):
        """势力按字符串 id 匹配出场记录"""
        db = _FakeDB([_FakeAppearance("5")])
        entities = [_FakeEntity("天机阁", 5), _FakeEntity("暗月楼", 6)]
        result = filter_appeared(db, 1, "faction", entities, id_fn=lambda f: str(f.id))
        assert [e.name for e in result] == ["天机阁"]

    def test_appeared_entity_ids(self):
        db = _FakeDB([_FakeAppearance("林晚"), _FakeAppearance("苏瑶"), _FakeAppearance("林晚")])
        assert appeared_entity_ids(db, 1, "character") == {"林晚", "苏瑶"}
