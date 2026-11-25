"""Compare request scopes and preserve failures without paid model calls."""

import json
from pathlib import Path

import httpx
import pytest

from deepdebug.agent.state import Budget
from deepdebug.evaluation.baselines import BASELINE_INSTRUCTIONS
from deepdebug.evaluation.runner import code_version, execute, load_plan, prepare, run_task
from deepdebug.security.review import confirm_materials, load_review

ROOT = Path(__file__).resolve().parents[1] / "benchmark"
ENDPOINT = "https://example.test/v1/responses"


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setattr("deepdebug.evaluation.runner.code_version", lambda: "frozen-code")
    monkeypatch.setenv("OPENAI_API_KEY", "test-evaluation-key")
    folder = tmp_path / "evaluation"
    plan = prepare(
        ROOT,
        folder,
        split="dev",
        model="fixed-model",
        endpoint=ENDPOINT,
        budget=Budget(max_tokens=200_000),
    )
    return folder, plan


def mock_http(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        "deepdebug.llm.openai.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def response(answer):
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "usage": {"input_tokens": 123, "output_tokens": 45},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(answer)}],
                }
            ],
        },
    )


BASELINE_ANSWER = {
    "summary": "需要更多信息",
    "category": "dependency",
    "root_causes": [],
    "fixes": [],
    "unresolved_questions": ["缺少实际启动配置"],
}
AGENT_ANSWER = {
    "observation": "需要更多信息",
    "hypotheses": [],
    "action": {"action": "need_info", "questions": ["缺少实际启动配置"], "reason": "证据不足"},
}


def test_three_approaches_have_correct_scopes_and_usage(bundle, monkeypatch):
    folder, plan = bundle
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return response(
            BASELINE_ANSWER if payload["instructions"] == BASELINE_INSTRUCTIONS else AGENT_ANSWER
        )

    mock_http(monkeypatch, handler)
    assert execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=3) == 3
    b0, b1, agent = [json.loads(p["input"][0]["content"]) for p in requests]
    assert {m["kind"] for m in b0["materials"]} == {"log"}
    assert "documents" not in b0
    assert {m["kind"] for m in b1["materials"]} >= {"log", "code", "config", "snapshot"}
    assert len(b1["documents"]) == 15
    assert "state" in agent and "materials" not in agent
    assert all("gold" not in json.dumps(p) for p in requests)
    for approach in ["B0", "B1", "A"]:
        result = json.loads((folder / f"dep_001.{approach}/result.json").read_text())
        assert (result["input_tokens"], result["output_tokens"]) == (123, 45)
        assert result["usage_complete"] is True
        assert result["report"] is not None
        assert result["estimated_cost_usd"] is None
        assert (folder / f"dep_001.{approach}/trace.jsonl").stat().st_size > 0


@pytest.mark.parametrize(
    "reviewed,endpoint,model",
    [
        (False, ENDPOINT, "fixed-model"),
        (True, "https://other.test/v1/responses", "fixed-model"),
        (True, ENDPOINT, "other-model"),
    ],
)
def test_missing_or_wrong_authorization_never_sends(bundle, monkeypatch, reviewed, endpoint, model):
    mock_http(monkeypatch, lambda request: pytest.fail("unexpected request"))
    with pytest.raises(ValueError, match="explicit"):
        execute(bundle[0], ROOT, reviewed=reviewed, send_to=endpoint, model=model)


def test_failed_baseline_retains_unknown_usage_and_is_not_retried(bundle, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, text="private provider body")

    mock_http(monkeypatch, handler)
    folder, plan = bundle
    execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=1)
    result = json.loads((folder / "dep_001.B0/result.json").read_text())
    assert result["failure"] == "unavailable" and result["usage_complete"] is False
    assert "private provider body" not in json.dumps(result)
    execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=1)
    assert len(calls) == 2 and (folder / "dep_001.B1/result.json").exists()


def test_plan_changes_after_start_are_rejected(bundle, monkeypatch):
    mock_http(monkeypatch, lambda request: response(BASELINE_ANSWER))
    folder, plan = bundle
    execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=1)
    path = folder / "plan.json"
    data = json.loads(path.read_text())
    data["model"] = "changed-model"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="after tasks started"):
        load_plan(folder, ROOT)


def test_changed_code_or_review_rejected(bundle, monkeypatch):
    folder, _ = bundle
    monkeypatch.setattr("deepdebug.evaluation.runner.code_version", lambda: "changed-code")
    with pytest.raises(ValueError, match="frozen code"):
        load_plan(folder, ROOT)
    monkeypatch.setattr("deepdebug.evaluation.runner.code_version", lambda: "frozen-code")
    path = folder / "dep_001.review.json"
    data = json.loads(path.read_text())
    data["content"]["materials"][0]["text"] = "changed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_plan(folder, ROOT)


def test_local_builtin_check_is_unavailable_in_frozen_evaluation(bundle, monkeypatch):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return response(
                {
                    "observation": "申请预置检查",
                    "hypotheses": [],
                    "action": {
                        "action": "tool",
                        "tool": "run_builtin_check",
                        "arguments": {"case_id": "dependency", "check_id": "before_fix"},
                        "purpose": "核查",
                    },
                }
            )
        return response(AGENT_ANSWER)

    mock_http(monkeypatch, handler)
    folder, plan = bundle
    review = confirm_materials(load_review(folder / "dep_001.review.json"))
    result, _ = run_task(review, plan, "A")
    assert result["state"]["tool_history"][-1]["result"]["status"] == "unavailable"
    assert result["input_tokens"] == 246


