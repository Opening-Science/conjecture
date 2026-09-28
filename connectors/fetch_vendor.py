"""Clone every upstream engine and judge at the commit its manifest pins.

vendor/ is not committed: it holds other projects' code under their own
licences. This recreates it from the manifests, so the checkout that
connectors/verify_bindings.py checks against is exactly the one the
status table names.

    python connectors/fetch_vendor.py            # clone or move to the pin
    python connectors/fetch_vendor.py --check    # report drift only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
VENDOR = HUB / "vendor"
sys.path.insert(0, str(HUB))

import contract  # noqa: E402


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    VENDOR.mkdir(exist_ok=True)
    drift = False
    for m in contract.discover():
        up = m["upstream"]
        if not (up["repo"] and up["commit"]):
            continue
        d = VENDOR / up["repo"].rstrip("/").split("/")[-1].removesuffix(".git")
        have = git("rev-parse", "HEAD", cwd=d) if d.exists() else None
        if have == up["commit"]:
            print(f"  ok     {m.name:<18} {d.name} @ {have[:7]}")
            continue
        drift = True
        if a.check:
            print(f"  DRIFT  {m.name:<18} {d.name} @ "
                  f"{have[:7] if have else 'absent'}, pinned "
                  f"{up['commit'][:7]}")
            continue
        if have is None:
            git("clone", "--quiet", up["repo"], str(d))
        else:
            git("fetch", "--quiet", "origin", cwd=d)
        git("checkout", "--quiet", up["commit"], cwd=d)
        print(f"  pinned {m.name:<18} {d.name} @ {up['commit'][:7]}")
    sys.exit(1 if drift and a.check else 0)


if __name__ == "__main__":
    main()
