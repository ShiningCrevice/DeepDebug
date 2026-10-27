"""Smoke checks for the installed package and both public entry points."""

import json
import subprocess
import sys
from importlib.metadata import version

import pytest


@pytest.mark.parametrize("command", [["deepdebug"], [sys.executable, "-m", "deepdebug"]])
def test_installed_entry_points(command: list[str]) -> None:
    result = subprocess.run(
        [*command, "--version"], capture_output=True, text=True, check=True, timeout=10
    )
    assert result.stdout.strip() == f"deepdebug {version('deepdebug-agent')}"


def test_unknown_command_is_rejected() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "deepdebug", "diagnose"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2


@pytest.mark.parametrize("kind", ["action", "state", "report", "snapshot"])
def test_schema_export_is_json(kind: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "deepdebug", "schema", kind],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    schema = json.loads(result.stdout)
    assert "$defs" in schema
    if kind == "action":
        assert schema["discriminator"]["propertyName"] == "action"