def test_interrupted_task_is_retained_and_resume_starts_next(bundle, monkeypatch):
    folder, plan = bundle

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("deepdebug.evaluation.runner.run_task", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=1)
    assert (folder / "dep_001.B0/started.json").exists()
    assert not (folder / "dep_001.B0/result.json").exists()


def test_invalid_baseline_keeps_usage_and_raw_response(bundle, monkeypatch):
    mock_http(monkeypatch, lambda request: response({"unsupported": "answer"}))
    folder, plan = bundle
    review = confirm_materials(load_review(folder / "dep_001.review.json"))
    result, trace = run_task(review, plan, "B0")
    assert result["failure"] == "invalid_report"
    assert result["input_tokens"] == 123 and result["usage_complete"]
    assert "unsupported" in trace


def test_test_plan_has_thirty_redacted_cases_and_no_gold(tmp_path, monkeypatch):
    monkeypatch.setattr("deepdebug.evaluation.runner.code_version", lambda: "frozen-code")
    folder = tmp_path / "test-evaluation"
    plan = prepare(
        ROOT,
        folder,
        split="test",
        model="fixed-model",
        endpoint=ENDPOINT,
        budget=Budget(max_tokens=200_000),
    )
    assert len(plan.cases) == 30
    assert len(list(folder.glob("*.review.json"))) == 30
    for path in folder.glob("*.review.json"):
        assert "sk-benchmark-fake-secret-123456789" not in path.read_text()
        assert "acceptable_root_causes" not in path.read_text()


def test_code_version_uses_loaded_checkout_when_cwd_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs["cwd"])

    monkeypatch.setattr("deepdebug.evaluation.runner.subprocess.run", run)

    def output(command, **kwargs):
        calls.append(kwargs["cwd"])
        return "checkout-sha\n"

    monkeypatch.setattr("deepdebug.evaluation.runner.subprocess.check_output", output)
    assert code_version() == "checkout-sha"
    assert set(calls) == {ROOT.parent}


def test_baseline_corpus_rejects_symlinks(tmp_path, monkeypatch):
    from deepdebug.evaluation.baselines import corpus_bytes
    from deepdebug.security.paths import MaterialError

    target = tmp_path / "outside.json"
    target.write_text("{}")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "documents.json").symlink_to(target)
    monkeypatch.setattr("deepdebug.tools.docs_search.CORPUS_ROOT", corpus)
    with pytest.raises(MaterialError):
        corpus_bytes()


def test_batch_rechecks_review_before_later_case(bundle, monkeypatch):
    from deepdebug.security.review import MaterialReview, ReviewContent, save_review

    folder, plan = bundle
    sent = []

    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            path = folder / "dep_002.review.json"
            original = load_review(path)
            content = original.content.model_dump()
            text = "RuntimeError: replaced after batch validation\n"
            content["materials"][0]["text"] = text
            content["materials"][0]["artifact"]["size_bytes"] = len(text.encode())
            content = ReviewContent.model_validate(content)
            path.unlink()
            save_review(path, MaterialReview(content=content, sha256=content.digest()))
        payload = json.loads(request.content)
        return response(
            BASELINE_ANSWER if payload["instructions"] == BASELINE_INSTRUCTIONS else AGENT_ANSWER
        )

    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match="during execution"):
        execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=4)
    assert len(sent) == 3


def test_agent_flushes_known_usage_before_interruption(bundle, monkeypatch):
    folder, plan = bundle
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response(
                {
                    "observation": "读取配置",
                    "hypotheses": [],
                    "action": {
                        "action": "tool",
                        "tool": "read_artifact",
                        "arguments": {"artifact_id": "A002", "start_line": 1, "max_lines": 10},
                        "purpose": "区分原因",
                    },
                }
            )
        raise KeyboardInterrupt()

    mock_http(monkeypatch, handler)
    review = confirm_materials(load_review(folder / "dep_001.review.json"))
    path = folder / "interrupted.jsonl"
    with path.open("x+") as stream, pytest.raises(KeyboardInterrupt):
        run_task(review, plan, "A", trace_stream=stream)
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(
        e["event"] == "model_response" and e["details"]["input_tokens"] == 123 for e in events
    )
    assert events[-1]["state"]["budget"]["tokens_used"] == 168
    assert events[-1]["state"]["tool_history"][-1]["tool"] == "read_artifact"


@pytest.mark.parametrize("approach", ["B0", "B1"])
def test_baseline_json_mode_requirement_is_present_in_user_message(bundle, monkeypatch, approach):
    def handler(request):
        payload = json.loads(request.content)
        if "json" not in payload["input"][0]["content"].lower():
            return httpx.Response(400, json={"error": {"type": "invalid_request_error"}})
        return response(BASELINE_ANSWER)

    mock_http(monkeypatch, handler)
    folder, plan = bundle
    review = confirm_materials(load_review(folder / "dep_001.review.json"))
    result, _ = run_task(review, plan, approach)
    assert result["failure"] is None
    assert result["report"] == BASELINE_ANSWER
