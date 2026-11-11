"""Control-loop behavior against real tools, scripted decisions and injected clocks."""

import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepdebug.agent.controller import Controller
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.agent.trace import JsonlTrace
from deepdebug.cli import main
from deepdebug.llm.client import ModelFailure, ModelResponse, ReplayModelClient
from deepdebug.replay import load_replay, replay
from deepdebug.security.paths import AuthorizedRoot
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession

ROOT = Path(__file__).resolve().parents[1]


def hypothesis(cause="缺少依赖", evidence=None):
    return dict(
        hypothesis_id="H1",
        cause=cause,
        confidence="有支持但待验证" if evidence else "信息不足",
        supporting_evidence=evidence or [],
    )


def tool(name="read_artifact", arguments=None, hypotheses=None):
    return dict(
        observation="检查候选原因所需材料。",
        hypotheses=hypotheses or [],
        action=dict(
            action="tool",
            tool=name,
            arguments=arguments or {"artifact_id": "A002"},
            purpose="区分缺包与启动配置不一致。",
        ),
    )


def need_info():
    return dict(
        observation="仍缺少目标环境。",
        hypotheses=[],
        action=dict(
            action="need_info", questions=["请提供故障解释器的环境快照。"], reason="目标环境未知。"
        ),
    )


def finish(evidence="E001"):
    return dict(
        observation="日志支持缺包候选，修复待验证。",
        hypotheses=[hypothesis(evidence=[evidence])],
        action=dict(action="finish", reason="已取得支持证据。", stop_reason="completed"),
        conclusion=dict(summary="缺少依赖候选。", category="dependency"),
    )


class RecordingModel(ReplayModelClient):
    def __init__(self, decisions, *, tokens=0):
        super().__init__(
            ModelResponse(
                content=d if isinstance(d, str) else json.dumps(d),
                output_tokens=tokens,
            )
            for d in decisions
        )
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        return super().decide(request)


@pytest.fixture
def session(tmp_path):
    (tmp_path / "log.txt").write_text("ModuleNotFoundError: No module named 'torch'\n")
    (tmp_path / "code.py").write_text("raise RuntimeError('MUST NOT EXECUTE')\n")
    materials = MaterialRegistry()
    with AuthorizedRoot(tmp_path) as root:
        materials.register(root, "log.txt", "log")
        materials.register(root, "code.py", "code")
    return CollectionSession(materials)


def run(session, decisions, *, budget=None, tokens=0, clock=lambda: 0):
    if budget is not None:
        session.state.budget = budget
    stream = io.StringIO()
    model = RecordingModel(decisions, tokens=tokens)
    state = Controller(
        ToolDispatcher(session),
        model,
        trace=JsonlTrace(stream),
        clock=clock,
    ).run("A001")
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    return state, model, events


def test_tool_observation_reaches_next_request_and_trace(session):
    state, model, events = run(session, [tool(), finish()])
    assert state.stop_reason == "completed"
    assert state.budget.decision_calls == 2
    assert state.budget.tool_calls == 2
    assert "MUST NOT EXECUTE" in model.requests[1].state.evidence[-1].content
    assert state.tool_history[1].purpose == "区分缺包与启动配置不一致。"
    assert state.report.verifications[0].status == "未执行"
    assert state.report.tool_history == state.tool_history
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    for event in events:
        DiagnosisState.model_validate(event["state"])
    assert events[-1]["event"] == "stop"
    assert events[-1]["state"] == state.model_dump(mode="json")


def test_need_info_retains_concrete_questions(session):
    state, _, _ = run(session, [need_info()])
    assert state.stop_reason == "need_info"
    assert state.report.unresolved_questions == ["请提供故障解释器的环境快照。"]


@pytest.mark.parametrize(
    "invalid",
    [
        "not JSON",
        tool("shell", {"command": "touch /tmp/forbidden"}),
        tool(arguments={"artifact_id": "A999"}),
        tool(arguments={"artifact_id": "A002", "path": "../../benchmark/gold"}),
        finish("E999"),
        {**finish(), "evidence": [{"content": "invented"}]},
        {**finish(), "conclusion": {**finish()["conclusion"], "verifications": []}},
    ],
)
def test_invalid_decision_gets_only_one_correction(session, invalid):
    state, model, events = run(session, [invalid, invalid, finish()])
    assert state.stop_reason == "invalid_action"
    assert state.budget.decision_calls == 2
    assert state.budget.tool_calls == 1
    assert model.requests[1].correction
    assert state.hypotheses == []
    assert len([e for e in events if e["event"] == "invalid_decision"]) == 2


