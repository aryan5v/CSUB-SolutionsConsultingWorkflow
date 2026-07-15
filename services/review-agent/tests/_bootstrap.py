"""Put the workspace ``src`` directory on sys.path for test discovery.

Import this first in every test module so tests run under plain
``python -m unittest`` without an editable install, from any working directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
