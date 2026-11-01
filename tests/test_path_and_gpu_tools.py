"""Path authorization and snapshot GPU evidence, including explicit failure history."""

import json
import os

import pytest

from deepdebug.agent.state import DiagnosisState
from deepdebug.cli import main
from deepdebug.collection import collect
from deepdebug.security.paths import AuthorizedRoot
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.tools.path_references import PathReferences
from deepdebug.tools.session import CollectionSession

pytestmark = pytest.mark.skipif(os.name != "posix", reason="safe paths require POSIX")
TIME = "2026-11-01T00:00:00+00:00"
GPU_TIME = "2026-11-01T00:00:02+00:00"


def snapshot_data(gpu=None):
    return {
        "environment": {
            "environment_id": "TARGET",
            "interpreter": "/target/python",
            "collected_at": TIME,
        },
        "python_version": "3.12.3",
        "gpu": gpu,
    }


def session_with_snapshot(tmp_path, gpu=None):
    (tmp_path / "snapshot.json").write_text(json.dumps(snapshot_data(gpu)))
    registry = MaterialRegistry()
    with AuthorizedRoot(tmp_path) as root:
        item = registry.register(root, "snapshot.json", "snapshot")
    return CollectionSession(registry), item.artifact_id


def test_path_presence_and_missing_are_local_timestamped_observations(tmp_path):
    (tmp_path / "log.txt").write_text("FileNotFoundError: model.pt\n")
    (tmp_path / "data").mkdir()
    state = collect(tmp_path, "log.txt", [], [], [], paths=["log.txt", "data", "missing/model.pt"])
    result = state.tool_history[-1].result
    assert result.status == "ok"
    assert [v["type"] for v in result.data.values()] == ["file", "directory", None]
    assert result.data["P003"]["exists"] is False
    assert result.source.kind == "local" and result.source.environment_id == "collector"
    assert state.target_environment is None
    for evidence in state.evidence[-3:]:
        ref = evidence.location.pointer[1:]
        assert json.loads(evidence.content) == result.data[ref]
        assert evidence.collected_at.tzinfo is not None
    assert DiagnosisState.model_validate_json(state.model_dump_json()) == state


@pytest.mark.parametrize(
    "reference",
    [
        "../secret",
        "/etc/passwd",
        ".env",
        "nested/../../secret",
        "nested\\secret",
        "benchmark/gold/answer.json",
        "\x00",
        "link",
        "alias/child",
        "hard",
        "pipe",
    ],
)
def test_path_denials_are_recorded_without_partial_success(tmp_path, reference):
    (tmp_path / "log.txt").write_text("FileNotFoundError: missing\n")
    (tmp_path / "link").symlink_to(tmp_path / "log.txt")
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    os.link(tmp_path / "log.txt", tmp_path / "hard")
    os.mkfifo(tmp_path / "pipe")
    with AuthorizedRoot(tmp_path) as root:
        refs = PathReferences(root)
        valid = refs.register("missing")
        invalid = refs.register(reference)
        session = CollectionSession(MaterialRegistry())
        result = session.check_paths(refs, [valid, invalid])
    assert result.status == "denied"
    assert result.data == {} and not result.evidence_ids
    assert not session.state.evidence
    assert session.state.budget.tool_calls == 1


def test_path_ids_and_call_limit_are_checked(tmp_path):
    with AuthorizedRoot(tmp_path) as root:
        refs = PathReferences(root)
        ref = refs.register("absent")
        session = CollectionSession(MaterialRegistry())
        assert session.check_paths(refs, ["unregistered"]).status == "denied"
        assert session.check_paths(refs, [ref] * 11).status == "error"


def test_path_root_remains_pinned(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "exists").touch()
    with AuthorizedRoot(materials) as root:
        refs = PathReferences(root)
        ref = refs.register("exists")
        materials.rename(tmp_path / "original")
        materials.symlink_to(tmp_path, target_is_directory=True)
        result = CollectionSession(MaterialRegistry()).check_paths(refs, [ref])
    assert result.data[ref]["exists"] is True


