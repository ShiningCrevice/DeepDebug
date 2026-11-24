"""Versioned data contracts; validation does not perform I/O or grant permissions."""

import re
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    StrictBool,
    StringConstraints,
    model_validator,
)

from deepdebug.security.destination import normalize_endpoint

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Count = Annotated[int, Field(strict=True, ge=0)]
PositiveCount = Annotated[int, Field(strict=True, ge=1)]
ArtifactId = Annotated[str, Field(pattern=r"^A[0-9]{3,}$")]
EvidenceId = Annotated[str, Field(pattern=r"^E[0-9]{3,}$")]
HypothesisId = Annotated[str, Field(pattern=r"^H[1-9][0-9]*$")]
ToolCallId = Annotated[str, Field(pattern=r"^T[0-9]{3,}$")]
Category = Literal[
    "cuda_oom", "device_mismatch", "dependency", "path", "configuration", "unknown", "out_of_scope"
]
StopReason = Literal[
    "completed",
    "need_info",
    "no_progress",
    "budget_exhausted",
    "tools_unavailable",
    "invalid_action",
    "model_error",
]
ToolName = Literal[
    "parse_log",
    "read_artifact",
    "check_paths",
    "inspect_environment",
    "query_gpu",
    "search_docs",
    "run_builtin_check",
]


class Contract(BaseModel):
    """Reject undocumented fields and revalidate model instances at boundaries."""

    model_config = ConfigDict(extra="forbid", validate_default=True, revalidate_instances="always")


class CloudConsent(Contract):
    """Explicit runtime permission for one reviewed scope and destination."""

    material_review_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    endpoint: Annotated[str, AfterValidator(normalize_endpoint)]
    model: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    confirmed_at: AwareDatetime
    scope: Literal["reviewed-evidence-tools-judgments-v1"] = "reviewed-evidence-tools-judgments-v1"


