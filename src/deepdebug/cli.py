"""Command-line entry point; diagnosis commands will be added incrementally."""

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from deepdebug.agent.actions import ACTION_ADAPTER
from deepdebug.agent.schemas import DiagnosisReport, EnvironmentSnapshot
from deepdebug.agent.state import DiagnosisState
from deepdebug.collection import collect
from deepdebug.security.paths import MaterialError


def main(argv: Sequence[str] | None = None) -> int:
    """Parse commands and emit local JSON; never call a model or execute input code."""
    parser = argparse.ArgumentParser(
        prog="deepdebug",
        description="DeepDebug：面向 PyTorch 故障的证据驱动诊断助手。",
        epilog="当前阶段：本地材料取证；自动诊断尚未实现。collect 输出未经脱敏，不发送网络请求。",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('deepdebug-agent')}"
    )
    commands = parser.add_subparsers(dest="command")
    schema = commands.add_parser("schema", help="输出数据协议的 JSON Schema")
    schema.add_argument("kind", choices=["action", "state", "report", "snapshot"])
    collection = commands.add_parser("collect", help="只读登记材料并输出取证状态 JSON")
    collection.add_argument("--root", type=Path, required=True, help="独立材料目录")
    collection.add_argument("--log", required=True, help="根目录内的日志相对路径")
    collection.add_argument("--code", action="append", default=[], help="代码材料，可重复")
    collection.add_argument("--config", action="append", default=[], help="配置材料，可重复")
    collection.add_argument(
        "--snapshot", action="append", default=[], help="环境快照，可重复；第一份为目标环境"
    )
    args = parser.parse_args(argv)
    if args.command == "collect":
        try:
            state = collect(args.root, args.log, args.code, args.config, args.snapshot)
        except MaterialError as exc:
            print(f"材料登记失败：{exc}", file=sys.stderr)
            return 2
        print(state.model_dump_json(indent=2))
        return 0 if all(r.result.status == "ok" for r in state.tool_history) else 1
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