def test_corrected_decision_is_accepted(session):
    state, _, _ = run(session, ["bad", finish()])
    assert state.stop_reason == "completed"
    assert state.budget.decision_calls == 2


def test_cache_and_two_round_no_progress_stop(session):
    state, _, events = run(session, [tool()] * 5)
    assert state.stop_reason == "no_progress"
    assert state.budget.decision_calls == 3
    assert state.budget.tool_calls == 2
    assert len(state.tool_history) == 2
    cached = [e for e in events if e["event"] == "tool" and e["details"]["cached"]]
    assert len(cached) == 2
    assert all(e["details"]["tool_call_id"] == "T002" for e in cached)


def test_hypothesis_change_resets_no_progress(session):
    decisions = [tool(), tool(), tool(hypotheses=[hypothesis()]), need_info()]
    state, _, _ = run(session, decisions)
    assert state.stop_reason == "need_info"
    assert state.budget.decision_calls == 4
    assert state.budget.tool_calls == 2


@pytest.mark.parametrize(
    "budget,expected",
    [
        (Budget(max_decision_calls=1), (1, 2)),
        (Budget(max_tool_calls=1), (0, 1)),
        (Budget(max_tool_calls=2), (1, 2)),
        (Budget(max_tokens=5, reserved_report_tokens=5), (0, 0)),
    ],
)
def test_call_budgets_stop_with_report(session, budget, expected):
    state, _, _ = run(session, [tool(), finish()], budget=budget)
    assert state.stop_reason == "budget_exhausted"
    assert (state.budget.decision_calls, state.budget.tool_calls) == expected
    assert state.report.stop_reason == state.stop_reason


def test_token_reserve_blocks_action_after_response(session):
    state, model, _ = run(
        session, [tool()], tokens=10, budget=Budget(max_tokens=15, reserved_report_tokens=5)
    )
    assert state.budget.tokens_used == 10
    assert model.requests[0].max_tokens == 10
    assert state.budget.tool_calls == 1
    assert state.stop_reason == "budget_exhausted"


def test_time_limit_blocks_late_model_action(session):
    now = [0.0]
    model = RecordingModel([tool()])
    original = model.decide

    def late(request):
        assert request.timeout_seconds == 1
        now[0] = 1.1
        return original(request)

    model.decide = late
    session.state.budget = Budget(max_duration_seconds=1)
    state = Controller(ToolDispatcher(session), model, clock=lambda: now[0]).run("A001")
    assert state.stop_reason == "budget_exhausted"
    assert state.budget.tool_calls == 1
    assert state.budget.elapsed_ms == 1100


@pytest.mark.parametrize("kind,attempts", [("timeout", 2), ("unavailable", 2), ("error", 1)])
def test_model_failures_are_traced_and_retry_is_bounded(session, kind, attempts):
    model = RecordingModel([])

    def fail(request):
        raise ModelFailure(kind)

    model.decide = fail
    stream = io.StringIO()
    state = Controller(ToolDispatcher(session), model, trace=JsonlTrace(stream)).run("A001")
    assert state.stop_reason == "model_error"
    assert state.budget.decision_calls == attempts
    assert stream.getvalue().count('"event": "model_error"') == attempts


def test_retry_counts_toward_decision_limit(session):
    state, _, _ = run(session, [], budget=Budget(max_decision_calls=1))
    assert state.stop_reason == "budget_exhausted"
    assert state.budget.decision_calls == 1


@pytest.mark.parametrize(
    "name,args,status",
    [
        (
            "inspect_environment",
            {"environment_id": "secret", "probe_ids": ["python_identity"]},
            "denied",
        ),
        ("query_gpu", {"environment_id": "secret"}, "denied"),
        ("check_paths", {"path_reference_ids": ["../../private"]}, "denied"),
        (
            "run_builtin_check",
            {"case_id": "dep_001", "check_id": "dependency_import"},
            "unavailable",
        ),
    ],
)
def test_dispatch_refusals_are_real_failed_records(session, name, args, status):
    state, model, _ = run(session, [tool(name, args), need_info()])
    record = state.tool_history[1]
    assert record.result.status == status
    assert record.result.data == {}
    assert record.result.evidence_ids == []
    assert model.requests[1].state.tool_history[1] == record