def unique_ids(values: list[str], label: str) -> set[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return set(values)


def require_refs(references: list[str], known: set[str], label: str) -> None:
    missing = set(references) - known
    if missing:
        raise ValueError(f"unknown {label}: {', '.join(sorted(missing))}")


class Artifact(Contract):
    artifact_id: ArtifactId
    kind: Literal["log", "code", "config", "snapshot"]
    display_name: Text
    origin: Literal["upload", "paste", "fixture", "local"]
    size_bytes: Annotated[int, Field(strict=True, ge=0, le=2 * 1024 * 1024)]
    redaction_status: Literal["pending", "reviewed"] = "pending"
    # Filesystem paths belong in the future server-side registry, not model actions.


class Source(Contract):
    kind: Literal["artifact", "snapshot", "local", "document"]
    id: Text
    environment_id: Text | None = None
    url: HttpUrl | None = None
    applicable_version: Text | None = None

    @model_validator(mode="after")
    def environment_is_identified(self) -> "Source":
        if self.kind in {"snapshot", "local"} and self.environment_id is None:
            raise ValueError("environment observations require environment_id")
        if self.kind == "document" and (self.url is None or self.applicable_version is None):
            raise ValueError("document observations require URL and applicable version")
        return self


class LineLocation(Contract):
    kind: Literal["lines"] = "lines"
    start: PositiveCount
    end: PositiveCount

    @model_validator(mode="after")
    def ordered_range(self) -> "LineLocation":
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class FieldLocation(Contract):
    kind: Literal["field"] = "field"
    pointer: Annotated[str, Field(pattern=r"^/")]


class Evidence(Contract):
    evidence_id: EvidenceId
    source: Source
    location: Annotated[LineLocation | FieldLocation, Field(discriminator="kind")]
    content: Annotated[str, Field(min_length=1)]
    collected_at: AwareDatetime
    truncated: StrictBool = False


class TargetEnvironment(Contract):
    mode: Literal["snapshot", "local"] = "snapshot"
    environment_id: Text
    interpreter: Text
    collected_at: AwareDatetime


class PackageObservation(Contract):
    name: Text
    status: Literal["installed", "not_found", "error"]
    version: Text | None = None
    error: Text | None = None

    @model_validator(mode="after")
    def consistent_metadata(self) -> "PackageObservation":
        if (self.status == "installed") != (self.version is not None):
            raise ValueError("only installed packages have a version")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("only failed metadata queries have an error")
        return self


class ProbeObservation(Contract):
    status: Literal["ok", "unavailable", "timeout", "error"]
    collected_at: AwareDatetime
    error: Text | None = None

    @model_validator(mode="after")
    def explicit_failure(self) -> "ProbeObservation":
        if (self.status == "ok") != (self.error is None):
            raise ValueError("probe failure requires an error")
        return self


class TorchCudaObservation(ProbeObservation):
    torch_version: Text | None = None
    cuda_version: Text | None = None
    cuda_available: StrictBool | None = None
    device_count: Count | None = None

    @model_validator(mode="after")
    def consistent_result(self) -> "TorchCudaObservation":
        if self.status == "ok":
            if (
                self.torch_version is None
                or self.cuda_available is None
                or self.device_count is None
            ):
                raise ValueError("successful torch probe requires version and availability")
            if self.cuda_available != (self.device_count > 0):
                raise ValueError("CUDA availability and device count disagree")
        elif any(
            value is not None
            for value in (
                self.torch_version,
                self.cuda_version,
                self.cuda_available,
                self.device_count,
            )
        ):
            raise ValueError("failed torch probe cannot contain success fields")
        return self


class GpuDevice(Contract):
    index: Count
    name: Text
    memory_total_mib: Count
    memory_used_mib: Count


class GpuObservation(ProbeObservation):
    devices: list[GpuDevice] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def consistent_result(self) -> "GpuObservation":
        if (self.status == "ok") != bool(self.devices):
            raise ValueError("only successful GPU probes contain devices")
        unique_ids([str(device.index) for device in self.devices], "GPU indices")
        return self


class EnvironmentSnapshot(Contract):
    schema_version: Literal["1"] = "1"
    environment: TargetEnvironment
    python_version: Text
    packages: list[PackageObservation] = Field(default_factory=list)
    torch_cuda: TorchCudaObservation | None = None
    gpu: GpuObservation | None = None

    @model_validator(mode="after")
    def unique_packages(self) -> "EnvironmentSnapshot":
        # Distribution names are case-insensitive; separators are equivalent.
        unique_ids(
            [re.sub(r"[-_.]+", "-", item.name).lower() for item in self.packages], "packages"
        )
        return self


class Hypothesis(Contract):
    hypothesis_id: HypothesisId
    cause: Text
    confidence: Literal["证据充分", "有支持但待验证", "信息不足"]
    supporting_evidence: list[EvidenceId] = Field(default_factory=list)
    opposing_evidence: list[EvidenceId] = Field(default_factory=list)
    pending_checks: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def supported_confidence(self) -> "Hypothesis":
        if self.confidence != "信息不足" and not self.supporting_evidence:
            raise ValueError("supported confidence requires supporting evidence")
        if set(self.supporting_evidence) & set(self.opposing_evidence):
            raise ValueError("same evidence cannot both support and oppose a hypothesis")
        return self


class ToolResult(Contract):
    tool_call_id: ToolCallId
    status: Literal["ok", "unavailable", "denied", "timeout", "error"]
    data: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    source: Source
    collected_at: AwareDatetime
    duration_ms: Count
    truncated: StrictBool = False
    error: Text | None = None

    @model_validator(mode="after")
    def failure_is_explicit(self) -> "ToolResult":
        if self.status == "ok":
            if self.error is not None:
                raise ValueError("successful tool result cannot contain an error")
        elif self.error is None or self.data:
            raise ValueError("failed tool result requires an error and no success data")
        return self


class ToolRecord(Contract):
    tool: ToolName
    purpose: Text
    arguments_summary: Text
    result: ToolResult


class FixSuggestion(Contract):
    hypothesis_id: HypothesisId
    description: Text
    conditions: Text
    impact: Text
    evidence_ids: list[EvidenceId] = Field(min_length=1)
    verification_steps: list[Text] = Field(min_length=1)
    success_criteria: Text


class CheckExecution(Contract):
    executed_at: AwareDatetime
    environment_id: Text
    exit_code: Annotated[int, Field(strict=True)]
    output: str
    truncated: StrictBool = False


class Verification(Contract):
    check_id: Text
    status: Literal["静态检查通过", "预置复现通过", "失败", "无法执行", "未执行"]
    reason: Text
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    execution: CheckExecution | None = None

    @model_validator(mode="after")
    def execution_matches_status(self) -> "Verification":
        executed = self.status in {"静态检查通过", "预置复现通过", "失败"}
        if executed != (self.execution is not None):
            raise ValueError("execution record must match verification status")
        if executed and not self.evidence_ids:
            raise ValueError("executed checks require evidence")
        if self.execution is not None:
            if self.status.endswith("通过") and self.execution.exit_code != 0:
                raise ValueError("passed check requires zero exit code")
            if self.status == "失败" and self.execution.truncated:
                raise ValueError("failed check must retain full output")
        return self


def validate_evidence_references(
    hypotheses: list[Hypothesis], history: list[ToolRecord], known: set[str]
) -> None:
    unique_ids([h.hypothesis_id for h in hypotheses], "hypothesis IDs")
    unique_ids([r.result.tool_call_id for r in history], "tool call IDs")
    for h in hypotheses:
        require_refs(h.supporting_evidence + h.opposing_evidence, known, "evidence IDs")
    for record in history:
        require_refs(record.result.evidence_ids, known, "evidence IDs")


class DiagnosisReport(Contract):
    schema_version: Literal["1"] = "1"
    session_id: Text
    materials: list[Artifact] = Field(default_factory=list, max_length=10)
    summary: Text
    category: Category
    target_environment: TargetEnvironment | None
    evidence: list[Evidence]
    hypotheses: list[Hypothesis] = Field(max_length=3)
    fixes: list[FixSuggestion]
    verifications: list[Verification] = Field(min_length=1)
    unresolved_questions: list[Text]
    tool_history: list[ToolRecord]
    stop_reason: StopReason

    @model_validator(mode="after")
    def references_exist(self) -> "DiagnosisReport":
        artifacts = unique_ids([a.artifact_id for a in self.materials], "artifact IDs")
        if self.materials:
            for evidence in self.evidence:
                if evidence.source.kind in {"artifact", "snapshot"}:
                    require_refs([evidence.source.id], artifacts, "artifact IDs")
        known = unique_ids([e.evidence_id for e in self.evidence], "evidence IDs")
        validate_evidence_references(self.hypotheses, self.tool_history, known)
        hypotheses = {h.hypothesis_id for h in self.hypotheses}
        for fix in self.fixes:
            require_refs([fix.hypothesis_id], hypotheses, "hypothesis IDs")
            require_refs(fix.evidence_ids, known, "evidence IDs")
        for check in self.verifications:
            require_refs(check.evidence_ids, known, "evidence IDs")
        if self.stop_reason == "completed" and not any(
            h.confidence != "信息不足" for h in self.hypotheses
        ):
            raise ValueError("completed report requires a supported hypothesis")
        if self.stop_reason == "need_info" and not self.unresolved_questions:
            raise ValueError("need_info requires concrete unresolved questions")
        return self
