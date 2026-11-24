"""Host-confirmed association of fixed demo checks with a report suggestion."""

import json
from pathlib import Path
from time import monotonic

from deepdebug.agent.schemas import (
    Evidence,
    FieldLocation,
    Source,
    ToolRecord,
    ToolResult,
    Verification,
)
from deepdebug.agent.state import DiagnosisState
from deepdebug.tools.builtin_checks import PHASES, PRESETS, run_builtin_check


def verify_report(
    state: DiagnosisState,
    case_id: str,
    fix_index: int,
    *,
    matches_preset: bool,
    python: Path | None = None,
) -> DiagnosisState:
    state = DiagnosisState.model_validate(state)
    if state.report is None or not 1 <= fix_index <= len(state.report.fixes):
        raise ValueError("请选择报告中已有的修复建议。")
    if case_id not in PRESETS:
        raise ValueError("预置案例未登记。")
    payload = state.model_dump(mode="json")
    checks = []
    next_evidence = max((int(e.evidence_id[1:]) for e in state.evidence), default=0) + 1
    next_tool = max((int(r.result.tool_call_id[1:]) for r in state.tool_history), default=0) + 1
    if not matches_preset:
        checks.append(
            Verification(
                check_id=f"{case_id}/after_fix",
                status="未执行",
                fix_index=fix_index,
                reason="尚未确认建议与预置修复匹配。",
            )
        )
    else:
        for phase in PHASES:
            started = monotonic()
            checked = run_builtin_check(case_id, phase, python)
            source = Source(
                kind="local", id=f"builtin/{case_id}/{phase}", environment_id=checked.environment_id
            )
            evidence_ids = []
            if checked.execution is not None:
                evidence_id = f"E{next_evidence:03}"
                next_evidence += 1
                evidence = Evidence(
                    evidence_id=evidence_id,
                    source=source,
                    location=FieldLocation(pointer="/execution"),
                    content=json.dumps(
                        checked.execution.model_dump(mode="json"), ensure_ascii=False
                    ),
                    collected_at=checked.executed_at,
                )
                payload["evidence"].append(evidence.model_dump(mode="json"))
                evidence_ids.append(evidence_id)
            result = ToolResult(
                tool_call_id=f"T{next_tool:03}",
                status=checked.tool_status,
                data=checked.data() if checked.tool_status == "ok" else {},
                evidence_ids=evidence_ids,
                source=source,
                collected_at=checked.executed_at,
                duration_ms=int((monotonic() - started) * 1000),
                error=checked.reason if checked.tool_status != "ok" else None,
            )
            next_tool += 1
            record = ToolRecord(
                tool="run_builtin_check",
                purpose="用户确认建议匹配后执行预置案例前后对照。",
                arguments_summary=json.dumps(
                    {"case_id": case_id, "check_id": phase, "interpreter": checked.interpreter}
                ),
                result=result,
            )
            payload["tool_history"].append(record.model_dump(mode="json"))
            payload["budget"]["tool_calls"] += 1
            payload["budget"]["elapsed_ms"] += result.duration_ms
            checks.append(
                Verification(
                    check_id=f"{case_id}/{phase}",
                    status=checked.status,
                    fix_index=fix_index,
                    reason=f"用户核查建议匹配预置修复：{PRESETS[case_id]['fix']} {checked.reason}",
                    evidence_ids=evidence_ids,
                    execution=checked.execution,
                )
            )
    # Retain earlier checks; replace the original 'none' placeholder once a check is requested.
    payload["report"]["verifications"] = [
        v for v in payload["report"]["verifications"] if v["check_id"] != "none"
    ] + [v.model_dump(mode="json") for v in checks]
    payload["report"]["evidence"] = payload["evidence"]
    payload["report"]["tool_history"] = payload["tool_history"]
    return DiagnosisState.model_validate(payload)