def test_remote_adapter_rejected_before_materials_are_sent(session):
    model = RecordingModel([finish()])
    model.transport = "remote"
    with pytest.raises(ValueError, match="脱敏"):
        Controller(ToolDispatcher(session), model)
    assert not model.requests
    assert not session.state.tool_history


def test_mutated_state_is_revalidated_before_any_execution(session):
    session.state.inputs.append(session.state.inputs[0])
    with pytest.raises(ValidationError):
        run(session, [finish()])
    assert not session.state.tool_history


def test_model_request_is_detached_from_host_state(session):
    model = RecordingModel([need_info()])
    original = model.decide

    def mutate(request):
        request.state.evidence[0].content = "forged"
        request.state.budget.max_tool_calls = 999
        return original(request)

    model.decide = mutate
    state = Controller(ToolDispatcher(session), model).run("A001")
    assert state.evidence[0].content != "forged"
    assert state.budget.max_tool_calls == 8


def test_real_dependency_example_changes_hypothesis(tmp_path):
    stream = io.StringIO()
    state = replay(
        ROOT / "benchmark/dev/dep_002/materials",
        "log.txt",
        [],
        ["launch.json"],
        ["target_snapshot.json", "project_snapshot.json"],
        load_replay(ROOT / "examples/dep_002_replay.json"),
        trace_stream=stream,
    )
    assert state.stop_reason == "completed"
    assert state.target_environment.environment_id == "ENV_EMPTY"
    assert len(state.evidence) == 9
    assert state.budget.tool_calls == 4
    assert state.budget.decision_calls == 4
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    decisions = [e["state"]["hypotheses"] for e in events if e["event"] == "decision"]
    assert decisions[0][0]["cause"] != decisions[-1][0]["cause"]
    assert state.report.verifications[0].status == "未执行"


