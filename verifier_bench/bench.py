"""Benchmark the verifiers against each other, on known ground truth.

Every project in this space ships a way of deciding whether a generated
hypothesis is any good — theoria certifies proofs step by step, the LLNL
co-scientist runs an Elo tournament of simulated debates, AI-Scientist
reflects, Robin ranks pairwise with Bradley-Terry, HypoGeniC scores
against labelled data, and this repository judges stance adversarially.
None of them has ever been measured against a labelled set, because
nobody had one.

This repository does: 861 evidence sentences whose stance toward a
scoped claim was adversarially judged, and 467 of those additionally
judged for strict entailment. That makes a discrimination task with a
known answer.

Task A, discrimination (ground truth exists). Each verifier is shown a
claim and a sentence, blind, and must say whether the sentence supports
it, refutes it, or does neither. Scored against the verified labels.
Because the sample is stratified to over-represent refutation, a
verifier that simply always says "support" scores badly, which is the
failure mode worth catching: agreement with the field's own positivity.

Task B, agreement on generated output (no ground truth). The same
verifiers judge the same engine candidates; we report pairwise
agreement, so a verifier that certifies everything is visible as such
even where nobody knows the right answer.

    python bench.py --prepare
    ...dispatch each verifier over its batch...
    python bench.py --score
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

KB = PACK.knowledgebase
OUT = PACK.bench_dir
SEED = 20260826
N_TASK_A = 60

TASK_A_PROMPT = """Judge each item independently and at face value.

You are shown a scientific CLAIM and one SENTENCE taken verbatim from a \
paper. Decide what the sentence asserts about the claim:

  "support"          the sentence reports evidence or results FOR the claim
  "refute"           it reports evidence AGAINST the claim, or that an \
attempt failed, or that an apparent effect was an artifact
  "discuss"          it is about the claim but commits to no evidential \
direction (review, proposal, hedge, historical mention)
  "not_about_claim"  the sentence is actually about something else

Judge only what THIS sentence asserts, not what you know about the \
field. A sentence describing someone else's positive finding counts as \
support only if it is presented as evidence. Do not assume that most \
sentences support their claim: this sample is deliberately not \
representative.

Return ONLY a JSON array:
[{"item_id": "A001", "verdict": "support|refute|discuss|not_about_claim", \
"confidence": "high|low"}]

