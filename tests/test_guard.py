"""The player and live packages must refuse to run if the referee has been touched."""
import importlib, shutil, subprocess, sys
from pathlib import Path
from referee import manifest

ROOT = Path(__file__).resolve().parent.parent


def test_guard_passes_on_intact_referee():
    from player import guard
    assert guard.check().ok


def test_guard_halts_on_tampered_referee(tmp_path):
    """Copy the repo, modify one referee byte, import guard in a subprocess: must exit non-zero."""
    dst = tmp_path / "repo"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".venv", "state", "__pycache__", ".git"))
    manifest.unlock(dst / "referee")
    p = dst / "referee" / "costs.py"
    p.write_text(p.read_text().replace("COMMISSION = 0.0010", "COMMISSION = 0.0000"))
    r = subprocess.run([sys.executable, "-c", "from player import guard; guard.enforce()"], cwd=dst, capture_output=True, text=True)
    assert r.returncode != 0
    assert "costs.py" in (r.stderr + r.stdout)
