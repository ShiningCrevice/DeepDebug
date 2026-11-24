"""Continued sessions preserve reviewed history while extending explicit scope and budget."""

import io
import json
from datetime import datetime, timezone

import pytest

from deepdebug.agent.state import Budget
from deepdebug.continuation import continue_session
from deepdebug.llm.client import ModelResponse, ReplayModelClient
from deepdebug.replay import replay_reviewed
from deepdebug.security.review import confirm_materials, extend_review
from deepdebug.sessions import SavedSession
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.ui.workflow import preview_uploads


def model(*decisions):
    return ReplayModelClient(ModelResponse(content=json.dumps(d)) for d in decisions)


def need_info():
    return dict(
        observation="缺少配置。",
        hypotheses=[],
        action=dict(action="need_info", questions=["请补充配置。"], reason="配置未知。"),
    )


@pytest.fixture
def saved():
    review = confirm_materials(preview_uploads("ValueError: missing configuration", []))
    trace = io.StringIO()
    state = replay_reviewed(review, model(need_info()), trace_stream=trace)
    return SavedSession(
        saved_at=datetime.now(timezone.utc), state=state, review=review, trace=trace.getvalue()
    )


def appended(saved):
    registry = MaterialRegistry()
    registry.register_bytes("config.json", b'{"width":4}', "config")
    return confirm_materials(extend_review(saved.review, registry))


def test_continue_retains_history_reuses_cache_and_reads_new_material(saved):
    review = appended(saved)
    decisions = [
        dict(
            observation="复用原日志。",
            hypotheses=[],
            action=dict(
                action="tool",
                tool="parse_log",
                arguments={"artifact_id": "A001"},
                purpose="复用日志证据。",
            ),
        ),
        dict(
            observation="读取补充配置。",
            hypotheses=[],
            action=dict(
                action="tool",
                tool="read_artifact",
                arguments={"artifact_id": "A002"},
                purpose="检查维度。",
            ),
        ),
        need_info(),
    ]
    updated = continue_session(saved, review, history_reviewed=True, replay_model=model(*decisions))
    assert updated.state.session_id == saved.state.session_id
    assert updated.state.inputs[:1] == saved.state.inputs
    assert updated.state.evidence[: len(saved.state.evidence)] == saved.state.evidence
    assert updated.state.tool_history[: len(saved.state.tool_history)] == saved.state.tool_history
    assert updated.state.budget.decision_calls == saved.state.budget.decision_calls + 3
    assert updated.state.budget.tool_calls == saved.state.budget.tool_calls + 1
    assert updated.state.continued_from_sha256
    assert updated.state.previous_conclusion.unresolved_questions == ["请补充配置。"]
    assert updated.trace.startswith(saved.trace)
    events = [json.loads(line) for line in updated.trace.splitlines()]
    assert any(e["event"] == "resume" for e in events)
    assert any(e["event"] == "tool" and e["details"].get("cached") for e in events)
    assert events[-1]["state"] == updated.state.model_dump(mode="json")
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert SavedSession.model_validate_json(updated.model_dump_json()) == updated
    assert len(saved.state.inputs) == 1


def test_scope_and_history_confirmation_are_required(saved):
    with pytest.raises(ValueError, match="核查"):
        continue_session(
            saved, appended(saved), history_reviewed=False, replay_model=model(need_info())
        )
    unrelated = confirm_materials(preview_uploads("different log", []))
    with pytest.raises(ValueError, match="追加"):
        continue_session(saved, unrelated, history_reviewed=True, replay_model=model(need_info()))
    preview = extend_review(saved.review, MaterialRegistry())
    with pytest.raises(ValueError, match="追加"):
        continue_session(saved, preview, history_reviewed=True, replay_model=model(need_info()))


def test_new_allowance_and_incomplete_usage_remain_explicit(saved):
    saved.state.budget.usage_complete = False
    saved.trace = ""
    updated = continue_session(
        saved,
        saved.review,
        history_reviewed=True,
        replay_model=model(need_info()),
        allowance=Budget(max_decision_calls=1, max_tool_calls=1),
    )
    assert updated.state.budget.max_decision_calls == saved.state.budget.decision_calls + 1
    assert not updated.state.budget.usage_complete
    assert json.loads(updated.trace.splitlines()[0])["event"] == "checkpoint"
    assert updated.state.budget.elapsed_ms >= saved.state.budget.elapsed_ms


def test_live_trace_rejects_nonempty_stream_before_running(saved):
    with pytest.raises(ValueError, match="内存轨迹"):
        continue_session(
            saved,
            saved.review,
            history_reviewed=True,
            replay_model=model(need_info()),
            trace_stream=io.StringIO("old"),
        )


def test_new_aliases_do_not_collide_with_saved_aliases():
    original = confirm_materials(
        preview_uploads("ValueError: /home/alice/model token=firstsecret", [])
    )
    extra = MaterialRegistry()
    extra.register_bytes("more.log", b"ValueError: /home/bob/model token=secondsecret", "log")
    extended = extend_review(original, extra)
    assert extended.content.materials[0] == original.content.materials[0]
    assert "/redacted/home_001" in extended.content.materials[0].text
    assert "/redacted/home_002" in extended.content.materials[1].text
    assert "[REDACTED_SECRET_002]" in extended.content.materials[1].text
    assert extended.content.materials[1].artifact.artifact_id == "A002"
    assert extended.status == "preview"


