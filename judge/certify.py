"""Certify-or-decline, in theoria's discipline.

theoria (Apache-2.0, zaladbar) does not evaluate whether an answer is
impressive; it decomposes the reasoning into steps, audits each step
independently, and certifies only when every step survives. We apply the
same discipline to generated hypotheses, with one addition the original
does not need: a citation step here must resolve to a work that exists
in OUR corpus and that actually says what the step claims. That check is
mechanical for existence and judged for support.

Three verdicts per candidate, mirroring theoria's funnel:
  CERTIFIED  every load-bearing step survived
  DECLINED   a load-bearing step failed; the failing step is named
  PEDANTIC   only non-load-bearing steps failed (recorded, not fatal)

Stage 1 (mechanical, free) runs here: citation existence, scope
completeness, experiment specificity, registry-restatement check. It
already declines a class of hypotheses without spending judge budget.
Stage 2 (judged) writes a batch for the model judges.

    python certify.py --prepare    # mechanical pass + judge batch
    python certify.py --apply      # fold in judge verdicts
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

KB = PACK.knowledgebase
CANDIDATES = PACK.merge_dir / "candidates.json"
OUT = PACK.judge_dir

VAGUE = re.compile(
    r"\b(further (study|research|work)|should be investigated|"
    r"more research is needed|future studies)\b", re.I)


def mechanical(cand: dict, corpus, registry: list[dict]) -> dict:
    """Checks that need no model. Cheap, and they catch real failures."""
    h = cand["hypothesis"]
    fails, warns = [], []

    cited = h.get("cited_work_ids") or []
    missing = [w for w in cited if corpus.get_work(w) is None]
    if missing:
        fails.append(f"cites works absent from the corpus: {missing[:4]}")
    if not cited:
        fails.append("no citations: ungrounded")

    steps = h.get("rationale") or []
    cit_steps = [s for s in steps if s.get("justification_type") == "citation"]
    if not cit_steps:
        fails.append("no citation step: nothing ties this to the literature")
    for i, s in enumerate(steps):
        if s.get("justification_type") == "citation" and not s.get(
                "work_ids"):
            fails.append(f"rationale step {i} cites nothing")

    scope = h.get("scope") or {}
    for k in ("population", "condition", "outcome"):
        if not (scope.get(k) or "").strip():
            fails.append(f"scope.{k} empty: claim is not testable as stated")

    if not (h.get("estimand") or "").strip():
        warns.append("no estimand: the deciding number is unnamed")
    if not (h.get("null_hypothesis") or "").strip():
        warns.append("no explicit null")

    expt = h.get("proposed_experiment") or ""
    if len(expt) < 60:
        fails.append("proposed experiment too thin to cost")
    if VAGUE.search(expt):
        warns.append("experiment contains a hand-wave phrase")
    if not (h.get("required_instrument") or "").strip():
        warns.append("no instrument named")

    # near-verbatim restatement of a registry claim earns nothing
    stmt = (h.get("statement") or "").lower()
    toks = set(re.findall(r"[a-z]{4,}", stmt))
    for r in registry:
        rtoks = set(re.findall(r"[a-z]{4,}", r["claim"].lower()))
        if rtoks and len(toks & rtoks) / max(len(rtoks), 1) > 0.75:
            warns.append(f"reads as a restatement of registry claim {r['id']}")
            break

    return {"mechanical_pass": not fails, "mechanical_fails": fails,
            "mechanical_warnings": warns}


def judge_batch(cands: list[dict], corpus) -> list[dict]:
    """One judging task per candidate, with the cited evidence inlined.

    The judge never sees the registry's verified evidence, so its verdict
    cannot leak ground truth into a scoreboard that measures rediscovery.
    """
    batch = []
    for c in cands:
        h = c["hypothesis"]
        cited = []
        # EVERY cited work, not a prefix: truncating the evidence makes
        # judges decline hypotheses for the harness's omission rather
        # than the hypothesis's fault, which is exactly what happened in
        # the first certification pass
        for wid in (h.get("cited_work_ids") or []):
            w = corpus.get_work(wid)
            if w is None:
                cited.append({"work_id": wid,
                              "abstract": "(NOT IN CORPUS)"})
                continue
            abstract = (w.abstract or "").strip()
            if len(abstract) < 120:
                # distinguish "the corpus holds no abstract" from "the
                # work does not say this", so a data gap is not read as
                # a failed citation
                abstract = (abstract + " [NOTE: the corpus holds no usable "
                            "abstract for this work. Judge its citation "
                            "step on the title alone and mark the step "
                            "unverifiable rather than false.]")
            cited.append({"work_id": w.work_id, "title": w.title,
                          "year": w.year, "type": w.type,
                          "abstract": abstract[:1600]})
        batch.append({
            "candidate_id": c["candidate_id"],
            "seed_id": c["seed_id"],
            "statement": h.get("statement"),
            "scope": h.get("scope"),
            "null_hypothesis": h.get("null_hypothesis"),
            "estimand": h.get("estimand"),
            "proposed_experiment": h.get("proposed_experiment"),
            "rationale": h.get("rationale"),
            "cited_works": cited,
        })
    return batch


JUDGE_PROMPT = """You are auditing generated scientific hypotheses in the \
discipline of a proof checker: decompose, audit each step, and certify \
ONLY if the reasoning survives. Assume the hypothesis is wrong until its \
steps prove otherwise. Being interesting is not a reason to certify.

