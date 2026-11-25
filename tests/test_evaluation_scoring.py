"""Score provenance, denominators, result binding and incomplete-run accounting."""

import json

import pytest
from test_evaluation_runner import (
    AGENT_ANSWER,
    BASELINE_ANSWER,
    BASELINE_INSTRUCTIONS,
    ENDPOINT,
    ROOT,
    mock_http,
    response,
)
from test_evaluation_runner import (
    bundle as bundle,
)

from deepdebug.evaluation.runner import execute
from deepdebug.evaluation.scoring import SemanticScore, distribution, prepare_scores, summarize


def fill_score(**changes):
    return {
        "reviewer": "test-human-fixture",
        "attested_human": True,
        "classification_correct": True,
        "root_cause_correct": True,
        "fix_feasible": True,
        "evidence_supported": 1,
        "evidence_total": 2,
        "rationale": "Test scoring fixture.",
        **changes,
    }


@pytest.fixture
def completed(bundle, monkeypatch):
    folder, plan = bundle

    def handler(request):
        payload = json.loads(request.content)
        return response(
            BASELINE_ANSWER if payload["instructions"] == BASELINE_INSTRUCTIONS else AGENT_ANSWER
        )

    mock_http(monkeypatch, handler)
    execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model)
    scores = folder / "scores.json"
    prepare_scores(folder, scores)
    return folder, scores


def test_pending_runs_keep_full_denominator(bundle):
    folder, _ = bundle
    scores = folder / "scores.json"
    prepare_scores(folder, scores)
    summary = summarize(folder, scores)
    assert summary["scoring"] == "pending"
    for result in summary["approaches"].values():
        assert result["not_started"] == 10
        assert result["root_cause_correct"] == {
            "numerator": 0,
            "denominator": 10,
            "value": None,
            "ready": False,
        }
        assert result["estimated_cost_usd"]["count"] == 0


def test_human_scores_produce_separate_provenance_and_claim_denominators(completed):
    folder, scores = completed
    data = json.loads(scores.read_text())
    for row in data["rows"]:
        row["score"] = fill_score()
    data["rows"][0]["score"]["root_cause_correct"] = False
    scores.write_text(json.dumps(data))
    summary = summarize(folder, scores)
    b0 = summary["approaches"]["B0"]
    assert b0["root_cause_correct"]["value"] == 0.9
    assert b0["evidence_support"] == {
        "numerator": 10,
        "denominator": 20,
        "value": 0.5,
        "ready": True,
    }
    assert b0["complete_tokens"]["median"] == 168
    assert b0["complete_input_tokens"]["median"] == 123
    assert b0["complete_output_tokens"]["p95"] == 45
    assert b0["estimated_cost_usd"]["count"] == 0
    assert summary["provenance"]["captured"]["B0"]["planned"] == 9
    assert summary["provenance"]["synthetic"]["B0"]["planned"] == 1


def test_partial_scoring_does_not_publish_accuracy(completed):
    folder, scores = completed
    data = json.loads(scores.read_text())
    data["rows"][0]["score"] = fill_score()
    scores.write_text(json.dumps(data))
    b0 = summarize(folder, scores)["approaches"]["B0"]
    assert b0["human_scored"] == 1
    assert b0["root_cause_correct"]["value"] is None
    assert b0["root_cause_correct"]["denominator"] == 10


@pytest.mark.parametrize("mixed", [False, True])
def test_ai_scores_keep_source_and_denominators(completed, mixed):
    folder, scores = completed
    data = json.loads(scores.read_text())
    for row in data["rows"]:
        row["score"] = fill_score(
            reviewer="test-ai-fixture",
            reviewer_kind="ai",
            reviewer_model="test-model-v1",
            attested_human=False,
        )
    if mixed:
        data["rows"][0]["score"] = fill_score()
    scores.write_text(json.dumps(data))
    summary = summarize(folder, scores)
    assert summary["scoring"] == ("mixed" if mixed else "ai")
    b0 = summary["approaches"]["B0"]
    assert b0["scored"] == 10
    assert b0["human_scored"] == int(mixed)
    assert b0["ai_scored"] == 10 - int(mixed)
    assert b0["root_cause_correct"]["value"] == 1
    assert b0["root_cause_correct"]["denominator"] == 10


