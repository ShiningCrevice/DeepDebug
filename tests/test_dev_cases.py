"""Verify fixture provenance and reference locations, without running input code."""

import json
from pathlib import Path

import pytest

from deepdebug.agent.schemas import EnvironmentSnapshot
from deepdebug.agent.state import DiagnosisState

ROOT = Path(__file__).resolve().parents[1] / "benchmark"


@pytest.mark.parametrize("case_id", ["dep_001", "dep_002"])
def test_captured_case_and_manual_reference_agree(case_id: str) -> None:
    case = ROOT / "dev" / case_id
    manifest = json.loads((case / "case.json").read_text(encoding="utf-8"))
    state = DiagnosisState.model_validate_json(
        (ROOT / "gold/dev" / f"{case_id}.json").read_text(encoding="utf-8")
    )
    assert manifest["metadata"]["synthetic"] is False
    assert manifest["metadata"]["paths_redacted"] is True
    assert manifest["split"] == "dev"
    assert manifest["metadata"]["exit_code"] != 0
    assert {Path(name).name for name in manifest["materials"]} == {
        a.display_name for a in state.inputs
    }
    paths = {a.artifact_id: case / "materials" / a.display_name for a in state.inputs}
    for artifact in state.inputs:
        assert artifact.size_bytes == paths[artifact.artifact_id].stat().st_size
        if artifact.kind == "snapshot":
            EnvironmentSnapshot.model_validate_json(paths[artifact.artifact_id].read_text())
    for evidence in state.evidence:
        raw = paths[evidence.source.id].read_text(encoding="utf-8")
        if evidence.location.kind == "lines":
            lines = raw.splitlines()
            assert evidence.content == "\n".join(
                lines[evidence.location.start - 1 : evidence.location.end]
            )
        else:
            value = json.loads(raw)
            for token in evidence.location.pointer.lstrip("/").split("/"):
                value = value[int(token)] if isinstance(value, list) else value[token]
            expected = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            assert evidence.content == expected
        if evidence.source.kind == "snapshot":
            snapshot = json.loads(raw)
            assert evidence.source.environment_id == snapshot["environment"]["environment_id"]
            assert (
                evidence.collected_at
                == EnvironmentSnapshot.model_validate(snapshot).environment.collected_at
            )


def test_similar_logs_require_environment_context() -> None:
    first = ROOT / "dev/dep_001/materials"
    second = ROOT / "dev/dep_002/materials"
    assert (first / "log.txt").read_text() == (second / "log.txt").read_text()
    missing = json.loads((first / "launch.json").read_text())
    mismatch = json.loads((second / "launch.json").read_text())
    assert missing["actual_interpreter"] == missing["intended_interpreter"]
    assert mismatch["actual_interpreter"] != mismatch["intended_interpreter"]
    project = EnvironmentSnapshot.model_validate_json(
        (second / "project_snapshot.json").read_text()
    )
    assert project.packages[0].status == "installed"
