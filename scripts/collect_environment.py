"""Manual snapshot entry point; shares the CLI's fixed probes and limits."""

import sys

from deepdebug.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["snapshot", *sys.argv[1:]]))
