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
# wording a pack may override (pack.yaml prompts.extras); defaults are the
# hub's original text
X = PACK.prompt_extras
TITLE = X.get("cards_title", "Experiment cards")
INTRO = X.get("cards_intro", (
    "Certified hypotheses from the hypothesis engine, rendered as "
    "experiments a laboratory could cost. Certified means the "
    "reasoning survived a step-by-step audit against the corpus it "
    "cites — not that the hypothesis is true. Every card names the "
    "measurement that would settle it and the measurement area "
    "whose procedure makes that measurement defensible."))
INSTRUMENT = X.get("instrument_label", "Instrument")
AREA = X.get("area_label", "Measurement area")


def seed_order(seed_id: str) -> tuple:
    """Q2 before Q10."""
    m = re.match(r"([A-Za-z]*)(\d+)", seed_id or "")
    return (m.group(1), int(m.group(2))) if m else (seed_id, 0)


def question_tracks() -> dict[str, str]:
    """Q-id -> the track line a questions document may carry ("Track A, C.")."""
    try:
        md = PACK.questions_source.read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for qid, body in re.findall(r"\n## (Q\d+)\. (.*?)(?=\n## Q\d+\. |\Z)", md, re.S):
        m = re.search(r"^Track (.+?)\.?$", body, re.M)
        if m:
            out[qid] = m.group(1)
    return out


def areas_for(text: str) -> list[str]:
    if X.get("area_ranking") == "matches":
        # rank by distinct matched terms; the best area always, others only
        # when at least two distinct terms support them
        score: dict[str, set] = {}
        for pattern, area in AREAS:
            terms = {m.group(0).lower() for m in re.finditer(pattern, text, re.I)}
            if terms:
                score.setdefault(area, set()).update(terms)
        ranked = sorted(score, key=lambda a: -len(score[a]))
        return [a for i, a in enumerate(ranked) if i == 0 or len(score[a]) >= 2][:3]
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
    certified = sorted(certified,
                       key=lambda r: (seed_order(r["seed_id"]), r["candidate_id"]))
    qtracks = question_tracks()
    full = {c["candidate_id"]: c for c in json.loads(
        MECH.read_text(encoding="utf-8"))}

    L = [f"# {TITLE}\n", INTRO + "\n", f"{len(certified)} cards in this run.\n"]

    def blob_of(row) -> str:
        h = full.get(row["candidate_id"], {}).get("hypothesis", {})
        return " ".join([row["statement"] or "", h.get("required_instrument") or "",
                         h.get("proposed_experiment") or "",
                         (h.get("scope") or {}).get("condition", "")])

    # index: which cards fall under each area, so a reader can go area-first
    index: dict[str, list[str]] = {area: [] for _, area in AREAS}
    unmatched = []
    for row in certified:
        hits = areas_for(blob_of(row))
        for a in hits:
            index[a].append(row["candidate_id"])
        if not hits:
            unmatched.append(row["candidate_id"])
    L.append(f"\n## By {AREA.lower()}\n")
    L.append(f"| {AREA} | Cards | Ids |\n|---|---|---|")
    for area, ids in index.items():
        L.append(f"| {area} | {len(ids)} | {', '.join(ids)} |")
    if unmatched:
        L.append(f"| none matched | {len(unmatched)} | {', '.join(unmatched)} |")
    L.append("")

    for row in certified:
        cid = row["candidate_id"]
        cand = full.get(cid, {})
        h = cand.get("hypothesis", {})
        scope = h.get("scope") or {}
        instrument = h.get("required_instrument") or ""
        areas = areas_for(blob_of(row))

        L.append(f"\n---\n\n## {cid} — {row['seed_id']} "
                 f"[{row['causal_level']}]\n")
        if row["seed_id"] in qtracks:
            L.append(f"**Question.** {row['seed_id']}, mapped to Track "
                     f"{qtracks[row['seed_id']]} in the questions document.\n")
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
            L.append(f"**{INSTRUMENT}.** {instrument}\n")
        if areas:
            L.append(f"**{AREA}.** " + "; ".join(areas) + "\n")
        else:
            L.append(f"**{AREA}.** None matched — either the "
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
