"""Local UI flows and explicit material review without paid model calls."""

import json
from pathlib import Path

import pytest

from deepdebug.security.paths import MAX_FILE_BYTES
from deepdebug.security.review import confirm_materials
from deepdebug.ui.workflow import preview_uploads

ROOT = Path(__file__).resolve().parents[1]


def test_upload_review_limits_and_origin():
    review = preview_uploads(
        "ValueError: token=secret123", [("a.py", b"raise RuntimeError()", "code")]
    )
    assert review.content.materials[0].artifact.origin == "paste"
    assert review.content.materials[1].artifact.origin == "upload"
    assert "secret123" not in review.model_dump_json()
    assert confirm_materials(review).status == "confirmed"


@pytest.mark.parametrize(
    "log,uploads",
    [
        ("", []),
        ("log", [("log.txt", b"log", "log")]),
        ("", [("a.txt", b"log", "log"), ("b.txt", b"log", "log")]),
        ("log", [("bad.py", b"\x00", "code")]),
        ("log", [("bad.py", b"\xff", "code")]),
        ("log", [("bad.py", b"a" * (MAX_FILE_BYTES + 1), "code")]),
        ("log", [(f"{i}.py", b"pass", "code") for i in range(10)]),
    ],
)
def test_invalid_uploads_are_rejected(log, uploads):
    with pytest.raises(ValueError):
        preview_uploads(log, uploads)


def app():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_demo_runs_real_tools_and_downloads_report():
    at = app()
    at.radio[0].set_value("离线预置演示").run()
    button(at, "运行依赖案例演示").click().run()
    assert not at.exception
    state = at.session_state["result"]
    assert state.report.materials and state.report.verifications[0].status == "未执行"
    events = at.session_state["events"]
    assert len(events) > 3
    assert events[-1]["state"] == state.model_dump(mode="json")
    assert json.loads(at.session_state["trace"].splitlines()[-1])["event"] == "stop"
    assert any("目标环境：ENV_EMPTY" in m.value for m in at.markdown)
    assert len(at.get("download_button")) == 4
    # Ordinary widget reruns retain the finished report and timeline.
    at.run()
    assert at.session_state["result"].session_id == state.session_id
    button(at, "清除当前会话").click().run()
    assert "result" not in at.session_state
    assert not at.exception


def test_review_is_required_and_input_change_invalidates_result():
    at = app()
    at.text_area[0].set_value("RuntimeError: example").run()
    button(at, "生成脱敏预览").click().run()
    assert not at.exception
    assert button(at, "授权发送并开始诊断").disabled
    at.text_input[1].set_value("test-model").run()
    at.checkbox[0].check().run()
    assert not button(at, "授权发送并开始诊断").disabled
    at.text_area[0].set_value("RuntimeError: changed").run()
    assert "preview" not in at.session_state
    assert not any(b.label == "授权发送并开始诊断" for b in at.button)
    button(at, "生成脱敏预览").click().run()
    assert not at.checkbox[0].value


def test_uploaded_code_is_never_executed(tmp_path):
    at = app()
    marker = tmp_path / "executed"
    at.file_uploader[0].upload("log.txt", b"RuntimeError: test").run()
    at.file_uploader[1].upload("a.py", f"open({str(marker)!r}, 'w').write('x')".encode()).run()
    button(at, "生成脱敏预览").click().run()
    assert not at.exception
    assert len(at.session_state["preview"].content.materials) == 2
    assert not marker.exists()


def test_send_uses_confirmed_scope_and_selected_destination(monkeypatch):
    pytest.importorskip("streamlit")
    from deepdebug.ui import app as ui_app

    calls = []

    def fake_diagnose(review, consent, **kwargs):
        calls.append((review, consent))
        raise ValueError("credential or transport issue")

    monkeypatch.setattr(ui_app, "diagnose", fake_diagnose)
    at = app()
    at.text_area[0].set_value("ValueError: example").run()
    button(at, "生成脱敏预览").click().run()
    at.checkbox[0].check().run()
    at.text_input[0].set_value("https://example.com/v1").run()
    at.text_input[1].set_value("test-model").run()
    button(at, "授权发送并开始诊断").click().run()
    assert not at.exception
    review, consent = calls[0]
    assert review.status == "confirmed"
    assert consent.material_review_sha256 == review.sha256
    assert consent.endpoint == "https://example.com/v1/responses"
    assert consent.model == "test-model"
    assert "result" not in at.session_state
    assert any("诊断启动失败" in error.value for error in at.error)


def test_ui_verification_appends_trace_and_updates_downloads():
    from deepdebug.tools.builtin_checks import PRESETS

    at = app()
    at.radio[0].set_value("离线预置演示").run()
    button(at, "运行依赖案例演示").click().run()
    at.session_state["result"].report.fixes[0].description = PRESETS["path"]["fix"]
    at.selectbox[0].set_value("path").run()
    assert button(at, "运行预置前后对照").disabled
    at.checkbox[0].check().run()
    button(at, "运行预置前后对照").click().run()
    assert not at.exception
    state = at.session_state["result"]
    assert [v.status for v in state.report.verifications] == ["失败", "预置复现通过"]
    events = at.session_state["events"]
    assert events[-1]["event"] == "verification"
    assert events[-1]["state"] == state.model_dump(mode="json")
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))


def test_save_reopen_delete_session(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from deepdebug.sessions import SessionStore
    from deepdebug.ui import app as ui_app

    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr(ui_app, "SessionStore", lambda root: store)
    at = app()
    at.radio[0].set_value("离线预置演示").run()
    button(at, "运行依赖案例演示").click().run()
    state = at.session_state["result"]
    button(at, "保存当前会话").click().run()
    assert not at.exception
    key = at.session_state["saved_id"]
    assert store.load(key).state == state
    button(at, "清除当前会话").click().run()
    assert "result" not in at.session_state
    button(at, "打开选中会话").click().run()
    assert not at.exception
    assert at.radio[0].value == "已保存会话"
    assert at.session_state["result"] == state
    assert at.session_state["events"][-1]["state"] == state.model_dump(mode="json")
    button(at, "删除选中会话").click().run()
    assert not at.exception and store.list_sessions() == []
    assert "result" not in at.session_state


@pytest.mark.parametrize("with_trace", [False, True])
def test_open_saved_collection_without_report(tmp_path, monkeypatch, with_trace):
    pytest.importorskip("streamlit")
    from datetime import datetime, timezone

    from deepdebug.agent.state import DiagnosisState
    from deepdebug.sessions import SavedSession, SessionStore
    from deepdebug.ui import app as ui_app

    store = SessionStore(tmp_path / "sessions")
    timestamp = datetime.now(timezone.utc)
    trace = (
        json.dumps(
            dict(
                sequence=1,
                event="checkpoint",
                details={},
                recorded_at=timestamp.isoformat(),
                session_id="collected",
                state={"session_id": "collected"},
            )
        )
        if with_trace
        else ""
    )
    store.save(
        SavedSession(saved_at=timestamp, state=DiagnosisState(session_id="collected"), trace=trace)
    )
    monkeypatch.setattr(ui_app, "SessionStore", lambda root: store)
    at = app()
    button(at, "打开选中会话").click().run()
    assert not at.exception
    assert at.session_state["result"].report is None
    assert any("尚无诊断报告" in message.value for message in at.info)
    assert len(at.get("download_button")) == (2 if with_trace else 1)
