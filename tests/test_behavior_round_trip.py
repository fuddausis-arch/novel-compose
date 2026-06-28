"""行为测试：覆盖 P0 逻辑路径，验证真实行为而非实现细节。"""
import pytest
import tempfile
from pathlib import Path
from novel_agent.config import Config, LLMConfig, load_config, save_config


class TestConfigRoundTrip:
    """配置 save/load round-trip 测试。"""

    def test_auditor_llm_round_trip(self, tmp_path):
        """save_config 写入 auditor_llm，load_config 必须读回来。"""
        yaml_path = tmp_path / "config.yaml"
        cfg = Config()
        cfg.llm = LLMConfig(base_url="http://a", api_key="key1", model="m1", temperature=0.5)
        cfg.auditor_llm = LLMConfig(base_url="http://b", api_key="key2", model="m2", temperature=0.2)
        save_config(cfg, yaml_path)

        loaded = load_config(yaml_path)
        assert loaded.auditor_llm is not None
        assert loaded.auditor_llm.model == "m2"
        assert loaded.auditor_llm.temperature == 0.2
        assert loaded.auditor_llm.api_key == "key2"

    def test_auditor_llm_none_when_absent(self, tmp_path):
        """yaml 中没有 auditor_llm 段时，load_config 返回 None。"""
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text("llm:\n  model: test\n  api_key: k\n", encoding="utf-8")
        loaded = load_config(yaml_path)
        assert loaded.auditor_llm is None


class TestValidatorBehavior:
    """validator 行为测试：验证判定是否正确。"""

    def test_foreshadow_check_by_description_not_id(self):
        """伏笔检查应查描述关键词，不是 ID。"""
        from novel_agent.audit.validator import check_foreshadows_planted
        draft = "神秘文物箱在地下室被发现"
        foreshadows = [{"id": "S-001", "description": "神秘文物箱"}]
        ok, missing = check_foreshadows_planted(draft, foreshadows)
        assert ok is True
        assert missing == []

    def test_foreshadow_missing_description(self):
        """描述关键词不在正文中时报 missing。"""
        from novel_agent.audit.validator import check_foreshadows_planted
        draft = "主角走在路上"
        foreshadows = [{"id": "S-001", "description": "神秘文物箱"}]
        ok, missing = check_foreshadows_planted(draft, foreshadows)
        assert ok is False
        assert len(missing) == 1

    def test_critical_severity_for_hard_violations(self):
        """确定性检查应对硬指标违规产生 critical 严重度。"""
        from novel_agent.audit.validator import run_deterministic_checks
        # 字数极低（<60%目标）+ 伏笔未植入 → 应有 critical
        result = run_deterministic_checks("短", [{"id": "S-001", "description": "某物"}])
        severities = [i["severity"] for i in result["issues"]]
        assert "critical" in severities  # 伏笔未植入 + 字数极低


class TestGraphRouting:
    """graph 路由行为测试。"""

    def test_route_after_write_failed(self):
        """write 失败时路由到 end_failed。"""
        from novel_agent.orchestrator.graph import _route_after_write
        assert _route_after_write({"status": "failed"}) == "end_failed"

    def test_route_after_write_empty_draft(self):
        """空草稿路由到 end_failed。"""
        from novel_agent.orchestrator.graph import _route_after_write
        assert _route_after_write({"status": "drafted", "draft": ""}) == "end_failed"

    def test_route_after_write_success(self):
        """正常草稿路由到 audit。"""
        from novel_agent.orchestrator.graph import _route_after_write
        assert _route_after_write({"status": "drafted", "draft": "正文内容"}) == "audit"


class TestOverdueForeshadow:
    """逾期伏笔巡检测试。"""

    def test_overdue_foreshadow_found(self, tmp_config):
        """planned_resolve < current_chapter 且未回收的伏笔应被查出。"""
        from novel_agent.bible.repository import BibleRepository
        from novel_agent.bible.database import set_config, SessionLocal
        from novel_agent.bible.models import Base, Project
        from novel_agent.bible import database as db_mod

        set_config(tmp_config)
        Base.metadata.create_all(bind=db_mod.engine)
        db = SessionLocal()
        p = Project(title="test")
        db.add(p)
        db.commit()
        db.refresh(p)
        repo = BibleRepository(db, project_id=p.id)
        # 创建逾期伏笔
        repo.create_foreshadow(
            foreshadow_id="S-001", tier="short",
            plant_chapter=1, planned_resolve_chapter=3,
            description="测试伏笔", status="planted",
        )
        overdue = repo.get_overdue_foreshadows(current_chapter=5)
        assert len(overdue) == 1
        assert overdue[0].foreshadow_id == "S-001"
        db.close()
