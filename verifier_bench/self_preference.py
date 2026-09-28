"""Measure whether judges prefer hypotheses from their own model family.

The design makes this testable almost for free. Both engines answered
the same seeds from an identical prompt over the same corpus, and every
candidate was then judged by both families. So for each judge family we
can compare its pass rate on its own family's output against its pass
rate on the other's.

The confound to rule out is simple quality: if one engine genuinely
writes more certifiable hypotheses, BOTH judges rank it higher. Self
preference has a different signature — each judge ranks its own higher,
so the two orderings disagree.

This matters beyond this project. Every hypothesis-generation system in
the plan verifies with the same model that generated (reflection loops,
simulated debate, self-scoring). If judges favour their own family, a
self-verified certification rate is not a measurement of quality, and
the published scores of such systems are not comparable to each other.

    python self_preference.py
"""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

AUDIT = PACK.audit_db
VERDICTS = PACK.judge_dir / "verdicts.json"
PASS = {"certified", "pedantic"}
FAMILY_OF_ENGINE = {"baseline-claude": "claude", "codex-solo": "codex"}


def family_of_judge(judge: str) -> str:
    return "codex" if judge.startswith("codex") else "claude"


def main() -> None:
    verdicts = json.loads(VERDICTS.read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{AUDIT}?mode=ro", uri=True)
    engine_of = {r[0]: r[1] for r in
                 conn.execute("SELECT candidate_id, engine FROM members")}

    tab: dict[tuple[str, str], collections.Counter] = (
        collections.defaultdict(collections.Counter))
    for v in verdicts:
        eng = engine_of.get(v.get("candidate_id"))
        if not eng:
            continue
        key = (family_of_judge(v.get("judge", "")), eng)
        tab[key]["pass" if v.get("verdict") in PASS else "decline"] += 1

    print(f"{'judge family':<14}{'engine judged':<18}{'pass':>6}"
          f"{'decline':>9}{'pass rate':>11}")
    for (fam, eng), c in sorted(tab.items()):
        n = c["pass"] + c["decline"]
        print(f"{fam:<14}{eng:<18}{c['pass']:>6}{c['decline']:>9}"
              f"{c['pass'] / max(n, 1):>10.0%}")

    print()
    result = {}
    for fam in ("claude", "codex"):
        own_engine = next(e for e, f in FAMILY_OF_ENGINE.items() if f == fam)
        other_engine = next(e for e, f in FAMILY_OF_ENGINE.items()
                            if f != fam)
        o, t = tab[(fam, own_engine)], tab[(fam, other_engine)]
        ro = o["pass"] / max(o["pass"] + o["decline"], 1)
        rt = t["pass"] / max(t["pass"] + t["decline"], 1)
        result[fam] = {"own_rate": round(ro, 3), "other_rate": round(rt, 3),
                       "delta": round(ro - rt, 3),
                       "n_own": o["pass"] + o["decline"],
                       "n_other": t["pass"] + t["decline"]}
        print(f"  {fam} judge: own family {ro:.0%}, other family {rt:.0%}, "
              f"delta {ro - rt:+.0%}")

    both_positive = all(r["delta"] > 0 for r in result.values())
    print("\n  Each judge favours its own family: "
          f"{'YES' if both_positive else 'no'}")
    if both_positive:
        print("  The two orderings disagree, which is the signature of self")
        print("  preference rather than of one engine simply writing better")
        print("  hypotheses (that would move both judges the same way).")
    (PACK.bench_dir / "self_preference.json").write_text(
        json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
