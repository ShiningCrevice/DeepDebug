import json
import sys
from pathlib import Path

config = json.loads(Path("config.json").read_text(encoding="utf-8"))
print(f"interpreter={sys.executable}", flush=True)
print(f"cwd={Path.cwd()}", flush=True)
import torch

model = torch.nn.Linear(config["in_features"], config["out_features"])
inputs = torch.zeros(config["batch_size"], config["input_features"])
print(f"input_shape={tuple(inputs.shape)} weight_shape={tuple(model.weight.shape)}", flush=True)
model(inputs)