Items:
"""


def task_a(conn: sqlite3.Connection) -> list[dict]:
    """Stratified, blinded discrimination set with known labels.

    Sentences quoted in the published inventory are excluded, for the
    same reason the human stance audit excludes them: they appear there
    under explicit support/refutation headings, so a verifier that has
    read the site would be answering from memory.
    """
    inventory = PACK.inventory
    published = set()
    if inventory and inventory.exists():
        import re
        for m in re.finditer(r'^- "(.+?)"\s*$',
                             inventory.read_text(encoding="utf-8"), re.M):
            published.add(m.group(1)[:200])

    rows = conn.execute("""
        SELECT e.rowid, e.hyp_id, h.claim, e.sentence, e.stance_verified
        FROM hypothesis_evidence e JOIN hypotheses h ON h.id = e.hyp_id
        WHERE e.stance_verified IS NOT NULL""").fetchall()
    pool = [dict(rowid=r[0], hyp_id=r[1], claim=r[2], sentence=r[3],
                 truth=r[4]) for r in rows
            if r[3][:200] not in published]

    rng = random.Random(SEED)
    by_class: dict[str, list] = {}
    for r in pool:
        by_class.setdefault(r["truth"], []).append(r)
    quota = {"support": 20, "refute": 20, "discuss": 10,
             "not_about_claim": 10}
    picked = []
    for cls, n in quota.items():
        avail = by_class.get(cls, [])
        rng.shuffle(avail)
        picked.extend(avail[:n])
    rng.shuffle(picked)
    for i, r in enumerate(picked, 1):
        r["item_id"] = f"A{i:03d}"
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{KB}?mode=ro", uri=True)
    OUT.mkdir(parents=True, exist_ok=True)

    if a.score:
        return score()

    items = task_a(conn)
    blind = [{"item_id": r["item_id"], "claim": r["claim"],
              "sentence": r["sentence"]} for r in items]
    key = [{"item_id": r["item_id"], "rowid": r["rowid"],
            "hyp_id": r["hyp_id"], "truth": r["truth"]} for r in items]
    (OUT / "taskA_blinded.json").write_text(
        json.dumps(blind, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "taskA_KEY_local.json").write_text(
        json.dumps(key, indent=1), encoding="utf-8")
    (OUT / "taskA_prompt.md").write_text(TASK_A_PROMPT, encoding="utf-8")
    dist: dict[str, int] = {}
    for r in items:
        dist[r["truth"]] = dist.get(r["truth"], 0) + 1
    print(f"  Task A: {len(items)} blinded items, truth distribution "
          f"{dist}")
    print("  key written to taskA_KEY_local.json (gitignored)")


def score() -> None:
    key = {k["item_id"]: k["truth"] for k in json.loads(
        (OUT / "taskA_KEY_local.json").read_text())}
    results = {}
    for path in sorted(OUT.glob("taskA_verdicts.*.json")):
        verifier = path.stem.split(".", 1)[1]
        verdicts = {v["item_id"]: v["verdict"]
                    for v in json.loads(path.read_text())}
        common = [i for i in key if i in verdicts]
        if not common:
            continue
        correct = sum(1 for i in common if verdicts[i] == key[i])
        # the failure worth catching: agreeing with the field's positivity
        refute_items = [i for i in common if key[i] == "refute"]
        refute_recall = (sum(1 for i in refute_items
                             if verdicts[i] == "refute")
                         / len(refute_items)) if refute_items else None
        called_support = sum(1 for i in common
                             if verdicts[i] == "support")
        # the evidential classes are what a verifier exists to separate;
        # the hedge class is where labelling is genuinely ambiguous, so
        # report them apart rather than hiding both in one accuracy
        evid = [i for i in common if key[i] in ("support", "refute")]
        evid_acc = (sum(1 for i in evid if verdicts[i] == key[i])
                    / len(evid)) if evid else None
        classes = ["support", "refute", "discuss", "not_about_claim"]
        cm = {t: {p: 0 for p in classes} for t in classes}
        for i in common:
            if key[i] in cm and verdicts[i] in cm[key[i]]:
                cm[key[i]][verdicts[i]] += 1
        results[verifier] = {
            "n": len(common),
            "accuracy": round(correct / len(common), 3),
            "evidential_accuracy": (round(evid_acc, 3)
                                    if evid_acc is not None else None),
            "refute_recall": (round(refute_recall, 3)
                              if refute_recall is not None else None),
            "support_rate": round(called_support / len(common), 3),
            "confusion": cm,
        }
    (OUT / "taskA_results.json").write_text(
        json.dumps(results, indent=1), encoding="utf-8")
    if not results:
        print("  no verifier verdict files yet "
              "(taskA_verdicts.<verifier>.json)")
        return
    print(f"\n{'verifier':<20}{'n':>5}{'acc':>7}{'evid_acc':>10}"
          f"{'refute_rec':>12}{'support_rate':>14}")
    for v, r in results.items():
        print(f"{v:<20}{r['n']:>5}{r['accuracy']:>7}"
              f"{str(r['evidential_accuracy']):>10}"
              f"{str(r['refute_recall']):>12}{r['support_rate']:>14}")
    classes = ["support", "refute", "discuss", "not_about_claim"]
    for v, r in results.items():
        print(f"\n  {v} confusion (rows truth, columns predicted)")
        print("  " + " " * 18 + "".join(f"{c[:9]:>11}" for c in classes))
        for t in classes:
            print(f"  {t:<18}"
                  + "".join(f"{r['confusion'][t][p]:>11}" for p in classes))
    if len(results) > 1:
        names = list(results)
        vfiles = {v: {x["item_id"]: x["verdict"] for x in json.loads(
            (OUT / f"taskA_verdicts.{v}.json").read_text())}
            for v in names}
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a_, b_ = vfiles[names[i]], vfiles[names[j]]
                shared = [k for k in a_ if k in b_]
                agree = sum(1 for k in shared if a_[k] == b_[k])
                print(f"\n  inter-verifier agreement "
                      f"{names[i]} vs {names[j]}: "
                      f"{agree}/{len(shared)} "
                      f"({agree / max(len(shared), 1):.0%})")


if __name__ == "__main__":
    main()
