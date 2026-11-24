"""Resume a reviewed stopped session with appended materials and a new allowance."""

import hashlib
import io
from datetime import datetime, timezone
from math import ceil

from deepdebug.agent.controller import Controller
from deepdebug.agent.decision import Conclusion
from deepdebug.agent.schemas import CloudConsent
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.agent.trace import JsonlTrace
from deepdebug.llm.client import ReplayModelClient
from deepdebug.llm.openai import OpenAIResponsesClient
from deepdebug.security.outbound import OutboundBoundary
from deepdebug.security.review import MaterialReview, reviewed_registry
from deepdebug.sessions import SavedSession
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession


def continue_session(
    saved: SavedSession,
    review: MaterialReview,
    *,
    history_reviewed: bool,
    allowance: Budget | None = None,
    consent: CloudConsent | None = None,
    replay_model: ReplayModelClient | None = None,
    trace_stream: io.StringIO | None = None,
) -> SavedSession:
    saved = SavedSession.model_validate(saved)
    review = MaterialReview.model_validate(review)
    if trace_stream is not None and (
        not isinstance(trace_stream, io.StringIO) or trace_stream.getvalue()
    ):
        raise ValueError("续跑需要空的内存轨迹流。")
    if not history_reviewed or saved.review is None or saved.state.stop_reason is None:
        raise ValueError("续跑需要已停止的确认会话，并重新核查历史状态。")
    if review.status != "confirmed" or (
        review.content.materials[: len(saved.review.content.materials)]
        != saved.review.content.materials
    ):
        raise ValueError("续跑材料只能追加，已有副本和顺序须保持不变。")
    if (consent is None) == (replay_model is None):
        raise ValueError("选择云端授权或离线响应之一。")
    extra = Budget.model_validate(allowance or Budget())
    if any((extra.decision_calls, extra.tool_calls, extra.tokens_used, extra.elapsed_ms)):
        raise ValueError("新增预算须尚未消费。")
    old = saved.state.budget
    budget = Budget.model_validate(
        {
            **old.model_dump(),
            "max_decision_calls": old.decision_calls + extra.max_decision_calls,
            "max_tool_calls": old.tool_calls + extra.max_tool_calls,
            "max_tokens": old.tokens_used + extra.max_tokens,
            "reserved_report_tokens": extra.reserved_report_tokens,
            "max_duration_seconds": ceil(old.elapsed_ms / 1000) + extra.max_duration_seconds,
        }
    )
    registry = reviewed_registry(review)
    state = DiagnosisState.model_validate(
        {
            **saved.state.model_dump(),
            "inputs": registry.artifacts(),
            "budget": budget,
            "material_review_sha256": review.sha256,
            "cloud_consent": consent,
            "continued_from_sha256": hashlib.sha256(
                saved.state.model_dump_json().encode()
            ).hexdigest(),
            "previous_conclusion": Conclusion(
                summary=saved.state.report.summary,
                category=saved.state.report.category,
                fixes=saved.state.report.fixes,
                unresolved_questions=saved.state.report.unresolved_questions,
            )
            if saved.state.report
            else None,
            "stop_reason": None,
            "report": None,
            "next_action": None,
        }
    )
    dispatcher = ToolDispatcher(CollectionSession(registry, state))
    model = (
        replay_model
        if replay_model is not None
        else OpenAIResponsesClient(OutboundBoundary(review, consent, dispatcher))
    )
    # The caller's live stream receives the original prefix as complete records too.
    stream = trace_stream if trace_stream is not None else io.StringIO()
    prefix = saved.trace.rstrip("\n")
    for line in prefix.splitlines():
        stream.write(line + "\n")
    trace = JsonlTrace(stream)
    trace.sequence = len(prefix.splitlines())
    if not prefix:
        trace.write("checkpoint", saved.state, {"source": "saved_state"})
    final = Controller(dispatcher, model, trace=trace).run(
        registry.artifacts()[0].artifact_id, resume=True
    )
    return SavedSession(
        saved_at=datetime.now(timezone.utc), state=final, review=review, trace=stream.getvalue()
    )
