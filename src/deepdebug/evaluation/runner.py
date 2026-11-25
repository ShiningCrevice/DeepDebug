"""Prepare, explicitly authorize and record B0/B1/A benchmark tasks."""

import argparse
import hashlib
import io
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Literal, TextIO

from dotenv import load_dotenv
from pydantic import Field, model_validator

from deepdebug.agent.controller import Controller
from deepdebug.agent.schemas import CloudConsent, Contract, Text
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.agent.trace import JsonlTrace
from deepdebug.evaluation.baselines import (
    BASELINE_INSTRUCTIONS,
    BaselineAnswer,
    BaselineBoundary,
    corpus_bytes,
)
from deepdebug.evaluation.dataset import cases, material_kind, verify_frozen
from deepdebug.llm.client import ModelFailure, ModelRequest
from deepdebug.llm.openai import OpenAIResponsesClient
from deepdebug.security.outbound import OutboundBoundary
from deepdebug.security.review import (
    confirm_materials,
    load_review,
    preview_materials,
    reviewed_registry,
    save_review,
)
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_version() -> str:
    checkout = Path(__file__).absolute().parents[3]
    if not (checkout / ".git").exists() or not (
        checkout / "src/deepdebug/evaluation/runner.py"
    ).samefile(__file__):
        raise ValueError("evaluation requires the source checkout")
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", "src/deepdebug/evaluation/runner.py"],
        cwd=checkout,
        check=True,
        timeout=10,
        stdout=subprocess.DEVNULL,
    )
    for command in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        subprocess.run(command, cwd=checkout, check=True, timeout=10)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True, timeout=10
    ).strip()


class EvaluationCase(Contract):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    group: Literal["common", "insufficient", "out_of_scope", "attack"]
    category: Text
    synthetic: bool
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationPlan(Contract):
    split: Literal["dev", "test"]
    code_version: Text
    dataset_sha256: Text
    baseline_prompt_sha256: Text
    documents_sha256: Text
    model: Text
    endpoint: Text
    budget: Budget
    cases: list[EvaluationCase]
    approaches: Literal["B0,B1,A"] = "B0,B1,A"
    sampling: Literal["provider-default; no sampling overrides"] = (
        "provider-default; no sampling overrides"
    )
    tools_mode: Literal["frozen-materials; local-checks-disabled"] = (
        "frozen-materials; local-checks-disabled"
    )
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
    price_source: str | None = None

    @model_validator(mode="after")
    def fresh_budget_and_prices(self):
        if (
            any(
                getattr(self.budget, name)
                for name in (
                    "decision_calls",
                    "tool_calls",
                    "report_repairs",
                    "tokens_used",
                    "elapsed_ms",
                )
            )
            or not self.budget.usage_complete
        ):
            raise ValueError("evaluation needs a fresh budget")
        prices = (self.input_usd_per_million, self.output_usd_per_million)
        if any(p is not None for p in prices) and (
            any(p is None for p in prices) or not self.price_source
        ):
            raise ValueError("prices need both rates and a dated source")
        return self


class EvaluationSession(CollectionSession):
    def run_builtin_check(self, case_id, check_id):
        return self.record_failure(
            "run_builtin_check",
            "固定材料评测",
            json.dumps({"case_id": case_id, "check_id": check_id}),
            "unavailable",
            "固定材料评测不运行本机预置检查；修复运行验证单独记录。",
        )


