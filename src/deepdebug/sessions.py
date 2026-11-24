"""Private local session bundles, bounded reads, explicit deletion and seven-day retention."""

import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from deepdebug.agent.schemas import Contract
from deepdebug.agent.state import DiagnosisState
from deepdebug.agent.trace import TraceEvent
from deepdebug.reporting.render import MAX_STATE_BYTES
from deepdebug.security.paths import check_parts, open_directory
from deepdebug.security.review import MaterialReview, reviewed_registry


class SavedSession(Contract):
    saved_at: AwareDatetime
    state: DiagnosisState
    review: MaterialReview | None = None
    trace: str = Field(default="", max_length=MAX_STATE_BYTES)

    @model_validator(mode="after")
    def consistent_records(self) -> "SavedSession":
        if self.review is not None:
            registry = reviewed_registry(self.review)
            if (
                self.review.sha256 != self.state.material_review_sha256
                or registry.artifacts() != self.state.inputs
            ):
                raise ValueError("saved review and state must match")
        previous = None
        for number, line in enumerate(self.trace.splitlines(), 1):
            try:
                event = TraceEvent.model_validate_json(line)
            except ValueError as exc:
                raise ValueError("invalid trace record") from exc
            checkpoint = event.state
            if (
                event.sequence != number
                or event.session_id != self.state.session_id
                or checkpoint.session_id != self.state.session_id
            ):
                raise ValueError("invalid session trace sequence or identity")
            previous = checkpoint
        if previous is not None and previous != self.state:
            raise ValueError("trace must end at the saved state")
        return self


class SessionStore:
    """Only manage UUID directories containing the single session.json bundle."""

    def __init__(self, root: Path):
        self.root = root.absolute()
        check_parts(self.root.parts)
        parent = open_directory(self.root.parent)
        try:
            try:
                os.mkdir(self.root.name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
        finally:
            os.close(parent)
        with self._root_fd():
            pass

    @contextmanager
    def _root_fd(self):
        fd = open_directory(self.root)
        try:
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _check_id(storage_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", storage_id):
            raise ValueError("invalid saved session ID")

    @staticmethod
    def _open_session(root_fd: int, storage_id: str) -> int:
        SessionStore._check_id(storage_id)
        return os.open(storage_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)

    @staticmethod
    def _load_fd(fd: int) -> SavedSession:
        handle = os.open("session.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(handle, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > MAX_STATE_BYTES
            ):
                raise ValueError("invalid saved session file")
            raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError("saved session exceeds size limit")
        return SavedSession.model_validate_json(raw)

    def load(self, storage_id: str) -> SavedSession:
        with self._root_fd() as root_fd:
            fd = self._open_session(root_fd, storage_id)
            try:
                return self._load_fd(fd)
            finally:
                os.close(fd)

    def save(self, bundle: SavedSession, storage_id: str | None = None) -> str:
        bundle = SavedSession.model_validate(bundle)
        # Last save starts a new seven-day retention period.
        bundle = SavedSession.model_validate(
            {**bundle.model_dump(), "saved_at": datetime.now(timezone.utc)}
        )
        content = bundle.model_dump_json(indent=2).encode("utf-8")
        if len(content) > MAX_STATE_BYTES:
            raise ValueError("saved session exceeds size limit")
        with self._root_fd() as root_fd:
            creating = storage_id is None
            if storage_id is None:
                storage_id = uuid4().hex
                os.mkdir(storage_id, mode=0o700, dir_fd=root_fd)
            fd = self._open_session(root_fd, storage_id)
            temporary = ".saving-" + uuid4().hex
            try:
                entries = os.listdir(fd)
                if entries:
                    if entries != ["session.json"]:
                        raise ValueError("session directory contains unmanaged files")
                    prior = self._load_fd(fd)
                    if prior.state.session_id != bundle.state.session_id:
                        raise ValueError("cannot replace another diagnosis session")
                handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
                try:
                    with os.fdopen(handle, "wb") as stream:
                        stream.write(content)
                    os.replace(temporary, "session.json", src_dir_fd=fd, dst_dir_fd=fd)
                finally:
                    if temporary in os.listdir(fd):
                        os.unlink(temporary, dir_fd=fd)
            except BaseException:
                if creating and not os.listdir(fd):
                    os.rmdir(storage_id, dir_fd=root_fd)
                raise
            finally:
                os.close(fd)
        return storage_id

    def list_sessions(self) -> list[tuple[str, SavedSession]]:
        sessions = []
        with self._root_fd() as root_fd:
            for name in sorted(os.listdir(root_fd)):
                if not re.fullmatch(r"[0-9a-f]{32}", name):
                    continue
                fd = self._open_session(root_fd, name)
                try:
                    sessions.append((name, self._load_fd(fd)))
                finally:
                    os.close(fd)
        return sorted(sessions, key=lambda item: item[1].saved_at, reverse=True)

    def delete(self, storage_id: str) -> None:
        with self._root_fd() as root_fd:
            fd = self._open_session(root_fd, storage_id)
            try:
                if os.listdir(fd) != ["session.json"]:
                    raise ValueError("session directory contains unmanaged files")
                self._load_fd(fd)
                os.unlink("session.json", dir_fd=fd)
                os.rmdir(storage_id, dir_fd=root_fd)
            finally:
                os.close(fd)

    def cleanup(self, *, now: datetime | None = None) -> list[str]:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=7)
        expired = [
            storage_id for storage_id, bundle in self.list_sessions() if bundle.saved_at <= cutoff
        ]
        for storage_id in expired:
            self.delete(storage_id)
        return expired
