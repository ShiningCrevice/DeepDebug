"""Exercise developer seed capture without importing or executing benchmark inputs."""

import json
import runpy
import sys
import venv
from pathlib import Path

import pytest

from deepdebug.agent.schemas import EnvironmentSnapshot
from deepdebug.collection import collect
from deepdebug.tools.process import run_probe

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = runpy.run_path(str(ROOT / "scripts/capture_failure_cases.py"))["capture"]


def test_capture_path_failure_and_collect(tmp_path: Path) -> None:
    output = tmp_path / "capture"
    summary = CAPTURE(output, Path(sys.executable), ["path_001"])
    assert summary["cases"]["path_001"] == {"status": "captured", "exit_code": 1}
    case = output / "path_001"
    manifest = json.loads((case / "case.json").read_text())
    assert manifest["metadata"]["synthetic"] is False
    materials = case / "materials"
    layout = json.loads((materials / "layout.json").read_text())
    assert layout["resolved_exists"] is False
    assert layout["project_relative_exists"] is True
    state = collect(
        materials,
        "log.txt",
        ["failure_demo.py"],
        ["config.json", "layout.json"],
        ["target_snapshot.json"],
    )
    assert "FileNotFoundError" in state.error_summary
    assert all(record.result.status == "ok" for record in state.tool_history)
    assert state.report is None
    assert state.target_environment.environment_id == layout["environment_id"]
    for path in materials.iterdir():
        text = path.read_text()
        assert str(tmp_path) not in text
        assert sys.prefix not in text
        assert "deepdebug-failure-" not in text
    EnvironmentSnapshot.model_validate_json((materials / "target_snapshot.json").read_text())


def test_missing_torch_does_not_create_failure_fixtures(tmp_path: Path) -> None:
    environment = tmp_path / "empty"
    venv.EnvBuilder(with_pip=False).create(environment)
    output = tmp_path / "capture"
    summary = CAPTURE(output, environment / "bin/python", ["shape_001", "device_001", "oom_001"])
    assert all(item["status"] == "unavailable" for item in summary["cases"].values())
    assert list(output.iterdir()) == [output / "capture_summary.json"]


def test_capture_refuses_existing_output(tmp_path: Path) -> None:
    marker = tmp_path / "keep.txt"
    marker.write_text("existing")
    with pytest.raises(FileExistsError):
        CAPTURE(tmp_path, Path(sys.executable), ["path_001"])
    assert marker.read_text() == "existing"
    assert list(tmp_path.iterdir()) == [marker]


@pytest.mark.parametrize("case_ids", [[], ["path_001", "path_001"], ["uploaded.py"]])
def test_capture_accepts_only_unique_fixed_cases(tmp_path: Path, case_ids: list[str]) -> None:
    output = tmp_path / "capture"
    with pytest.raises(ValueError):
        CAPTURE(output, Path(sys.executable), case_ids)
    assert not output.exists()


def test_probe_retains_real_failure_output(tmp_path: Path) -> None:
    result = run_probe(
        [sys.executable, "-I", "-c", "raise ValueError('fixed failure')"], tmp_path, 10
    )
    assert result.status == "error"
    assert result.exit_code == 1
    assert b"ValueError: fixed failure" in result.output


def test_capture_rejects_relative_interpreter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        CAPTURE(tmp_path / "capture", Path("python"), ["path_001"])
