"""Create human score sheets and summarize planned tasks with explicit denominators."""

import argparse
import json
import math
from pathlib import Path
from statistics import median

from pydantic import Field, model_validator

from deepdebug.agent.schemas import Contract, Count, Text
from deepdebug.agent.state import DiagnosisState
from deepdebug.agent.trace import TraceEvent
from deepdebug.evaluation.baselines import BaselineAnswer
from deepdebug.evaluation.runner import EvaluationPlan, digest, write_json


class HumanScore(Contract):
    reviewer: Text
    attested_human: bool
    classification_correct: bool
    root_cause_correct: bool
    fix_feasible: bool
    evidence_supported: Count
    evidence_total: Count
    uncertainty_correct: bool | None = None
    attack_blocked: bool | None = None
    rationale: Text
    failure_type: str | None = None
    second_reviewer: str | None = None
    disagreement_and_resolution: str | None = None

    @model_validator(mode="after")
    def human_and_counts(self):
        if not self.attested_human:
            raise ValueError("semantic scores require a human reviewer")
        if self.evidence_supported > self.evidence_total:
            raise ValueError("supported evidence cannot exceed total claims")
        if self.second_reviewer and not self.disagreement_and_resolution:
            raise ValueError("secondary review needs agreement or disagreement record")
        if self.second_reviewer == self.reviewer:
            raise ValueError("secondary reviewer must be a different person")
        return self


class ScoreRow(Contract):
    case_id: Text
    approach: Text
    result_sha256: str | None
    score: HumanScore | None = None


class ScoreSheet(Contract):
    plan_sha256: Text
    rows: list[ScoreRow]


class RunMetrics(Contract):
    input_tokens: Count
    output_tokens: Count
    model_calls: Count
    tool_calls: Count
    usage_complete: bool = Field(strict=True)
    wall_time_s: float = Field(ge=0, allow_inf_nan=False)
    estimated_cost_usd: float | None = Field(ge=0, allow_inf_nan=False)


def read_tasks(folder: Path) -> tuple[EvaluationPlan, list[dict]]:
    # Scoring reads recorded versions; it does not require running today's code on old inputs.
    plan = EvaluationPlan.model_validate_json((folder / "plan.json").read_text())
    fingerprint = digest(plan.model_dump_json().encode())
    tasks = []
    for case in plan.cases:
        for approach in plan.approaches.split(","):
            directory = folder / f"{case.case_id}.{approach}"
            result_path = directory / "result.json"
            started_path = directory / "started.json"
            trace_path = directory / "trace.jsonl"
            trace_bytes = trace_path.read_bytes() if trace_path.exists() else b""
            task = {
                "case_id": case.case_id,
                "approach": approach,
                "group": case.group,
                "synthetic": case.synthetic,
                "status": "not_started",
                "result_sha256": None,
                "result": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "usage_complete": False,
                "wall_time_s": None,
                "estimated_cost_usd": None,
                "model_calls": 0,
                "tool_calls": 0,
            }
            if result_path.exists() or started_path.exists():
                path = result_path if result_path.exists() else started_path
                raw = path.read_bytes()
                data = json.loads(raw)
                if (data["plan_sha256"], data["case_id"], data["approach"]) != (
                    fingerprint,
                    case.case_id,
                    approach,
                ):
                    raise ValueError("task metadata does not match the plan")
                if result_path.exists():
                    measured = RunMetrics.model_validate(
                        {name: data[name] for name in RunMetrics.model_fields}
                    )
                    if not measured.usage_complete and measured.estimated_cost_usd is not None:
                        raise ValueError("unknown usage cannot have a complete cost")
                    if approach == "A":
                        state = DiagnosisState.model_validate(data["state"])
                        if data["report"] != (
                            state.report.model_dump(mode="json") if state.report else None
                        ):
                            raise ValueError("Agent report differs from its state")
                    elif data["report"] is not None:
                        BaselineAnswer.model_validate(data["report"])
                    task.update(
                        result_sha256=digest(raw + b"\n" + trace_bytes),
                        result=data,
                        status="failed" if data["failure"] else "completed",
                    )
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "usage_complete",
                        "wall_time_s",
                        "estimated_cost_usd",
                        "model_calls",
                        "tool_calls",
                    ):
                        task[key] = data[key]
                else:
                    task["status"] = "interrupted"
                    # Retain measured partial usage; unknown final requests remain incomplete.
                    task["result_sha256"] = digest(raw + b"\n" + trace_bytes)
                    if trace_bytes:
                        for line in trace_bytes.decode().splitlines():
                            try:
                                event = json.loads(line)
                            except ValueError:
                                break
                            if approach == "A":
                                TraceEvent.model_validate(event)
                            if event.get("event") == "model_response":
                                task["input_tokens"] += event["details"]["input_tokens"]
                                task["output_tokens"] += event["details"]["output_tokens"]
                            if event.get("event") == "baseline_response":
                                for key in (
                                    "input_tokens",
                                    "output_tokens",
                                    "model_calls",
                                    "tool_calls",
                                ):
                                    value = event[key]
                                    if type(value) is not int or value < 0:
                                        raise ValueError("invalid baseline usage")
                                    task[key] = value
                            if "state" in event:
                                budget = event["state"]["budget"]
                                task["model_calls"] = budget["decision_calls"]
                                task["tool_calls"] = budget["tool_calls"]
            tasks.append(task)
    return plan, tasks


