"""临时桥接：提供 project_data 路径。Task 5 会重构进 config。"""
from __future__ import annotations

import os
from pathlib import Path


def _PROJECT_DATA_DIR() -> Path:
    return Path(os.getenv("NOVEL_PROJECT_DATA", "project_data"))
