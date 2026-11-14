"""Outbound authorization and real adapter behavior with a local HTTP transport."""

import asyncio
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import httpx
import pytest

from deepdebug.agent.controller import Controller
from deepdebug.agent.decision import INSTRUCTIONS, Decision
from deepdebug.agent.schemas import CloudConsent
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.cli import main
from deepdebug.diagnosis import diagnose
from deepdebug.llm.client import ModelFailure, ModelRequest
from deepdebug.llm.openai import MAX_RESPONSE_BYTES, OpenAIResponsesClient
from deepdebug.security.outbound import OutboundBoundary
from deepdebug.security.redaction import Redactor
from deepdebug.security.review import (
    confirm_materials,
    preview_materials,
    reviewed_registry,
    save_review,
)
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://api.openai.com/v1/responses"
KEY = "fake-provider-credential-for-test"


def need_info():
    return {
        "observation": "缺少环境信息。",
        "hypotheses": [],
        "action": {"action": "need_info", "questions": ["请补充环境快照。"], "reason": "环境未知"},
    }


def response(decision=None, **changes):
    return {
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 40},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(decision or need_info())}],
            }
        ],
        **changes,
    }


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / "log.txt").write_text(
        "API_KEY='private-material-secret'\n"
        '  File "/home/alice/train.py", line 3, in <module>\n'
        "ModuleNotFoundError: No module named 'torch'\n",
        encoding="utf-8",
    )
    (tmp_path / "code.py").write_text("raise RuntimeError('unread-code-must-not-be-sent')\n")
    preview = preview_materials(tmp_path, "log.txt", ["code.py"], [], [])
    return confirm_materials(preview)


def consent(review):
    return CloudConsent(
        material_review_sha256=review.sha256,
        endpoint=ENDPOINT,
        model="test-model",
        confirmed_at=datetime.now(timezone.utc),
    )


def client_request(review):
    permission = consent(review)
    session = CollectionSession(reviewed_registry(review))
    session.state = DiagnosisState.model_validate(
        {
            **session.state.model_dump(),
            "material_review_sha256": review.sha256,
            "cloud_consent": permission,
        }
    )
    dispatcher = ToolDispatcher(session)
    client = OpenAIResponsesClient(OutboundBoundary(review, permission, dispatcher))
    session.parse_log("A001")
    request = ModelRequest(
        instructions=INSTRUCTIONS,
        state=session.state,
        environments=dispatcher.environments,
        path_reference_ids=[],
        response_schema=Decision.model_json_schema(),
        timeout_seconds=1,
        max_tokens=45_000,
    )
    return client, request


