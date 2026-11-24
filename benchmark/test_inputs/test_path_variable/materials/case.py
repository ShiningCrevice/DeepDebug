import os
from pathlib import Path
Path('models').mkdir()
Path('models/weights.json').write_text('{}')
os.environ['MODEL_DIR'] = str(Path('models').absolute())
configured = '$MODEL_DIR/weights.json'
print('configured=',configured,'actual=models/weights.json')
print(Path(configured).read_text())
