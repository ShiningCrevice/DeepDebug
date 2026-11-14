"""Provider-independent model requests, usage and classified failures."""

from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import Field

from deepdebug.agent.schemas import Contract, Count, PositiveCount, Text
from deepdebug.agent.state import DiagnosisState


class ModelRequest(Contract):
    instructions: Text
    state: DiagnosisState
    environments: dict[str, str]
    path_reference_ids: list[str]
    response_schema: dict
    correction: str | None = None
    timeout_seconds: float = Field(gt=0)
    max_tokens: PositiveCount


class ModelResponse(Contract):
    content: str
    input_tokens: Count = 0
    output_tokens: Count = 0
    failure: Literal["refused", "incomplete", "error"] | None = None

    @property
    def tokens_used(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelFailure(Exception):
    """Adapters report transport failures without exposing provider exception text."""

    def __init__(
        self,
        kind: Literal["timeout", "unavailable", "error", "budget"],
        *,
        usage_unknown: bool = False,
    ):
        self.kind = kind
        self.usage_unknown = usage_unknown
        super().__init__(kind)


class ModelClient(Protocol):
    transport: Literal["offline", "remote"]

    def decide(self, request: ModelRequest) -> ModelResponse:
        """Honor the supplied deadline/token allowance and return usage with raw JSON."""
        ...


class ReplayModelClient:
    """Scripted responses exercise the controller, not diagnostic model quality.

    Token counts are fixture-supplied simulated usage, never billing measurements.
    """

    transport = "offline"

    def __init__(self, responses: Iterable[ModelResponse]):
        self._responses = iter(responses)

    def decide(self, request: ModelRequest) -> ModelResponse:
        try:
            return ModelResponse.model_validate(next(self._responses))
        except StopIteration as exc:
            raise ModelFailure("unavailable") from exc
