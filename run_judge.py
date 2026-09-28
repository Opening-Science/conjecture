"""Run a judge adapter over the certification chunks.

    python run_judge.py --list
    python run_judge.py codex                        # every chunk
    python run_judge.py codex chunk_01.json chunk_02.json
    python run_judge.py claude-subagent --as claude-a chunk_01.json

Verdicts accumulate in the pack's judge/verdicts.<label>.json (label defaults to
the judge's name); chunks already judged under that label are skipped.
Then run judge/collect_verdicts.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import contract
from pack import PACK
from run_engine import list_adapters

JUDGE = PACK.judge_dir
CHUNKS = JUDGE / "chunks"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("judge", nargs="?")
    ap.add_argument("chunks", nargs="*")
    ap.add_argument("--as", dest="label")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--timeout", type=int, default=1200)
    a = ap.parse_args()
    if a.list or not a.judge:
        list_adapters("judge")
        return
    m = contract.get("judge", a.judge)
    label = a.label or m.name
    out_path = JUDGE / f"verdicts.{label}.json"
    verdicts = (json.loads(out_path.read_text(encoding="utf-8"))
                if out_path.exists() else [])
    done = {v["candidate_id"] for v in verdicts}
    names = a.chunks or [p.name for p in sorted(CHUNKS.glob("*.json"))]
    failed = False
    for name in names:
        items = json.loads((CHUNKS / name).read_text(encoding="utf-8"))
        if all(c["candidate_id"] in done for c in items):
            print(f"  {name}: already judged as {label}, skipping")
            continue
        try:
            r = contract.run_judge(m, items, label=label,
                                   tag=Path(name).stem, timeout=a.timeout)
        except contract.Pending as task:
            print(task)
            continue
        except subprocess.TimeoutExpired:
            r = {"ok": False, "error": "timeout"}
        if not r["ok"]:
            failed = True
            print(f"  {name}: FAILED - {r['error']}")
            continue
        for p in r["problems"][:5]:
            print(f"    ! {p}")
        for v in r["verdicts"]:
            if v.get("candidate_id") not in done:
                verdicts.append(v)
                done.add(v["candidate_id"])
        out_path.write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
        cert = sum(1 for v in r["verdicts"] if v.get("verdict") == "certified")
        print(f"  {name}: {len(r['verdicts'])} judged, {cert} certified "
              f"({len(verdicts)} total as {label})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
