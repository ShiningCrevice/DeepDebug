"""Render both report formats from one validated state without model calls."""

import json
import os
import re
from pathlib import Path

from deepdebug.agent.schemas import DiagnosisReport
from deepdebug.agent.state import DiagnosisState
from deepdebug.security.paths import AuthorizedRoot

MAX_STATE_BYTES = 128 * 1024 * 1024

# Explicit sections keep report order independent of serialization internals.
SECTIONS = (
    ("schema_version", "协议版本"),
    ("session_id", "会话"),
    ("materials", "输入材料目录"),
    ("summary", "问题摘要"),
    ("category", "故障类别"),
    ("target_environment", "目标环境（采集时刻）"),
    ("evidence", "已观察事实与文档来源"),
    ("hypotheses", "候选根因"),
    ("fixes", "修复建议与验证方法"),
    ("verifications", "验证结果"),
    ("unresolved_questions", "未决问题"),
    ("tool_history", "工具记录"),
    ("stop_reason", "停止原因"),
)
LABELS = {
    "fix_index": "关联修复序号",
    "artifact_id": "材料编号",
    "display_name": "显示名称",
    "origin": "登记来源",
    "size_bytes": "字节数",
    "redaction_status": "脱敏状态",
    "mode": "模式",
    "environment_id": "环境标识",
    "interpreter": "解释器",
    "collected_at": "采集时间",
    "evidence_id": "证据编号",
    "source": "来源",
    "kind": "类型",
    "id": "来源编号",
    "url": "来源 URL",
    "applicable_version": "适用版本",
    "location": "位置",
    "start": "起始行",
    "end": "结束行",
    "pointer": "JSON Pointer",
    "content": "证据原文",
    "truncated": "已截断",
    "hypothesis_id": "假设编号",
    "cause": "候选原因",
    "confidence": "置信度",
    "supporting_evidence": "支持证据",
    "opposing_evidence": "反对证据",
    "pending_checks": "待检查项",
    "description": "建议",
    "conditions": "适用条件",
    "impact": "影响",
    "evidence_ids": "引用证据",
    "verification_steps": "验证步骤",
    "success_criteria": "成功判据",
    "check_id": "检查编号",
    "status": "状态",
    "reason": "原因",
    "execution": "执行记录",
    "executed_at": "执行时间",
    "exit_code": "退出码",
    "output": "输出",
    "tool": "工具",
    "purpose": "目的",
    "arguments_summary": "参数摘要",
    "result": "结果",
    "tool_call_id": "调用编号",
    "data": "数据",
    "duration_ms": "耗时 ms",
    "error": "错误",
}


def _literal(text: str) -> str:
    """Use a longer fence than any input run, retaining text as inert data."""
    fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", text)), default=0))
    return f"{fence}text\n{text}\n{fence}\n"


def _fields(value: object, indent: str = "") -> str:
    if isinstance(value, dict) and value:
        lines = []
        for key, item in value.items():
            # Tool result data has arbitrary keys; serialize it as literal JSON.
            lines.append(f"{indent}- **{LABELS.get(key, key)}**\n")
            if key == "data":
                rendered = _literal(json.dumps(item, ensure_ascii=False, indent=2))
                lines.append(
                    "\n" + "".join(indent + "  " + s + "\n" for s in rendered.split("\n")[:-1])
                )
            else:
                lines.append(_fields(item, indent + "  "))
        return "".join(lines)
    if isinstance(value, list) and value:
        return "".join(
            f"{indent}{i}.\n" + _fields(item, indent + " " * (len(str(i)) + 2))
            for i, item in enumerate(value, 1)
        )
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return "\n" + "".join(indent + s + "\n" for s in _literal(text).split("\n")[:-1]) + "\n"


def render_markdown(report: DiagnosisReport) -> str:
    report = DiagnosisReport.model_validate(report)
    data = report.model_dump(mode="json")
    return "# DeepDebug 诊断报告\n\n" + "".join(
        f"## {title}\n\n{_fields(data[key])}\n" for key, title in SECTIONS
    )


def export_report(state: DiagnosisState) -> tuple[str, str]:
    """Revalidate state/report links, then return JSON and Markdown of that report."""
    state = DiagnosisState.model_validate(state)
    if state.report is None:
        raise ValueError("状态尚无诊断报告。")
    # Older saved states predate the report material directory; use their registry.
    report = DiagnosisReport.model_validate(
        {**state.report.model_dump(), "materials": state.inputs}
    )
    return report.model_dump_json(indent=2) + "\n", render_markdown(report)


def load_state(path: Path) -> DiagnosisState:
    with AuthorizedRoot(path.absolute().parent) as root:
        return DiagnosisState.model_validate_json(root.read(path.name, max_bytes=MAX_STATE_BYTES))


def save_export(path: Path, content: str) -> None:
    # Raw replay reports can contain private material; never replace existing files.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)


def check_report_files(json_path: Path, markdown_path: Path) -> bool:
    with AuthorizedRoot(json_path.absolute().parent) as root:
        report = DiagnosisReport.model_validate_json(
            root.read(json_path.name, max_bytes=MAX_STATE_BYTES)
        )
    with AuthorizedRoot(markdown_path.absolute().parent) as root:
        markdown = root.read(markdown_path.name, max_bytes=MAX_STATE_BYTES).decode("utf-8")
    return markdown == render_markdown(report)
