"""Local preview and explicit confirmation of a bounded, frozen material scope."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from deepdebug.agent.schemas import Artifact, Contract
from deepdebug.security.paths import MAX_FILE_BYTES, AuthorizedRoot, MaterialError
from deepdebug.security.redaction import Redactor
from deepdebug.tools.artifacts import MaterialRegistry, RegisteredMaterial

# JSON escaping can expand the ten 2 MiB UTF-8 inputs by up to six times.
MAX_REVIEW_BYTES = 128 * 1024 * 1024
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PreviewMaterial(Contract):
    artifact: Artifact
    text: str
    registered_at: AwareDatetime

    @model_validator(mode="after")
    def bounded_content(self) -> "PreviewMaterial":
        size = len(self.text.encode("utf-8"))
        if size > MAX_FILE_BYTES or size != self.artifact.size_bytes or "\x00" in self.text:
            raise ValueError("invalid material size or encoding")
        if self.artifact.redaction_status != "pending":
            raise ValueError("preview artifacts remain pending until confirmation is loaded")
        return self


class ReviewContent(Contract):
    format_version: Literal[1] = 1
    redaction_version: Literal["common-secrets-home-v1"] = "common-secrets-home-v1"
    materials: Annotated[list[PreviewMaterial], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def explicit_scope(self) -> "ReviewContent":
        if self.materials[0].artifact.kind != "log":
            raise ValueError("first material must be the log")
        for index, item in enumerate(self.materials, 1):
            if item.artifact.artifact_id != f"A{index:03}":
                raise ValueError("material IDs must be ordered and unique")
            if index > 1 and item.artifact.kind == "log":
                raise ValueError("only one log is supported")
        return self

    def digest(self) -> str:
        data = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


class MaterialReview(Contract):
    content: ReviewContent
    sha256: Digest
    status: Literal["preview", "confirmed"] = "preview"
    confirmed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def intact(self) -> "MaterialReview":
        if self.sha256 != self.content.digest():
            raise ValueError("preview content or scope changed")
        if (self.status == "confirmed") != (self.confirmed_at is not None):
            raise ValueError("confirmation requires a timestamp")
        return self


def preview_materials(
    root: Path, log: str, code: list[str], config: list[str], snapshots: list[str]
) -> MaterialReview:
    registry = MaterialRegistry()
    with AuthorizedRoot(root) as authorized:
        registry.register(authorized, log, "log")
        for kind, names in (("code", code), ("config", config), ("snapshot", snapshots)):
            for name in names:
                registry.register(authorized, name, kind)
    originals = [registry.get(a.artifact_id) for a in registry.artifacts()]
    redactor = Redactor(item.text for item in originals)
    materials = []
    for item in originals:
        text = redactor.redact(item.text)
        artifact = Artifact.model_validate(
            {
                **item.artifact.model_dump(),
                "display_name": item.artifact.artifact_id + Path(item.artifact.display_name).suffix,
                "size_bytes": len(text.encode("utf-8")),
            }
        )
        materials.append(
            PreviewMaterial(artifact=artifact, text=text, registered_at=item.registered_at)
        )
    content = ReviewContent(materials=materials)
    return MaterialReview(content=content, sha256=content.digest())


def confirm_materials(review: MaterialReview) -> MaterialReview:
    review = MaterialReview.model_validate(review)
    if review.status != "preview":
        raise ValueError("confirmation requires a preview")
    return MaterialReview(
        content=review.content,
        sha256=review.sha256,
        status="confirmed",
        confirmed_at=datetime.now(timezone.utc),
    )


def save_review(path: Path, review: MaterialReview) -> None:
    review = MaterialReview.model_validate(review)
    # Local previews may contain undetected private text; create owner-only files.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(review.model_dump_json(indent=2) + "\n")


def load_review(path: Path) -> MaterialReview:
    with AuthorizedRoot(path.absolute().parent) as root:
        data = root.read(path.name, max_bytes=MAX_REVIEW_BYTES)
    return MaterialReview.model_validate_json(data)


def reviewed_registry(review: MaterialReview) -> MaterialRegistry:
    review = MaterialReview.model_validate(review)
    if review.status != "confirmed":
        raise MaterialError("材料预览尚未确认。")
    registry = MaterialRegistry()
    for item in review.content.materials:
        artifact = Artifact.model_validate(
            {**item.artifact.model_dump(), "redaction_status": "reviewed"}
        )
        registry.add_reviewed(RegisteredMaterial(artifact, item.text, item.registered_at))
    return registry
