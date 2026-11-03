"""Discriminated action protocol with tool-specific argument allowlists."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from deepdebug.agent.schemas import (
    ArtifactId,
    Category,
    Contract,
    HypothesisId,
    PositiveCount,
    StopReason,
    Text,
)

ProbeId = Literal["python_identity", "package_metadata", "torch_cuda"]


class ParseLogArguments(Contract):
    artifact_id: ArtifactId
    context_lines: Annotated[int, Field(strict=True, ge=0, le=50)] = 5


class ReadArtifactArguments(Contract):
    artifact_id: ArtifactId
    start_line: PositiveCount = 1
    max_lines: Annotated[int, Field(strict=True, ge=1, le=200)] = 200


class InspectEnvironmentArguments(Contract):
    environment_id: Text
    probe_ids: list[ProbeId] = Field(min_length=1, max_length=3)


class CheckPathsArguments(Contract):
    path_reference_ids: list[Text] = Field(min_length=1, max_length=10)


class QueryGpuArguments(Contract):
    environment_id: Text


class SearchDocsArguments(Contract):
    query: Annotated[Text, Field(max_length=500)]
    category: Category | None = None
    max_results: Annotated[int, Field(strict=True, ge=1, le=3)] = 3


class BuiltinCheckArguments(Contract):
    case_id: Text
    # Protocol reservation only; these checks have no executor yet.
    check_id: Literal["dependency_import", "interpreter_identity"]


class ToolActionBase(Contract):
    action: Literal["tool"] = "tool"
    purpose: Text
    related_hypotheses: list[HypothesisId] = Field(default_factory=list, max_length=3)


class ParseLogAction(ToolActionBase):
    tool: Literal["parse_log"]
    arguments: ParseLogArguments


class ReadArtifactAction(ToolActionBase):
    tool: Literal["read_artifact"]
    arguments: ReadArtifactArguments


class InspectEnvironmentAction(ToolActionBase):
    tool: Literal["inspect_environment"]
    arguments: InspectEnvironmentArguments


class CheckPathsAction(ToolActionBase):
    tool: Literal["check_paths"]
    arguments: CheckPathsArguments


class QueryGpuAction(ToolActionBase):
    tool: Literal["query_gpu"]
    arguments: QueryGpuArguments


class SearchDocsAction(ToolActionBase):
    tool: Literal["search_docs"]
    arguments: SearchDocsArguments


class BuiltinCheckAction(ToolActionBase):
    tool: Literal["run_builtin_check"]
    arguments: BuiltinCheckArguments


ToolAction = Annotated[
    ParseLogAction
    | ReadArtifactAction
    | InspectEnvironmentAction
    | CheckPathsAction
    | QueryGpuAction
    | SearchDocsAction
    | BuiltinCheckAction,
    Field(discriminator="tool"),
]


class NeedInfoAction(Contract):
    action: Literal["need_info"]
    questions: list[Text] = Field(min_length=1)
    reason: Text


class FinishAction(Contract):
    action: Literal["finish"]
    reason: Text
    stop_reason: StopReason


Action = Annotated[ToolAction | NeedInfoAction | FinishAction, Field(discriminator="action")]
ACTION_ADAPTER = TypeAdapter(Action)