def write_json(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def preview_case(case):
    files = {kind: [] for kind in ("log", "code", "config", "snapshot")}
    for name in case["materials"]:
        files[material_kind(name)].append(Path(name).name)
    return preview_materials(
        case["root"] / "materials",
        files["log"][0],
        files["code"],
        files["config"],
        files["snapshot"],
    )


def prepare(
    root: Path, output: Path, *, split: str, model: str, endpoint: str, budget: Budget
) -> EvaluationPlan:
    verify_frozen(root)
    version = code_version()
    # Validate destination/model before creating the review bundle.
    CloudConsent(
        material_review_sha256="0" * 64,
        endpoint=endpoint,
        model=model,
        confirmed_at=datetime.now(timezone.utc),
    )
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    entries = []
    for case in cases(root):
        if case["split"] != split:
            continue
        review = preview_case(case)
        save_review(output / f"{case['case_id']}.review.json", review)
        entries.append(
            EvaluationCase(
                case_id=case["case_id"],
                group=case["group"],
                category=case["category"],
                synthetic=case["metadata"]["synthetic"],
                review_sha256=review.sha256,
            )
        )
    plan = EvaluationPlan(
        split=split,
        code_version=version,
        dataset_sha256=digest((root / "frozen.json").read_bytes()),
        baseline_prompt_sha256=digest(BASELINE_INSTRUCTIONS.encode()),
        documents_sha256=digest(corpus_bytes()),
        model=model,
        endpoint=endpoint,
        budget=budget,
        cases=entries,
    )
    write_json(output / "plan.json", plan.model_dump(mode="json"))
    return plan


def load_plan(folder: Path, root: Path) -> EvaluationPlan:
    verify_frozen(root)
    plan = EvaluationPlan.model_validate_json((folder / "plan.json").read_text())
    expected = [c for c in cases(root) if c["split"] == plan.split]
    if (
        plan.code_version != code_version()
        or plan.dataset_sha256 != digest((root / "frozen.json").read_bytes())
        or plan.baseline_prompt_sha256 != digest(BASELINE_INSTRUCTIONS.encode())
        or plan.documents_sha256 != digest(corpus_bytes())
        or [c.case_id for c in plan.cases] != [c["case_id"] for c in expected]
    ):
        raise ValueError("evaluation plan differs from frozen code or data")
    fingerprint = digest(plan.model_dump_json().encode())
    for item, case in zip(plan.cases, expected, strict=True):
        if (item.group, item.category, item.synthetic) != (
            case["group"],
            case["category"],
            case["metadata"]["synthetic"],
        ):
            raise ValueError("evaluation case metadata changed")
        review = load_review(folder / f"{item.case_id}.review.json")
        original = preview_case(case)

        def content(value):
            return [(m.artifact.model_dump(), m.text) for m in value.content.materials]

        if review.sha256 != item.review_sha256 or content(review) != content(original):
            raise ValueError("evaluation material review changed")
        for approach in plan.approaches.split(","):
            started = folder / f"{item.case_id}.{approach}" / "started.json"
            if started.exists() and json.loads(started.read_text())["plan_sha256"] != fingerprint:
                raise ValueError("cannot change a plan after tasks started")
    return plan


def baseline(review, consent, approach: str, budget: Budget) -> dict:
    session = CollectionSession(reviewed_registry(review))
    session.state = DiagnosisState.model_validate(
        {
            **session.state.model_dump(),
            "budget": budget,
            "cloud_consent": consent,
            "material_review_sha256": review.sha256,
        }
    )
    dispatcher = ToolDispatcher(session)
    boundary = BaselineBoundary(review, consent, dispatcher, approach)
    client = OpenAIResponsesClient(boundary)
    request = ModelRequest(
        instructions=BASELINE_INSTRUCTIONS.strip(),
        state=session.state,
        environments=dispatcher.environments,
        path_reference_ids=[],
        response_schema=BaselineAnswer.model_json_schema(),
        timeout_seconds=budget.max_duration_seconds,
        max_tokens=budget.max_tokens,
    )
    result = {
        "report": None,
        "model_calls": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "usage_complete": True,
        "failure": None,
        "failure_http_status": None,
    }
    try:
        response = client.decide(request)
        result.update(
            model_calls=1,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            failure=response.failure,
            response=response.content,
        )
        if response.failure is None:
            try:
                result["report"] = BaselineAnswer.model_validate_json(response.content).model_dump(
                    mode="json"
                )
            except ValueError:
                result["failure"] = "invalid_report"
    except ModelFailure as exc:
        result.update(
            failure=exc.kind,
            failure_http_status=exc.http_status,
            usage_complete=not exc.usage_unknown,
            model_calls=0 if exc.kind == "budget" else 1,
        )
    return result


def run_task(
    review, plan: EvaluationPlan, approach: str, *, trace_stream: TextIO | None = None
) -> tuple[dict, str]:
    consent = CloudConsent(
        material_review_sha256=review.sha256,
        endpoint=plan.endpoint,
        model=plan.model,
        confirmed_at=datetime.now(timezone.utc),
    )
    start = monotonic()
    if approach == "A":
        trace = trace_stream if trace_stream is not None else io.StringIO()
        session = EvaluationSession(reviewed_registry(review))
        session.state = DiagnosisState.model_validate(
            {
                **session.state.model_dump(),
                "budget": plan.budget,
                "cloud_consent": consent,
                "material_review_sha256": review.sha256,
            }
        )
        dispatcher = ToolDispatcher(session)
        model = OpenAIResponsesClient(OutboundBoundary(review, consent, dispatcher))
        state = Controller(dispatcher, model, trace=JsonlTrace(trace)).run(
            review.content.materials[0].artifact.artifact_id
        )
        trace.flush()
        trace.seek(0)
        trajectory = trace.read()
        events = [json.loads(line) for line in trajectory.splitlines()]
        usage = [e["details"] for e in events if e["event"] == "model_response"]
        result = {
            "report": state.report.model_dump(mode="json") if state.report else None,
            "state": state.model_dump(mode="json"),
            "model_calls": state.budget.decision_calls,
            "tool_calls": state.budget.tool_calls,
            "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
            "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
            "usage_complete": state.budget.usage_complete,
            "failure": None
            if state.stop_reason in {"completed", "need_info"}
            else state.stop_reason,
            "failure_http_status": next(
                (
                    event["details"].get("http_status")
                    for event in reversed(events)
                    if event["event"] in {"model_error", "model_response"}
                ),
                None,
            )
            if state.stop_reason not in {"completed", "need_info"}
            else None,
        }
    else:
        result = baseline(review, consent, approach, plan.budget)
        trajectory = json.dumps({"event": "baseline_response", **result}, ensure_ascii=False) + "\n"
        if trace_stream is not None:
            trace_stream.write(trajectory)
            trace_stream.flush()
    result["wall_time_s"] = monotonic() - start
    prices = (plan.input_usd_per_million, plan.output_usd_per_million)
    result["estimated_cost_usd"] = (
        (result["input_tokens"] * prices[0] + result["output_tokens"] * prices[1]) / 1_000_000
        if result["usage_complete"] and all(p is not None for p in prices)
        else None
    )
    return result, trajectory


def execute(
    folder: Path, root: Path, *, reviewed: bool, send_to: str, model: str, limit: int | None = None
) -> int:
    plan = load_plan(folder, root)
    if not reviewed or send_to != plan.endpoint or model != plan.model:
        raise ValueError("explicit review, destination and model must match the plan")
    # Check credentials before reserving tasks.
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is required")
    completed = 0
    for case in plan.cases:
        review = load_review(folder / f"{case.case_id}.review.json")
        if review.sha256 != case.review_sha256:
            raise ValueError("evaluation material review changed during execution")
        if review.status == "preview":
            review = confirm_materials(review)
        for approach in plan.approaches.split(","):
            if limit is not None and completed >= limit:
                return completed
            output = folder / f"{case.case_id}.{approach}"
            if output.exists():
                # A started task is never silently retried or removed from the denominator.
                continue
            output.mkdir(mode=0o700)
            metadata = {
                "plan_sha256": digest(plan.model_dump_json().encode()),
                "case_id": case.case_id,
                "approach": approach,
                "group": case.group,
                "synthetic": case.synthetic,
                "code_version": plan.code_version,
                "model": plan.model,
                "endpoint": plan.endpoint,
                "material_review_sha256": review.sha256,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "parameters": {"sampling": plan.sampling, "budget": plan.budget.model_dump()},
                "price_source": plan.price_source,
            }
            write_json(output / "started.json", {**metadata, "usage_complete": False})
            with (output / "trace.jsonl").open("x+", encoding="utf-8") as stream:
                os.chmod(output / "trace.jsonl", 0o600)
                result, _ = run_task(review, plan, approach, trace_stream=stream)
            write_json(output / "result.json", {**metadata, **result})
            completed += 1
            print(f"{case.case_id}/{approach}: {result['failure'] or 'recorded'}", flush=True)
            if result.get("failure_http_status") in {401, 403}:
                raise ModelFailure("error", http_status=result["failure_http_status"])
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "run"])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--root", type=Path, default=Path("benchmark"))
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--model", required=True)
    parser.add_argument("--send-to", required=True)
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    load_dotenv(Path.cwd() / ".env", override=False)
    try:
        if args.operation == "prepare":
            plan = prepare(
                args.root,
                args.folder,
                split=args.split,
                model=args.model,
                endpoint=args.send_to,
                budget=Budget(max_tokens=200_000, max_duration_seconds=180),
            )
            print(
                f"已生成 {len(plan.cases)} 份预览、{len(plan.cases) * 3} 个任务；"
                "核查各 review.json 与 plan.json 后运行。"
            )
        else:
            if args.limit is not None and args.limit < 1:
                raise ValueError("limit must be positive")
            execute(
                args.folder,
                args.root,
                reviewed=args.reviewed,
                send_to=args.send_to,
                model=args.model,
                limit=args.limit,
            )
    except ModelFailure as exc:
        print(f"评测已停止：模型服务返回 HTTP {exc.http_status}，本次失败结果已保存。")
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print("评测准备或执行失败：检查冻结版本、计划、确认范围及模型配置。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
