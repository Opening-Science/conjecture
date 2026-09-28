"""Score the run and write the audit database.

Metrics, per engine and per causal level:

  rediscovery      how many registry claims the engine reached blind.
                   Validation, not the prize: an engine that cannot
                   recover what the field already believes is not
                   reading the literature.
  grounding        fraction of citations that exist and are judged to
                   support the step that cites them.
  certification    fraction surviving the certify-or-decline audit.
  novelty yield    certified and grounded hypotheses that are NOT
                   restatements of the registry. This is the prize.
  cost             wall-clock and corpus calls per certified hypothesis.
  auditability     what provenance the engine emitted natively.

Following theoria's reproducibility pattern, everything lands in a small
committed audit.db with the queries that regenerate every headline
number, so no figure in the write-up is a hand-copied literal.

    python score.py
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

KB = PACK.knowledgebase
AUDIT = PACK.audit_db
RESTATE_THRESHOLD = 0.75


def registry_claims() -> list[dict]:
    kb = sqlite3.connect(f"file:{KB}?mode=ro", uri=True)
    return [{"id": r[0], "level": r[1], "claim": r[2]}
            for r in kb.execute(
                "SELECT id, level, claim FROM hypotheses_v2")]


def similarity_matrix(a_texts: list[str], b_texts: list[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    if not a_texts or not b_texts:
        return []
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    m = vec.fit_transform(a_texts + b_texts)
    return cosine_similarity(m[:len(a_texts)], m[len(a_texts):])


def build(conn: sqlite3.Connection) -> dict:
    mech_path = PACK.judge_dir / "mechanical.json"
    cands = json.loads(mech_path.read_text(encoding="utf-8"))
    verdict_path = PACK.judge_dir / "verdicts.json"
    verdicts = {}
    if verdict_path.exists():
        for v in json.loads(verdict_path.read_text(encoding="utf-8")):
            verdicts.setdefault(v["candidate_id"], []).append(v)

    claims = registry_claims()
    sim = similarity_matrix(
        [c["hypothesis"].get("statement", "") for c in cands],
        [c["claim"] for c in claims])

    conn.executescript("""
    DROP TABLE IF EXISTS candidates;
    DROP TABLE IF EXISTS verdicts;
    DROP TABLE IF EXISTS members;
    CREATE TABLE candidates(
      candidate_id TEXT PRIMARY KEY, seed_id TEXT, engines TEXT,
      convergent INT, causal_level TEXT, statement TEXT,
      n_citations INT, mechanical_pass INT, mechanical_fails TEXT,
      nearest_claim TEXT, nearest_similarity REAL, is_restatement INT,
      certified INT, verdict TEXT, judge_reason TEXT,
      grounded INT, testable INT, novel INT);
    CREATE TABLE verdicts(
      candidate_id TEXT, judge TEXT, verdict TEXT, failing_step INT,
      grounded INT, testable INT, novel INT, reason TEXT);
    CREATE TABLE members(
      candidate_id TEXT, engine TEXT, hyp_id TEXT, statement TEXT);
    """)

    for i, c in enumerate(cands):
        h = c["hypothesis"]
        row_sim = list(sim[i]) if len(sim) else []
        best = max(range(len(row_sim)), key=lambda k: row_sim[k]) \
            if row_sim else None
        near_id = claims[best]["id"] if best is not None else None
        near_s = float(row_sim[best]) if best is not None else 0.0
        vs = verdicts.get(c["candidate_id"], [])
        for v in vs:
            conn.execute(
                "INSERT INTO verdicts VALUES(?,?,?,?,?,?,?,?)",
                (c["candidate_id"], v.get("judge", "?"), v.get("verdict"),
                 v.get("failing_step"), int(bool(v.get("grounded"))),
                 int(bool(v.get("testable"))), int(bool(v.get("novel"))),
                 v.get("reason", "")))
        # a candidate is certified only if every judge that saw it
        # certified it; one decline is a decline (theoria's discipline)
        certified = bool(vs) and all(
            v.get("verdict") in ("certified", "pedantic") for v in vs) \
            and c["mechanical_pass"]
        # the lexical restatement flag is a floor, not the test: token
        # overlap misses a claim reworded into different vocabulary, the
        # same weakness that made TF-IDF useless for cross-engine
        # convergence. Judged novelty is the semantic check, and a
        # candidate counts as novel only if every judge agreed.
        judged_novel = bool(vs) and all(v.get("novel") for v in vs)
        verdict = ("certified" if certified else
                   "declined" if vs else "unjudged")
        for m in c["members"]:
            conn.execute("INSERT INTO members VALUES(?,?,?,?)",
                         (c["candidate_id"], m["engine"], m.get("hyp_id"),
                          m.get("statement", "")[:400]))
        conn.execute(
            "INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,?)",
            (c["candidate_id"], c["seed_id"], ",".join(c["engines"]),
             int(c["convergent"]), h.get("causal_level"),
             h.get("statement", ""), len(h.get("cited_work_ids") or []),
             int(c["mechanical_pass"]), "; ".join(c["mechanical_fails"]),
             near_id, round(near_s, 3),
             int(near_s >= RESTATE_THRESHOLD or (bool(vs)
                                                 and not judged_novel)),
             int(certified), verdict,
             "; ".join(v.get("reason", "") for v in vs)[:500],
             int(all(v.get("grounded") for v in vs)) if vs else 0,
             int(all(v.get("testable") for v in vs)) if vs else 0,
             int(all(v.get("novel") for v in vs)) if vs else 0))
    conn.commit()

    engines = [r[0] for r in conn.execute(
        "SELECT DISTINCT engine FROM members ORDER BY engine")]
    board = []
    for e in engines:
        row = conn.execute("""
          SELECT COUNT(DISTINCT c.candidate_id),
                 SUM(c.certified), SUM(c.is_restatement),
                 SUM(CASE WHEN c.certified=1 AND c.is_restatement=0
                          THEN 1 ELSE 0 END),
                 AVG(c.n_citations)
          FROM candidates c JOIN members m USING(candidate_id)
          WHERE m.engine = ?""", (e,)).fetchone()
        board.append({
            "engine": e, "candidates": row[0] or 0,
            "certified": row[1] or 0, "restatements": row[2] or 0,
            "novelty_yield": row[3] or 0,
            "mean_citations": round(row[4] or 0, 1),
            "certification_rate": round((row[1] or 0) / (row[0] or 1), 2),
        })
    return {"engines": board, "n_candidates": len(cands),
            "n_claims": len(claims)}


def main() -> None:
    AUDIT.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(AUDIT)
    summary = build(conn)
    PACK.scoreboard.write_text(
        json.dumps(summary, indent=1), encoding="utf-8")
    print(f"  {summary['n_candidates']} candidates scored against "
          f"{summary['n_claims']} registry claims -> audit.db")
    hdr = f"{'engine':<18}{'cand':>6}{'cert':>6}{'restate':>9}{'novel':>7}"
    print("\n" + hdr)
    for e in summary["engines"]:
        print(f"{e['engine']:<18}{e['candidates']:>6}{e['certified']:>6}"
              f"{e['restatements']:>9}{e['novelty_yield']:>7}")
    conn.close()


if __name__ == "__main__":
    main()
