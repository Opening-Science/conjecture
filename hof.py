"""Validate and normalise HOF payloads.

Schema validation is necessary but not sufficient: the checks that
actually matter are semantic, and they are the ones an engine is most
likely to fail. A hypothesis that cites a work_id which is not in the
corpus is not a hypothesis about this literature, it is a hallucination
with a plausible shape, and it must be caught here rather than in the
certification stage where it would consume judge budget.

    python hof.py runs/Q5.baseline-claude.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema" / "hof.schema.json"
WORK_ID_OK = __import__("re").compile(r"^W[0-9]+$")


def config_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode())
    return h.hexdigest()[:12]


def validate(payload: dict, corpus=None) -> list[str]:
    """Return a list of problems; empty means the payload is usable.

    corpus, when supplied, is used to check that every cited work_id
    actually exists — the check that separates grounded output from
    fluent invention.
    """
    problems: list[str] = []
    try:
        import jsonschema
        schema = json.loads(SCHEMA.read_text())
        for err in jsonschema.Draft202012Validator(schema).iter_errors(
                payload):
            loc = "/".join(str(p) for p in err.path)
            problems.append(f"schema[{loc}]: {err.message}")
    except ImportError:
        # structural fallback so the pipeline still runs without the dep
        if payload.get("hof_version") != "1.0":
            problems.append("hof_version must be '1.0'")
        if not isinstance(payload.get("hypotheses"), list):
            problems.append("hypotheses must be a list")

    seen_ids = set()
    for i, h in enumerate(payload.get("hypotheses", [])):
        tag = f"hypotheses[{i}]"
        hid = h.get("id")
        if hid in seen_ids:
            problems.append(f"{tag}: duplicate id {hid!r}")
        seen_ids.add(hid)

        cited = h.get("cited_work_ids") or []
        for wid in cited:
            if not WORK_ID_OK.match(str(wid)):
                problems.append(f"{tag}: malformed work_id {wid!r}")
            elif corpus is not None and corpus.get_work(wid) is None:
                problems.append(
                    f"{tag}: cited work {wid} is not in the corpus")

        # a citation step with no work_ids is an unfalsifiable appeal
        for j, step in enumerate(h.get("rationale") or []):
            if step.get("justification_type") == "citation":
                ids = step.get("work_ids") or []
                if not ids:
                    problems.append(
                        f"{tag}.rationale[{j}]: citation step carries no "
                        "work_ids")
                for wid in ids:
                    if wid not in cited:
                        problems.append(
                            f"{tag}.rationale[{j}]: cites {wid} which is "
                            "absent from cited_work_ids")
        if not cited:
            problems.append(f"{tag}: no cited_work_ids (ungrounded)")
    return problems


def load(path: Path, corpus=None, strict: bool = True) -> dict:
    payload = json.loads(Path(path).read_text())
    problems = validate(payload, corpus=corpus)
    if problems and strict:
        raise ValueError(
            f"{path.name}: {len(problems)} HOF problems\n  "
            + "\n  ".join(problems[:20]))
    payload["_problems"] = problems
    return payload


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--no-corpus", action="store_true")
    a = ap.parse_args()
    corpus = None
    if not a.no_corpus:
        sys.path.insert(0, str(HERE))
        from corpus_api import Corpus
        corpus = Corpus()
    bad = 0
    for p in a.paths:
        payload = json.loads(p.read_text())
        problems = validate(payload, corpus=corpus)
        n = len(payload.get("hypotheses", []))
        if problems:
            bad += 1
            print(f"FAIL {p.name}: {n} hypotheses, {len(problems)} problems")
            for pr in problems[:10]:
                print(f"   - {pr}")
        else:
            print(f"OK   {p.name}: {n} hypotheses")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    _main()