@pytest.fixture
def http(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def install(handler):
        async def capture(request):
            requests.append(request)
            value = handler(request)
            return await value if asyncio.iscoroutine(value) else value

        def factory(**kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False
            return original(transport=httpx.MockTransport(capture), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return requests

    return install


def test_adapter_sends_reviewed_excerpts_and_keeps_authorization_local(reviewed, http):
    requests = http(lambda _: httpx.Response(200, json=response()))
    trace = io.StringIO()
    state = diagnose(reviewed, consent(reviewed), trace_stream=trace)
    assert state.stop_reason == "need_info"
    assert state.budget.tokens_used == 140
    assert state.budget.usage_complete
    assert state.cloud_consent == consent(reviewed).model_copy(
        update={"confirmed_at": state.cloud_consent.confirmed_at}
    )
    assert len(requests) == 1
    sent = requests[0]
    assert str(sent.url) == ENDPOINT
    assert sent.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(sent.content)
    assert body["store"] is False
    assert body["text"] == {"format": {"type": "json_object"}}
    assert body["model"] == "test-model"
    assert 16 <= body["max_output_tokens"] <= 4096
    assert body["instructions"] == INSTRUCTIONS
    assert "ModuleNotFoundError" in body["input"][0]["content"]
    for secret in (KEY, "private-material-secret", "/home/alice", "unread-code-must-not-be-sent"):
        assert secret not in sent.content.decode()
        assert secret not in trace.getvalue()
        assert secret not in state.model_dump_json()
    events = [json.loads(line) for line in trace.getvalue().splitlines()]
    assert events[0]["details"]["mode"] == "remote"
    assert DiagnosisState.model_validate(events[-1]["state"]) == state
    assert state.report.verifications[0].status == "未执行"


def test_four_turn_hypothesis_update_uses_real_tools_with_http_fixture(monkeypatch, http):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    preview = preview_materials(
        ROOT / "benchmark/dev/dep_002/materials",
        "log.txt",
        [],
        ["launch.json"],
        ["target_snapshot.json", "project_snapshot.json"],
    )
    review = confirm_materials(preview)
    turns = iter(json.loads((ROOT / "examples/dep_002_replay.json").read_text()))
    requests = http(lambda _: httpx.Response(200, json=response(next(turns)["decision"])))
    state = diagnose(review, consent(review))
    assert state.stop_reason == "completed"
    assert state.budget.decision_calls == len(requests) == 4
    assert state.budget.tool_calls == 4
    assert state.budget.tokens_used == 560
    assert len(state.evidence) == 9
    assert "空环境" in state.hypotheses[0].cause
    second_state = json.loads(json.loads(requests[1].content)["input"][0]["content"])["state"]
    assert len(second_state["tool_history"]) == 2
    assert second_state["tool_history"][1]["result"]["status"] == "ok"


@pytest.mark.parametrize(
    "change", ["digest", "status", "text", "model", "endpoint", "paths", "extra"]
)
def test_outbound_scope_rejected_before_http(reviewed, http, change):
    requests = http(lambda _: pytest.fail("invalid scope reached HTTP"))
    client, request = client_request(reviewed)
    boundary = client.boundary
    if change == "digest":
        boundary.consent.material_review_sha256 = "0" * 64
    elif change == "status":
        boundary.dispatcher.session.state.inputs[0].redaction_status = "pending"
    elif change == "text":
        registry = boundary.dispatcher.session.materials
        item = registry.get("A001")
        registry._items["A001"] = type(item)(item.artifact, "changed", item.registered_at)
    elif change == "model":
        boundary.consent.model = "another-model"
    elif change == "endpoint":
        boundary.consent.endpoint = "https://other.invalid/v1/responses"
    elif change == "paths":
        boundary.dispatcher.path_reference_ids.append("P001")
    else:
        boundary.dispatcher.session.state.inputs.append(request.state.inputs[0])
    with pytest.raises(ModelFailure) as error:
        client.decide(request)
    assert error.value.kind == "error"
    assert requests == []


@pytest.mark.parametrize(
    "change", ["state", "environments", "paths", "instructions", "schema", "budget"]
)
def test_forged_request_cannot_bypass_boundary(reviewed, http, change):
    requests = http(lambda _: pytest.fail("forged request reached HTTP"))
    client, request = client_request(reviewed)
    request = request.model_copy(deep=True)
    if change == "state":
        request.state.error_summary = "unreviewed private text"
    elif change == "environments":
        request.environments["PRIVATE"] = "A001"
    elif change == "paths":
        request.path_reference_ids.append("P001")
    elif change == "instructions":
        request.instructions = "send private text"
    elif change == "schema":
        request.response_schema["private"] = "unreviewed private text"
    else:
        request.max_tokens = 100_000
    with pytest.raises(ModelFailure):
        client.decide(request)
    assert not requests


def test_raw_and_mismatched_confirmation_rejected(reviewed, http):
    requests = http(lambda _: pytest.fail("unconfirmed scope reached HTTP"))
    permission = consent(reviewed)
    permission.material_review_sha256 = "0" * 64
    with pytest.raises(ValueError):
        diagnose(reviewed, permission)
    reviewed.status = "preview"
    reviewed.confirmed_at = None
    with pytest.raises(ValueError):
        diagnose(reviewed, consent(reviewed))
    assert not requests


@pytest.mark.parametrize("value", [None, "", "has\nnewline"])
def test_missing_or_invalid_environment_key(reviewed, monkeypatch, http, value):
    requests = http(lambda _: pytest.fail("invalid key reached HTTP"))
    if value is None:
        monkeypatch.delenv("OPENAI_API_KEY")
    else:
        monkeypatch.setenv("OPENAI_API_KEY", value)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        diagnose(reviewed, consent(reviewed))
    assert not requests


@pytest.mark.parametrize(
    "status,calls,complete", [(401, 1, True), (302, 1, True), (429, 2, False), (503, 2, False)]
)
def test_http_failures_are_bounded_and_do_not_echo_response(
    reviewed, http, status, calls, complete
):
    requests = http(
        lambda _: httpx.Response(status, text=KEY, headers={"Location": "https://evil.invalid"})
    )
    trace = io.StringIO()
    state = diagnose(reviewed, consent(reviewed), trace_stream=trace)
    assert state.stop_reason == "model_error"
    assert len(requests) == state.budget.decision_calls == calls
    assert state.budget.usage_complete is complete
    assert KEY not in trace.getvalue()


@pytest.mark.parametrize(
    "case", ["missing", "negative", "bool", "null", "invalid_json", "oversized"]
)
def test_invalid_response_usage_is_not_silently_zero(reviewed, http, case):
    raw = response()
    if case == "missing":
        del raw["usage"]["input_tokens"]
    elif case == "negative":
        raw["usage"]["output_tokens"] = -1
    elif case == "bool":
        raw["usage"]["input_tokens"] = True
    elif case == "null":
        raw["usage"] = None
    if case == "invalid_json":
        http(lambda _: httpx.Response(200, text="not JSON"))
    elif case == "oversized":
        http(lambda _: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
    else:
        http(lambda _: httpx.Response(200, json=raw))
    state = diagnose(reviewed, consent(reviewed))
    assert state.stop_reason == "model_error"
    assert state.budget.tokens_used == 0
    assert not state.budget.usage_complete
    assert state.budget.decision_calls == 1


@pytest.mark.parametrize("case", ["refusal", "incomplete", "failed", "malformed", "tool_call"])
def test_non_decisions_retain_usage_without_executing_actions(reviewed, http, case):
    raw = response()
    if case == "refusal":
        raw["output"][0]["content"] = [{"type": "refusal", "refusal": KEY}]
    elif case in {"incomplete", "failed"}:
        raw["status"] = case
    elif case == "malformed":
        raw["output"] = None
    else:
        raw["output"] = [{"type": "function_call", "name": "shell", "arguments": "rm"}]
    requests = http(lambda _: httpx.Response(200, json=raw))
    state = diagnose(reviewed, consent(reviewed))
    assert state.stop_reason == "model_error"
    assert state.budget.tokens_used == 140
    assert state.budget.usage_complete
    assert len(requests) == state.budget.tool_calls == 1
    assert KEY not in state.model_dump_json()


def test_response_secrets_are_removed_before_trace_and_followup(reviewed, http):
    call = 0

    def handler(_):
        nonlocal call
        call += 1
        if call == 1:
            decision = {
                "observation": f"API_KEY='{KEY}' /home/private/model",
                "hypotheses": [],
                "action": {
                    "action": "tool",
                    "tool": "read_artifact",
                    "arguments": {"artifact_id": "A002"},
                    "purpose": f"token='model-secret' {KEY}",
                },
            }
        else:
            decision = need_info()
        return httpx.Response(200, json=response(decision))

    requests = http(handler)
    trace = io.StringIO()
    state = diagnose(reviewed, consent(reviewed), trace_stream=trace)
    assert len(requests) == 2
    for private in (KEY, "model-secret", "/home/private"):
        assert private not in trace.getvalue()
        assert private not in state.model_dump_json()
        assert private not in requests[1].content.decode()


def test_boundary_rescans_tool_results_and_escaped_json(reviewed, http):
    requests = http(lambda _: httpx.Response(200, json=response()))
    client, request = client_request(reviewed)
    # A known credential returned by an internal tool is masked again at the wire boundary.
    request.correction = json.dumps({"password": "new-tool-secret", "echo": KEY})
    client.decide(request)
    assert "new-tool-secret" not in requests[0].content.decode()
    assert KEY not in requests[0].content.decode()


def test_insufficient_input_output_allowance_makes_no_request(reviewed, http):
    requests = http(lambda _: pytest.fail("over-budget input reached HTTP"))
    state = diagnose(reviewed, consent(reviewed), budget=Budget(max_tokens=5010))
    assert state.stop_reason == "budget_exhausted"
    assert state.budget.tokens_used == 0
    assert state.budget.usage_complete
    assert not requests


def test_reported_over_budget_usage_stops_before_action(reviewed, http):
    requests = http(
        lambda _: httpx.Response(
            200, json=response(usage={"input_tokens": 50_000, "output_tokens": 40})
        )
    )
    state = diagnose(reviewed, consent(reviewed))
    assert state.stop_reason == "budget_exhausted"
    assert state.budget.tokens_used == 50_040
    assert state.budget.tool_calls == len(requests) == 1


def test_wall_timeout_cancels_http_before_late_response(reviewed, http):
    cancelled = []

    async def slow(_):
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.append(True)
        return httpx.Response(200, json=response())

    http(slow)
    client, request = client_request(reviewed)
    request.timeout_seconds = 0.05
    started = monotonic()
    with pytest.raises(ModelFailure) as error:
        client.decide(request)
    assert error.value.kind == "timeout"
    assert error.value.usage_unknown
    assert cancelled == [True]
    assert monotonic() - started < 1


def test_transport_retry_records_unknown_usage(reviewed, http):
    def failed(request):
        raise httpx.ConnectError(KEY, request=request)

    requests = http(failed)
    trace = io.StringIO()
    state = diagnose(reviewed, consent(reviewed), trace_stream=trace)
    assert state.stop_reason == "model_error"
    assert not state.budget.usage_complete
    assert len(requests) == 2
    assert KEY not in trace.getvalue()


def test_invalid_decision_repair_uses_same_authorized_boundary(reviewed, http):
    count = 0

    def handler(_):
        nonlocal count
        count += 1
        raw = response()
        if count == 1:
            raw["output"][0]["content"][0]["text"] = "{}"
        return httpx.Response(200, json=raw)

    requests = http(handler)
    state = diagnose(reviewed, consent(reviewed))
    assert state.stop_reason == "need_info"
    assert state.budget.tokens_used == 280
    second = json.loads(json.loads(requests[1].content)["input"][0]["content"])
    assert second["correction"]


def test_cli_requires_external_consent_and_reports_full_state(reviewed, tmp_path, http, capsys):
    path = tmp_path / "reviewed.json"
    trace = tmp_path / "trace.jsonl"
    save_review(path, reviewed)
    args = [
        "diagnose",
        "--reviewed",
        str(path),
        "--model",
        "test-model",
    ]
    requests = http(lambda _: httpx.Response(200, json=response()))
    with pytest.raises(SystemExit):
        main(args)
    assert not requests
    capsys.readouterr()
    assert main([*args, "--send-to", ENDPOINT, "--trace", str(trace)]) == 0
    output = capsys.readouterr()
    state = DiagnosisState.model_validate_json(output.out)
    assert "材料范围" in output.err and ENDPOINT in output.err
    assert state.cloud_consent.material_review_sha256 == reviewed.sha256
    assert state.stop_reason == "need_info"
    assert trace.exists()
    assert main([*args, "--send-to", ENDPOINT, "--trace", str(trace)]) == 2
    assert len(requests) == 1


def test_redaction_is_stable_for_review_placeholders():
    text = '{"api_key":"[REDACTED_SECRET_002]", "home":"/redacted/home_001"}'
    assert Redactor([text]).redact(text) == text


def test_remote_client_cannot_be_reused_for_another_dispatcher(reviewed):
    client, _ = client_request(reviewed)
    other = ToolDispatcher(CollectionSession(reviewed_registry(reviewed)))
    with pytest.raises(ValueError):
        Controller(other, client)


@pytest.mark.parametrize(
    "base_url,env_url,send_to,expected",
    [
        (None, None, ENDPOINT, ENDPOINT),
        (
            "https://gateway.example/api/v1/",
            None,
            "https://gateway.example/api/v1/responses",
            "https://gateway.example/api/v1/responses",
        ),
        (
            None,
            "https://gateway.example/v1",
            "https://gateway.example/v1/responses",
            "https://gateway.example/v1/responses",
        ),
        (
            "https://chosen.example/v1",
            "https://env.example/v1",
            "https://chosen.example/v1/responses",
            "https://chosen.example/v1/responses",
        ),
        (
            "https://chosen.example/v1",
            "invalid-env-url",
            "https://chosen.example/v1/responses",
            "https://chosen.example/v1/responses",
        ),
        (
            "https://GATEWAY.example:443/v1/",
            None,
            "https://gateway.example/v1/responses/",
            "https://gateway.example/v1/responses",
        ),
        (
            "http://localhost:8000/v1",
            None,
            "http://localhost:8000/v1/responses",
            "http://localhost:8000/v1/responses",
        ),
        (
            "http://[::1]:8000",
            None,
            "http://[::1]:8000/responses",
            "http://[::1]:8000/responses",
        ),
    ],
)
def test_cli_custom_base_url_routing_and_consent(
    reviewed, tmp_path, monkeypatch, http, capsys, base_url, env_url, send_to, expected
):
    path = tmp_path / "reviewed.json"
    trace = tmp_path / "trace.jsonl"
    save_review(path, reviewed)
    if env_url is not None:
        monkeypatch.setenv("OPENAI_BASE_URL", env_url)
    args = [
        "diagnose",
        "--reviewed",
        str(path),
        "--model",
        "custom-model",
        "--send-to",
        send_to,
        "--trace",
        str(trace),
    ]
    if base_url is not None:
        args.extend(["--base-url", base_url])
    requests = http(lambda _: httpx.Response(200, json=response()))
    assert main(args) == 0
    state = DiagnosisState.model_validate_json(capsys.readouterr().out)
    assert state.cloud_consent.endpoint == expected
    assert state.cloud_consent.model == "custom-model"
    assert state.stop_reason == "need_info"
    assert len(requests) == 1
    assert str(requests[0].url) == expected
    assert requests[0].headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(requests[0].content)
    assert body["model"] == "custom-model"
    assert body["text"]["format"]["type"] == "json_object"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert all(event["state"]["cloud_consent"]["endpoint"] == expected for event in events)


@pytest.mark.parametrize(
    "base_url,send_to",
    [
        ("https://gateway.example/v1", ENDPOINT),
        ("https://gateway.example/v2", "https://gateway.example/v1/responses"),
        ("http://gateway.example/v1", "https://gateway.example/v1/responses"),
        ("https://gateway.example:8443/v1", "https://gateway.example/v1/responses"),
        ("https://gateway.example/v1/responses", "https://gateway.example/v1/responses"),
        ("", ENDPOINT),
        ("gateway.example/v1", ENDPOINT),
        ("ftp://gateway.example/v1", ENDPOINT),
        ("https://gateway.example/v1?key=private-url-secret", ENDPOINT),
        ("https://gateway.example/v1#private-url-secret", ENDPOINT),
        ("https://user:private-url-secret@gateway.example/v1", ENDPOINT),
        ("https://gateway.example/\nv1", ENDPOINT),
        ("https://api.openai.com/v1", ENDPOINT + "?key=private-url-secret"),
        (
            "https://api.openai.com/v1",
            "https://user:private-url-secret@api.openai.com/v1/responses",
        ),
        ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
    ],
)
def test_cli_rejects_invalid_or_unconfirmed_destination_before_http(
    reviewed, tmp_path, http, capsys, base_url, send_to
):
    path = tmp_path / "reviewed.json"
    trace = tmp_path / "trace.jsonl"
    save_review(path, reviewed)
    requests = http(lambda _: pytest.fail("unconfirmed destination reached HTTP"))
    assert (
        main(
            [
                "diagnose",
                "--reviewed",
                str(path),
                "--model",
                "custom-model",
                "--base-url",
                base_url,
                "--send-to",
                send_to,
                "--trace",
                str(trace),
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert not output.out
    assert "private-url-secret" not in output.err
    assert not requests
    assert not trace.exists()


def test_custom_destination_does_not_follow_redirect(reviewed, http):
    permission = consent(reviewed)
    permission.endpoint = "https://gateway.example/v1/responses"
    requests = http(lambda _: httpx.Response(307, headers={"Location": ENDPOINT}))
    state = diagnose(reviewed, permission)
    assert state.stop_reason == "model_error"
    assert len(requests) == 1
    assert str(requests[0].url) == permission.endpoint


def test_boundary_uses_revalidated_canonical_destination(reviewed, http):
    requests = http(lambda _: httpx.Response(200, json=response()))
    client, request = client_request(reviewed)
    client.boundary.consent.endpoint = "https://API.OPENAI.COM:443/v1/responses/"
    client.decide(request)
    assert str(requests[0].url) == ENDPOINT
    assert client.boundary.consent.endpoint == request.state.cloud_consent.endpoint


@pytest.mark.parametrize("environment_override", [False, True])
def test_cli_loads_dotenv_with_environment_priority(
    reviewed, tmp_path, monkeypatch, http, capsys, environment_override
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="file-test-key"\nOPENAI_BASE_URL=https://file.example/v1\n',
        encoding="utf-8",
    )
    key, base = "file-test-key", "https://file.example/v1"
    if environment_override:
        key, base = KEY, "https://environment.example/v1"
        monkeypatch.setenv("OPENAI_API_KEY", key)
        monkeypatch.setenv("OPENAI_BASE_URL", base)
    path = tmp_path / "reviewed.json"
    save_review(path, reviewed)
    requests = http(lambda _: httpx.Response(200, json=response()))
    assert (
        main(
            [
                "diagnose",
                "--reviewed",
                str(path),
                "--model",
                "test-model",
                "--send-to",
                base + "/responses",
            ]
        )
        == 0
    )
    assert len(requests) == 1
    assert str(requests[0].url) == base + "/responses"
    assert requests[0].headers["Authorization"] == f"Bearer {key}"
    output = capsys.readouterr()
    assert key not in output.out + output.err
