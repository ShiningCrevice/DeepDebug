"""Local response replay workflow for exercising the agent without a cloud model."""

import json
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

from pydantic import TypeAdapter

from deepdebug.agent.controller import Controller
from deepdebug.agent.schemas import Contract, Count
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.agent.trace import JsonlTrace
from deepdebug.llm.client import ModelResponse, ReplayModelClient
from deepdebug.security.paths import AuthorizedRoot
from deepdebug.security.review import MaterialReview, reviewed_registry
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.tools.path_references import PathReferences
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession


class ReplayTurn(Contract):
    decision: dict | str
    input_tokens: Count = 0
    output_tokens: Count = 0


def replay_reviewed(
    review: MaterialReview,
    model: ReplayModelClient,
    *,
    budget: Budget | None = None,
    trace_stream: TextIO | None = None,
) -> DiagnosisState:
    review = MaterialReview.model_validate(review)
    session = CollectionSession(reviewed_registry(review))
    session.state = DiagnosisState.model_validate(
        {
            **session.state.model_dump(),
            "budget": budget or Budget(),
            "material_review_sha256": review.sha256,
        }
    )
    return Controller(
        ToolDispatcher(session),
        model,
        trace=JsonlTrace(trace_stream) if trace_stream is not None else None,
    ).run(review.content.materials[0].artifact.artifact_id)


def load_replay(path: Path) -> ReplayModelClient:
    with AuthorizedRoot(path.absolute().parent) as root:
        turns = TypeAdapter(list[ReplayTurn]).validate_json(root.read(path.name))
    return ReplayModelClient(
        ModelResponse(
            content=turn.decision if isinstance(turn.decision, str) else json.dumps(turn.decision),
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
        )
        for turn in turns
    )


def replay(
    root: Path,
    log: str,
    code: list[str],
    config: list[str],
    snapshots: list[str],
    model: ReplayModelClient,
    *,
    budget: Budget | None = None,
    paths: list[str] | None = None,
    path_root: Path | None = None,
    trace_stream: TextIO | None = None,
) -> DiagnosisState:
    materials = MaterialRegistry()
    with ExitStack() as stack:
        authorized = stack.enter_context(AuthorizedRoot(root))
        artifact = materials.register(authorized, log, "log")
        for kind, names in (("code", code), ("config", config), ("snapshot", snapshots)):
            for name in names:
                materials.register(authorized, name, kind)
        references = None
        reference_ids = []
        if paths:
            path_authorized = stack.enter_context(AuthorizedRoot(path_root or root))
            references = PathReferences(path_authorized)
            reference_ids = [references.register(path) for path in paths]
        session = CollectionSession(materials)
        if budget is not None:
            session.state = DiagnosisState.model_validate(
                {
                    **session.state.model_dump(),
                    "budget": budget,
                }
            )
        controller = Controller(
            ToolDispatcher(session, references, reference_ids),
            model,
            trace=JsonlTrace(trace_stream) if trace_stream is not None else None,
        )
        return controller.run(artifact.artifact_id)
