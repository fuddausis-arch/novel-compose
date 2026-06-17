"""测试 delta schema 校验。"""
import pytest
from pydantic import ValidationError

from novel_agent.protocol.schemas import (
    Delta, ForeshadowDelta, CharacterDelta, SummaryDelta,
)


def test_foreshadow_plant_delta_valid():
    d = Delta(
        target="foreshadow",
        action="plant",
        chapter=3,
        data=ForeshadowDelta(foreshadow_id="S-001", description="神秘文物箱"),
    )
    assert d.action == "plant"


def test_foreshadow_delta_missing_id_rejected():
    with pytest.raises(ValidationError):
        ForeshadowDelta(description="缺 id")


def test_character_state_change_valid():
    d = Delta(
        target="character",
        action="state_change",
        chapter=5,
        data=CharacterDelta(name="刘洋", current_emotion="愤怒", current_location="基地"),
    )
    assert d.data.name == "刘洋"


def test_summary_delta_valid():
    d = Delta(
        target="chapter_summary",
        action="create",
        chapter=1,
        data=SummaryDelta(title="无声征召", word_count=1500, core_events="征召事件"),
    )
    assert d.data.word_count == 1500


def test_delta_invalid_target_rejected():
    with pytest.raises(ValidationError):
        Delta(target="invalid", action="create", chapter=1, data={})


def test_delta_invalid_action_rejected():
    with pytest.raises(ValidationError):
        Delta(target="foreshadow", action="teleport", chapter=1,
              data=ForeshadowDelta(foreshadow_id="S-001"))
