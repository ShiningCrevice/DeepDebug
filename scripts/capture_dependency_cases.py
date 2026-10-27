"""Capture two developer-owned cases offline; never execute uploaded materials."""

import argparse
import json
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timezone
from pathlib import Path

from deepdebug.agent.schemas import EnvironmentSnapshot

PROBE = """
import json, platform, sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
try:
    package = {"name": "pydantic", "status": "installed", "version": version("pydantic")}
except PackageNotFoundError:
    package = {"name": "pydantic", "status": "not_found"}
print(json.dumps({
    "environment": {"environment_id": sys.argv[1], "interpreter": sys.executable,
                    "collected_at": datetime.now(timezone.utc).isoformat()},
    "python_version": platform.python_version(), "packages": [package]
}))
"""
PROGRAM = 'import sys\nprint(f"interpreter={sys.executable}", flush=True)\nimport pydantic\n'


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def capture(output: Path) -> None:
    """Use an empty temporary venv and the current project's installed metadata."""
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="deepdebug-seeds-") as directory:
        work = Path(directory)
        empty_env = work / "empty-env"
        venv.EnvBuilder(with_pip=False).create(empty_env)
        empty_python = empty_env / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        replacements = {
            str(empty_env): "/demo/empty-env",
            sys.prefix: "/demo/project/.venv",
            str(work): "/demo/work",
        }

        def redact(text: str) -> str:
            for original, replacement in replacements.items():
                text = text.replace(original, replacement)
            return text

        def snapshot(interpreter: str, environment_id: str) -> dict:
            result = subprocess.run(
                [interpreter, "-I", "-c", PROBE, environment_id],
                cwd=work,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            # Parse before redaction so Windows JSON escaping cannot hide paths.
            data = json.loads(result.stdout)
            data["environment"]["interpreter"] = redact(data["environment"]["interpreter"])
            return EnvironmentSnapshot.model_validate(data).model_dump(mode="json")

        empty = snapshot(str(empty_python), "ENV_EMPTY")
        installed = snapshot(sys.executable, "ENV_PROJECT")
        if empty["packages"][0]["status"] != "not_found":
            raise RuntimeError("empty environment unexpectedly contains pydantic")
        if installed["packages"][0]["status"] != "installed":
            raise RuntimeError("run with uv run so the project environment contains pydantic")
        program = work / "dependency_demo.py"
        program.write_text(PROGRAM, encoding="utf-8")
        for case_id in ("dep_001", "dep_002"):
            case = output / case_id
            materials = case / "materials"
            materials.mkdir(parents=True)
            captured_at = datetime.now(timezone.utc).isoformat()
            result = subprocess.run(
                [str(empty_python), "-I", str(program)],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 or "ModuleNotFoundError" not in result.stderr:
                raise RuntimeError("expected a real missing-dependency failure")
            log = redact(result.stdout + result.stderr)
            (materials / "log.txt").write_text(log, encoding="utf-8")
            (materials / "dependency_demo.py").write_text(PROGRAM, encoding="utf-8")
            write_json(materials / "target_snapshot.json", empty)
            intended = empty if case_id == "dep_001" else installed
            write_json(
                materials / "launch.json",
                {
                    "intended_interpreter": intended["environment"]["interpreter"],
                    "actual_interpreter": empty["environment"]["interpreter"],
                    "required_distribution": "pydantic",
                    "isolated_mode": True,
                },
            )
            files = ["log.txt", "dependency_demo.py", "launch.json", "target_snapshot.json"]
            if case_id == "dep_002":
                write_json(materials / "project_snapshot.json", installed)
                files.append("project_snapshot.json")
            write_json(
                case / "case.json",
                {
                    "case_id": case_id,
                    "family_id": "dependency_interpreter",
                    "split": "dev",
                    "category": "dependency",
                    "materials": [f"materials/{name}" for name in files],
                    "metadata": {
                        "captured_at": captured_at,
                        "synthetic": False,
                        "paths_redacted": True,
                        "capture_method": "scripts/capture_dependency_cases.py",
                        "exit_code": result.returncode,
                        "scope": "真实 Python 依赖导入失败；非 PyTorch 训练或 GPU 运行。"
                        "launch.json 的预期解释器由开发者设定；快照为独立探针进程采集。",
                    },
                },
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="new output directory; existing paths are rejected"
    )
    capture(parser.parse_args().output)
