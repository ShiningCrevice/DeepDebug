import json
import sys
from pathlib import Path

config = json.loads(Path("config.json").read_text(encoding="utf-8"))
print(f"interpreter={sys.executable}", flush=True)
print(f"cwd={Path.cwd()}", flush=True)
import torch

# A fixed 64 MiB request exceeds a process quota capped at 32 MiB.
total = torch.cuda.get_device_properties(config["device"]).total_memory
fraction = min(config["memory_fraction"], (32 * 1024 * 1024) / total)
torch.cuda.set_per_process_memory_fraction(fraction, config["device"])
print(f"device_total_bytes={total} quota_bytes={int(total * fraction)}", flush=True)
print(f"request_bytes={config['request_bytes']}", flush=True)
torch.empty(config["request_bytes"], dtype=torch.uint8, device=config["device"])
