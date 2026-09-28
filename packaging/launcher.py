"""Entry point for the frozen Windows executable.

``python -m auto_trade`` works because the package is importable, but a frozen
build runs this file as a top-level script with no parent package, so the
relative import in ``auto_trade.__main__`` cannot be used here.
"""

from __future__ import annotations

import sys

from auto_trade.cli import main

if __name__ == "__main__":
    sys.exit(main())
