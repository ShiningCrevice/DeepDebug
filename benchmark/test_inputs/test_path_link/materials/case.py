import os
from pathlib import Path
Path('real.bin').write_bytes(b'demo')
Path('weights.bin').symlink_to('real.bin')
print('weights.bin is_symlink=True; reader=O_NOFOLLOW')
os.open('weights.bin', os.O_RDONLY | os.O_NOFOLLOW)
