"""Capture fixed developer-owned failure seeds with an explicitly chosen interpreter."""

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from deepdebug.agent.schemas import EnvironmentSnapshot
from deepdebug.tools.capture import CaptureError, capture_environment
from deepdebug.tools.process import run_probe

HEADER = """import json
import sys
from pathlib import Path

config = json.loads(Path("config.json").read_text(encoding="utf-8"))
print(f"interpreter={sys.executable}", flush=True)
print(f"cwd={Path.cwd()}", flush=True)
"""
CASES = {
    "path_001": {
        "family_id": "relative_working_directory",
        "category": "path",
        "config": {"weights": "checkpoints/model.json"},
        "program": HEADER
        + """print(f"weights={config['weights']}", flush=True)
with Path(config["weights"]).open(encoding="utf-8") as stream:
    weights = json.load(stream)
""",
        "expected": "FileNotFoundError",
        "scope": "真实 Python 相对路径读取失败；工作目录为 project/jobs，"
        "文件由采集器创建于 project/checkpoints/model.json；未加载模型或执行训练。",
    },
    "shape_001": {
        "family_id": "linear_input_features",
        "category": "configuration",
        "config": {"batch_size": 2, "input_features": 5, "in_features": 4, "out_features": 3},
        "program": HEADER
        + """import torch

model = torch.nn.Linear(config["in_features"], config["out_features"])
inputs = torch.zeros(config["batch_size"], config["input_features"])
print(f"input_shape={tuple(inputs.shape)} weight_shape={tuple(model.weight.shape)}", flush=True)
model(inputs)
""",
        "expected": "mat1 and mat2 shapes cannot be multiplied",
        "scope": "真实 CPU PyTorch Linear 输入维度失败；仅执行一个小型前向运算。",
    },
    "device_001": {
        "family_id": "cpu_input_cuda_model",
        "category": "device_mismatch",
        "config": {"batch_size": 2, "in_features": 4, "out_features": 3, "device": "cuda:0"},
        "program": HEADER
        + """import torch

model = torch.nn.Linear(config["in_features"], config["out_features"]).to(config["device"])
inputs = torch.zeros(config["batch_size"], config["in_features"])
print(f"input_device={inputs.device} weight_device={model.weight.device}", flush=True)
model(inputs)
""",
        "expected": "same device",
        "scope": "真实 CPU 输入与 CUDA Linear 权重设备不一致；仅使用小张量。",
    },
    "oom_001": {
        "family_id": "cuda_allocator_quota",
        "category": "cuda_oom",
        "config": {"device": "cuda:0", "memory_fraction": 0.001, "request_bytes": 67108864},
        "program": HEADER
        + """import torch

# A fixed 64 MiB request exceeds a process quota capped at 32 MiB.
total = torch.cuda.get_device_properties(config["device"]).total_memory
fraction = min(config["memory_fraction"], (32 * 1024 * 1024) / total)
torch.cuda.set_per_process_memory_fraction(fraction, config["device"])
print(f"device_total_bytes={total} quota_bytes={int(total * fraction)}", flush=True)
print(f"request_bytes={config['request_bytes']}", flush=True)
torch.empty(config["request_bytes"], dtype=torch.uint8, device=config["device"])
""",
        "expected": "out of memory",
        "scope": "真实 CUDA 分配器配额 OOM；固定申请 64 MiB，进程配额最多 32 MiB。"
        "不代表整卡显存耗尽、训练 batch 过大、泄漏或碎片化。",
    },
}


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def redact(value, replacements: dict[str, str]):
    if isinstance(value, str):
        for original, replacement in sorted(replacements.items(), key=lambda item: -len(item[0])):
            value = value.replace(original, replacement)
        return value
    if isinstance(value, dict):
        return {key: redact(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, replacements) for item in value]
    return value


