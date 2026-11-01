"""Explicit host-side snapshot capture with fixed isolated Python and GPU probes."""

import csv
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from deepdebug.agent.schemas import EnvironmentSnapshot, GpuObservation, TorchCudaObservation
from deepdebug.tools.process import run_probe

IDENTITY_PROBE = """
import json, platform, sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
packages = []
for name in sys.argv[2:]:
    try:
        packages.append({"name": name, "status": "installed", "version": version(name)})
    except PackageNotFoundError:
        packages.append({"name": name, "status": "not_found"})
    except Exception:
        packages.append({"name": name, "status": "error",
                         "error": "Package metadata query failed."})
print(json.dumps({
    "environment": {"mode": "snapshot", "environment_id": sys.argv[1],
                    "interpreter": sys.executable,
                    "collected_at": datetime.now(timezone.utc).isoformat()},
    "python_version": platform.python_version(), "packages": packages
}))
"""
TORCH_PROBE = """
import json
from datetime import datetime, timezone
result = {"collected_at": datetime.now(timezone.utc).isoformat()}
try:
    import torch
    result.update(status="ok", torch_version=str(torch.__version__),
                  cuda_version=torch.version.cuda, cuda_available=torch.cuda.is_available(),
                  device_count=torch.cuda.device_count())
except ModuleNotFoundError as exc:
    result.update(status="unavailable" if exc.name == "torch" else "error",
                  error="PyTorch missing." if exc.name == "torch" else "PyTorch import failed.")
except Exception:
    result.update(status="error", error="PyTorch CUDA probe failed.")
print(json.dumps(result))
"""
GPU_ARGUMENTS = ["--query-gpu=index,name,memory.total,memory.used", "--format=csv,noheader,nounits"]


class CaptureError(ValueError):
    """Safe-to-display capture failure; no partial snapshot is emitted."""


def capture_environment(
    interpreter: Path,
    environment_id: str,
    packages: list[str],
    *,
    torch_cuda: bool = False,
    gpu: bool = False,
) -> EnvironmentSnapshot:
    if not interpreter.is_absolute() or not environment_id.strip() or len(environment_id) > 200:
        raise CaptureError("请提供解释器绝对路径及 1～200 字符的环境标识。")
    if len(packages) > 10 or any(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name) is None for name in packages
    ):
        raise CaptureError("最多查询 10 个包；包名只能包含字母、数字、点、下划线和连字符。")
    normalized = [re.sub(r"[-_.]+", "-", name).lower() for name in packages]
    if len(set(normalized)) != len(normalized):
        raise CaptureError("包名不能重复。")
    with tempfile.TemporaryDirectory(prefix="deepdebug-probe-") as directory:
        work = Path(directory)
        identity = run_probe(
            [str(interpreter), "-I", "-c", IDENTITY_PROBE, environment_id, *packages], work, 10
        )
        if identity.status != "ok":
            raise CaptureError(f"{identity.status}: {identity.error}")
        try:
            snapshot = EnvironmentSnapshot.model_validate_json(identity.output)
        except ValueError as exc:
            raise CaptureError("解释器探针返回了无效快照。") from exc
        data = snapshot.model_dump()
        if torch_cuda:
            timestamp = datetime.now(timezone.utc)
            result = run_probe([str(interpreter), "-I", "-c", TORCH_PROBE], work, 15)
            if result.status == "ok":
                try:
                    observation = TorchCudaObservation.model_validate_json(result.output)
                except ValueError:
                    observation = TorchCudaObservation(
                        status="error", collected_at=timestamp, error="PyTorch 探针返回结构无效。"
                    )
            else:
                observation = TorchCudaObservation(
                    status=result.status, collected_at=timestamp, error=result.error
                )
            data["torch_cuda"] = observation
        if gpu:
            data["gpu"] = capture_gpu(work)
    return EnvironmentSnapshot.model_validate(data)


def capture_gpu(work: Path) -> GpuObservation:
    timestamp = datetime.now(timezone.utc)
    # System search path excludes the project directory and user PATH entries.
    executable = shutil.which("nvidia-smi", path=os.defpath)
    if executable is None:
        return GpuObservation(
            status="unavailable", collected_at=timestamp, error="系统路径中未找到 nvidia-smi。"
        )
    result = run_probe([executable, *GPU_ARGUMENTS], work, 15)
    if result.status != "ok":
        return GpuObservation(status=result.status, collected_at=timestamp, error=result.error)
    try:
        rows = list(csv.reader(result.output.decode("utf-8").splitlines(), skipinitialspace=True))
        if not rows:
            return GpuObservation(
                status="unavailable", collected_at=timestamp, error="未检测到 NVIDIA GPU。"
            )
        devices = []
        for index, name, total, used in rows:
            devices.append(
                dict(
                    index=int(index),
                    name=name.strip(),
                    memory_total_mib=int(total),
                    memory_used_mib=int(used),
                )
            )
        return GpuObservation(status="ok", collected_at=timestamp, devices=devices)
    except (ValueError, UnicodeError):
        return GpuObservation(
            status="error", collected_at=timestamp, error="nvidia-smi 返回结构无效。"
        )
