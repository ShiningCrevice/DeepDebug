"""Registration freezes explicit input bytes; subsequent reads use material IDs."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from deepdebug.agent.schemas import Artifact
from deepdebug.security.paths import AuthorizedRoot, MaterialError

MAX_EXCERPT_CHARS = 16_000
SUFFIXES = {
    "log": {".txt", ".log"},
    "code": {".py"},
    "config": {".json", ".yaml", ".yml"},
    "snapshot": {".json"},
}


@dataclass(frozen=True)
class RegisteredMaterial:
    artifact: Artifact
    text: str
    registered_at: datetime


class MaterialRegistry:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredMaterial] = {}
        self._names: set[str] = set()

    def register(
        self,
        root: AuthorizedRoot,
        relative: str,
        kind: Literal["log", "code", "config", "snapshot"],
    ) -> Artifact:
        if len(self._items) >= 10:
            raise MaterialError("每个会话最多登记 10 份材料。")
        if kind not in SUFFIXES or Path(relative).suffix.lower() not in SUFFIXES[kind]:
            raise MaterialError("材料类型与文件扩展名不匹配。")
        name = Path(relative).as_posix()
        if name in self._names:
            raise MaterialError("同一材料不能重复登记。")
        raw = root.read(relative)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MaterialError("材料必须是 UTF-8 文本。") from exc
        if "\x00" in text:
            raise MaterialError("材料包含二进制内容。")
        artifact = Artifact(
            artifact_id=f"A{len(self._items) + 1:03}",
            kind=kind,
            display_name=name,
            origin="local",
            size_bytes=len(raw),
            redaction_status="pending",
        )
        self._items[artifact.artifact_id] = RegisteredMaterial(
            artifact.model_copy(deep=True), text, datetime.now(timezone.utc)
        )
        self._names.add(name)
        return artifact

    def get(self, artifact_id: str) -> RegisteredMaterial:
        try:
            item = self._items[artifact_id]
        except KeyError as exc:
            raise MaterialError("材料 ID 未登记。") from exc
        return RegisteredMaterial(
            item.artifact.model_copy(deep=True), item.text, item.registered_at
        )

    def add_reviewed(self, item: RegisteredMaterial) -> None:
        """Import an explicitly confirmed copy; this method never reads original files."""
        artifact = Artifact.model_validate(item.artifact)
        if (
            len(self._items) >= 10
            or artifact.artifact_id != f"A{len(self._items) + 1:03}"
            or artifact.display_name in self._names
            or artifact.redaction_status != "reviewed"
            or artifact.size_bytes != len(item.text.encode("utf-8"))
            or "\x00" in item.text
        ):
            raise MaterialError("已确认材料的结构或内容无效。")
        self._items[artifact.artifact_id] = RegisteredMaterial(
            artifact, item.text, item.registered_at
        )
        self._names.add(artifact.display_name)

    def artifacts(self) -> list[Artifact]:
        return [item.artifact.model_copy(deep=True) for item in self._items.values()]


@dataclass(frozen=True)
class Excerpt:
    start: int
    end: int
    content: str
    truncated: bool


def excerpt(
    lines: list[str], start: int, max_lines: int, max_chars: int = MAX_EXCERPT_CHARS
) -> Excerpt | None:
    if start > len(lines):
        return None
    selected: list[str] = []
    remaining = max_chars
    clipped = False
    for line in lines[start - 1 : start - 1 + max_lines]:
        separator = 1 if selected else 0
        if remaining <= separator:
            break
        part = line[: remaining - separator]
        selected.append(part)
        remaining -= len(part) + separator
        if len(part) != len(line):
            clipped = True
            break
    if not selected:
        return None
    end = start + len(selected) - 1
    return Excerpt(start, end, "\n".join(selected), clipped or start > 1 or end < len(lines))
