"""Upload-to-review workflow and streaming trace presentation data."""

import io
from collections.abc import Callable, Sequence
from typing import Literal

from deepdebug.agent.trace import TraceEvent
from deepdebug.security.review import MaterialReview, preview_registry
from deepdebug.tools.artifacts import MaterialRegistry

UploadKind = Literal["log", "code", "config", "snapshot"]


def preview_uploads(
    pasted_log: str, uploads: Sequence[tuple[str, bytes, UploadKind]]
) -> MaterialReview:
    registry = MaterialRegistry()
    logs = [u for u in uploads if u[2] == "log"]
    if bool(pasted_log.strip()) == bool(logs) or len(logs) > 1:
        raise ValueError("请选择粘贴日志或上传一份日志。")
    if pasted_log.strip():
        registry.register_bytes("pasted.log", pasted_log.encode("utf-8"), "log", origin="paste")
    for kind in ("log", "code", "config", "snapshot"):
        for name, content, upload_kind in uploads:
            if upload_kind == kind:
                registry.register_bytes(name, content, kind)
    return preview_registry(registry)


class ProgressStream(io.StringIO):
    """Consume the JSONL writer's complete records and keep the downloadable trace."""

    def __init__(self, on_event: Callable[[dict], None]):
        super().__init__()
        self.on_event = on_event
        self.events: list[dict] = []

    def write(self, text: str) -> int:
        entry = TraceEvent.model_validate_json(text).model_dump(mode="json")
        self.events.append(entry)
        result = super().write(text)
        self.on_event(entry)
        return result
