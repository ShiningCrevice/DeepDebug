"""Preview/consent boundaries and evidence from frozen, redacted content."""

import io
import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepdebug.agent.controller import Controller
from deepdebug.agent.state import DiagnosisState
from deepdebug.cli import main
from deepdebug.llm.client import ModelResponse, ReplayModelClient
from deepdebug.replay import load_replay, replay_reviewed
from deepdebug.security.paths import AuthorizedRoot, MaterialError
from deepdebug.security.redaction import Redactor
from deepdebug.security.review import (
    MaterialReview,
    confirm_materials,
    load_review,
    preview_materials,
    reviewed_registry,
    save_review,
)
from deepdebug.tools.registry import ToolDispatcher
from deepdebug.tools.session import CollectionSession

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "text,secret",
    [
        ('API_KEY="fake key with spaces"', "fake key with spaces"),
        ("password: 'private words'", "private words"),
        ("OPENAI_API_KEY=sk-test-1234567890abcdef", "sk-test-1234567890abcdef"),
        ("Authorization: Bearer eyJfake.payload.signature", "eyJfake.payload.signature"),
        ("token=abcdef1234", "abcdef1234"),
        ("aws_secret_access_key: fake-aws-secret", "fake-aws-secret"),
        ("ghp_123456789012345678901234", "ghp_123456789012345678901234"),
        ("hf_123456789012345678901234", "hf_123456789012345678901234"),
        ("https://user:private-pass@example.com/path", "user:private-pass"),
        ("/home/alice/env/bin/python", "/home/alice"),
        ("/Users/alice/project/train.py", "/Users/alice"),
        (r"C:\Users\alice\env\python.exe", r"C:\Users\alice"),
        ('password="invalid\\escape"', r"invalid\escape"),
        (r'API_KEY="private\"quoted\\secret"', r"private\"quoted\\secret"),
    ],
)
def test_common_patterns_and_cross_material_repetition(text, secret):
    redactor = Redactor([text, f"copied: {secret}"])
    assert secret not in redactor.redact(text)
    assert secret not in redactor.redact(f"copied: {secret}")


def test_json_escaping_line_numbers_and_path_relationships():
    secret = 'private "quoted" \\ secret'
    source = json.dumps(
        {
            "api_key": secret,
            "copy": secret,
            "windows": r"C:\Users\alice\env\python.exe",
            "unicode": "/home/小明/env/python",
            "password": 12345,
        },
        ensure_ascii=True,
        indent=2,
    )
    log = "File /home/小明/project/train.py\nRuntimeError: failed\n"
    redactor = Redactor([source, log])
    result = redactor.redact(source)
    data = json.loads(result)
    assert secret not in data.values()
    assert data["copy"] == data["api_key"]
    assert "alice" not in data["windows"]
    assert "小明" not in data["unicode"]
    assert data["password"] == "[REDACTED_SECRET]"
    assert result.count("\n") == source.count("\n")
    assert redactor.redact(log).count("\n") == log.count("\n")
    assert data["unicode"].split("/env")[0] in redactor.redact(log)


def test_private_key_keeps_physical_lines():
    key = "-----BEGIN PRIVATE KEY-----\r\nSECRETLINE1\r\nSECRETLINE2\r\n-----END PRIVATE KEY-----"
    source = "before\r\n" + key + "\r\nRuntimeError: after\r\n"
    result = Redactor([source]).redact(source)
    assert "SECRETLINE" not in result
    assert result.count("\r\n") == source.count("\r\n")
    assert result.splitlines()[-1] == "RuntimeError: after"


def test_escaped_newline_in_plain_secret_does_not_add_lines():
    text = r'API_KEY="private\nsecret"' + "\nRuntimeError: failed\n"
    result = Redactor([text]).redact(text)
    assert "private" not in result
    assert result.count("\n") == text.count("\n")


