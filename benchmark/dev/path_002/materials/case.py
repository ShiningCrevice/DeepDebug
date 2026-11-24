from pathlib import Path
Path('weights').mkdir()
print('weights is_dir=', Path('weights').is_dir())
print(Path('weights').read_bytes())