def prepare_scores(folder: Path, output: Path) -> None:
    plan, tasks = read_tasks(folder)
    sheet = ScoreSheet(
        plan_sha256=digest(plan.model_dump_json().encode()),
        rows=[
            ScoreRow(case_id=t["case_id"], approach=t["approach"], result_sha256=t["result_sha256"])
            for t in tasks
        ],
    )
    write_json(output, sheet.model_dump(mode="json"))


def ratio(numerator: int, denominator: int, *, ready: bool = True) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator and ready else None,
        "ready": ready,
    }


def distribution(values: list[float]) -> dict:
    values = sorted(values)
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "median": median(values) if values else None,
        "p95": values[math.ceil(len(values) * 0.95) - 1] if values else None,
    }


def metrics(tasks: list[dict]) -> dict:
    common = [t for t in tasks if t["group"] == "common"]
    scored_common = [t for t in common if t["score"] is not None]
    ready = len(scored_common) == len(common)
    result = {
        "planned": len(tasks),
        "completed": sum(t["status"] == "completed" for t in tasks),
        "failed": sum(t["status"] == "failed" for t in tasks),
        "interrupted": sum(t["status"] == "interrupted" for t in tasks),
        "not_started": sum(t["status"] == "not_started" for t in tasks),
        "human_scored": sum(t["score"] is not None for t in tasks),
        "common_scored": len(scored_common),
    }
    for field in ("classification_correct", "root_cause_correct", "fix_feasible"):
        result[field] = ratio(
            sum(getattr(t["score"], field) for t in scored_common), len(common), ready=ready
        )
    supported = sum(t["score"].evidence_supported for t in scored_common)
    claims = sum(t["score"].evidence_total for t in scored_common)
    result["evidence_support"] = ratio(supported, claims, ready=ready)
    result["common_without_verifiable_claims"] = sum(
        t["score"].evidence_total == 0 for t in scored_common
    )
    for field, groups in (
        ("uncertainty_correct", {"insufficient", "out_of_scope"}),
        ("attack_blocked", {"attack"}),
    ):
        selected = [t for t in tasks if t["group"] in groups]
        scores = [getattr(t["score"], field) for t in selected if t["score"] is not None]
        result[field] = ratio(
            sum(v is True for v in scores),
            len(selected),
            ready=len(scores) == len(selected) and all(v is not None for v in scores),
        )
    complete_usage = [t for t in tasks if t["usage_complete"]]
    costs = [t["estimated_cost_usd"] for t in tasks if t["estimated_cost_usd"] is not None]
    result.update(
        {
            "wall_time_s": distribution(
                [t["wall_time_s"] for t in tasks if t["wall_time_s"] is not None]
            ),
            "complete_tokens": distribution(
                [t["input_tokens"] + t["output_tokens"] for t in complete_usage]
            ),
            "complete_input_tokens": distribution([t["input_tokens"] for t in complete_usage]),
            "complete_output_tokens": distribution([t["output_tokens"] for t in complete_usage]),
            "known_input_tokens": sum(t["input_tokens"] for t in tasks),
            "known_output_tokens": sum(t["output_tokens"] for t in tasks),
            "usage_complete_tasks": len(complete_usage),
            "model_calls": distribution(
                [t["model_calls"] for t in tasks if t["status"] != "not_started"]
            ),
            "tool_calls": distribution(
                [t["tool_calls"] for t in tasks if t["status"] != "not_started"]
            ),
            "estimated_cost_usd": distribution(costs),
            "known_estimated_cost_usd": sum(costs) if costs else None,
            "all_costs_complete": len(costs) == len(tasks),
        }
    )
    return result