@pytest.fixture
def preview(tmp_path):
    (tmp_path / "private-name.log").write_text(
        'API_KEY="fake-integration-secret"\n'
        '  File "/home/alice/project/train.py", line 3, in <module>\n'
        "RuntimeError: fake-integration-secret\n",
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text(
        '{"token": "fake-integration-secret", "path": "/home/alice/env/python"}',
        encoding="utf-8",
    )
    return preview_materials(tmp_path, "private-name.log", [], ["config.json"], [])


def test_preview_scope_metadata_and_confirmation(preview, tmp_path):
    serialized = preview.model_dump_json()
    for private in ("private-name", "fake-integration-secret", "/home/alice", str(tmp_path)):
        assert private not in serialized
    assert preview.status == "preview"
    with pytest.raises(MaterialError, match="尚未确认"):
        reviewed_registry(preview)
    confirmed = confirm_materials(preview)
    assert confirmed.confirmed_at is not None
    assert confirmed.sha256 == preview.sha256
    registry = reviewed_registry(confirmed)
    assert all(a.redaction_status == "reviewed" for a in registry.artifacts())
    assert all(item.artifact.redaction_status == "pending" for item in preview.content.materials)
    with pytest.raises(ValueError):
        confirm_materials(confirmed)


@pytest.mark.parametrize("change", ["text", "remove", "order", "type", "status", "time"])
def test_changed_preview_cannot_reuse_confirmation(preview, change):
    data = preview.model_dump(mode="json")
    if change == "text":
        data["content"]["materials"][0]["text"] += "x"
    elif change == "remove":
        data["content"]["materials"].pop()
    elif change == "order":
        data["content"]["materials"].reverse()
    elif change == "type":
        data["content"]["materials"][1]["artifact"]["kind"] = "code"
    elif change == "status":
        data["status"] = "confirmed"
    else:
        data["content"]["materials"][0]["registered_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        MaterialReview.model_validate(data)


def test_boundaries_revalidate_mutated_models(preview, tmp_path):
    preview.content.materials[0].text += "changed"
    for operation in (
        lambda: confirm_materials(preview),
        lambda: save_review(tmp_path / "out.json", preview),
        lambda: reviewed_registry(preview),
    ):
        with pytest.raises(ValueError):
            operation()
    assert not (tmp_path / "out.json").exists()


def test_owner_only_exclusive_output_and_link_rejection(preview, tmp_path):
    output = tmp_path / "preview.json"
    save_review(output, preview)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert load_review(output) == preview
    with pytest.raises(FileExistsError):
        save_review(output, preview)
    link = tmp_path / "link.json"
    link.symlink_to(output)
    with pytest.raises(MaterialError):
        load_review(link)


def test_review_bundle_supports_multiple_materials_over_two_mib(tmp_path):
    text = "plain text\n" * 100_000
    (tmp_path / "log.txt").write_text(text)
    (tmp_path / "code.py").write_text(text)
    preview = preview_materials(tmp_path, "log.txt", ["code.py"], [], [])
    output = tmp_path / "preview.json"
    save_review(output, preview)
    assert output.stat().st_size > 2 * 1024 * 1024
    assert load_review(output) == preview
    with AuthorizedRoot(tmp_path) as root, pytest.raises(MaterialError, match="2 MiB"):
        root.read("preview.json")


def test_review_keeps_input_count_and_size_limits(tmp_path):
    (tmp_path / "log.txt").write_text("x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(MaterialError):
        preview_materials(tmp_path, "log.txt", [], [], [])
    (tmp_path / "log.txt").write_text("RuntimeError: test")
    names = [f"code{i}.py" for i in range(10)]
    for name in names:
        (tmp_path / name).write_text("pass")
    with pytest.raises(MaterialError, match="10"):
        preview_materials(tmp_path, "log.txt", names, [], [])


def test_reviewed_replay_uses_frozen_content_in_requests_report_and_trace(preview, tmp_path):
    confirmed = confirm_materials(preview)
    (tmp_path / "private-name.log").write_text("RuntimeError: CHANGED_AFTER_PREVIEW")
    (tmp_path / "config.json").unlink()
    decisions = [
        dict(
            observation="读取配置",
            hypotheses=[],
            action=dict(
                action="tool",
                tool="read_artifact",
                arguments={"artifact_id": "A002"},
                purpose="查看配置",
            ),
        ),
        dict(
            observation="需补充材料",
            hypotheses=[],
            action=dict(
                action="need_info",
                questions=["请提供环境快照"],
                reason="缺少环境信息",
            ),
        ),
    ]

    class RecordingModel(ReplayModelClient):
        def decide(self, request):
            requests.append(request.model_dump_json())
            return super().decide(request)

    requests = []
    model = RecordingModel(ModelResponse(content=json.dumps(d)) for d in decisions)
    trace = io.StringIO()
    state = replay_reviewed(confirmed, model, trace_stream=trace)
    assert state.stop_reason == "need_info"
    assert state.material_review_sha256 == preview.sha256
    assert state.report.verifications[0].status == "未执行"
    outputs = "\n".join([state.model_dump_json(), trace.getvalue(), *requests])
    for secret in (
        "fake-integration-secret",
        "/home/alice",
        "private-name",
        "CHANGED_AFTER_PREVIEW",
    ):
        assert secret not in outputs
    for evidence in state.evidence:
        if evidence.location.kind == "lines":
            item = confirmed.content.materials[int(evidence.source.id[1:]) - 1]
            assert evidence.content == "\n".join(
                item.text.splitlines()[evidence.location.start - 1 : evidence.location.end]
            )
    for event in trace.getvalue().splitlines():
        DiagnosisState.model_validate(json.loads(event)["state"])


def test_real_development_replay_and_snapshot_field_evidence():
    preview = preview_materials(
        ROOT / "benchmark/dev/dep_002/materials",
        "log.txt",
        [],
        ["launch.json"],
        ["target_snapshot.json", "project_snapshot.json"],
    )
    confirmed = confirm_materials(preview)
    state = replay_reviewed(confirmed, load_replay(ROOT / "examples/dep_002_replay.json"))
    assert state.stop_reason == "completed"
    assert state.target_environment.environment_id == "ENV_EMPTY"
    for evidence in state.evidence:
        if evidence.source.kind == "snapshot":
            item = confirmed.content.materials[int(evidence.source.id[1:]) - 1]
            value = json.loads(item.text)
            for part in evidence.location.pointer.lstrip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
            assert json.loads(evidence.content) == value


def test_remote_still_rejected_after_confirmation(preview):
    model = ReplayModelClient([])
    model.transport = "remote"
    session = CollectionSession(reviewed_registry(confirm_materials(preview)))
    with pytest.raises(ValueError, match="云端模型需要已确认"):
        Controller(ToolDispatcher(session), model)


def test_review_digest_cannot_label_pending_state():
    with pytest.raises(ValidationError):
        DiagnosisState(session_id="test", material_review_sha256="0" * 64)


def test_cli_preview_confirm_replay(preview, tmp_path, capsys):
    output = tmp_path / "preview.json"
    assert (
        main(
            [
                "preview",
                "--root",
                str(tmp_path),
                "--log",
                "private-name.log",
                "--config",
                "config.json",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "自动脱敏可能遗漏" in captured.err
    reviewed = tmp_path / "reviewed.json"
    changed = {**data, "sha256": "0" * 64}
    output.write_text(json.dumps(changed))
    assert main(["confirm", "--preview", str(output), "--output", str(reviewed)]) == 2
    output.write_text(json.dumps(data))
    assert not reviewed.exists()
    capsys.readouterr()
    assert (
        main(
            [
                "confirm",
                "--preview",
                str(output),
                "--output",
                str(reviewed),
            ]
        )
        == 0
    )
    confirmed_output = capsys.readouterr()
    assert "材料范围" in confirmed_output.err
    assert "A001.log" in confirmed_output.err
    responses = ROOT / "examples/dep_002_replay.json"
    assert (
        main(
            [
                "replay",
                "--reviewed",
                str(reviewed),
                "--responses",
                str(responses),
                "--max-decisions",
                "1",
            ]
        )
        == 1
    )
    state = json.loads(capsys.readouterr().out)
    assert state["material_review_sha256"] == data["sha256"]
    assert state["inputs"][0]["redaction_status"] == "reviewed"
    assert main(["replay", "--reviewed", str(output), "--responses", str(responses)]) == 2
    for extra in (["--log", "log.txt"], ["--path", "data"], ["--snapshot", "extra.json"]):
        with pytest.raises(SystemExit) as exc:
            main(["replay", "--reviewed", str(reviewed), "--responses", str(responses), *extra])
        assert exc.value.code == 2


def test_invalid_preview_cli_does_not_echo_sensitive_content(tmp_path, capsys):
    output = tmp_path / "bad.json"
    output.write_text('{"password": "DO_NOT_ECHO"}')
    assert (
        main(
            [
                "confirm",
                "--preview",
                str(output),
                "--output",
                str(tmp_path / "confirmed.json"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "DO_NOT_ECHO" not in captured.out + captured.err
