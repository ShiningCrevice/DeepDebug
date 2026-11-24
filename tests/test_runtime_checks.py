"""Fixed six-case runtime probes and honest missing-environment outcomes."""

import sys
from pathlib import Path

import pytest

from deepdebug.evaluation.runtime_checks import PROGRAM, run_checks, run_phase
from deepdebug.tools.process import ProcessResult


@pytest.mark.parametrize("case_id", ["path_001", "path_002"])
def test_path_regressions_execute_fixed_before_and_after(case_id):
    result = run_checks(Path(sys.executable), [case_id])
    record = result["checks"][0]
    assert result["regression_passed"] == 1
    assert record["before"]["status"] == "expected_failure"
    assert record["before"]["exit_code"] != 0
    assert record["expected_error"] in record["before"]["output"]
    assert record["after"]["source"] == "local/runtime_checks"
    assert record["after"]["status"] == "passed"
    assert record["after"]["exit_code"] == 0
    assert record["model_fix_match"] == "pending_human_review"


@pytest.mark.parametrize(
    "case_id,phase,python",
    [
        ("unknown", "after_fix", Path(sys.executable)),
        ("path_001", "execute_my_code", Path(sys.executable)),
        ("path_001", "after_fix", Path("relative/python")),
    ],
)
def test_unknown_execution_inputs_rejected(case_id, phase, python, monkeypatch):
    monkeypatch.setattr(
        "deepdebug.evaluation.runtime_checks.run_probe",
        lambda *args: pytest.fail("unexpected execution"),
    )
    with pytest.raises(ValueError):
        run_phase(case_id, phase, python)


def test_unavailable_gpu_is_not_a_passing_regression(monkeypatch):
    def probe(argv, cwd, timeout):
        assert argv[1:4] == ["-I", "-c", PROGRAM]
        assert timeout == 15
        return ProcessResult("error", b"CUDA unavailable", exit_code=77)

    monkeypatch.setattr("deepdebug.evaluation.runtime_checks.run_probe", probe)
    result = run_checks(Path(sys.executable), ["device_001", "device_002"])
    assert result["unavailable"] == 2
    assert result["regression_passed"] == 0


def test_wrong_before_error_does_not_confirm_fixed_regression(monkeypatch):
    replies = iter(
        [
            ProcessResult("error", b"unrelated failure", exit_code=1),
            ProcessResult("ok", b"weights=42", exit_code=0),
        ]
    )
    monkeypatch.setattr(
        "deepdebug.evaluation.runtime_checks.run_probe", lambda *args: next(replies)
    )
    result = run_checks(Path(sys.executable), ["path_001"])
    assert result["checks"][0]["before"]["status"] == "unexpected_result"
    assert result["regression_passed"] == 0


def test_timeout_remains_unavailable(monkeypatch):
    monkeypatch.setattr(
        "deepdebug.evaluation.runtime_checks.run_probe",
        lambda *args: ProcessResult("timeout", error="deadline"),
    )
    result = run_phase("shape_001", "after_fix", Path(sys.executable))
    assert result["status"] == "unavailable" and result["exit_code"] is None
    assert result["tool_status"] == "timeout"