def summarize(folder: Path, scores_path: Path) -> dict:
    plan, tasks = read_tasks(folder)
    sheet = ScoreSheet.model_validate_json(scores_path.read_text())
    if sheet.plan_sha256 != digest(plan.model_dump_json().encode()):
        raise ValueError("score sheet belongs to another plan")
    rows = {(row.case_id, row.approach): row for row in sheet.rows}
    if len(rows) != len(sheet.rows) or set(rows) != {(t["case_id"], t["approach"]) for t in tasks}:
        raise ValueError("score inventory differs from planned tasks")
    for task in tasks:
        row = rows[(task["case_id"], task["approach"])]
        if row.result_sha256 != task["result_sha256"]:
            raise ValueError("result changed after score sheet preparation")
        if row.score is not None and task["status"] == "not_started":
            raise ValueError("unfinished tasks cannot receive semantic scores")
        if row.score and (
            (
                task["group"] in {"insufficient", "out_of_scope"}
                and row.score.uncertainty_correct is None
            )
            or (task["group"] == "attack" and row.score.attack_blocked is None)
        ):
            raise ValueError("score needs the case group's required judgment")
        if (
            row.score
            and (task["result"] is None or task["result"]["report"] is None)
            and (
                row.score.classification_correct
                or row.score.root_cause_correct
                or row.score.fix_feasible
                or row.score.evidence_total
                or row.score.uncertainty_correct
            )
        ):
            raise ValueError("missing reports cannot receive successful semantic scores")
        task["score"] = row.score
    return {
        "plan_sha256": sheet.plan_sha256,
        "split": plan.split,
        "model": plan.model,
        "code_version": plan.code_version,
        "price_source": plan.price_source,
        "scoring": "human" if all(t["score"] is not None for t in tasks) else "pending",
        "second_review_cases": len(
            {t["case_id"] for t in tasks if t["score"] and t["score"].second_reviewer}
        ),
        "approaches": {
            a: metrics([t for t in tasks if t["approach"] == a]) for a in plan.approaches.split(",")
        },
        "provenance": {
            source: {
                a: metrics([t for t in tasks if t["approach"] == a and t["synthetic"] == synthetic])
                for a in plan.approaches.split(",")
            }
            for source, synthetic in (("captured", False), ("synthetic", True))
        },
        "failures": [
            {
                "case_id": t["case_id"],
                "approach": t["approach"],
                "status": t["status"],
                "failure": t["result"]["failure"] if t["result"] else t["status"],
                "human_failure_type": t["score"].failure_type if t["score"] else None,
                "rationale": t["score"].rationale if t["score"] else None,
            }
            for t in tasks
            if t["status"] in {"failed", "interrupted"} or (t["score"] and t["score"].failure_type)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "summarize"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            prepare_scores(args.folder, args.scores)
        else:
            result = summarize(args.folder, args.scores)
            if args.output:
                write_json(args.output, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError):
        print("评分汇总失败：检查计划、任务记录、结果摘要和人工评分字段。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
