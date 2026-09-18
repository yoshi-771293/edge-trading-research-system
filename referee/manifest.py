"""Integrity: SHA-256 manifest of every referee file, verified at every startup.
Any mismatch, addition or deletion -> the caller halts and alerts."""
from __future__ import annotations
import hashlib, os, stat
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "MANIFEST.sha256"


def _files(d: Path):
    return sorted(p for p in d.rglob("*") if p.is_file() and p.name != MANIFEST_NAME and "__pycache__" not in p.parts)


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(d: Path) -> Path:
    lines = [f"{_digest(p)}  {p.relative_to(d).as_posix()}" for p in _files(d)]
    m = d / MANIFEST_NAME
    if m.exists():
        os.chmod(m, stat.S_IRUSR | stat.S_IWUSR)
    m.write_text("\n".join(lines) + "\n")
    return m


@dataclass
class Verification:
    ok: bool
    detail: str = ""


def verify(d: Path) -> Verification:
    m = d / MANIFEST_NAME
    if not m.exists():
        return Verification(False, "manifest missing")
    expected = {}
    for line in m.read_text().splitlines():
        if line.strip():
            h, rel = line.split("  ", 1); expected[rel] = h
    actual = {p.relative_to(d).as_posix(): _digest(p) for p in _files(d)}
    problems = []
    for rel, h in expected.items():
        if rel not in actual:
            problems.append(f"missing {rel}")
        elif actual[rel] != h:
            problems.append(f"modified {rel}")
    for rel in actual:
        if rel not in expected:
            problems.append(f"unexpected {rel}")
    return Verification(not problems, "; ".join(problems) or "all files match")


def lock(d: Path) -> None:
    for p in _files(d) + [d / MANIFEST_NAME]:
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    os.chmod(d, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)


def unlock(d: Path) -> None:
    os.chmod(d, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    for p in _files(d) + [d / MANIFEST_NAME]:
        if p.exists():
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
