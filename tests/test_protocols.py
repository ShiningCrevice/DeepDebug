"""Reject invalid actions, fabricated references, and misleading result states."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepdebug.agent.actions import ACTION_ADAPTER
from deepdebug.agent.schemas import (
    DiagnosisReport,
    EnvironmentSnapshot,
    Source,
    ToolResult,
    Verification,
)
from deepdebug.agent.state import Budget, DiagnosisState

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def state_data() -> dict:
    return json.loads((ROOT / "benchmark/gold/dev/dep_002.json").read_text(encoding="utf-8"))


def test_reference_roundtrip(state_data: dict) -> None:
    state = DiagnosisState.model_validate(state_data)
    assert DiagnosisState.model_validate_json(state.model_dump_json()) == state
    assert state.report.verifications[0].status == "未执行"
    assert state.budget.tool_calls == 0


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("parse_log", {"artifact_id": "A001"}),
        ("read_artifact", {"artifact_id": "A002", "max_lines": 200}),
        ("inspect_environment", {"environment_id": "ENV_EMPTY", "probe_ids": ["package_metadata"]}),
        ("check_paths", {"path_reference_ids": ["P001"]}),
        ("query_gpu", {"environment_id": "ENV_EMPTY"}),
        ("search_docs", {"query": "dependency", "max_results": 3}),
        ("run_builtin_check", {"case_id": "dep_001", "check_id": "dependency_import"}),
    ],
)
def test_allowlisted_tool_shapes(tool: str, arguments: dict) -> None:
    payload = dict(action="tool", tool=tool, arguments=arguments, purpose="区分候选原因")
    action = ACTION_ADAPTER.validate_json(json.dumps(payload))
    assert action.tool == tool


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("shell", {"command": "echo unsafe"}),
        ("read_artifact", {"artifact_id": "A001", "path": "/etc/passwd"}),
        ("read_artifact", {"artifact_id": "../../private"}),
        ("read_artifact", {"artifact_id": "A001", "max_lines": 201}),
        ("read_artifact", {"artifact_id": "A001", "start_line": 0}),
        ("parse_log", {"artifact_id": "A001", "context_lines": True}),
        ("inspect_environment", {"environment_id": "ENV_EMPTY", "probe_ids": ["exec_python"]}),
        (
            "inspect_environment",
            {"environment_id": "ENV_EMPTY", "probe_ids": [], "code": "print(1)"},
        ),
        ("check_paths", {"path_reference_ids": ["P001"] * 11}),
        ("search_docs", {"query": "dependency", "max_results": 4}),
        ("run_builtin_check", {"case_id": "dep_001", "check_id": "arbitrary_command"}),
    ],
)
def test_unsafe_or_invalid_action_is_rejected(tool: str, arguments: dict) -> None:
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_python(
            dict(action="tool", tool=tool, arguments=arguments, purpose="检查")
        )


def test_need_info_requires_specific_question() -> None:
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_python(dict(action="need_info", questions=[], reason="材料不足"))
    action = ACTION_ADAPTER.validate_python(
        dict(action="need_info", questions=["实际解释器路径？"], reason="缺少环境信息")
    )
    assert action.action == "need_info"
    assert (
        ACTION_ADAPTER.validate_python(
            dict(action="finish", reason="调用预算耗尽", stop_reason="budget_exhausted")
        ).action
        == "finish"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence", "duplicate"),
        ("hypotheses", "unknown_evidence"),
        ("inputs", "duplicate"),
        ("inputs", "too_many"),
        ("inputs", "too_large"),
        ("inputs", "unknown_field"),
        ("evidence", "unknown_artifact"),
        ("evidence", "inverted_lines"),
        ("evidence", "naive_time"),
    ],
)
def test_invalid_state_is_rejected(state_data: dict, field: str, value: str) -> None:
    if value == "duplicate":
        state_data[field].append(deepcopy(state_data[field][0]))
    elif value == "unknown_evidence":
        state_data[field][0]["supporting_evidence"] = ["E999"]
    elif value == "too_many":
        state_data[field] = state_data[field] * 3
    elif value == "too_large":
        state_data[field][0]["size_bytes"] = 2 * 1024 * 1024 + 1
    elif value == "unknown_field":
        state_data[field][0]["server_path"] = "/private"
    elif value == "unknown_artifact":
        state_data[field][0]["source"]["id"] = "A999"
    elif value == "inverted_lines":
        state_data[field][0]["location"] = dict(kind="lines", start=5, end=4)
    elif value == "naive_time":
        state_data[field][0]["collected_at"] = "2026-10-28T10:00:00"
    with pytest.raises(ValidationError):
        DiagnosisState.model_validate(state_data)


def test_pending_action_must_reference_registered_material(state_data: dict) -> None:
    state_data.update(
        report=None,
        stop_reason=None,
        next_action=dict(
            action="tool",
            tool="read_artifact",
            arguments={"artifact_id": "A999"},
            purpose="补充证据",
        ),
    )
    with pytest.raises(ValidationError, match="unknown artifact"):
        DiagnosisState.model_validate(state_data)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_reference",
        "altered_content",
        "other_session",
        "other_environment",
        "different_stop",
        "unsupported_completion",
    ],
)
def test_report_cannot_invent_session_facts(state_data: dict, mutation: str) -> None:
    report = state_data["report"]
    if mutation == "unknown_reference":
        report["fixes"][0]["evidence_ids"] = ["E999"]
    elif mutation == "altered_content":
        report["evidence"][0]["content"] = "fabricated observation"
    elif mutation == "other_session":
        report["session_id"] = "another-session"
    elif mutation == "other_environment":
        report["target_environment"]["environment_id"] = "ENV_OTHER"
    elif mutation == "different_stop":
        report["stop_reason"] = "budget_exhausted"
    elif mutation == "unsupported_completion":
        report["hypotheses"][0]["confidence"] = "信息不足"
    with pytest.raises(ValidationError):
        DiagnosisState.model_validate(state_data)


def test_missing_information_report_can_be_honest() -> None:
    report = DiagnosisReport(
        session_id="empty",
        summary="没有足够材料",
        category="unknown",
        target_environment=None,
        evidence=[],
        hypotheses=[],
        fixes=[],
        verifications=[Verification(check_id="none", status="未执行", reason="没有可用案例")],
        unresolved_questions=["请提供日志与目标环境快照"],
        tool_history=[],
        stop_reason="need_info",
    )
    assert report.evidence == []


@pytest.mark.parametrize("status", ["unavailable", "denied", "timeout", "error"])
def test_failed_tool_needs_reason_and_cannot_claim_success_data(status: str) -> None:
    payload = dict(
        tool_call_id="T001",
        status=status,
        source={"kind": "local", "id": "probe", "environment_id": "ENV_EMPTY"},
        collected_at="2026-10-28T09:00:00+08:00",
        duration_ms=1,
    )
    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)
    payload["error"] = "probe did not run"
    assert ToolResult.model_validate(payload).status == status
    payload["data"] = {"cuda_available": True}
    with pytest.raises(ValidationError):
        ToolResult.model_validate(payload)


def test_verification_requires_execution_and_evidence() -> None:
    payload = dict(check_id="dependency_import", status="预置复现通过", reason="import check")
    with pytest.raises(ValidationError):
        Verification.model_validate(payload)
    payload["execution"] = dict(
        executed_at="2026-10-28T09:00:00+08:00",
        environment_id="ENV_PROJECT",
        exit_code=0,
        output="ok",
    )
    with pytest.raises(ValidationError):
        Verification.model_validate(payload)
    payload["evidence_ids"] = ["E001"]
    assert Verification.model_validate(payload).status == "预置复现通过"
    payload["execution"]["exit_code"] = 1
    with pytest.raises(ValidationError):
        Verification.model_validate(payload)
    payload["status"] = "未执行"
    with pytest.raises(ValidationError):
        Verification.model_validate(payload)


def test_environment_and_document_sources_cannot_be_ambiguous() -> None:
    for kind in ("snapshot", "local", "document"):
        with pytest.raises(ValidationError):
            Source(kind=kind, id="source")


def test_snapshot_does_not_confuse_missing_package_with_probe_failure() -> None:
    data = json.loads((ROOT / "benchmark/dev/dep_001/materials/target_snapshot.json").read_text())
    data["packages"][0]["version"] = "1.0"
    with pytest.raises(ValidationError):
        EnvironmentSnapshot.model_validate(data)


def test_budget_and_independent_session_defaults() -> None:
    with pytest.raises(ValidationError):
        Budget(max_tokens=100, reserved_report_tokens=101)
    with pytest.raises(ValidationError):
        Budget(tool_calls=-1)
    first, second = DiagnosisState(session_id="first"), DiagnosisState(session_id="second")
    first.budget.tool_calls = 1
    assert second.budget.tool_calls == 0


def test_report_cannot_silently_change_current_hypothesis(state_data: dict) -> None:
    state_data["report"]["hypotheses"][0]["cause"] = "另一个未经状态更新的原因"
    with pytest.raises(ValidationError, match="hypotheses must match"):
        DiagnosisState.model_validate(state_data)


def test_snapshot_source_must_point_to_snapshot_material(state_data: dict) -> None:
    state_data["evidence"][2]["source"]["id"] = "A002"
    with pytest.raises(ValidationError, match="snapshot artifact"):
        DiagnosisState.model_validate(state_data)


def test_evidence_preserves_original_whitespace(state_data: dict) -> None:
    from deepdebug.agent.schemas import Evidence

    data = state_data["evidence"][0]
    data["content"] = "    import pydantic\n"
    assert Evidence.model_validate(data).content == data["content"]


def test_failed_check_output_must_not_be_truncated() -> None:
    with pytest.raises(ValidationError, match="full output"):
        Verification(
            check_id="dependency_import",
            status="失败",
            reason="导入失败",
            evidence_ids=["E001"],
            execution={
                "executed_at": "2026-10-28T09:00:00+08:00",
                "environment_id": "ENV_EMPTY",
                "exit_code": 1,
                "output": "partial traceback",
                "truncated": True,
            },
        )
