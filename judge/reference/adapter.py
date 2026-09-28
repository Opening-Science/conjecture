"""Judge: the reference judge. No model; a floor, not an auditor.

A citation step survives if most of its content words occur in the
title or abstract of a work it cites; the experiment is testable if it
names a comparison. That catches only the crudest miscitation, which is
the point: any model judge should do strictly better.
"""
from __future__ import annotations

import re

WORD = re.compile(r"[a-z][a-z0-9]{3,}")
COMPARES = re.compile(r"\b(compar\w*|versus|vs\.?|paired|control\w*|"
                      r"against|relative to)\b", re.I)
SUPPORT = 0.6


def words(text: str) -> set[str]:
    return set(WORD.findall((text or "").lower()))


def verdict(item: dict) -> dict:
    shown = {w["work_id"]: words(f"{w.get('title')} {w.get('abstract')}")
             for w in item.get("cited_works") or []}
    base = {"candidate_id": item["candidate_id"], "novel": True}
    for i, step in enumerate(item.get("rationale") or []):
        if step.get("justification_type") != "citation":
            continue
        need = words(step.get("step"))
        have = set().union(*(shown.get(w, set())
                             for w in step.get("work_ids") or []))
        if not need or len(need & have) / len(need) < SUPPORT:
            return {**base, "verdict": "declined", "failing_step": i,
                    "grounded": False, "testable": True,
                    "reason": f"step {i} is not borne out by the abstracts "
                              f"it cites"}
    if not COMPARES.search(item.get("proposed_experiment") or ""):
        return {**base, "verdict": "declined", "failing_step": None,
                "grounded": True, "testable": False,
                "reason": "the proposed experiment names no comparison"}
    return {**base, "verdict": "certified", "failing_step": None,
            "grounded": True, "testable": True,
            "reason": "every citation step overlaps its cited abstracts"}


def judge(req) -> list[dict]:
    return [verdict(item) for item in req.items]
