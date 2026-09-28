"""Turn certified hypotheses into experiment cards.

A certified hypothesis is still just text. What the instrumentation
programme can act on is a card: what is measured, on what, with which
detector class in which band, what would count as a positive and a
negative result, which artifacts have to be excluded first, and which
measurement area the procedure belongs to.

The mapping to measurement areas is deliberate. The field's bottleneck is
the measurement chain; if a generated hypothesis cannot be pointed at an
area with an established procedure, that is a finding about the
hypothesis.

    python cards.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

AUDIT = PACK.audit_db
MECH = PACK.judge_dir / "mechanical.json"
OUT_MD = PACK.outputs_dir / "experiment_cards.md"

# instrument vocabulary -> the measurement area whose procedure applies
AREAS = PACK.measurement_areas


def areas_for(text: str) -> list[str]:
    hits = []
    for pattern, area in AREAS:
        if re.search(pattern, text, re.I) and area not in hits:
            hits.append(area)
    return hits[:3]


def main() -> None:
    if not AUDIT.exists():
        raise SystemExit("run scoreboard/score.py first")
    conn = sqlite3.connect(f"file:{AUDIT}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    certified = conn.execute(
        "SELECT * FROM candidates WHERE certified=1 AND is_restatement=0 "
        "ORDER BY seed_id, candidate_id").fetchall()
    full = {c["candidate_id"]: c for c in json.loads(
        MECH.read_text(encoding="utf-8"))}

    L = ["# Experiment cards\n",
         "Certified hypotheses from the hypothesis engine, rendered as "
         "experiments a laboratory could cost. Certified means the "
         "reasoning survived a step-by-step audit against the corpus it "
         "cites — not that the hypothesis is true. Every card names the "
         "measurement that would settle it and the measurement area "
         "whose procedure makes that measurement defensible.\n",
         f"{len(certified)} cards in this run.\n"]

    for row in certified:
        cid = row["candidate_id"]
        cand = full.get(cid, {})
        h = cand.get("hypothesis", {})
        scope = h.get("scope") or {}
        instrument = h.get("required_instrument") or ""
        blob = " ".join([row["statement"] or "", instrument,
                         h.get("proposed_experiment") or "",
                         scope.get("condition", "")])
        areas = areas_for(blob)

        L.append(f"\n---\n\n## {cid} — {row['seed_id']} "
                 f"[{row['causal_level']}]\n")
        L.append(f"**Claim.** {row['statement']}\n")
        if h.get("null_hypothesis"):
            L.append(f"**Negative result looks like.** "
                     f"{h['null_hypothesis']}\n")
        if h.get("estimand"):
            L.append(f"**The deciding number.** {h['estimand']}\n")
        L.append("**Scope.** "
                 + "; ".join(f"{k}: {v}" for k, v in scope.items() if v)
                 + "\n")
        L.append(f"**Measurement.** {h.get('proposed_experiment', '')}\n")
        if instrument:
            L.append(f"**Instrument.** {instrument}\n")
        if areas:
            L.append("**Measurement area.** " + "; ".join(areas) + "\n")
        else:
            L.append("**Measurement area.** None matched — either the "
                     "instrument is outside the mapped areas or the card "
                     "is under-specified.\n")
        cited = h.get("cited_work_ids") or []
        L.append(f"**Grounded in.** {len(cited)} corpus works: "
                 + ", ".join(f"`{w}`" for w in cited[:8]) + "\n")
        L.append(f"**Provenance.** Proposed by {row['engines']}"
                 + (" (reached independently by more than one engine)"
                    if row["convergent"] else "")
                 + f"; nearest existing registry claim "
                 f"{row['nearest_claim']} at similarity "
                 f"{row['nearest_similarity']}.\n")
        if row["judge_reason"]:
            L.append(f"**Audit.** {row['judge_reason']}\n")

    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"  {len(certified)} experiment cards -> {OUT_MD.name}")


if __name__ == "__main__":
    main()
