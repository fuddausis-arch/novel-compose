"""测试审计维度定义。"""
from novel_agent.audit.dimensions import DIMENSIONS, CRITICAL_DIMENSIONS, AuditCategory


def test_all_dimensions_present():
    """应含一致性/人物/情节/文风/物理/环境/关系 7 类。"""
    categories = {d.category for d in DIMENSIONS}
    assert AuditCategory.CONSISTENCY in categories
    assert AuditCategory.CHARACTER in categories
    assert AuditCategory.PLOT in categories
    assert AuditCategory.STYLE in categories
    assert AuditCategory.PHYSICAL in categories
    assert AuditCategory.ENVIRONMENT in categories
    assert AuditCategory.RELATIONSHIP in categories


def test_critical_dimensions_marked():
    """关键维度（设定一致/OOC/伏笔/信息边界/物理）任一不过直接打回。"""
    crit_names = {d.name for d in CRITICAL_DIMENSIONS}
    assert "设定一致性" in crit_names
    assert "人物OOC" in crit_names
    assert "伏笔准确性" in crit_names
    assert "信息边界" in crit_names
    assert "物理一致性" in crit_names


def test_dimension_has_name_category_check_desc():
    """每个维度有 name/category/check/description。"""
    for d in DIMENSIONS:
        assert d.name
        assert d.category
        assert d.check
