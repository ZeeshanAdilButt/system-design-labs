from __future__ import annotations

import sys


def use_utf8_output() -> None:
    """Print characters like the middle dot correctly on Windows consoles."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
