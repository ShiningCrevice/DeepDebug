"""Command-line entry point; diagnosis commands will be added incrementally."""

import argparse
import json
from collections.abc import Sequence
from importlib.metadata import version

from deepdebug.agent.actions import ACTION_ADAPTER
from deepdebug.agent.schemas import DiagnosisReport, EnvironmentSnapshot
from deepdebug.agent.state import DiagnosisState


def main(argv: Sequence[str] | None = None) -> int:
    """Show available commands without probing environments or calling models."""
    parser = argparse.ArgumentParser(
        prog="deepdebug",
        description="DeepDebug：面向 PyTorch 故障的证据驱动诊断助手。",
        epilog="当前阶段：数据协议与开发案例；诊断功能尚未实现。",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('deepdebug-agent')}"
    )
    commands = parser.add_subparsers(dest="command")
    schema = commands.add_parser("schema", help="输出数据协议的 JSON Schema")
    schema.add_argument("kind", choices=["action", "state", "report", "snapshot"])
    args = parser.parse_args(argv)
    if args.command == "schema":
        schemas = {
            "action": ACTION_ADAPTER.json_schema,
            "state": DiagnosisState.model_json_schema,
            "report": DiagnosisReport.model_json_schema,
            "snapshot": EnvironmentSnapshot.model_json_schema,
        }
        print(json.dumps(schemas[args.kind](), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 0