def test_added_materials_keep_total_limit(saved):
    extra = MaterialRegistry()
    for i in range(10):
        extra.register_bytes(f"{i}.py", b"pass", "code")
    with pytest.raises(ValueError):
        extend_review(saved.review, extra)


def test_cloud_continuation_binds_new_scope_and_sends_history(saved, monkeypatch):
    import httpx

    from deepdebug.agent.schemas import CloudConsent

    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=dict(
                status="completed",
                usage=dict(input_tokens=100, output_tokens=40),
                output=[
                    dict(
                        type="message",
                        role="assistant",
                        content=[dict(type="output_text", text=json.dumps(need_info()))],
                    )
                ],
            ),
        )

    monkeypatch.setattr(
        "deepdebug.llm.openai.httpx.AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-credential")
    review = appended(saved)
    consent = CloudConsent(
        material_review_sha256=review.sha256,
        endpoint="https://example.com/v1/responses",
        model="test",
        confirmed_at=datetime.now(timezone.utc),
    )
    updated = continue_session(saved, review, history_reviewed=True, consent=consent)
    assert len(requests) == 1
    data = json.loads(requests[0]["input"][0]["content"])
    assert data["state"]["continued_from_sha256"] == updated.state.continued_from_sha256
    assert data["state"]["previous_conclusion"]["unresolved_questions"] == ["请补充配置。"]
    assert len(data["state"]["inputs"]) == 2
    assert updated.state.budget.tokens_used == saved.state.budget.tokens_used + 140
    assert updated.state.cloud_consent == consent
    wrong = consent.model_copy(update={"material_review_sha256": saved.review.sha256})
    with pytest.raises(ValueError):
        continue_session(saved, review, history_reviewed=True, consent=wrong)
    assert len(requests) == 1


def test_cli_append_confirm_continue(saved, tmp_path, capsys):
    from deepdebug.cli import main
    from deepdebug.security.review import load_review, save_review
    from deepdebug.sessions import SessionStore

    store = SessionStore(tmp_path / "sessions")
    key = store.save(saved)
    additions = tmp_path / "additions"
    additions.mkdir()
    (additions / "extra.log").write_text("ValueError: supplementary details")
    preview_path, confirmed_path = tmp_path / "preview.json", tmp_path / "reviewed.json"
    args = ["--directory", str(store.root), "--session", key]
    assert (
        main(
            [
                "extend-preview",
                *args,
                "--root",
                str(additions),
                "--log",
                "extra.log",
                "--output",
                str(preview_path),
            ]
        )
        == 0
    )
    confirmed = confirm_materials(load_review(preview_path))
    save_review(confirmed_path, confirmed)
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps([dict(decision=need_info())]))
    resume = ["continue", *args, "--reviewed", str(confirmed_path), "--responses", str(responses)]
    assert main(resume) == 2
    assert store.load(key).state == saved.state
    assert main([*resume, "--review-history"]) == 0
    updated = store.load(key)
    assert len(updated.state.inputs) == 2
    assert updated.state.budget.decision_calls == saved.state.budget.decision_calls + 1


@pytest.mark.parametrize("had_snapshot", [False, True])
def test_environment_cache_rechecks_changed_snapshot_binding(had_snapshot):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    snapshot = (root / "benchmark/dev/dep_002/materials/target_snapshot.json").read_bytes()
    initial_files = [("target.json", snapshot, "snapshot")] if had_snapshot else []
    review = confirm_materials(preview_uploads("ModuleNotFoundError: pydantic", initial_files))
    inspect = dict(
        observation="检查故障解释器。",
        hypotheses=[],
        action=dict(
            action="tool",
            tool="inspect_environment",
            purpose="读取目标快照。",
            arguments=dict(environment_id="ENV_EMPTY", probe_ids=["python_identity"]),
        ),
    )
    trace = io.StringIO()
    state = replay_reviewed(review, model(inspect, need_info()), trace_stream=trace)
    assert state.tool_history[-1].result.status == ("ok" if had_snapshot else "denied")
    saved = SavedSession(
        saved_at=datetime.now(timezone.utc), state=state, review=review, trace=trace.getvalue()
    )
    additions = MaterialRegistry()
    additions.register_bytes("new.json", snapshot, "snapshot")
    extended = confirm_materials(extend_review(review, additions))
    updated = continue_session(
        saved, extended, history_reviewed=True, replay_model=model(inspect, need_info())
    )
    latest = updated.state.tool_history[-1]
    assert latest.result.status == ("denied" if had_snapshot else "ok")
    assert len(updated.state.tool_history) == len(state.tool_history) + 1
    assert updated.state.tool_history[: len(state.tool_history)] == state.tool_history
    if had_snapshot:
        assert updated.state.target_environment is None
    else:
        assert updated.state.target_environment.environment_id == "ENV_EMPTY"