def capture(output: Path, interpreter: Path, case_ids: list[str]) -> dict:
    if not interpreter.is_absolute():
        raise ValueError("--python must be an absolute interpreter path")
    if not case_ids or len(set(case_ids)) != len(case_ids) or set(case_ids) - CASES.keys():
        raise ValueError("select unique built-in case IDs")
    output.mkdir(parents=True, exist_ok=False)
    summary = {"cases": {}}
    for case_id in case_ids:
        spec = CASES[case_id]
        needs_torch = case_id != "path_001"
        needs_cuda = case_id in {"device_001", "oom_001"}
        try:
            snapshot = capture_environment(
                interpreter,
                f"ENV_{case_id.upper()}",
                ["torch"] if needs_torch else [],
                torch_cuda=needs_torch,
                gpu=needs_cuda,
            )
        except CaptureError as exc:
            summary["cases"][case_id] = {"status": "unavailable", "reason": str(exc)}
            continue
        torch = snapshot.torch_cuda
        if needs_torch and (torch.status != "ok" or (needs_cuda and not torch.cuda_available)):
            summary["cases"][case_id] = {
                "status": torch.status if torch.status != "ok" else "unavailable",
                "reason": torch.error or "CUDA unavailable in the selected interpreter.",
            }
            continue
        with tempfile.TemporaryDirectory(prefix="deepdebug-failure-") as directory:
            work = Path(directory)
            project = work / "project"
            cwd = project / "jobs"
            cwd.mkdir(parents=True)
            program = cwd / "failure_demo.py"
            program.write_text(spec["program"], encoding="utf-8")
            write_json(cwd / "config.json", spec["config"])
            if case_id == "path_001":
                (project / "checkpoints").mkdir()
                write_json(project / "checkpoints/model.json", {"weights": [1, 2, 3]})
            captured_at = datetime.now(timezone.utc).isoformat()
            result = run_probe([str(interpreter), "-I", str(program)], cwd, 15)
            log = result.output.decode("utf-8", errors="replace")
            if (
                result.exit_code is None
                or result.exit_code <= 0
                or spec["expected"].lower() not in log.lower()
            ):
                summary["cases"][case_id] = {
                    "status": result.status if result.exit_code is None else "error",
                    "reason": result.error or "Expected failure was not observed.",
                }
                continue
            replacements = {
                str(work): "/demo/work",
                str(interpreter.parent.parent): "/demo/target-env",
            }
            # Torch tracebacks can resolve venv links to a separate installation prefix.
            identity = run_probe(
                [
                    str(interpreter),
                    "-I",
                    "-c",
                    "import sys; print(sys.prefix); print(sys.base_prefix)",
                ],
                cwd,
                10,
            )
            if identity.status != "ok":
                summary["cases"][case_id] = {"status": identity.status, "reason": identity.error}
                continue
            for index, prefix in enumerate(identity.output.decode().splitlines()):
                replacements.setdefault(prefix, f"/demo/python-prefix-{index}")
            case = output / case_id
            materials = case / "materials"
            materials.mkdir(parents=True)
            (materials / "log.txt").write_text(redact(log, replacements), encoding="utf-8")
            (materials / "failure_demo.py").write_text(spec["program"], encoding="utf-8")
            write_json(materials / "config.json", spec["config"])
            data = redact(snapshot.model_dump(mode="json"), replacements)
            EnvironmentSnapshot.model_validate(data)
            write_json(materials / "target_snapshot.json", data)
            files = ["log.txt", "failure_demo.py", "config.json", "target_snapshot.json"]
            if case_id == "path_001":
                write_json(
                    materials / "layout.json",
                    {
                        "cwd": "/demo/work/project/jobs",
                        "configured_path": "checkpoints/model.json",
                        "resolved_exists": (cwd / spec["config"]["weights"]).exists(),
                        "project_relative_path": "checkpoints/model.json",
                        "project_relative_exists": (project / spec["config"]["weights"]).is_file(),
                        "project_root": "/demo/work/project",
                        "environment_id": snapshot.environment.environment_id,
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                files.append("layout.json")
            write_json(
                case / "case.json",
                {
                    "case_id": case_id,
                    "family_id": spec["family_id"],
                    "split": "dev",
                    "category": spec["category"],
                    "materials": [f"materials/{name}" for name in files],
                    "metadata": {
                        "captured_at": captured_at,
                        "synthetic": False,
                        "paths_redacted": True,
                        "capture_method": "scripts/capture_failure_cases.py",
                        "exit_code": result.exit_code,
                        "scope": spec["scope"],
                        "python_version": snapshot.python_version,
                        "pytorch_version": torch.torch_version if torch else None,
                        "cuda_version": torch.cuda_version if torch else None,
                    },
                },
            )
            summary["cases"][case_id] = {"status": "captured", "exit_code": result.exit_code}
    write_json(output / "capture_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new output directory; existing paths rejected")
    parser.add_argument("--python", required=True, type=Path, help="absolute target interpreter")
    parser.add_argument("--case", action="append", choices=CASES, dest="case_ids", required=True)
    args = parser.parse_args()
    try:
        summary = capture(args.output, args.python, args.case_ids)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if all(item["status"] == "captured" for item in summary["cases"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
