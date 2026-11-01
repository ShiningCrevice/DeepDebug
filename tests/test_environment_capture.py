"""Fixed probes, isolation, process limits, and import-compatible snapshot output."""

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepdebug.agent.schemas import EnvironmentSnapshot, GpuObservation, TorchCudaObservation
from deepdebug.cli import main
from deepdebug.tools import capture
from deepdebug.tools.capture import CaptureError, capture_environment, capture_gpu
from deepdebug.tools.process import MAX_OUTPUT_BYTES, ProcessResult, run_probe

pytestmark = pytest.mark.skipif(os.name != "posix", reason="probe runner requires POSIX")
TIME = "2026-11-01T00:00:00+00:00"


def test_empty_interpreter_capture_isolated_from_project(tmp_path, monkeypatch):
    environment = tmp_path / "empty"
    venv.EnvBuilder(with_pip=False).create(environment)
    marker = tmp_path / "executed"
    malicious = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    for name in ("torch.py", "pydantic.py", "sitecustomize.py"):
        (tmp_path / name).write_text(malicious)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    snapshot = capture_environment(
        environment / "bin/python", "EMPTY", ["pydantic"], torch_cuda=True
    )
    assert snapshot.environment.mode == "snapshot"
    assert snapshot.environment.environment_id == "EMPTY"
    assert snapshot.environment.interpreter == str(environment / "bin/python")
    assert snapshot.packages[0].status == "not_found"
    assert snapshot.torch_cuda.status == "unavailable"
    assert snapshot.gpu is None
    assert not marker.exists()


def test_snapshot_cli_and_import_roundtrip(capsys):
    code = main(
        [
            "snapshot",
            "--python",
            sys.executable,
            "--environment-id",
            "PROJECT",
            "--package",
            "pydantic",
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    snapshot = EnvironmentSnapshot.model_validate_json(text)
    assert snapshot.packages[0].status == "installed"
    assert snapshot.environment.collected_at.tzinfo is not None
    assert "torch_cuda" not in json.loads(text)
    assert "gpu" not in json.loads(text)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interpreter": Path("python")},
        {"environment_id": " "},
        {"packages": ["-c"]},
        {"packages": ["a;print(1)"]},
        {"packages": ["pydantic", "Pydantic"]},
        {"packages": ["a"] * 11},
    ],
)
def test_invalid_capture_arguments_do_not_execute(kwargs, monkeypatch):
    def forbidden(*args):
        pytest.fail("invalid arguments reached subprocess")

    monkeypatch.setattr(capture, "run_probe", forbidden)
    args = dict(interpreter=Path(sys.executable), environment_id="TEST", packages=[])
    args.update(kwargs)
    with pytest.raises(CaptureError):
        capture_environment(**args)


def test_missing_interpreter_cli_failure_has_no_partial_json(tmp_path, capsys):
    code = main(["snapshot", "--python", str(tmp_path / "absent"), "--environment-id", "X"])
    output = capsys.readouterr()
    assert code == 2 and not output.out
    assert "unavailable" in output.err


@pytest.mark.parametrize(
    "program,status",
    [
        ('print("ok")', "ok"),
        ("raise SystemExit(3)", "error"),
        ("import time; time.sleep(10)", "timeout"),
        (f'import os; os.write(1, b"x" * {MAX_OUTPUT_BYTES + 1})', "error"),
        ("import os, time; os.close(1); os.close(2); time.sleep(10)", "timeout"),
    ],
)
def test_real_subprocess_limits_and_reaping(tmp_path, monkeypatch, program, status):
    processes = []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", launch)
    result = run_probe([sys.executable, "-I", "-c", program], tmp_path, 0.3)
    assert result.status == status
    assert processes[0].poll() is not None
    if status != "ok":
        assert not result.output and result.error


def test_gpu_missing_command_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(capture.shutil, "which", lambda *args, **kwargs: None)
    assert capture_gpu(tmp_path).status == "unavailable"


@pytest.mark.parametrize(
    "process,expected",
    [
        (ProcessResult("ok", b"0, Demo GPU, 8192, 123\n"), "ok"),
        (ProcessResult("ok", b""), "unavailable"),
        (ProcessResult("ok", b"bad output"), "error"),
        (ProcessResult("ok", b"0, GPU, N/A, 0\n"), "error"),
        (ProcessResult("timeout", error="expired"), "timeout"),
        (ProcessResult("error", error="failed"), "error"),
    ],
)
def test_gpu_probe_parsing_and_fixed_arguments(tmp_path, monkeypatch, process, expected):
    monkeypatch.setattr(capture.shutil, "which", lambda *args, **kwargs: "/usr/bin/nvidia-smi")

    def run(argv, cwd, timeout):
        assert argv == ["/usr/bin/nvidia-smi", *capture.GPU_ARGUMENTS]
        assert cwd == tmp_path and timeout == 15
        return process

    monkeypatch.setattr(capture, "run_probe", run)
    observation = capture_gpu(tmp_path)
    assert observation.status == expected
    if expected == "ok":
        assert observation.devices[0].memory_used_mib == 123


@pytest.mark.parametrize(
    "probe_result,expected",
    [
        (ProcessResult("timeout", error="expired"), "timeout"),
        (ProcessResult("ok", b'{"secret":"not a probe"}'), "error"),
        (
            ProcessResult(
                "ok",
                json.dumps(
                    {
                        "status": "ok",
                        "collected_at": TIME,
                        "torch_version": "2.0+cpu",
                        "cuda_available": False,
                        "device_count": 0,
                    }
                ).encode(),
            ),
            "ok",
        ),
    ],
)
def test_optional_torch_failure_keeps_python_evidence(monkeypatch, probe_result, expected):
    original = capture.run_probe

    def run(argv, cwd, timeout):
        if argv[3] == capture.TORCH_PROBE:
            assert argv[:3] == [sys.executable, "-I", "-c"] and timeout == 15
            return probe_result
        return original(argv, cwd, timeout)

    monkeypatch.setattr(capture, "run_probe", run)
    snapshot = capture_environment(Path(sys.executable), "X", [], torch_cuda=True)
    assert snapshot.python_version
    assert snapshot.torch_cuda.status == expected


def test_snapshot_cli_partial_status(capsys, monkeypatch):
    monkeypatch.setattr(capture.shutil, "which", lambda *args, **kwargs: None)
    assert main(["snapshot", "--python", sys.executable, "--environment-id", "X", "--gpu"]) == 1
    snapshot = EnvironmentSnapshot.model_validate_json(capsys.readouterr().out)
    assert snapshot.gpu.status == "unavailable" and snapshot.python_version


@pytest.mark.parametrize(
    "model,data",
    [
        (GpuObservation, {"status": "ok", "devices": []}),
        (GpuObservation, {"status": "timeout"}),
        (TorchCudaObservation, {"status": "ok", "cuda_available": False}),
        (TorchCudaObservation, {"status": "unavailable", "error": "missing", "device_count": 0}),
    ],
)
def test_probe_contract_rejects_ambiguous_states(model, data):
    with pytest.raises(ValidationError):
        model.model_validate({"collected_at": TIME, **data})
