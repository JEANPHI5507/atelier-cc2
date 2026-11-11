"""Starts the dashboard against tests/fakeprinter.py (used by the interface tests)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fakeprinter

os.environ.setdefault("CC2_HOST", fakeprinter.SIM_HOST)
os.environ.setdefault("CC2_ACCESS_CODE", fakeprinter.SIM_CODE)
os.environ.setdefault("CC2_SERIAL", fakeprinter.SIM_SERIAL)
fakeprinter.patch_pycentauri()

from elegoo_lab.cli import app

if __name__ == "__main__":
    app()
