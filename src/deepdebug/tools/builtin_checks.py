"""Developer-owned minimal cases; only enum selections reach isolated subprocesses."""

import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from deepdebug.agent.schemas import CheckExecution
from deepdebug.tools.process import run_probe

PRESETS = {
    "dependency": {
        "fix": "使用包含所需模块的项目导入目录，修正导入搜索路径。",
        "criteria": "导入预置模块，得到 value=42。",
    },
    "path": {
        "fix": "保持 jobs 工作目录，将权重路径改为 ../checkpoints/model.json。",
        "criteria": "配置与权重均成功读取，权重值为 42。",
    },
    "shape": {
        "fix": "将 Linear 输入末维与 in_features=4 对齐。",
        "criteria": "固定输入通过 Linear(4, 2)，输出形状为 (2, 2)。",
    },
    "device": {
        "fix": "将输入张量移动到模型所在 CUDA 设备。",
        "criteria": "CUDA 模型前向成功，输出位于同一 CUDA 设备。",
    },
}
PHASES = ("before_fix", "after_fix")

# This program and its tiny fixtures are developer-owned. No uploaded paths or code enter it.
PROGRAM = r"""
import importlib
import json
import sys
from pathlib import Path
case, phase = sys.argv[1:]
fixed = phase == "after_fix"
root = Path.cwd()
if case == "dependency":
    library = root / "project_lib"
    library.mkdir()
    (library / "deepdebug_demo_module.py").write_text("value = 42\n")
    if fixed:
        sys.path.insert(0, str(library))
    module = importlib.import_module("deepdebug_demo_module")
    assert module.value == 42
    print("value=42")
elif case == "path":
    jobs, checkpoints = root / "jobs", root / "checkpoints"
    jobs.mkdir()
    checkpoints.mkdir()
    (checkpoints / "model.json").write_text('{"value":42}')
    (jobs / "config.json").write_text(json.dumps({"weights":
        "../checkpoints/model.json" if fixed else "checkpoints/model.json"}))
    import os
    os.chdir(jobs)
    config = json.loads(Path("config.json").read_text())
    weights = json.loads(Path(config["weights"]).read_text())
    assert weights["value"] == 42
    print("config=ok; weights=42")
else:
    try:
        import torch
    except ImportError:
        print("PyTorch unavailable")
        sys.exit(77)
    if case == "shape":
        model = torch.nn.Linear(4, 2)
        result = model(torch.ones(2, 4 if fixed else 5))
        assert tuple(result.shape) == (2, 2)
        print("output_shape=(2, 2)")
    else:
        if not torch.cuda.is_available():
            print("CUDA unavailable")
            sys.exit(77)
        model = torch.nn.Linear(4, 2).to("cuda:0")
        data = torch.ones(2, 4)
        if fixed:
            data = data.to(next(model.parameters()).device)
        result = model(data)
        assert result.device == next(model.parameters()).device
        torch.cuda.synchronize()
        print("output_device=cuda:0; output_shape=(2, 2)")
"""


@dataclass(frozen=True)
class BuiltinResult:
    case_id: str
    check_id: str
    status: str
    reason: str
    environment_id: str
    interpreter: str
    executed_at: datetime
    execution: CheckExecution | None
    tool_status: str = "ok"

    def data(self) -> dict:
        return {
            "case_id": self.case_id,
            "check_id": self.check_id,
            "status": self.status,
            "reason": self.reason,
            "preset_fix": PRESETS[self.case_id]["fix"],
            "success_criteria": PRESETS[self.case_id]["criteria"],
            "environment_id": self.environment_id,
            "interpreter": self.interpreter,
            "executed_at": self.executed_at.isoformat(),
            "execution": self.execution.model_dump(mode="json") if self.execution else None,
        }


def environment_id(python: Path) -> str:
    return "builtin-" + hashlib.sha256(str(python).encode()).hexdigest()[:12]


def run_builtin_check(case_id: str, check_id: str, python: Path | None = None) -> BuiltinResult:
    if case_id not in PRESETS or check_id not in PHASES:
        raise ValueError("预置案例或检查 ID 未登记。")
    interpreter = python or Path(sys.executable)
    if not interpreter.is_absolute():
        raise ValueError("解释器须为绝对路径。")
    timestamp = datetime.now(timezone.utc)
    environment = environment_id(interpreter)
    with TemporaryDirectory(prefix="deepdebug-check-") as folder:
        result = run_probe(
            [str(interpreter), "-I", "-c", PROGRAM, case_id, check_id],
            Path(folder),
            timeout=15 if case_id == "device" else 10,
        )
    if result.exit_code is None or result.exit_code == 77:
        return BuiltinResult(
            case_id,
            check_id,
            "无法执行",
            result.error
            if result.exit_code is None
            else result.output.decode("utf-8", errors="replace").strip(),
            environment,
            str(interpreter),
            timestamp,
            None,
            result.status if result.exit_code is None else "unavailable",
        )
    execution = CheckExecution(
        executed_at=timestamp,
        environment_id=environment,
        exit_code=result.exit_code,
        output=result.output.decode("utf-8", errors="replace"),
        truncated=False,
    )
    return BuiltinResult(
        case_id,
        check_id,
        "预置复现通过" if result.exit_code == 0 else "失败",
        "仅运行开发者预置案例；不表示用户训练或生成补丁已验证。",
        environment,
        str(interpreter),
        timestamp,
        execution,
    )
