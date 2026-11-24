"""Session persistence boundaries, consistency, deletion and retention."""

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from deepdebug.agent.state import DiagnosisState
from deepdebug.cli import main
from deepdebug.sessions import SavedSession, SessionStore


def bundle():
    return SavedSession(
        saved_at=datetime.now(timezone.utc), state=DiagnosisState(session_id="test")
    )


def test_private_save_reload_update_delete(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    saved = bundle()
    key = store.save(saved)
    path = store.root / key
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE((path / "session.json").stat().st_mode) == 0o600
    assert store.load(key).state == saved.state
    changed = saved.model_copy(
        update={"state": saved.state.model_copy(update={"error_summary": "new"})}
    )
    assert store.save(changed, key) == key
    assert store.load(key).state.error_summary == "new"
    assert len(store.list_sessions()) == 1
    store.delete(key)
    assert store.list_sessions() == [] and not path.exists()


def test_retention_expires_after_last_save(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    key = store.save(bundle())
    timestamp = store.load(key).saved_at
    assert store.cleanup(now=timestamp + timedelta(days=7, microseconds=-1)) == []
    assert store.cleanup(now=timestamp + timedelta(days=7)) == [key]
    assert not (store.root / key).exists()


def test_foreign_files_and_sessions_cannot_be_deleted_or_replaced(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    key = store.save(bundle())
    (store.root / key / "user.txt").write_text("retain")
    with pytest.raises(ValueError, match="unmanaged"):
        store.delete(key)
    with pytest.raises(ValueError, match="unmanaged"):
        store.save(bundle(), key)
    assert (store.root / key / "session.json").exists()
    (store.root / key / "user.txt").unlink()
    foreign = SavedSession(
        saved_at=datetime.now(timezone.utc), state=DiagnosisState(session_id="other")
    )
    with pytest.raises(ValueError, match="another"):
        store.save(foreign, key)
    assert store.load(key).state.session_id == "test"


def test_traversal_and_symlinks_are_rejected(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    with pytest.raises(ValueError):
        store.load("../outside")
    outside = tmp_path / "outside"
    outside.mkdir()
    key = "f" * 32
    (store.root / key).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        store.load(key)
    with pytest.raises(OSError):
        store.delete(key)
    root_link = tmp_path / "linked"
    root_link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        SessionStore(root_link)
    assert outside.is_dir()


@pytest.mark.parametrize("link_kind", ["symbolic", "hard"])
def test_linked_bundle_is_rejected(tmp_path, link_kind):
    store = SessionStore(tmp_path / "sessions")
    key = store.save(bundle())
    path = store.root / key / "session.json"
    original = tmp_path / "original.json"
    path.rename(original)
    if link_kind == "symbolic":
        path.symlink_to(original)
    else:
        os.link(original, path)
    with pytest.raises((OSError, ValueError)):
        store.load(key)
    with pytest.raises((OSError, ValueError)):
        store.delete(key)
    assert original.exists()


def test_invalid_checkpoint_cannot_be_persisted(tmp_path):
    saved = bundle()
    event = dict(
        sequence=1,
        session_id="test",
        event="checkpoint",
        recorded_at=datetime.now(timezone.utc).isoformat(),
        details={},
        state=saved.state.model_dump(mode="json"),
    )
    saved.trace = json.dumps(event) + "\n"
    store = SessionStore(tmp_path / "sessions")
    assert store.load(store.save(saved)).trace == saved.trace
    saved.state.error_summary = "different final state"
    with pytest.raises(ValidationError, match="trace must end"):
        store.save(saved)
    saved.trace = json.dumps({**event, "sequence": 2})
    with pytest.raises(ValidationError, match="sequence"):
        store.save(saved)


def test_corrupt_bundle_is_reported_and_not_cleaned(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    key = store.save(bundle())
    path = store.root / key / "session.json"
    path.write_text('{"invalid":true}')
    with pytest.raises(ValidationError):
        store.cleanup(now=datetime.now(timezone.utc) + timedelta(days=10))
    assert path.exists()


def test_cli_save_list_load_delete(tmp_path, capsys):
    directory = tmp_path / "sessions"
    source = tmp_path / "state.json"
    source.write_text(bundle().state.model_dump_json())
    args = ["--directory", str(directory)]
    assert main(["sessions", "save", *args, "--state", str(source)]) == 0
    key = capsys.readouterr().out.strip()
    assert main(["sessions", "list", *args]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == key
    assert main(["sessions", "load", *args, "--id", key]) == 0
    assert SavedSession.model_validate_json(capsys.readouterr().out).state.session_id == "test"
    assert main(["sessions", "delete", *args, "--id", key]) == 0
    assert not (directory / key).exists()


@pytest.mark.parametrize("trace", ["[]", '{"sequence":1}', "null"])
def test_malformed_trace_is_validation_error(trace):
    with pytest.raises(ValidationError, match="invalid trace"):
        SavedSession(
            saved_at=datetime.now(timezone.utc),
            state=DiagnosisState(session_id="test"),
            trace=trace,
        )


def test_failed_save_preserves_prior_state_and_cleans_new_directory(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    saved = bundle()
    key = store.save(saved)

    def fail(*args, **kwargs):
        raise OSError("write failed")

    monkeypatch.setattr("deepdebug.sessions.os.replace", fail)
    with pytest.raises(OSError):
        store.save(saved, key)
    assert store.load(key).state == saved.state
    assert list((store.root / key).iterdir()) == [store.root / key / "session.json"]
    with pytest.raises(OSError):
        store.save(saved)
    assert len(store.list_sessions()) == 1


def test_trace_missing_presentation_fields_is_rejected():
    state = DiagnosisState(session_id="test")
    event = dict(sequence=1, session_id="test", state=state.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="invalid trace"):
        SavedSession(saved_at=datetime.now(timezone.utc), state=state, trace=json.dumps(event))
