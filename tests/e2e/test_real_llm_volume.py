"""真实 LLM 端到端一卷验证测试。

该测试调用 scripts/e2e_run_volume.py，使用生产 config.yaml 中的真实 API 凭证
生成 5 章并检查输出。默认不运行，需显式指定 -m e2e。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_real_llm_volume(tmp_path: Path):
    """验证 e2e_run_volume.py 可被调用并产生章节输出文件。"""
    project_root = Path(__file__).resolve().parent.parent.parent
    script = project_root / "scripts" / "e2e_run_volume.py"
    assert script.exists(), f"e2e 脚本不存在: {script}"

    # 脚本内部会设置 NOVEL_PROJECT_DATA / NOVEL_CONFIG_PATH
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=3600,
    )

    assert result.returncode == 0, (
        f"e2e 脚本退出码非 0:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    output_dir = project_root / "e2e_output"
    exported = sorted(output_dir.glob("ch*.txt"))
    chapter_numbers = [int(p.stem.replace("ch", "")) for p in exported]
    assert set(chapter_numbers) >= {1, 2, 3, 4, 5}, (
        f"缺少章节输出文件: {exported}"
    )

    for p in exported:
        text = p.read_text(encoding="utf-8")
        assert len(text.strip()) > 0, f"章节文件为空: {p}"