def test_cli_replay_and_exclusive_trace(tmp_path, capsys):
    trace = tmp_path / "trace.jsonl"
    args = [
        "replay",
        "--root",
        str(ROOT / "benchmark/dev/dep_002/materials"),
        "--log",
        "log.txt",
        "--config",
        "launch.json",
        "--snapshot",
        "target_snapshot.json",
        "--snapshot",
        "project_snapshot.json",
        "--responses",
        str(ROOT / "examples/dep_002_replay.json"),
        "--trace",
        str(trace),
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["report"]["stop_reason"] == "completed"
    original = trace.read_bytes()
    assert main(args) == 2
    assert not capsys.readouterr().out
    assert trace.read_bytes() == original


def test_invalid_usage_envelope_stops_without_executing_action(session):
    model = RecordingModel([])
    model.decide = lambda request: ModelResponse(content="{}", input_tokens=-1)
    state = Controller(ToolDispatcher(session), model).run("A001")
    assert state.stop_reason == "model_error"
    assert state.budget.tool_calls == 1


def test_retry_can_recover_and_keeps_usage(session):
    model = RecordingModel([finish()], tokens=12)
    original = model.decide
    calls = []

    def transient(request):
        calls.append(request)
        if len(calls) == 1:
            raise ModelFailure("timeout")
        return original(request)

    model.decide = transient
    state = Controller(ToolDispatcher(session), model).run("A001")
    assert state.stop_reason == "completed"
    assert state.budget.decision_calls == 2
    assert state.budget.tokens_used == 12


def test_snapshot_probe_selection_and_target_binding():
    model = RecordingModel(
        [
            tool(
                "inspect_environment",
                {"environment_id": "ENV_PROJECT", "probe_ids": ["package_metadata"]},
            ),
            tool(
                "inspect_environment",
                {"environment_id": "ENV_EMPTY", "probe_ids": ["python_identity"]},
            ),
            tool("query_gpu", {"environment_id": "ENV_EMPTY"}),
            need_info(),
        ]
    )
    state = replay(
        ROOT / "benchmark/dev/dep_002/materials",
        "log.txt",
        [],
        [],
        ["target_snapshot.json", "project_snapshot.json"],
        model,
    )
    assert model.requests[1].state.target_environment is None
    project = state.tool_history[1].result
    assert set(project.data) == {"environment", "packages"}
    assert state.target_environment.environment_id == "ENV_EMPTY"
    assert set(state.tool_history[2].result.data) == {"environment", "python_version"}
    assert state.tool_history[3].result.status == "unavailable"
    assert state.tool_history[3].result.source.environment_id == "ENV_EMPTY"
    assert not any(
        e.location.pointer == "/python_version" for e in state.evidence if e.source.id == "A003"
    )


@pytest.mark.parametrize("invalid_target", ["duplicate", "malformed"])
def test_invalid_target_never_silently_becomes_comparison(tmp_path, invalid_target):
    (tmp_path / "log.txt").write_text("ModuleNotFoundError: missing\n")
    raw = (ROOT / "benchmark/dev/dep_002/materials/project_snapshot.json").read_text()
    (tmp_path / "target.json").write_text(raw if invalid_target == "duplicate" else "{}")
    (tmp_path / "comparison.json").write_text(raw)
    state = replay(
        tmp_path,
        "log.txt",
        [],
        [],
        ["target.json", "comparison.json"],
        RecordingModel(
            [
                tool(
                    "inspect_environment",
                    {"environment_id": "ENV_PROJECT", "probe_ids": ["python_identity"]},
                ),
                need_info(),
            ]
        ),
    )
    assert state.target_environment is None
    assert state.tool_history[1].result.status == (
        "denied" if invalid_target == "duplicate" else "ok"
    )


def test_registered_paths_keep_host_source_and_reject_traversal(tmp_path):
    (tmp_path / "log.txt").write_text("FileNotFoundError: missing\n")
    state = replay(
        tmp_path,
        "log.txt",
        [],
        [],
        [],
        RecordingModel(
            [
                tool("check_paths", {"path_reference_ids": ["P001"]}),
                tool("check_paths", {"path_reference_ids": ["P002"]}),
                need_info(),
            ]
        ),
        paths=["log.txt", "../private"],
    )
    assert state.tool_history[1].result.data["P001"]["exists"] is True
    assert state.tool_history[1].result.source.environment_id == "collector"
    assert state.tool_history[2].result.status == "denied"
    assert state.target_environment is None


def test_document_dispatch_retains_real_document_evidence(session):
    state, _, _ = run(session, [tool("search_docs", {"query": "torch.nn.Linear"}), need_info()])
    assert state.tool_history[1].result.status == "ok"
    docs = [e for e in state.evidence if e.source.kind == "document"]
    assert docs
    assert docs[0].source.url
    assert docs[0].source.applicable_version == "PyTorch 2.9"


def test_injected_material_cannot_execute_a_new_tool(session):
    # The hostile string is read as evidence; even a model following it is refused.
    state, _, _ = run(session, [tool(), tool("shell", {"command": "echo stolen"}), need_info()])
    assert state.stop_reason == "need_info"
    assert [r.tool for r in state.tool_history] == ["parse_log", "read_artifact"]


def test_trace_revalidates_mutated_state(session):
    session.state.budget.tool_calls = -1
    stream = io.StringIO()
    with pytest.raises(ValidationError):
        JsonlTrace(stream).write("start", session.state, {})
    assert not stream.getvalue()


def test_cli_decision_schema(capsys):
    assert main(["schema", "decision"]) == 0
    assert "hypotheses" in json.loads(capsys.readouterr().out)["properties"]


def test_trace_io_time_cannot_start_model_after_deadline(session):
    now = [0.0]

    class SlowTrace(io.StringIO):
        def write(self, text):
            if json.loads(text)["event"] == "model_request":
                now[0] = 1.0
            return super().write(text)

    session.state.budget = Budget(max_duration_seconds=1)
    model = RecordingModel([finish()])
    state = Controller(
        ToolDispatcher(session), model, clock=lambda: now[0], trace=JsonlTrace(SlowTrace())
    ).run("A001")
    assert not model.requests
    assert state.stop_reason == "budget_exhausted"
    assert state.budget.tool_calls == 1
