"""Session-wide literal aliases, applied before tools can observe reviewed material."""

import json
import re
from collections.abc import Iterable

# Credentials are discovered in assignments as well as standalone token formats.
_KEY = (
    r"[\w-]*(?:api[_-]?key|access[_-]?key|access[_-]?token|auth[_-]?token"
    r"|token|password|passwd|secret|private[_-]?key)"
)
_ASSIGNMENT = re.compile(
    rf"(?i)\b{_KEY}[\"']?\s*[:=]\s*"
    r"""(?P<value>"(?:\\.|[^"\r\n])*"|'[^'\r\n]*'|[^\s,;#}\]]+)"""
)
_KEY_NAME = re.compile(rf"(?i)^{_KEY}$")
_TOKEN = re.compile(
    r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}"
    r"|github_pat_[A-Za-z0-9_]{12,}|hf_[A-Za-z0-9]{12,}|AKIA[A-Z0-9]{16})\b"
)
_BEARER = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]+)")
_HOME = re.compile(r"/(?:home|Users)/[^/\s\"'\\:,]+|[A-Za-z]:\\Users\\[^\\\s\"',:]+")
_PEM = re.compile(
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z]+ )?PRIVATE KEY-----",
    re.DOTALL,
)
_URL_AUTH = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://([^/\s:@]+:[^/\s@]+)@")
_JSON_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_JSON_SCALAR_FIELD = re.compile(
    r'(?P<key>"(?:\\.|[^"\\])*")(?P<sep>\s*:\s*)'
    r"(?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)(?=\s*[,}])"
)


def _json(text: str):
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


class Redactor:
    """Collect all replacements first, so repeated bare secrets are masked too.

    This is a finite set of common patterns, followed by human scope/content review.
    The original-to-alias map lives only in memory and is never serialized.
    """

    def __init__(self, texts: Iterable[str]):
        self._replacements: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        texts = list(texts)
        for text in texts:
            self._learn(text)
            data = _json(text)
            if data is not None:
                self._learn_json(data)
        self._pattern = (
            re.compile(
                "|".join(re.escape(s) for s in sorted(self._replacements, key=len, reverse=True))
            )
            if self._replacements
            else None
        )

    def _add(self, value: str, kind: str) -> None:
        if not value or value in self._replacements:
            return
        self._counts[kind] = self._counts.get(kind, 0) + 1
        number = self._counts[kind]
        alias = f"[REDACTED_{kind}_{number:03}]"
        if kind == "HOME":
            alias = f"/redacted/home_{number:03}"
        # Keep physical line boundaries, including those in PEM blocks.
        self._replacements[value] = re.sub(r"[^\r\n]+", lambda _: alias, value)

    def _learn(self, text: str) -> None:
        for match in _PEM.finditer(text):
            self._add(match.group(), "SECRET")
        for match in _ASSIGNMENT.finditer(text):
            value = match["value"]
            escaped = None
            if value.startswith('"'):
                escaped = value[1:-1]
                try:
                    value = json.loads(value)
                except ValueError:
                    value = value[1:-1]
            elif value.startswith("'"):
                value = value[1:-1]
            self._add(value, "SECRET")
            if escaped and escaped != value:
                self._replacements[escaped] = self._replacements[value].splitlines()[0]
        for pattern in (_BEARER, _URL_AUTH):
            for match in pattern.finditer(text):
                self._add(match[1], "SECRET")
        for match in _TOKEN.finditer(text):
            self._add(match.group(), "SECRET")
        for match in _HOME.finditer(text):
            self._add(match.group(), "HOME")

    def _learn_json(self, value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if _KEY_NAME.fullmatch(key) and isinstance(item, str):
                    self._add(item, "SECRET")
                self._learn(key)
                self._learn_json(item)
        elif isinstance(value, list):
            for item in value:
                self._learn_json(item)
        elif isinstance(value, str):
            self._learn(value)

    def _replace(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self._replacements[m.group()], text)

    def redact(self, text: str) -> str:
        if _json(text) is not None:
            # Replace inside decoded strings and re-escape only changed tokens.
            # Whitespace, physical line numbers and JSON structure stay intact.
            def replace_string(match: re.Match) -> str:
                value = json.loads(match.group())
                redacted = self._replace(value)
                return (
                    json.dumps(redacted, ensure_ascii=False) if value != redacted else match.group()
                )

            def replace_scalar(match: re.Match) -> str:
                if _KEY_NAME.fullmatch(json.loads(match["key"])):
                    return (
                        match["key"]
                        + match["sep"]
                        + json.dumps("[REDACTED_SECRET]", ensure_ascii=False)
                    )
                return match.group()

            return _JSON_STRING.sub(replace_string, _JSON_SCALAR_FIELD.sub(replace_scalar, text))
        return self._replace(text)
