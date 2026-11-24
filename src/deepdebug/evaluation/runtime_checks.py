"""Six fixed developer-owned regression checks, separate from model-effect scoring."""

import argparse
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from deepdebug.evaluation.runner import write_json
from deepdebug.tools.builtin_checks import environment_id
from deepdebug.tools.process import run_probe


@dataclass(frozen=True)
class RuntimeCase:
    expected_error: str
    fix: str
    success_criteria: str


CASES = {
    "path_001": RuntimeCase(
        "FileNotFoundError",
        "保持工作目录，将权重引用改为 ../checkpoints/model.json。",
        "weights=42",
    ),
    "path_002": RuntimeCase(
        "IsADirectoryError", "将目录引用替换为目录内的实际模型文件。", "weights=42"
    ),
    "shape_001": RuntimeCase(
        "mat1 and mat2 shapes cannot be multiplied",
        "将输入末维与 Linear.in_features=4 对齐。",
        "shape=(2, 3)",
    ),
    "shape_002": RuntimeCase(
        "Expected input batch_size",
        "保持 logits 与标签批量长度一致，每个样本对应一个标签。",
        "loss=finite",
    ),
    "device_001": RuntimeCase(
        "same device", "将输入迁移到模型参数所在 CUDA 设备。", "device=cuda:0"
    ),
    "device_002": RuntimeCase("same device", "在输入的 device/dtype 上创建 eye。", "device=cuda:0"),
}


# Only these fixed statements reach Python. Material files and model text are never executed.
PROGRAM = r"""
import json
import math
import os
import sys
from pathlib import Path
case, phase = sys.argv[1:]
fixed = phase == "after_fix"
print("python=" + sys.version.split()[0], flush=True)
if case.startswith("path"):
    if case == "path_001":
        Path("jobs").mkdir()
        Path("checkpoints").mkdir()
        Path("checkpoints/model.json").write_text('{"value":42}')
        Path("jobs/config.json").write_text(json.dumps({"weights":
            "../checkpoints/model.json" if fixed else "checkpoints/model.json"}))
        os.chdir("jobs")
        config = json.loads(Path("config.json").read_text())
        value = json.loads(Path(config["weights"]).read_text())["value"]
    else:
        Path("weights").mkdir()
        Path("weights/model.bin").write_bytes(b"42")
        value = int(Path("weights/model.bin" if fixed else "weights").read_bytes())
    assert value == 42
    print("weights=42")
else:
    try:
        import torch
    except ImportError:
        print("PyTorch unavailable")
        sys.exit(77)
    print("torch=" + torch.__version__, flush=True)
    if case.startswith("device") and not torch.cuda.is_available():
        print("CUDA unavailable")
        sys.exit(77)
    if case == "shape_001":
        model = torch.nn.Linear(4, 3)
        data = torch.zeros(2, 4 if fixed else 5)
        result = model(data)
        assert tuple(result.shape) == (2, 3)
        print("shape=(2, 3)")
    elif case == "shape_002":
        logits = torch.ones(4, 3)
        targets = torch.tensor([0, 1, 2, 0] if fixed else [0, 1, 2])
        loss = torch.nn.functional.cross_entropy(logits, targets)
        assert math.isfinite(loss.item())
        print("loss=finite")
    elif case == "device_001":
        model = torch.nn.Linear(4, 3).to("cuda:0")
        data = torch.zeros(2, 4)
        if fixed:
            data = data.to(next(model.parameters()).device)
        result = model(data)
        assert result.device == next(model.parameters()).device
        assert tuple(result.shape) == (2, 3)
        torch.cuda.synchronize()
        print("device=cuda:0")
    else:
        data = torch.ones(4, 4, device="cuda:0")
        bias = torch.eye(4, device=data.device, dtype=data.dtype) if fixed else torch.eye(4)
        result = data + bias
        assert result.device == data.device and tuple(result.shape) == (4, 4)
        torch.cuda.synchronize()
        print("device=cuda:0")
"""


def run_phase(case_id: str, phase: str, python: Path) -> dict:
    if case_id not in CASES or phase not in {"before_fix", "after_fix"} or not python.is_absolute():
        raise ValueError("select a registered case, phase and absolute interpreter")
    timestamp = datetime.now(timezone.utc).isoformat()
    with TemporaryDirectory(prefix="deepdebug-runtime-") as folder:
        result = run_probe([str(python), "-I", "-c", PROGRAM, case_id, phase], Path(folder), 15)
    output = result.output.decode("utf-8", errors="replace")
    if result.exit_code is None or result.exit_code == 77:
        status = "unavailable"
    elif phase == "before_fix":
        status = (
            "expected_failure"
            if result.exit_code != 0 and CASES[case_id].expected_error in output
            else "unexpected_result"
        )
    else:
        status = (
            "passed"
            if result.exit_code == 0 and CASES[case_id].success_criteria in output
            else "failed"
        )
    return {
        "source": "local/runtime_checks",
        "phase": phase,
        "status": status,
        "executed_at": timestamp,
        "environment_id": environment_id(python),
        "interpreter": str(python),
        "exit_code": result.exit_code,
        "output": output,
        "tool_status": result.status,
        "error": result.error,
    }


def run_checks(python: Path, selected: list[str]) -> dict:
    if not selected or len(selected) != len(set(selected)) or set(selected) - CASES.keys():
        raise ValueError("select unique registered cases")
    records = []
    for case_id in selected:
        before = run_phase(case_id, "before_fix", python)
        after = run_phase(case_id, "after_fix", python)
        records.append(
            {
                "case_id": case_id,
                "expected_error": CASES[case_id].expected_error,
                "preset_fix": CASES[case_id].fix,
                "success_criteria": CASES[case_id].success_criteria,
                "before": before,
                "after": after,
                "regression_passed": before["status"] == "expected_failure"
                and after["status"] == "passed",
                "model_fix_match": "pending_human_review",
            }
        )
    return {
        "scope": "固定最小程序前后对照；未执行上传代码，尚未判定模型建议匹配。",
        "program_sha256": hashlib.sha256(PROGRAM.encode()).hexdigest(),
        "selected_cases": selected,
        "checks": records,
        "regression_passed": sum(r["regression_passed"] for r in records),
        "unavailable": sum(
            r["before"]["status"] == "unavailable" or r["after"]["status"] == "unavailable"
            for r in records
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not exist")
    try:
        result = run_checks(args.python, args.case or list(CASES))
        write_json(args.output, result)
    except (OSError, ValueError):
        print("运行检查失败：检查解释器、案例和输出目录。")
        return 2
    print(
        f"固定回归通过 {result['regression_passed']}/{len(result['checks'])}，"
        f"无法执行 {result['unavailable']}。"
    )
    return 0 if result["regression_passed"] == len(result["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
