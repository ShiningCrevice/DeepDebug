"""Session state and cross-record integrity checks, without controller execution."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from deepdebug.agent.actions import Action
from deepdebug.agent.schemas import (
    Artifact,
    CloudConsent,
    Contract,
    Count,
    DiagnosisReport,
    Evidence,
    Hypothesis,
    PositiveCount,
    StopReason,
    TargetEnvironment,
    Text,
    ToolRecord,
    require_refs,
    unique_ids,
    validate_evidence_references,
)


class Budget(Contract):
    max_decision_calls: PositiveCount = 6
    max_tool_calls: PositiveCount = 8
    max_report_repairs: Annotated[int, Field(strict=True, ge=0, le=1)] = 1
    max_tokens: PositiveCount = 50_000
    reserved_report_tokens: Count = 5_000
    max_duration_seconds: PositiveCount = 120
    tool_timeout_seconds: PositiveCount = 10
    gpu_timeout_seconds: PositiveCount = 15
    decision_calls: Count = 0
    tool_calls: Count = 0
    report_repairs: Count = 0
    tokens_used: Count = 0
    usage_complete: bool = True
    elapsed_ms: Count = 0

    @model_validator(mode="after")
    def reserve_fits_total(self) -> "Budget":
        if self.reserved_report_tokens > self.max_tokens:
            raise ValueError("report token reserve exceeds total token budget")
        return self


class DiagnosisState(Contract):
    schema_version: Literal["1"] = "1"
    session_id: Text
    inputs: list[Artifact] = Field(default_factory=list, max_length=10)
    material_review_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    cloud_consent: CloudConsent | None = None
    target_environment: TargetEnvironment | None = None
    error_summary: Text | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=3)
    next_action: Action | None = None
    tool_history: list[ToolRecord] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    stop_reason: StopReason | None = None
    report: DiagnosisReport | None = None

    @model_validator(mode="after")
    def registered_references(self) -> "DiagnosisState":
        if self.cloud_consent is not None and (
            self.cloud_consent.material_review_sha256 != self.material_review_sha256
        ):
            raise ValueError("cloud consent must match the reviewed material scope")
        if self.material_review_sha256 is not None and (
            not self.inputs or any(a.redaction_status != "reviewed" for a in self.inputs)
        ):
            raise ValueError("review digest requires reviewed materials")
        artifacts = unique_ids([a.artifact_id for a in self.inputs], "artifact IDs")
        known = unique_ids([e.evidence_id for e in self.evidence], "evidence IDs")
        validate_evidence_references(self.hypotheses, self.tool_history, known)
        sources = [e.source for e in self.evidence] + [r.result.source for r in self.tool_history]
        snapshot_ids = {a.artifact_id for a in self.inputs if a.kind == "snapshot"}
        for source in sources:
            if source.kind in {"artifact", "snapshot"}:
                require_refs([source.id], artifacts, "artifact IDs")
            if source.kind == "snapshot":
                require_refs([source.id], snapshot_ids, "snapshot artifact IDs")
        if self.next_action is not None and self.next_action.action == "tool":
            require_refs(
                self.next_action.related_hypotheses,
                {h.hypothesis_id for h in self.hypotheses},
                "hypothesis IDs",
            )
            if self.next_action.tool in {"parse_log", "read_artifact"}:
                require_refs([self.next_action.arguments.artifact_id], artifacts, "artifact IDs")
        if self.stop_reason is not None and self.next_action is not None:
            raise ValueError("stopped state cannot have a pending action")
        if self.report is not None:
            if self.report.session_id != self.session_id:
                raise ValueError("report belongs to another session")
            if self.report.stop_reason != self.stop_reason:
                raise ValueError("report and state must agree on stop_reason")
            if self.report.target_environment != self.target_environment:
                raise ValueError("report and state must agree on target environment")
            if self.report.hypotheses != self.hypotheses:
                raise ValueError("report hypotheses must match current session hypotheses")
            registered = {e.evidence_id: e for e in self.evidence}
            for evidence in self.report.evidence:
                if registered.get(evidence.evidence_id) != evidence:
                    raise ValueError("report evidence must match registered evidence")
            if self.report.tool_history != self.tool_history:
                raise ValueError("report tool history must match session history")
        return self
