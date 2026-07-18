"""Test suite for the boonyard package.

Ensures ``package/`` is importable whether or not the package is pip-installed,
so the suite runs with a bare ``python -m unittest`` (ADR-0001: verifying
boonyard must never require installing anything).
"""

import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "package"
if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))
