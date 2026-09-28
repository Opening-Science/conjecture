"""Measure what withholding evidence did to the verdicts.

Pass 1 showed judges only the first eight cited abstracts per candidate;
pass 2 shows every one. Both passes used the same candidates, the same
prompt and the same judges, so the difference is attributable to the
evidence shown. That makes an accidental harness defect into a small
controlled experiment: how much does an auditor's verdict depend on
being shown the evidence the author actually cited?

    python compare_passes.py
"""
from __future__ import annotations

import json
from collections import Counter
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from pack import PACK  # noqa: E402

JUDGE = PACK.judge_dir
PASS1 = JUDGE / "pass1_truncated_evidence"
RANK = {"declined": 0, "pedantic": 1, "certified": 2}


def load(d: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in sorted(d.glob("verdicts.*.json")):
        judge = path.stem.split(".", 1)[1]
        if judge == "json":
            continue
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for v in items:
            cid = v.get("candidate_id")
            if cid:
                out.setdefault(judge, {})[cid] = v.get("verdict")
    return out


def main() -> None:
    p1, p2 = load(PASS1), load(JUDGE)
    if not p2:
        raise SystemExit("pass 2 verdicts not written yet")

    print(f"{'judge':<14}{'both':>6}{'same':>7}{'harsher1':>10}"
          f"{'softer1':>9}")
    total_same = total = 0
    moved: list[tuple[str, str, str, str]] = []
    for judge in sorted(set(p1) & set(p2)):
        common = set(p1[judge]) & set(p2[judge])
        same = harsh = soft = 0
        for cid in common:
            a, b = p1[judge][cid], p2[judge][cid]
            if a == b:
                same += 1
            elif RANK.get(a, 1) < RANK.get(b, 1):
                harsh += 1        # pass 1 was harsher; evidence rescued it
                moved.append((judge, cid, a, b))
            else:
                soft += 1
                moved.append((judge, cid, a, b))
        total_same += same
        total += len(common)
        print(f"{judge:<14}{len(common):>6}{same:>7}{harsh:>10}{soft:>9}")

    if total:
        print(f"\n  verdict stability across the two passes: "
              f"{total_same}/{total} ({total_same / total:.0%})")
    for judge in sorted(p2):
        c = Counter(p2[judge].values())
        print(f"  pass2 {judge:<12} {dict(c)}")
    if moved:
        print(f"\n  {len(moved)} verdicts moved when the withheld "
              f"citations were shown; first 12:")
        for judge, cid, a, b in moved[:12]:
            print(f"    {cid} [{judge}] {a} -> {b}")


if __name__ == "__main__":
    main()
