"""Run an engine adapter over the active pack's questions.

    python run_engine.py --list
    python run_engine.py codex-solo Q5 Q6
    python run_engine.py codex-solo --all
    python run_engine.py baseline-claude Q5    # handoff: prints the task,
                                               # collects once answered

Writes runs/<seed>.<engine>.json in the pack's state directory, and the
raw answer and hub-side corpus call log under runs/raw/.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import contract
from pack import PACK


def list_adapters(kind: str) -> None:
    for m in contract.discover(kind):
        state = "built" if m.built else "designed"
        miss = m.missing() if m.built else []
        extra = f"  (needs {', '.join(miss)})" if miss else ""
        print(f"  {m.name:<18} {state:<9} {m['invocation']:<13}"
              f"{m['corpus_access']:<10}{m['title']}{extra}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("engine", nargs="?")
    ap.add_argument("seeds", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    if a.list or not a.engine:
        list_adapters("engine")
        return
    m = contract.get("engine", a.engine)
    seeds = a.seeds
    if a.all or not seeds:
        seeds = [p.stem for p in sorted(PACK.seeds_dir.glob("*.json"))]
    failed = False
    for s in seeds:
        try:
            r = contract.run_engine(m, s, timeout=a.timeout)
        except contract.Pending as task:
            print(task)
            continue
        except subprocess.TimeoutExpired:
            r = {"ok": False, "error": "timeout"}
        if r.get("ok"):
            print(f"{s}: {r['n']} hypotheses in {r['elapsed_s']}s, "
                  f"{r['corpus_calls_observed']} corpus calls observed, "
                  f"{len(r['problems'])} HOF problems")
            for p in r["problems"][:5]:
                print(f"    ! {p}")
        else:
            failed = True
            print(f"{s}: FAILED - {r.get('error')}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
