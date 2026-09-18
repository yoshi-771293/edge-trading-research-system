"""Startup integrity gate. Every player/live entry point calls enforce() first."""
import sys
from pathlib import Path
from referee import manifest

REFEREE_DIR = Path(__file__).resolve().parent.parent / "referee"


def check():
    return manifest.verify(REFEREE_DIR)


def enforce():
    v = check()
    if not v.ok:
        msg = f"REFEREE INTEGRITY FAILURE: {v.detail}. Halting."
        print(msg, file=sys.stderr)
        try:
            from live import notify
            notify.alert("Edge Tournament HALT", msg)
        except Exception:
            pass
        sys.exit(2)
    return v
