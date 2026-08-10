"""测试命名权威（name_authority）与 validator 集成。

覆盖：
1. classify_name 三分类（kinship/generic_alias/person/unknown）
2. validator.check_character_name_consistency 用词表过滤称呼误报
3. 别名修正 repository 的增删回滚
"""
from __future__ import annotations

import pytest

from novel_agent.audit.name_authority import (
    classify_name,
    is_non_person_name,
)
from novel_agent.audit.validator import check_character_name_consistency


class TestClassifyName:
    """命名权威三分类"""

    @pytest.mark.parametrize("name", [
        "母亲", "大哥", "师父", "陛下", "王爷", "夫人",
        "王兄", "李大人", "赵将军", "孙姑娘", "皇太后", "太上皇",
    ])
    def test_kinship_terms(self, name):
        """亲属/敬称/姓氏+称呼后缀 应判为 kinship"""
        assert classify_name(name) == "kinship", name

    @pytest.mark.parametrize("name", [
        "少女", "老者", "黑衣人", "蒙面人", "掌柜", "店小二", "护卫", "众人",
    ])
    def test_generic_aliases(self, name):
        """通用人物别名应判为 generic_alias"""
        assert classify_name(name) == "generic_alias", name

    @pytest.mark.parametrize("name", ["林晚", "陆辰", "苏瑶", "陈默"])
    def test_person_names(self, name):
        """姓氏开头且无称呼后缀应判为 person"""
        assert classify_name(name) == "person", name

    @pytest.mark.parametrize("name", ["小美", "阿强", "老张"])
    def test_unknown(self, name):
        """非姓氏开头、非称呼 → unknown"""
        assert classify_name(name) == "unknown", name

    def test_is_non_person(self):
        """is_non_person_name 只认 kinship/generic_alias"""
        assert is_non_person_name("王兄")
        assert is_non_person_name("老者")
        assert not is_non_person_name("林晚")
        assert not is_non_person_name("小美")


class _FakeRepo:
    """最小 repo 桩：只有 list_characters。"""

    def __init__(self, names):
        self.names = names

    def list_characters(self):
        class _C:
            pass
        return [_C_with(name) for name in self.names]


def _C_with(name):
    class _C:
        pass
    c = _C()
    c.name = name
    return c


class TestValidatorIntegration:
    """validator 用命名权威过滤称呼误报"""

    def test_honorific_not_flagged(self):
        """'王兄道：' '李大人说：' 是敬称，不应报疑似未知角色"""
        draft = "王兄道：\"此事不可声张。\"李大人说：\"明日启程。\"赵将军问：\"可备好兵马？\""
        repo = _FakeRepo(["林晚", "陆辰"])
        issues = check_character_name_consistency(draft, repo)
        assert issues == []

    def test_kinship_not_flagged(self):
        """'母亲道：' 是亲属称呼，不应报疑似未知角色"""
        draft = "母亲道：\"回来就好。\"师父说：\"下山去吧。\""
        repo = _FakeRepo(["林晚"])
        issues = check_character_name_consistency(draft, repo)
        assert issues == []

    def test_unknown_character_flagged(self):
        """真正的未知角色（姓氏开头）仍应报"""
        draft = "林晚道：\"走吧。\"萧云问道：\"去哪？\""
        repo = _FakeRepo(["林晚"])
        issues = check_character_name_consistency(draft, repo)
        # 萧云不在角色列表 → 报 1 条
        assert len(issues) == 1
        assert "萧云" in issues[0]["message"]

    def test_generic_alias_not_flagged(self):
        """'老者说：' '黑衣人道：' 是通用别名，不应报"""
        draft = "老者说：\"老夫在此等候多时。\"黑衣人道：\"动手。\""
        repo = _FakeRepo(["林晚"])
        issues = check_character_name_consistency(draft, repo)
        assert issues == []
