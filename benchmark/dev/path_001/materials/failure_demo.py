import json
import sys
from pathlib import Path

config = json.loads(Path("config.json").read_text(encoding="utf-8"))
print(f"interpreter={sys.executable}", flush=True)
print(f"cwd={Path.cwd()}", flush=True)
print(f"weights={config['weights']}", flush=True)
with Path(config["weights"]).open(encoding="utf-8") as stream:
    weights = json.load(stream)
