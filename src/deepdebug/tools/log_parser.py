"""Bounded Python traceback extraction; matches are observations, not root causes."""

import re
from collections import deque

from deepdebug.tools.artifacts import MAX_EXCERPT_CHARS, Excerpt, excerpt

EXCEPTION = re.compile(
    r"^(?P<type>(?:[\w]+\.)*[\w]*(?:Error|Exception)|KeyboardInterrupt|SystemExit)"
    r"(?::\s*(?P<message>.*))?$"
)
FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<function>.*))?$')


def parse_log(text: str, context_lines: int) -> tuple[dict, list[Excerpt], bool]:
    lines = text.splitlines()
    exceptions: deque[dict] = deque(maxlen=5)
    frames: deque[dict] = deque(maxlen=10)
    total_exceptions = total_frames = 0
    shortened = False
    for number, line in enumerate(lines, 1):
        match = EXCEPTION.match(line)
        if match:
            total_exceptions += 1
            message = match.group("message") or ""
            exceptions.append(
                {"type": match.group("type")[:200], "message": message[:1000], "line": number}
            )
            shortened |= len(message) > 1000 or len(match.group("type")) > 200
        match = FRAME.match(line)
        if match:
            total_frames += 1
            frames.append(
                {
                    "file": match.group("file")[:500],
                    "file_line": match.group("line")[:20],
                    "function": (match.group("function") or "")[:200],
                    "log_line": number,
                }
            )
            shortened |= len(line) > 700
    # Include original frame lines and error neighborhoods, retain the most recent 200 lines.
    selected: set[int] = {frame["log_line"] for frame in frames}
    for error in exceptions:
        selected.update(
            range(
                max(1, error["line"] - context_lines),
                min(len(lines), error["line"] + context_lines) + 1,
            )
        )
    positions = sorted(selected)[-200:]
    windows: list[tuple[int, int]] = []
    for number in positions:
        if windows and windows[-1][1] + 1 == number:
            windows[-1] = (windows[-1][0], number)
        else:
            windows.append((number, number))
    # Spend the content budget from the end to keep the final exception on long logs.
    snippets: list[Excerpt] = []
    remaining = MAX_EXCERPT_CHARS
    for start, end in reversed(windows):
        if remaining <= 0:
            break
        piece = excerpt(lines, start, end - start + 1, remaining)
        if piece is not None:
            snippets.append(piece)
            remaining -= len(piece.content)
    snippets.reverse()
    truncated = (
        shortened
        or total_exceptions > 5
        or total_frames > 10
        or len(positions) < len(lines)
        or any(p.truncated for p in snippets)
    )
    return (
        {
            "exceptions": list(exceptions),
            "frames": list(frames),
            "total_lines": len(lines),
            "matched_exceptions": total_exceptions,
            "matched_frames": total_frames,
        },
        snippets,
        truncated,
    )
