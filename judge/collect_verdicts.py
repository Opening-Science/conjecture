"""Gather judge verdicts from per-judge files into verdicts.json.

Each judge writes verdicts.<judge>.json (a JSON array). This merges them,
tagging every verdict with the judge that produced it, so the scoreboard
can require unanimity and the verifier benchmark can measure agreement.

    python collect_verdicts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from pack import PACK  # noqa: E402

JUDGE = PACK.judge_dir


def main() -> None:
    out = []
    seen_by_judge: dict[str, set] = {}
    for path in sorted(JUDGE.glob("verdicts.*.json")):
        judge = path.stem.split(".", 1)[1]
        if judge == "json":
            continue
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"  {path.name}: unparseable ({exc})")
            continue
        if isinstance(items, dict):
            items = items.get("verdicts", [])
        for v in items:
            if not isinstance(v, dict) or "candidate_id" not in v:
                continue
            v["judge"] = judge
            out.append(v)
            seen_by_judge.setdefault(judge, set()).add(v["candidate_id"])
    (JUDGE / "verdicts.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for judge, ids in sorted(seen_by_judge.items()):
        print(f"  {judge}: {len(ids)} candidates judged")
    print(f"  {len(out)} verdicts total -> verdicts.json")


if __name__ == "__main__":
    main()