def test_gpu_preserves_raw_value_and_sample_time(tmp_path):
    gpu = {
        "status": "ok",
        "collected_at": GPU_TIME,
        "devices": [
            {"index": 0, "name": "Demo GPU", "memory_total_mib": 8192, "memory_used_mib": 100}
        ],
    }
    session, artifact_id = session_with_snapshot(tmp_path, gpu)
    session.inspect_snapshot(artifact_id)
    target = session.state.target_environment.model_copy(deep=True)
    result = session.query_gpu(artifact_id)
    assert result.status == "ok" and result.data == gpu
    assert result.source.environment_id == "TARGET"
    assert result.collected_at.isoformat() == GPU_TIME
    evidence = session.state.evidence[-1]
    assert evidence.location.pointer == "/gpu"
    assert json.loads(evidence.content) == gpu
    assert evidence.collected_at == result.collected_at
    assert session.state.target_environment == target


@pytest.mark.parametrize("status", [None, "unavailable", "timeout", "error"])
def test_gpu_failure_retains_original_source_and_no_success_data(tmp_path, status):
    gpu = dict(status=status, collected_at=GPU_TIME, error="probe failed") if status else None
    session, artifact_id = session_with_snapshot(tmp_path, gpu)
    result = session.query_gpu(artifact_id)
    assert result.status == (status or "unavailable")
    assert result.source.kind == "snapshot"
    assert result.source.environment_id == "TARGET"
    assert result.collected_at.isoformat() == (GPU_TIME if status else TIME)
    assert not result.data and not result.evidence_ids
    assert session.state.tool_history[-1].result == result


def test_collect_cli_gpu_and_paths(tmp_path, capsys):
    (tmp_path / "log.txt").write_text("FileNotFoundError: missing\n")
    (tmp_path / "snapshot.json").write_text(json.dumps(snapshot_data()))
    code = main(
        [
            "collect",
            "--root",
            str(tmp_path),
            "--log",
            "log.txt",
            "--snapshot",
            "snapshot.json",
            "--query-gpu",
            "--path",
            "missing",
        ]
    )
    assert code == 1
    state = DiagnosisState.model_validate_json(capsys.readouterr().out)
    assert [r.result.status for r in state.tool_history] == ["ok", "ok", "unavailable", "ok"]
    assert state.target_environment.environment_id == "TARGET"
    assert state.tool_history[-1].result.source.environment_id == "collector"


def test_gpu_rejects_conflicting_environment_ids(tmp_path):
    (tmp_path / "first.json").write_text(json.dumps(snapshot_data()))
    (tmp_path / "second.json").write_text(json.dumps(snapshot_data()))
    registry = MaterialRegistry()
    with AuthorizedRoot(tmp_path) as root:
        first = registry.register(root, "first.json", "snapshot")
        second = registry.register(root, "second.json", "snapshot")
    session = CollectionSession(registry)
    session.inspect_snapshot(first.artifact_id)
    result = session.query_gpu(second.artifact_id)
    assert result.status == "error"
    assert not result.data and not result.evidence_ids


def test_explicit_path_root_does_not_change_snapshot_target(tmp_path):
    materials = tmp_path / "materials"
    project = tmp_path / "project-data"
    materials.mkdir()
    project.mkdir()
    (materials / "log.txt").write_text("FileNotFoundError: model.pt\n")
    (materials / "snapshot.json").write_text(json.dumps(snapshot_data()))
    (project / "model.pt").touch()
    state = collect(
        materials,
        "log.txt",
        [],
        [],
        ["snapshot.json"],
        paths=["model.pt"],
        path_root=project,
    )
    result = state.tool_history[-1].result
    assert result.data["P001"]["base_directory"] == str(project)
    assert result.data["P001"]["exists"] is True
    assert state.target_environment.environment_id == "TARGET"
    assert result.source.environment_id == "collector"
