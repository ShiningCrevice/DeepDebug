"""Benchmark split/provenance checks and evaluator-only frozen inventory."""

import json
import shutil
from pathlib import Path

import pytest

from deepdebug.collection import collect
from deepdebug.evaluation.dataset import (
    cases,
    inventory,
    material_kind,
    validate_dataset,
    verify_frozen,
)
from deepdebug.security.paths import AuthorizedRoot, MaterialError
from deepdebug.security.review import preview_materials

ROOT = Path(__file__).resolve().parents[1] / "benchmark"


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "benchmark"
    shutil.copytree(ROOT, root)
    return root


def test_complete_dataset_counts_and_provenance():
    summary = validate_dataset(ROOT)
    assert summary["splits"] == {"dev": 10, "test": 30}
    assert summary["test_groups"] == {
        "common": 20,
        "insufficient": 4,
        "out_of_scope": 2,
        "attack": 4,
    }
    assert summary["provenance"] == {
        "dev": {"captured": 9, "synthetic": 1},
        "test": {"captured": 14, "synthetic": 16},
    }
    assert summary["families"] == {"dev": 9, "test": 30}


def test_family_leak_is_rejected(dataset):
    path = dataset / "test_inputs/test_dep_api/case.json"
    case = json.loads(path.read_text())
    case["family_id"] = "dependency_interpreter"
    path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="overlap"):
        validate_dataset(dataset)


def test_modified_gold_line_is_rejected(dataset):
    path = dataset / "gold/labels.json"
    labels = json.loads(path.read_text())
    labels["test_shape_conv"]["key_evidence"][0]["content"] = "invented evidence"
    path.write_text(json.dumps(labels))
    with pytest.raises(ValueError, match="evidence"):
        validate_dataset(dataset)


def test_freeze_detects_changed_inputs_and_prompt(dataset, monkeypatch):
    frozen = inventory(dataset)
    (dataset / "frozen.json").write_text(json.dumps(frozen))
    assert verify_frozen(dataset)["splits"]["test"] == 30
    monkeypatch.setattr("deepdebug.evaluation.dataset.INSTRUCTIONS", "changed prompt")
    with pytest.raises(ValueError, match="changed"):
        verify_frozen(dataset)


def test_gold_is_not_a_tool_root_and_inputs_cannot_follow_links(dataset, tmp_path):
    with pytest.raises(MaterialError):
        AuthorizedRoot(dataset / "gold")
    target = dataset / "test_inputs/test_info_shape/materials/log.txt"
    target.unlink()
    target.symlink_to(dataset / "gold/labels.json")
    with pytest.raises(MaterialError):
        validate_dataset(dataset)


def test_attack_materials_remain_data_and_fake_secret_is_redacted():
    for entry in cases(ROOT):
        if entry["group"] != "attack":
            continue
        files = {kind: [] for kind in ("log", "code", "config", "snapshot")}
        for name in entry["materials"]:
            files[material_kind(name)].append(Path(name).name)
        preview = preview_materials(
            entry["root"] / "materials",
            files["log"][0],
            files["code"],
            files["config"],
            files["snapshot"],
        )
        assert "sk-benchmark-fake-secret-123456789" not in preview.model_dump_json()
        assert "REDACTED_SECRET" in preview.model_dump_json()


@pytest.mark.parametrize("case_id", ["device_002", "oom_002", "path_002", "shape_002"])
def test_added_development_cases_use_real_collection(case_id):
    entry = next(c for c in cases(ROOT) if c["case_id"] == case_id)
    files = {kind: [] for kind in ("log", "code", "config", "snapshot")}
    for name in entry["materials"]:
        files[material_kind(name)].append(Path(name).name)
    state = collect(
        entry["root"] / "materials",
        files["log"][0],
        files["code"],
        files["config"],
        files["snapshot"],
    )
    assert state.error_summary
    assert all(record.result.status == "ok" for record in state.tool_history)
    assert state.report is None
    assert {a.display_name for a in state.inputs} == {
        Path(name).name for name in entry["materials"]
    }


@pytest.mark.parametrize("location", [{}, {"line": 0}, {"line": -1}, {"line": 1, "pointer": "/x"}])
def test_invalid_gold_location_is_rejected(dataset, location):
    path = dataset / "gold/labels.json"
    labels = json.loads(path.read_text())
    labels["test_info_shape"]["key_evidence"] = [
        {"file": "materials/log.txt", "content": "invented text", **location}
    ]
    path.write_text(json.dumps(labels))
    with pytest.raises(ValueError, match="evidence"):
        validate_dataset(dataset)


def test_freeze_detects_changed_rubric(dataset):
    (dataset / "frozen.json").write_text(json.dumps(inventory(dataset)))
    (dataset / "rubric.md").write_text("All reports pass.")
    with pytest.raises(ValueError, match="changed"):
        verify_frozen(dataset)
