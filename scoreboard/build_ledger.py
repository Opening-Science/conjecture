"""One row per hypothesis, every verdict against it, in a single table.

The pipeline produced its results in the shape of the pipeline: mechanical
checks here, judge verdicts there, theoria's audit somewhere else. That is
the wrong shape for a reader, who wants the object — the hypothesis — with
everything said about it alongside.

This joins the four sources into one ledger:

    judge/mechanical.json        the candidate and its mechanical checks
    judge/verdicts.json          one Claude judge and one Codex judge each
    judge/verdicts.theoria.json  theoria's own certify-or-decline
    audit.db                     certification, restatement, convergence

theoria only sees candidates carrying arithmetic. A candidate with no
computation step is marked "no arithmetic" rather than left blank: there
is nothing for theoria to check in a purely empirical proposal, and an
empty cell would read as an unrun check.

    python build_ledger.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

J = PACK.judge_dir
OUT = PACK.ledger


def load(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default



def resolve_works(rows: list[dict]) -> dict:
    """Map every cited work_id to {title, authors, year, doi, url}.

    Reads the knowledgebase read-only. The site shows the paper, not the
    bare OpenAlex id; a work absent from the knowledgebase (or a run built
    without it) keeps its id and is marked so the gap is visible rather
    than silently blank.
    """
    ids = set()
    for r in rows:
        ids.update(r.get("citations") or [])
        for s in r.get("rationale") or []:
            ids.update(s.get("works") or [])
    if not ids:
        return {}
    sys.path.insert(0, str(HUB))
    from pack import PACK
    kb_path = PACK.knowledgebase
    if not kb_path.exists():
        print(f"  note: knowledgebase not found at {kb_path}; citations "
              f"stay as ids")
        return {wid: {"id": wid, "missing": True} for wid in ids}
    kb = sqlite3.connect(f"file:{kb_path}?mode=ro", uri=True)
    kb.row_factory = sqlite3.Row
    cols = {r[1] for r in kb.execute("PRAGMA table_info(works)")}
    pick = [c for c in ("work_id", "title", "authors", "year", "doi")
            if c in cols]
    works = {}
    q = ",".join("?" * len(ids))
    for row in kb.execute(
            f"SELECT {','.join(pick)} FROM works WHERE work_id IN ({q})",
            tuple(ids)):
        d = dict(row)
        doi = (d.get("doi") or "").strip()
        # OpenAlex sometimes stores the full https URL; normalise to a bare DOI
        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        works[d["work_id"]] = {
            "id": d["work_id"],
            "title": (d.get("title") or "").strip() or None,
            "authors": (d.get("authors") or "").strip() or None,
            "year": int(d["year"]) if d.get("year") else None,
            "doi": doi or None,
            "url": f"https://doi.org/{doi}" if doi else None,
        }
    for wid in ids:                       # cited but not in the knowledgebase
        works.setdefault(wid, {"id": wid, "missing": True})
    # id order, not row order: the same ledger from any build of a corpus
    works = dict(sorted(works.items()))
    n_missing = sum(1 for w in works.values() if w.get("missing"))
    print(f"  resolved {len(works) - n_missing}/{len(works)} cited works"
          f"{f' ({n_missing} not in knowledgebase)' if n_missing else ''}")
    return works


def main() -> None:
    mech = load(J / "mechanical.json", [])
    verdicts = load(J / "verdicts.json", [])
    theoria = {}
    for tv in load(J / "verdicts.theoria.json", []):
        cid = tv["candidate_id"]
        if cid in theoria and theoria[cid].get("verdict") != tv.get("verdict"):
            raise SystemExit(f"duplicate theoria verdicts for {cid} disagree")
        theoria[cid] = tv
    claims = {c["candidate_id"]: c for c in load(J / "theoria_claims.json", [])}

    by_cand: dict[str, dict] = {}
    for v in verdicts:
        slot = by_cand.setdefault(v["candidate_id"], {})
        key = v["judge"]
        if key in slot and slot[key].get("verdict") != v.get("verdict"):
            raise SystemExit(
                f"conflicting verdicts for {v['candidate_id']}/{key}: "
                f"{slot[key].get('verdict')} vs {v.get('verdict')} — the "
                f"verdict files disagree; refusing to pick by file order")
        slot[key] = v

    db = sqlite3.connect(f"file:{PACK.audit_db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    audit = {r["candidate_id"]: dict(r)
             for r in db.execute("SELECT * FROM candidates")}

    rows = []
    for c in mech:
        cid = c["candidate_id"]
        h = c["hypothesis"]
        a = audit.get(cid, {})
        judges = by_cand.get(cid, {})
        t = theoria.get(cid)

        if t:
            th = {"verdict": t["verdict"], "answer": t.get("theoria_answer", ""),
                  "proof_verified": t.get("theoria_proof_verified"),
                  "steps": claims.get(cid, {}).get("n_computation_steps")}
        elif cid in claims:
            th = {"verdict": "queued",
                  "steps": claims[cid]["n_computation_steps"],
                  "answer": "", "proof_verified": None}
        else:
            th = {"verdict": "n/a", "steps": 0, "answer": "", "proof_verified": None,
                  "note": "no computation step — nothing to re-derive"}

        rows.append({
            "id": cid,
            "seed": c["seed_id"],
            "level": h.get("causal_level"),
            "engines": c["engines"],
            "convergent": bool(c.get("convergent")),
            "statement": h.get("statement", ""),
            "estimand": h.get("estimand", ""),
            "null": h.get("null_hypothesis", ""),
            "experiment": h.get("proposed_experiment", ""),
            "instrument": h.get("required_instrument", ""),
            "citations": h.get("cited_work_ids", []),
            "rationale": [
                {"step": s.get("step", ""), "type": s.get("justification_type"),
                 "works": s.get("work_ids", [])}
                for s in (h.get("rationale") or [])],
            "mechanical": {"pass": bool(c.get("mechanical_pass")),
                           "fails": c.get("mechanical_fails") or [],
                           "warnings": c.get("mechanical_warnings") or []},
            "judges": {k: {"verdict": v["verdict"], "reason": v.get("reason", ""),
                           "failing_step": v.get("failing_step")}
                       for k, v in judges.items()},
            "theoria": th,
            "certified": bool(a.get("certified")),
            "restatement": bool(a.get("is_restatement")),
            "nearest_claim": a.get("nearest_claim"),
            "nearest_similarity": a.get("nearest_similarity"),
        })

    rows.sort(key=lambda r: (r["seed"], r["id"]))
    # count theoria only for candidates present in this run, keyed off the
    # rows we actually built — a stale verdict for a dropped candidate must
    # not inflate the totals.
    current = {r["id"] for r in rows}
    tv = [theoria[c] for c in current if c in theoria]
    def _n(*verdicts):
        return sum(1 for v in tv if v["verdict"] in verdicts)
    ran = _n("certified", "declined", "inconclusive")
    tally = {
        "n": len(rows),
        "certified": sum(r["certified"] for r in rows),
        "theoria_eligible": sum(1 for c in claims if c in current),
        "theoria_run": ran,                       # completed rulings only
        "theoria_certified": _n("certified"),
        "theoria_declined": _n("declined"),
        "theoria_inconclusive": _n("inconclusive"),
        "theoria_error": _n("error"),             # timeouts, kept separate
    }
    stale = [c for c in theoria if c not in current]
    if stale:
        print(f"  WARNING: {len(stale)} theoria verdict(s) for candidates "
              f"not in this run, ignored: {', '.join(sorted(stale)[:5])}"
              f"{'…' if len(stale) > 5 else ''}")
    works = resolve_works(rows)
    OUT.write_text(json.dumps({"tally": tally, "rows": rows, "works": works},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {tally['n']} hypotheses, theoria {tally['theoria_run']}"
          f"/{tally['theoria_eligible']} run -> {OUT.name}")


if __name__ == "__main__":
    main()
