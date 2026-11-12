"""前端契约镜像防漂移：生成结果必须与仓库内提交的 fieldContractData.ts 逐字节一致。

字段描述的单一所有者是后端 declarations.py。若有人直接改前端镜像、或改了后端
声明却忘记重新生成，此用例会失败，保证适配层共用的是同一份契约而不是两份猜测。
"""
from __future__ import annotations

from pathlib import Path

from app.contracts.codegen_ts import default_output_path, render


def test_generated_mirror_matches_committed_file():
    target = default_output_path()
    assert target.exists(), f"缺少前端镜像文件：{target}"
    committed = target.read_text(encoding="utf-8")
    regenerated = render()
    assert committed == regenerated, (
        "前端字段契约镜像与后端声明不一致：请在 backend 目录执行 "
        "python -m app.contracts.codegen_ts 重新生成，不要手工修改镜像文件"
    )


def test_mirror_lives_at_expected_frontend_location():
    target = default_output_path()
    expected = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "fieldContractData.ts"
    assert target.resolve() == expected.resolve()
