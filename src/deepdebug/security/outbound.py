"""Bind every remote request to the reviewed registry and host-owned session."""

import json

from deepdebug.agent.decision import INSTRUCTIONS, Decision
from deepdebug.agent.schemas import CloudConsent
from deepdebug.agent.state import DiagnosisState
from deepdebug.llm.client import ModelRequest
from deepdebug.security.redaction import Redactor
from deepdebug.security.review import MaterialReview, reviewed_registry
from deepdebug.tools.registry import ToolDispatcher


class OutboundBoundary:
    def __init__(self, review: MaterialReview, consent: CloudConsent, dispatcher: ToolDispatcher):
        self._review = MaterialReview.model_validate(review)
        self.consent = CloudConsent.model_validate(consent)
        self._expected = reviewed_registry(self._review)
        self.dispatcher = dispatcher
        self.validate_dispatcher(dispatcher)

    def validate_dispatcher(self, dispatcher: ToolDispatcher) -> None:
        consent = CloudConsent.model_validate(self.consent)
        state = DiagnosisState.model_validate(dispatcher.session.state)
        if (
            dispatcher is not self.dispatcher
            or dispatcher.paths is not None
            or dispatcher.path_reference_ids
            or consent.material_review_sha256 != self._review.sha256
            or state.material_review_sha256 != self._review.sha256
            or state.cloud_consent != consent
            or state.inputs != self._expected.artifacts()
            or dispatcher.session.materials.artifacts() != self._expected.artifacts()
        ):
            raise ValueError("云端请求与已确认范围不一致。")
        for artifact in self._expected.artifacts():
            if dispatcher.session.materials.get(artifact.artifact_id) != self._expected.get(
                artifact.artifact_id
            ):
                raise ValueError("已确认材料内容发生变化。")
        # Send the normalized value that was compared with the recorded consent.
        self.consent = consent

    def payload(self, request: ModelRequest, *, api_key: str) -> dict:
        self.validate_dispatcher(self.dispatcher)
        request = ModelRequest.model_validate(request)
        # Only elapsed time can advance between constructing a request and sending it.
        candidate = request.state.model_dump(exclude={"budget"})
        current = self.dispatcher.session.state.model_dump(exclude={"budget"})
        budget = self.dispatcher.session.state.budget
        if (
            candidate != current
            or request.path_reference_ids
            or request.environments != self.dispatcher.environments
            or request.instructions != INSTRUCTIONS.strip()
            or request.response_schema != Decision.model_json_schema()
            or request.state.budget.model_dump(exclude={"elapsed_ms"})
            != budget.model_dump(exclude={"elapsed_ms"})
            or request.max_tokens
            > budget.max_tokens - budget.reserved_report_tokens - budget.tokens_used
            or request.timeout_seconds > budget.max_duration_seconds - budget.elapsed_ms / 1000
            or request.state.evidence != self.dispatcher.session.evidence.values()
        ):
            raise ValueError("云端请求必须来自当前宿主会话。")
        # Full source files are not attached. Tools select evidence excerpts as needed.
        data = {
            "state": request.state.model_dump(
                mode="json", exclude={"budget", "cloud_consent", "report", "next_action"}
            ),
            "environments": request.environments,
            "path_reference_ids": [],
            "response_schema": request.response_schema,
            "correction": request.correction,
        }
        encoded = json.dumps(data, ensure_ascii=False)
        encoded = Redactor([encoded], secrets=[api_key]).redact(encoded)
        return {
            "model": self.consent.model,
            "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": encoded}],
            "text": {"format": {"type": "json_object"}},
            "store": False,
        }
