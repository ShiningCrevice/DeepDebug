"""Command-line entry point; diagnosis commands will be added incrementally."""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def main(argv: Sequence[str] | None = None) -> int:
    """Show available commands without probing environments or calling models."""
    parser = argparse.ArgumentParser(
        prog="deepdebug",
        description="DeepDebug：面向 PyTorch 故障的证据驱动诊断助手。",
        epilog="当前阶段：项目初始化；诊断功能尚未实现。",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('deepdebug-agent')}"
    )
    parser.parse_args(argv)
    parser.print_help()
    return 0
