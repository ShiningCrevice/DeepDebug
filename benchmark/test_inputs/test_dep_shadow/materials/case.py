import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import numpy
print('numpy_file=',numpy.__file__)
print(numpy.array([1,2]))