def test_partial_ai_scores_do_not_publish_accuracy(completed):
    folder, scores = completed
    data = json.loads(scores.read_text())
    data["rows"][0]["score"] = fill_score(
        reviewer="test-ai-fixture",
        reviewer_kind="ai",
        reviewer_model="test-model-v1",
        attested_human=False,
    )
    scores.write_text(json.dumps(data))
    summary = summarize(folder, scores)
    assert summary["scoring"] == "pending"
    b0 = summary["approaches"]["B0"]
    assert b0["ai_scored"] == 1
    assert b0["human_scored"] == 0
    assert b0["root_cause_correct"]["value"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewer_kind": "ai", "reviewer_model": "model"},
        {"reviewer_kind": "ai", "attested_human": False},
        {"reviewer_model": "model"},
        {"second_reviewer_kind": "ai", "second_reviewer_model": "model"},
        {"second_reviewer": "peer", "second_reviewer_kind": "ai"},
        {"second_reviewer": "peer", "second_reviewer_model": "model"},
    ],
)
def test_inconsistent_reviewer_provenance_rejected(changes):
    with pytest.raises(ValueError):
        SemanticScore.model_validate(fill_score(disagreement_and_resolution="fixture", **changes))


@pytest.mark.parametrize("kind", ["human", "ai"])
def test_secondary_review_kind_is_preserved(kind):
    score = SemanticScore.model_validate(
        fill_score(
            second_reviewer="peer-fixture",
            second_reviewer_kind=kind,
            second_reviewer_model="peer-model" if kind == "ai" else None,
            disagreement_and_resolution="Independent fixture review agrees.",
        )
    )
    assert score.second_reviewer_kind == kind
    assert score.second_reviewer_model == ("peer-model" if kind == "ai" else None)


def test_changed_results_invalidate_existing_scores(completed):
    folder, scores = completed
    path = folder / "dep_001.B0/result.json"
    data = json.loads(path.read_text())
    data["wall_time_s"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="changed after"):
        summarize(folder, scores)


@pytest.mark.parametrize(
    "changes", [{"attested_human": False}, {"evidence_supported": 3}, {"second_reviewer": "peer"}]
)
def test_invalid_human_scores_rejected(changes):
    with pytest.raises(ValueError):
        SemanticScore.model_validate(fill_score(**changes))


def test_duplicate_rows_cannot_reduce_denominator(completed):
    folder, scores = completed
    data = json.loads(scores.read_text())
    data["rows"][1] = data["rows"][0]
    scores.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="inventory"):
        summarize(folder, scores)


def test_unstarted_case_cannot_be_scored(bundle):
    folder, _ = bundle
    scores = folder / "scores.json"
    prepare_scores(folder, scores)
    data = json.loads(scores.read_text())
    data["rows"][0]["score"] = fill_score()
    scores.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unfinished"):
        summarize(folder, scores)


def test_failed_tasks_keep_unknown_usage_and_full_denominator(bundle, monkeypatch):
    import httpx

    folder, plan = bundle
    mock_http(monkeypatch, lambda request: httpx.Response(503))
    execute(folder, ROOT, reviewed=True, send_to=ENDPOINT, model=plan.model, limit=1)
    scores = folder / "scores.json"
    prepare_scores(folder, scores)
    summary = summarize(folder, scores)
    b0 = summary["approaches"]["B0"]
    assert b0["failed"] == 1 and b0["not_started"] == 9
    assert b0["usage_complete_tasks"] == 0
    assert b0["complete_tokens"]["median"] is None
    assert b0["root_cause_correct"]["denominator"] == 10
    data = json.loads(scores.read_text())
    data["rows"][0]["score"] = fill_score()
    scores.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="missing reports"):
        summarize(folder, scores)


def test_nearest_rank_percentile():
    result = distribution(list(range(1, 21)))
    assert result == {"count": 20, "mean": 10.5, "median": 10.5, "p95": 19}


def test_interrupted_trace_preserves_known_usage_and_binds_scores(completed):
    folder, _ = completed
    (folder / "dep_001.A/result.json").unlink()
    scores = folder / "interrupted-scores.json"
    prepare_scores(folder, scores)
    summary = summarize(folder, scores)
    agent = summary["approaches"]["A"]
    assert agent["interrupted"] == 1
    assert agent["known_input_tokens"] == 1230
    assert agent["usage_complete_tasks"] == 9
    assert agent["wall_time_s"]["count"] == 9
    path = folder / "dep_001.A/trace.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed after"):
        summarize(folder, scores)


@pytest.mark.parametrize("approach", ["B0", "B1"])
def test_interrupted_baseline_preserves_known_usage(completed, approach):
    folder, _ = completed
    (folder / f"dep_001.{approach}/result.json").unlink()
    scores = folder / "interrupted-baseline-scores.json"
    prepare_scores(folder, scores)
    result = summarize(folder, scores)["approaches"][approach]
    assert result["interrupted"] == 1
    assert result["known_input_tokens"] == 1230
    assert result["known_output_tokens"] == 450
    assert result["usage_complete_tasks"] == 9
    assert result["model_calls"]["mean"] == 1


def test_completed_trace_changes_invalidate_scores(completed):
    folder, scores = completed
    trace = folder / "dep_001.B0/trace.jsonl"
    trace.write_text(trace.read_text() + "\n")
    with pytest.raises(ValueError, match="changed after"):
        summarize(folder, scores)
