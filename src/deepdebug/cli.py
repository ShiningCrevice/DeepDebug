"""Command-line entry point; diagnosis commands will be added incrementally."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv

from deepdebug.agent.actions import ACTION_ADAPTER
from deepdebug.agent.decision import Decision
from deepdebug.agent.schemas import Category, CloudConsent, DiagnosisReport, EnvironmentSnapshot
from deepdebug.agent.state import Budget, DiagnosisState
from deepdebug.collection import collect, search_documents
from deepdebug.diagnosis import diagnose
from deepdebug.replay import load_replay, replay, replay_reviewed
from deepdebug.reporting.render import check_report_files, export_report, load_state, save_export
from deepdebug.security.destination import DEFAULT_BASE_URL, responses_endpoint
from deepdebug.security.paths import MaterialError
from deepdebug.security.review import (
    MaterialReview,
    confirm_materials,
    load_review,
    preview_materials,
    save_review,
)
from deepdebug.tools.capture import CaptureError, capture_environment


def _show_materials(review: MaterialReview) -> None:
    print("材料范围：", file=sys.stderr)
    for item in review.content.materials:
        artifact = item.artifact
        print(
            f"  {artifact.display_name} ({artifact.kind}, {artifact.size_bytes} bytes)",
            file=sys.stderr,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse commands and emit local JSON, including offline model-response replay."""
    parser = argparse.ArgumentParser(
        prog="deepdebug",
        description="DeepDebug：面向 PyTorch 故障的证据驱动诊断助手。",
        epilog="支持本地取证、脱敏确认、离线回放，以及显式授权后的云端诊断。",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('deepdebug-agent')}"
    )
    commands = parser.add_subparsers(dest="command")
    schema = commands.add_parser("schema", help="输出数据协议的 JSON Schema")
    schema.add_argument("kind", choices=["action", "state", "report", "snapshot", "decision"])
    report = commands.add_parser("report", help="从完整状态导出报告；不调用模型")
    report.add_argument("--state", type=Path, required=True)
    report.add_argument("--format", choices=["markdown", "json"], default="markdown")
    report.add_argument("--output", type=Path, help="新建输出文件；省略时输出到标准输出")
    check_report = commands.add_parser("check-report", help="检查 Markdown 与 JSON 报告一致性")
    check_report.add_argument("--json", type=Path, required=True)
    check_report.add_argument("--markdown", type=Path, required=True)
    preview = commands.add_parser("preview", help="预览显式材料的脱敏副本，保存待确认 JSON")
    preview.add_argument("--root", type=Path, required=True, help="独立材料目录")
    preview.add_argument("--log", required=True)
    preview.add_argument("--code", action="append", default=[])
    preview.add_argument("--config", action="append", default=[])
    preview.add_argument("--snapshot", action="append", default=[])
    preview.add_argument("--output", type=Path, required=True, help="新建本地预览文件")
    confirm = commands.add_parser("confirm", help="确认已核查全部预览材料，保存确认副本")
    confirm.add_argument("--preview", type=Path, required=True)
    confirm.add_argument("--output", type=Path, required=True, help="新建已确认材料文件")
    diagnosis = commands.add_parser("diagnose", help="授权已核查材料发送至指定模型并诊断")
    diagnosis.add_argument("--reviewed", type=Path, required=True)
    diagnosis.add_argument("--model", required=True, help="支持 Responses JSON mode 的模型 ID")
    diagnosis.add_argument(
        "--base-url",
        help="API 基础地址（含版本前缀）；优先于 OPENAI_BASE_URL，默认 https://api.openai.com/v1",
    )
    diagnosis.add_argument(
        "--send-to",
        required=True,
        help="确认材料片段、工具结果及判断发送至此完整地址；须匹配 base_url + /responses",
    )
    diagnosis.add_argument("--trace", type=Path)
    diagnosis.add_argument("--max-decisions", type=int, default=6)
    diagnosis.add_argument("--max-tools", type=int, default=8)
    diagnosis.add_argument("--max-seconds", type=int, default=120)
    diagnosis.add_argument(
        "--max-tokens", type=int, default=50_000, help="总 token 预算，含报告预留 5,000"
    )
    replay_parser = commands.add_parser("replay", help="离线回放固定模型响应，输出状态与 JSON 报告")
    replay_source = replay_parser.add_mutually_exclusive_group(required=True)
    replay_source.add_argument("--root", type=Path, help="独立材料目录")
    replay_source.add_argument("--reviewed", type=Path, help="使用已确认脱敏材料文件")
    replay_parser.add_argument("--log")
    replay_parser.add_argument("--code", action="append", default=[])
    replay_parser.add_argument("--config", action="append", default=[])
    replay_parser.add_argument("--snapshot", action="append", default=[])
    replay_parser.add_argument("--path", action="append", default=[])
    replay_parser.add_argument("--path-root", type=Path)
    replay_parser.add_argument("--responses", type=Path, required=True, help="固定响应 JSON 文件")
    replay_parser.add_argument("--trace", type=Path, help="新建 JSONL 轨迹文件；父目录须已存在")
    replay_parser.add_argument("--max-decisions", type=int, default=6)
    replay_parser.add_argument("--max-tools", type=int, default=8)
    replay_parser.add_argument("--max-seconds", type=int, default=120)
    search = commands.add_parser("search-docs", help="检索本地官方文档摘要并输出带证据的状态")
    search.add_argument("query", help="查询词，1～500 字符")
    search.add_argument("--category", choices=get_args(Category), help="按故障类别过滤")
    search.add_argument("--max-results", type=int, choices=[1, 2, 3], default=3)
    capture = commands.add_parser("snapshot", help="显式选择本机解释器，采集环境快照 JSON")
    capture.add_argument("--python", type=Path, required=True, help="目标解释器的绝对路径")
    capture.add_argument("--environment-id", required=True, help="用户指定的环境标识")
    capture.add_argument("--package", action="append", default=[], help="查询包元数据，最多 10 个")
    capture.add_argument("--torch-cuda", action="store_true", help="在隔离进程中导入 PyTorch")
    capture.add_argument("--gpu", action="store_true", help="运行固定 nvidia-smi 查询")
    collection = commands.add_parser("collect", help="只读登记材料并输出取证状态 JSON")
    collection.add_argument("--root", type=Path, required=True, help="独立材料目录")
    collection.add_argument("--log", required=True, help="根目录内的日志相对路径")
    collection.add_argument("--code", action="append", default=[], help="代码材料，可重复")
    collection.add_argument("--config", action="append", default=[], help="配置材料，可重复")
    collection.add_argument(
        "--snapshot", action="append", default=[], help="环境快照，可重复；第一份为目标环境"
    )
    collection.add_argument("--query-gpu", action="store_true", help="读取每份快照中的 GPU 结果")
    collection.add_argument("--path", action="append", default=[], help="登记并检查本机相对路径")
    collection.add_argument("--path-root", type=Path, help="路径检查的独立授权目录，默认同 --root")
    collection.add_argument("--docs-query", help="追加一次本地文档检索，最多返回 3 条")
    collection.add_argument("--docs-category", choices=get_args(Category), help="文档故障类别过滤")
    args = parser.parse_args(argv)
    if args.command in {"report", "check-report"}:
        try:
            if args.command == "check-report":
                matches = check_report_files(args.json, args.markdown)
                print("报告内容一致。" if matches else "Markdown 与 JSON 报告不一致。")
                return 0 if matches else 1
            json_report, markdown = export_report(load_state(args.state))
            content = markdown if args.format == "markdown" else json_report
            if args.output:
                save_export(args.output, content)
            else:
                print(content, end="")
        except (OSError, ValueError, RecursionError):
            print(
                "报告操作失败：检查完整状态、报告文件及输出路径；输出文件必须不存在。",
                file=sys.stderr,
            )
            return 2
        return 0
    if args.command in {"preview", "confirm"}:
        try:
            if args.command == "preview":
                review = preview_materials(
                    args.root, args.log, args.code, args.config, args.snapshot
                )
            else:
                review = confirm_materials(load_review(args.preview))
                _show_materials(review)
            save_review(args.output, review)
        except (OSError, ValueError, RecursionError):
            print(
                "材料预览/确认失败：检查输入、内容摘要和输出路径；输出文件必须不存在。",
                file=sys.stderr,
            )
            return 2
        print(review.model_dump_json(indent=2))
        if args.command == "preview":
            print(
                "请核查全部 text 及材料范围；自动脱敏可能遗漏。"
                "confirm 仅确认本地副本；diagnose 需另行指定外发目的地和模型。",
                file=sys.stderr,
            )
        return 0
    if args.command == "diagnose":
        try:
            load_dotenv(Path.cwd() / ".env", override=False)
            review = load_review(args.reviewed)
            consent = CloudConsent(
                material_review_sha256=review.sha256,
                endpoint=args.send_to,
                model=args.model,
                confirmed_at=datetime.now(timezone.utc),
            )
            base_url = (
                args.base_url
                if args.base_url is not None
                else os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
            )
            if consent.endpoint != responses_endpoint(base_url):
                print("--send-to 必须与 base_url 后追加 /responses 的地址一致。", file=sys.stderr)
                return 2
            _show_materials(review)
            print(f"发送至：{consent.endpoint}；模型：{consent.model}", file=sys.stderr)
            budget = Budget(
                max_tokens=args.max_tokens,
                max_decision_calls=args.max_decisions,
                max_tool_calls=args.max_tools,
                max_duration_seconds=args.max_seconds,
            )
            trace_context = (
                args.trace.open("x", encoding="utf-8") if args.trace else nullcontext(None)
            )
            with trace_context as stream:
                state = diagnose(review, consent, budget=budget, trace_stream=stream)
        except (OSError, ValueError, MaterialError):
            print(
                "诊断启动失败：检查材料、摘要、base_url、--send-to、模型、密钥、预算与轨迹路径。",
                file=sys.stderr,
            )
            return 2
        print(state.model_dump_json(indent=2))
        return 0 if state.stop_reason in {"completed", "need_info", "no_progress"} else 1
    if args.command == "replay":
        if args.root and not args.log:
            parser.error("--root 需要 --log。")
        if args.reviewed and any(
            (args.log, args.code, args.config, args.snapshot, args.path, args.path_root)
        ):
            parser.error("--reviewed 仅使用已确认材料，不能追加原始材料或本机路径。")
        if args.path_root and not args.path:
            parser.error("--path-root 需要至少一个 --path。")
        try:
            review = load_review(args.reviewed) if args.reviewed else None
            if review is not None and review.status != "confirmed":
                raise ValueError("材料尚未确认。")
            model = load_replay(args.responses)
            budget = Budget(
                max_decision_calls=args.max_decisions,
                max_tool_calls=args.max_tools,
                max_duration_seconds=args.max_seconds,
            )
            trace_context = (
                args.trace.open("x", encoding="utf-8") if args.trace else nullcontext(None)
            )
            with trace_context as stream:
                if review is not None:
                    state = replay_reviewed(review, model, budget=budget, trace_stream=stream)
                else:
                    state = replay(
                        args.root,
                        args.log,
                        args.code,
                        args.config,
                        args.snapshot,
                        model,
                        budget=budget,
                        paths=args.path,
                        path_root=args.path_root,
                        trace_stream=stream,
                    )
        except (OSError, ValueError, MaterialError):
            print(
                "回放失败：请检查材料、响应文件、预算与轨迹路径；轨迹文件不得已存在。",
                file=sys.stderr,
            )
            return 2
        print(state.model_dump_json(indent=2))
        return 0 if state.stop_reason in {"completed", "need_info", "no_progress"} else 1
    if args.command == "search-docs":
        state = search_documents(args.query, args.category, args.max_results)
        print(state.model_dump_json(indent=2))
        return 0 if state.tool_history[0].result.status == "ok" else 1
    if args.command == "snapshot":
        try:
            snapshot = capture_environment(
                args.python,
                args.environment_id,
                args.package,
                torch_cuda=args.torch_cuda,
                gpu=args.gpu,
            )
        except CaptureError as exc:
            print(f"环境采集失败：{exc}", file=sys.stderr)
            return 2
        print(snapshot.model_dump_json(indent=2, exclude_none=True))
        failed = any(p.status == "error" for p in snapshot.packages) or any(
            probe is not None and probe.status != "ok"
            for probe in (snapshot.torch_cuda, snapshot.gpu)
        )
        return 1 if failed else 0
    if args.command == "collect":
        if args.query_gpu and not args.snapshot:
            parser.error("--query-gpu 需要至少一份 --snapshot。")
        if args.path_root and not args.path:
            parser.error("--path-root 需要至少一个 --path。")
        if args.docs_category and args.docs_query is None:
            parser.error("--docs-category 需要 --docs-query。")
        try:
            state = collect(
                args.root,
                args.log,
                args.code,
                args.config,
                args.snapshot,
                paths=args.path,
                path_root=args.path_root,
                query_gpu=args.query_gpu,
                docs_query=args.docs_query,
                docs_category=args.docs_category,
            )
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
            "decision": Decision.model_json_schema,
        }
        print(json.dumps(schemas[args.kind](), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 0
