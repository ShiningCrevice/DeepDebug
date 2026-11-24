"""Report export preserves facts and rejects invalid state at the output boundary."""

import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepdebug.agent.schemas import DiagnosisReport
from deepdebug.agent.state import DiagnosisState
from deepdebug.cli import main
from deepdebug.replay import load_replay, replay
from deepdebug.reporting.render import check_report_files, export_report, render_markdown

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def state():
    return replay(
        ROOT / "benchmark/dev/dep_002/materials",
        "log.txt",
        [],
        ["launch.json"],
        ["target_snapshot.json", "project_snapshot.json"],
        load_replay(ROOT / "examples/dep_002_replay.json"),
    )


def test_export_preserves_complete_report(state):
    json_text, markdown = export_report(state)
    assert DiagnosisReport.model_validate_json(json_text) == state.report
    data = json.loads(json_text)
    assert data["verifications"][0]["status"] == "未执行"
    assert "未执行" in markdown
    assert "ENV_EMPTY" in markdown
    assert "支持证据" in markdown and "反对证据" in markdown
    assert "适用条件" in markdown and "成功判据" in markdown

    # Each scalar fact, including source positions, times and tool results, is visible.
    def assert_visible(value):
        if isinstance(value, dict):
            for item in value.values():
                assert_visible(item)
        elif isinstance(value, list):
            for item in value:
                assert_visible(item)
        elif isinstance(value, str):
            for line in value.splitlines():
                assert line in markdown or json.dumps(line, ensure_ascii=False)[1:-1] in markdown
        else:
            assert json.dumps(value) in markdown

    assert_visible(data)


def test_document_provenance_and_hostile_content_are_literal(state):
    payload = (
        "```\n# forged heading\n<script>alert(1)</script>\n![image](https://example.com)\n````"
    )
    data = state.model_dump(mode="json")
    data["evidence"][0]["content"] = payload
    data["report"]["evidence"][0]["content"] = payload
    evidence = dict(
        evidence_id="E999",
        source=dict(
            kind="document",
            id="D001",
            url="https://pytorch.org/docs/stable/",
            applicable_version="PyTorch 2.9",
        ),
        location=dict(kind="field", pointer="/excerpt"),
        content="通用规则",
        collected_at="2026-01-01T00:00:00Z",
        truncated=True,
    )
    data["evidence"].append(evidence)
    data["report"]["evidence"].append(evidence)
    _, markdown = export_report(DiagnosisState.model_validate(data))
    assert "`````text" in markdown
    assert "https://pytorch.org/docs/stable/" in markdown
    assert "PyTorch 2.9" in markdown and "/excerpt" in markdown
    assert "已截断" in markdown


@pytest.mark.parametrize("mutation", ["evidence", "hypothesis", "environment", "stop"])
def test_export_revalidates_mutable_state(state, mutation):
    if mutation == "evidence":
        state.report.evidence[0] = state.report.evidence[0].model_copy(
            update={"content": "changed"}
        )
    elif mutation == "hypothesis":
        state.report.hypotheses[0].supporting_evidence.append("E999")
    elif mutation == "environment":
        state.report.target_environment = None
    else:
        state.stop_reason = "model_error"
    with pytest.raises(ValidationError):
        export_report(state)


def test_no_report_is_not_exportable():
    with pytest.raises(ValueError, match="尚无"):
        export_report(DiagnosisState(session_id="empty"))


@pytest.mark.parametrize(
    "reason", ["need_info", "budget_exhausted", "model_error", "tools_unavailable"]
)
def test_stopped_reports_preserve_failure_and_questions(state, reason):
    data = state.model_dump(mode="json")
    data["stop_reason"] = data["report"]["stop_reason"] = reason
    data["report"]["unresolved_questions"] = ["请补充运行环境。"]
    _, markdown = export_report(DiagnosisState.model_validate(data))
    assert reason in markdown and "请补充运行环境。" in markdown
    assert "未执行" in markdown


def test_cli_export_check_and_no_overwrite(state, tmp_path, capsys):
    source = tmp_path / "state.json"
    source.write_text(state.model_dump_json(), encoding="utf-8")
    md, js = tmp_path / "report.md", tmp_path / "report.json"
    for fmt, path in [("markdown", md), ("json", js)]:
        args = ["report", "--state", str(source), "--format", fmt, "--output", str(path)]
        assert main(args) == 0
        before = path.read_bytes()
        assert main(args) == 2
        assert path.read_bytes() == before
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    check_args = ["check-report", "--json", str(js), "--markdown", str(md)]
    assert main(check_args) == 0
    assert check_report_files(js, md)
    md.write_text(md.read_text().replace("未执行", "预置复现通过"))
    assert main(check_args) == 1
    assert main(["report", "--state", str(source)]) == 0
    assert "# DeepDebug 诊断报告" in capsys.readouterr().out


def test_cli_rejects_invalid_state_and_links(tmp_path):
    source = tmp_path / "state.json"
    source.write_text('{"session_id":"empty"}')
    output = tmp_path / "report.md"
    args = ["report", "--state", str(source), "--output", str(output)]
    assert main(args) == 2
    assert not output.exists()
    link = tmp_path / "link.json"
    link.symlink_to(source)
    assert main(["report", "--state", str(link)]) == 2


def test_render_revalidates_report(state):
    state.report.fixes[0].evidence_ids.append("E999")
    with pytest.raises(ValidationError):
        render_markdown(state.report)


def test_literal_preserves_non_lf_separators_and_wide_list_numbers(state):
    content = "a\rb\x85c\u2028d\u2029e\vf\fg"
    data = state.model_dump(mode="json")
    data["evidence"][0]["content"] = content
    data["report"]["evidence"][0]["content"] = content
    data["report"]["unresolved_questions"] = [f"问题 {i}" for i in range(12)]
    _, markdown = export_report(DiagnosisState.model_validate(data))
    assert content in markdown
    assert "10.\n\n    ```text\n    问题 9" in markdown


def test_legacy_state_export_restores_material_directory(state):
    data = state.model_dump(mode="json")
    del data["report"]["materials"]
    legacy = DiagnosisState.model_validate(data)
    json_text, markdown = export_report(legacy)
    report = DiagnosisReport.model_validate_json(json_text)
    assert report.materials == state.inputs
    assert "log.txt" in markdown and "launch.json" in markdown
    assert legacy.report.materials == []


def test_export_rejects_incorrect_material_directory(state):
    state.report.materials[0] = state.inputs[0].model_copy(update={"display_name": "wrong.txt"})
    with pytest.raises(ValidationError, match="materials"):
        export_report(state)
