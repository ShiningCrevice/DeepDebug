"""Fixed-case execution, no uploaded code, and host-confirmed report linkage."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepdebug.agent.actions import ACTION_ADAPTER
from deepdebug.agent.state import DiagnosisState
from deepdebug.cli import main
from deepdebug.replay import load_replay, replay
from deepdebug.reporting.render import export_report
from deepdebug.tools import builtin_checks
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.tools.builtin_checks import run_builtin_check
from deepdebug.tools.process import ProcessResult
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession
from deepdebug.verification import verify_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["dependency", "path"])
def test_before_fails_after_passes_with_full_execution(case):
    before = run_builtin_check(case, "before_fix")
    after = run_builtin_check(case, "after_fix")
    assert before.status == "失败"
    assert before.execution.exit_code != 0
    assert "Traceback" in before.execution.output
    assert not before.execution.truncated
    assert after.status == "预置复现通过"
    assert after.execution.exit_code == 0
    assert before.environment_id == after.environment_id
    assert before.executed_at.tzinfo


@pytest.mark.parametrize(
    "result",
    [
        ProcessResult("error", b"CUDA unavailable\n", "exit=77", 77),
        ProcessResult("unavailable", error="missing interpreter"),
        ProcessResult("timeout", error="timeout"),
        ProcessResult("error", error="output limit"),
    ],
)
def test_unexecutable_checks_preserve_failure_status(monkeypatch, result):
    monkeypatch.setattr(builtin_checks, "run_probe", lambda *a, **k: result)
    check = run_builtin_check("device", "after_fix")
    assert check.status == "无法执行" and check.execution is None
    assert check.tool_status != "ok"
    assert check.reason


def test_fixed_argv_and_no_arbitrary_case(monkeypatch):
    calls = []

    def probe(argv, cwd, timeout):
        calls.append((argv, cwd, timeout))
        assert cwd.is_dir()
        return ProcessResult("ok", b"ok", exit_code=0)

    monkeypatch.setattr(builtin_checks, "run_probe", probe)
    with pytest.raises(ValueError):
        run_builtin_check("../upload.py", "after_fix")
    with pytest.raises(ValueError):
        run_builtin_check("dependency", "shell-command")
    assert not calls
    run_builtin_check("shape", "after_fix", Path(sys.executable))
    argv, cwd, timeout = calls[0]
    assert argv == [sys.executable, "-I", "-c", builtin_checks.PROGRAM, "shape", "after_fix"]
    assert timeout == 10 and not cwd.exists()


def test_dispatch_records_and_caches_preset_execution():
    session = CollectionSession(MaterialRegistry())
    dispatcher = ToolDispatcher(session)
    action = ACTION_ADAPTER.validate_python(
        dict(
            action="tool",
            tool="run_builtin_check",
            purpose="检查固定路径修复。",
            arguments=dict(case_id="path", check_id="after_fix"),
        )
    )
    result, cached = dispatcher.dispatch(action)
    assert not cached and result.status == "ok"
    assert result.data["status"] == "预置复现通过"
    assert result.source.environment_id == result.data["environment_id"]
    evidence = session.state.evidence[0]
    assert evidence.source == result.source
    assert json.loads(evidence.content) == result.data["execution"]
    repeated, cached = dispatcher.dispatch(action)
    assert cached and repeated == result
    assert len(session.state.tool_history) == 1
    assert session.state.target_environment is None


@pytest.fixture
def state():
    state = replay(
        ROOT / "benchmark/dev/dep_002/materials",
        "log.txt",
        [],
        ["launch.json"],
        ["target_snapshot.json", "project_snapshot.json"],
        load_replay(ROOT / "examples/dep_002_replay.json"),
    )
    # The host confirmation is tested with an explicitly matching synthetic suggestion.
    state.report.fixes[0].description = builtin_checks.PRESETS["path"]["fix"]
    return state


def test_unconfirmed_match_does_not_execute(state, monkeypatch):
    monkeypatch.setattr(
        "deepdebug.verification.run_builtin_check", lambda *a: pytest.fail("executed")
    )
    updated = verify_report(state, "path", 1, matches_preset=False)
    assert updated.report.verifications[-1].status == "未执行"
    assert updated.tool_history == state.tool_history


def test_verified_report_is_consistent_and_retains_previous_checks(state):
    updated = verify_report(state, "path", 1, matches_preset=True)
    checks = updated.report.verifications
    assert [v.status for v in checks] == ["失败", "预置复现通过"]
    assert all(v.fix_index == 1 and v.evidence_ids for v in checks)
    assert updated.target_environment == state.target_environment
    assert updated.report.tool_history == updated.tool_history
    assert len(updated.tool_history) == len(state.tool_history) + 2
    assert state.report.verifications[0].status == "未执行"
    assert DiagnosisState.model_validate_json(updated.model_dump_json()) == updated
    json_report, markdown = export_report(updated)
    assert "预置复现通过" in markdown and "失败" in json_report
    repeated = verify_report(updated, "path", 1, matches_preset=True)
    assert len(repeated.report.verifications) == 4
    assert len({e.evidence_id for e in repeated.evidence}) == len(repeated.evidence)


def test_bad_fix_index_and_tampered_report_are_rejected(state):
    with pytest.raises(ValueError):
        verify_report(state, "path", 2, matches_preset=True)
    state.report.verifications[0].fix_index = 2
    with pytest.raises(ValidationError):
        verify_report(state, "path", 1, matches_preset=True)


def test_cli_list_check_and_report_verification(state, tmp_path, capsys):
    assert main(["builtin-check"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == set(builtin_checks.PRESETS)
    assert main(["builtin-check", "--case", "path", "--check", "before_fix"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "失败"
    source, output = tmp_path / "state.json", tmp_path / "verified.json"
    source.write_text(state.model_dump_json())
    assert (
        main(
            [
                "verify-report",
                "--state",
                str(source),
                "--case",
                "path",
                "--fix-index",
                "1",
                "--matches-preset",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    updated = DiagnosisState.model_validate_json(output.read_text())
    assert updated.report.verifications[-1].status == "预置复现通过"


def test_cli_retry_success_keeps_prior_unexecuted_check(state, tmp_path):
    pending = verify_report(state, "path", 1, matches_preset=False)
    source, output = tmp_path / "pending.json", tmp_path / "verified.json"
    source.write_text(pending.model_dump_json())
    assert (
        main(
            [
                "verify-report",
                "--state",
                str(source),
                "--case",
                "path",
                "--fix-index",
                "1",
                "--matches-preset",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    updated = DiagnosisState.model_validate_json(output.read_text())
    assert [v.status for v in updated.report.verifications] == ["未执行", "失败", "预置复现通过"]
