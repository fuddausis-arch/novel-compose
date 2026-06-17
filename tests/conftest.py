"""pytest 共享 fixtures。"""
from __future__ import annotations

from pathlib import Path

import pytest

from novel_agent.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """临时项目数据目录的配置。"""
    return Config(project_data_dir=tmp_path / "project_data")
