"""Engine: the reference adapter. No model; a floor, not a contender.

It exists so the contract can be exercised end to end with nothing but
this repository: it reaches the corpus the way an agent does (over MCP,
logged by the hub), and it emits HOF the way an engine must. What it
proposes is the least a hypothesis engine could do: that the best-
matching findings for the question replicate. Any engine worth running
should beat it on every judged axis.
"""
from __future__ import annotations

import re

from mcp_client import McpClient


def first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return next((p for p in parts if len(p) > 30), parts[0] if parts else "")


def generate(req) -> dict:
    seed_id = req.seed_id
    queries = req.seed.get("entry_queries") or [req.seed["title"]]
    found: dict[str, dict] = {}
    with McpClient(req.mcp) as corpus:
        for q in queries:
            for w in corpus.call("search", query=q, limit=3):
                found.setdefault(w["work_id"], w)
        top = list(found)[:3]
        works = [corpus.call("get_work", work_id=wid) for wid in top]

    hyps = []
    for i, w in enumerate(works, 1):
        finding = first_sentence(w["abstract"].split(". ", 1)[-1])
        wid = w["work_id"]
        hyps.append({
            "id": f"{seed_id}-{i}",
            "statement": (f"The finding of {wid} ({w['year']}) replicates "
                          f"in an independent laboratory: {finding}"),
            "scope": {"population": f"the preparation studied in {wid}",
                      "condition": "the original protocol, repeated "
                                   "independently",
                      "comparator": "the originally reported value",
                      "outcome": "the quantity the original reports"},
            "null_hypothesis": "the independent value differs from the "
                               "original beyond the stated uncertainty",
            "estimand": "independent value / original value",
            "causal_level": "L5",
            "rationale": [
                {"step": f"{w['title']} reports: {finding}",
                 "justification_type": "citation", "work_ids": [wid]},
                {"step": f"It is among the best corpus matches for "
                         f"{seed_id}: {req.seed['title']}",
                 "justification_type": "given"}],
            "cited_work_ids": [wid],
            "proposed_experiment": f"Repeat the measurement of {wid} in "
                                   f"a second laboratory with a shared "
                                   f"reference and compare the values.",
            "required_instrument": f"as used in {wid}",
            "engine_native_score": 0.5,
            "novelty_self_claim": "none: a replication baseline"})
    return {"hof_version": "1.0",
            "run": {"engine": req.manifest.name, "seed_id": seed_id,
                    "backend": req.manifest["backend"],
                    "config_hash": req.config_hash},
            "hypotheses": hyps}
