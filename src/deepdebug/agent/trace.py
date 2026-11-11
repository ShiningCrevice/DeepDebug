"""Streaming local JSONL checkpoints, validated before serialization."""

import json
from datetime import datetime, timezone
from typing import TextIO

from deepdebug.agent.state import DiagnosisState


class JsonlTrace:
    def __init__(self, stream: TextIO):
        self.stream = stream
        self.sequence = 0

    def write(self, event: str, state: DiagnosisState, details: dict) -> None:
        state = DiagnosisState.model_validate(state)
        self.sequence += 1
        entry = dict(
            sequence=self.sequence,
            event=event,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            session_id=state.session_id,
            details=details,
            state=state.model_dump(mode="json"),
        )
        self.stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.stream.flush()
