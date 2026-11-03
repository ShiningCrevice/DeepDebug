import json
import sys
from pathlib import Path

config = json.loads(Path("config.json").read_text(encoding="utf-8"))
print(f"interpreter={sys.executable}", flush=True)
print(f"cwd={Path.cwd()}", flush=True)
import torch

model = torch.nn.Linear(config["in_features"], config["out_features"]).to(config["device"])
inputs = torch.zeros(config["batch_size"], config["in_features"])
print(f"input_device={inputs.device} weight_device={model.weight.device}", flush=True)
model(inputs)