For each item you are given the claim, its scope, its proposed \
experiment, its rationale steps, and the FULL TEXT OF THE ABSTRACTS of \
every work it cites.

Audit each rationale step:
- a "citation" step survives only if the cited works, as shown to you, \
actually assert what the step claims. A work that is merely on the same \
topic does NOT support a specific claim. Misattribution is the failure \
you are hunting.
- a "computation" step survives only if the stated reasoning is \
checkable and correct on its face.
- a "given" step survives if it restates the question honestly.

Then judge the whole:
- GROUNDED: does the literature shown actually support the claim, or has \
the engine over-read it?
- TESTABLE: would the proposed experiment, as described, actually \
discriminate the claim from its null? Would a competent laboratory know \
what to do?
- NOVEL: does this go beyond restating what the cited works already \
concluded?

Verdict for each item:
  "certified"  every load-bearing step survived; grounded and testable
  "pedantic"   sound overall, but a non-load-bearing step is flawed \
(say which)
  "declined"   a load-bearing step failed; name the step and why

Return ONLY a JSON array:
[{"candidate_id": "C001", "verdict": "certified|pedantic|declined", \
"failing_step": <index or null>, "grounded": true/false, \
"testable": true/false, "novel": true/false, \
"reason": "<one sentence, concrete>"}]

Items to audit:
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    # chunks inline the cited abstracts, so a dozen candidates is
    # already a large read for one judge; eight keeps each task small
    # enough to judge carefully and parallelises better
    ap.add_argument("--chunk", type=int, default=8)
    a = ap.parse_args()

    from corpus_api import Corpus
    corpus = Corpus()
    kb = sqlite3.connect(f"file:{KB}?mode=ro", uri=True)
    registry = [{"id": r[0], "claim": r[1]} for r in kb.execute(
        "SELECT id, claim FROM hypotheses_v2")]

    cands = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    for c in cands:
        c.update(mechanical(c, corpus, registry))
    passed = [c for c in cands if c["mechanical_pass"]]
    (OUT / "mechanical.json").write_text(
        json.dumps(cands, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  mechanical: {len(passed)}/{len(cands)} passed, "
          f"{len(cands) - len(passed)} declined before judging")
    for c in cands:
        if not c["mechanical_pass"]:
            print(f"    x {c['candidate_id']}: {c['mechanical_fails'][0]}")

    batch = judge_batch(passed, corpus)
    OUT.mkdir(exist_ok=True)
    (OUT / "judge_batch.json").write_text(
        json.dumps(batch, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "judge_prompt.md").write_text(JUDGE_PROMPT, encoding="utf-8")
    # one self-contained file per chunk: a judge reads exactly one file
    # and never has to slice an array correctly
    chunk_dir = OUT / "chunks"
    chunk_dir.mkdir(exist_ok=True)
    for old in chunk_dir.glob("chunk_*.json"):
        old.unlink()
    chunks = []
    for n, i in enumerate(range(0, len(batch), a.chunk), 1):
        part = batch[i:i + a.chunk]
        path = chunk_dir / f"chunk_{n:02d}.json"
        path.write_text(json.dumps(part, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        chunks.append({"chunk": path.name, "n": len(part),
                       "ids": [p["candidate_id"] for p in part]})
    (OUT / "judge_chunks.json").write_text(
        json.dumps(chunks, indent=1), encoding="utf-8")
    print(f"  judge batch: {len(batch)} candidates in {len(chunks)} chunk "
          f"files -> judge/chunks/")


if __name__ == "__main__":
    main()
