from pathlib import Path

import pytest

from quant_system import QuantSystem


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_resolve_data_dir_accepts_project_relative_path():
    resolved = Path(QuantSystem._resolve_data_dir("data"))

    assert resolved == (PROJECT_ROOT / "data").resolve()


def test_resolve_data_dir_rejects_path_outside_project():
    outside_path = PROJECT_ROOT.parent

    with pytest.raises(ValueError, match="data_dir 必须位于项目根目录内"):
        QuantSystem._resolve_data_dir(outside_path)
