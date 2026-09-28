"""Which pack the tests run against.

$CONJECTURE_PACK if set, so a pack can run the hub's tests against its
own corpus and runs. Otherwise the toy pack, built once per test process
into a temporary directory: the hub's tests need no real corpus.

Import this before anything that imports pack.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
TOY = HUB / "conformance" / "toy_pack"


_TOY: Path | None = None


def toy_pack() -> Path:
    """A built toy pack, whatever CONJECTURE_PACK says (for tests that are
    about the toy pack's shape rather than about the pack under test)."""
    global _TOY
    if _TOY is None:
        out = Path(tempfile.mkdtemp(prefix="conjecture-toy-"))
        for f in ("pack.yaml", "questions.md"):
            shutil.copy2(TOY / f, out / f)
        subprocess.run([sys.executable, str(TOY / "build.py"),
                        "--out", str(out)], check=True)
        _TOY = out / "pack.yaml"
    return _TOY


def ensure_pack() -> Path:
    if not os.environ.get("CONJECTURE_PACK"):
        os.environ["CONJECTURE_PACK"] = str(toy_pack())
    return Path(os.environ["CONJECTURE_PACK"])


PACK_YAML = ensure_pack()
