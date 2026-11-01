"""Bounded execution for developer-owned probes; never exposed as an Agent tool."""

import os
import selectors
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

MAX_OUTPUT_BYTES = 64 * 1024


@dataclass(frozen=True)
class ProcessResult:
    status: str
    output: bytes = b""
    error: str | None = None


def run_probe(argv: list[str], cwd: Path, timeout: float) -> ProcessResult:
    if os.name != "posix":
        return ProcessResult("unavailable", error="当前探针执行需要 POSIX 系统。")
    deadline = monotonic() + timeout
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
        )
    except OSError:
        return ProcessResult("unavailable", error="探针程序不存在或无法启动。")
    with process, selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        output = bytearray()
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    return ProcessResult("timeout", error="探针超过执行时限。")
                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > MAX_OUTPUT_BYTES:
                    return ProcessResult("error", error="探针输出超过 64 KiB。")
            try:
                code = process.wait(timeout=max(0, deadline - monotonic()))
            except subprocess.TimeoutExpired:
                return ProcessResult("timeout", error="探针超过执行时限。")
            if code != 0:
                return ProcessResult("error", error=f"探针退出码为 {code}。")
            return ProcessResult("ok", bytes(output))
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
