"""python -m local_ci ..."""

from __future__ import annotations

import sys

from local_ci.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
