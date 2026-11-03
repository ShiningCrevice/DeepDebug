"""Verify fixture provenance and reference locations, without running input code."""

import json
from pathlib import Path

import pytest

from deepdebug.agent.schemas import EnvironmentSnapshot
from deepdebug.agent.state import DiagnosisState
from deepdebug.collection import collect

ROOT = Path(__file__).resolve().parents[1] / "benchmark"


def test_seed_categories_cover_mvp() -> None:
    manifests = [json.loads(path.read_text()) for path in (ROOT / "dev").glob("*/case.json")]
    assert {case["category"] for case in manifests} == {
        "dependency",
        "path",
        "configuration",
        "device_mismatch",
        "cuda_oom",
    }
    assert all(case["split"] == "dev" for case in manifests)


@pytest.mark.parametrize(
    "case_id", sorted(path.name for path in (ROOT / "dev").iterdir() if path.is_dir())
)
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
    assert state.report is not None
    assert state.tool_history == []
    assert all(check.status == "未执行" for check in state.report.verifications)
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


@pytest.mark.parametrize(
    "case_id",
    sorted(path.name for path in (ROOT / "dev").iterdir() if path.is_dir()),
)
def test_captured_inputs_produce_traceable_collection(case_id: str) -> None:
    case = ROOT / "dev" / case_id
    reference = DiagnosisState.model_validate_json(
        (ROOT / "gold/dev" / f"{case_id}.json").read_text()
    )

    def names(kind: str) -> list[str]:
        return [a.display_name for a in reference.inputs if a.kind == kind]

    state = collect(
        case / "materials", names("log")[0], names("code"), names("config"), names("snapshot")
    )
    assert state.error_summary
    assert all(record.result.status == "ok" for record in state.tool_history)
    assert state.target_environment == reference.target_environment
    assert state.report is None
    assert state.hypotheses == []
    assert all(artifact.redaction_status == "pending" for artifact in state.inputs)
    artifacts = {a.artifact_id: case / "materials" / a.display_name for a in state.inputs}
    for evidence in state.evidence:
        raw = artifacts[evidence.source.id].read_text()
        if evidence.location.kind == "lines":
            assert evidence.content == "\n".join(
                raw.splitlines()[evidence.location.start - 1 : evidence.location.end]
            )
        else:
            value = json.loads(raw)
            for token in evidence.location.pointer.lstrip("/").split("/"):
                value = value[int(token)] if isinstance(value, list) else value[token]
            assert json.loads(evidence.content) == value
