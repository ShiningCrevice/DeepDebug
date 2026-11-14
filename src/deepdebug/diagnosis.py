"""Cloud diagnosis from a frozen reviewed copy and explicit destination consent."""

from typing import TextIO

from deepdebug.agent.controller import Controller
from deepdebug.agent.schemas import CloudConsent
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.agent.trace import JsonlTrace
from deepdebug.llm.openai import OpenAIResponsesClient
from deepdebug.security.outbound import OutboundBoundary
from deepdebug.security.review import MaterialReview, reviewed_registry
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession


def diagnose(
    review: MaterialReview,
    consent: CloudConsent,
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
            "cloud_consent": consent,
        }
    )
    dispatcher = ToolDispatcher(session)
    model = OpenAIResponsesClient(OutboundBoundary(review, consent, dispatcher))
    return Controller(
        dispatcher,
        model,
        trace=JsonlTrace(trace_stream) if trace_stream is not None else None,
    ).run(review.content.materials[0].artifact.artifact_id)
