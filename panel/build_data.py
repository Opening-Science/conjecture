"""Build the run panel's data from the active pack.

Two files, both derived, never typed:

    pack.json   what the pack and hub contain: the pack's name and
                questions, every engine and judge manifest with its
                status, requirements and cost profile, what has run
    data.json   the results of the pack's runs: candidates, certified
                and declined, convergences and conflicts, the verifier
                bench and the self-preference measurement

    python panel/build_data.py              # -> the pack's outputs/panel/
    python panel/build_data.py --out DIR

server.py builds both on every request, so the local panel is always
current; export.py writes them next to a static copy of the page.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PANEL = Path(__file__).resolve().parent
HUB = PANEL.parent
sys.path.insert(0, str(HUB))

import contract  # noqa: E402
from pack import PACK  # noqa: E402


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _hypotheses_per_engine() -> dict[str, int]:
    out: dict[str, int] = {}
    for f in sorted(PACK.runs_dir.glob("*.json")):
        engine = f.name.split(".")[1]
        out[engine] = out.get(engine, 0) + len(
            _load(f, {}).get("hypotheses", []))
    return out


def _plain(text: str) -> str:
    """Questions shown without long dashes (the OSF brand's copy rule);
    the seed files themselves are run history and stay as they were."""
    for dash in (" \u2014 ", " \u2013 "):
        text = text.replace(dash, ", ")
    return text.replace("\u2014", ", ").replace("\u2013", " to ")


def _questions() -> list[list[str]]:
    qs = []
    for f in sorted(PACK.seeds_dir.glob("*.json")):
        s = _load(f, {})
        qs.append([s.get("seed_id", f.stem), _plain(s.get("title", ""))])
    return qs


def _status(m, runs: dict[str, int]) -> dict:
    """What a row on the Run and Sources pages says about an adapter."""
    miss = m.missing() if m.built else []
    ran = runs.get(m.name, 0) if m.kind == "engine" else 0
    if not m.built:
        state = "designed"
    elif miss:
        state = "needs"
    else:
        state = "ready"
    res = _load(HUB / "conformance" / "results" / f"{m.kind}.{m.name}.json",
                {})
    return {"state": state, "missing": miss, "ran": ran,
            "conformance": res.get("status")}


def pack_json(local: bool = False) -> dict:
    """local: the panel is served from this machine, so its command hints
    may name real paths. A static export gets placeholders instead, so no
    local path ends up on a website."""
    runs = _hypotheses_per_engine()
    engines, judges, keys = [], [], set()
    for m in contract.discover():
        req = m.get("requires") or {}
        keys.update(req.get("env") or [])
        keys.update(req.get("env_any") or [])
        cost = m.get("cost") or {}
        tph = cost.get("tokens_per_hypothesis") or {}
        row = {"id": m.name, "name": m["title"], "summary": m["summary"],
               "built": m.built, "invocation": m["invocation"],
               "backend": m["backend"],
               "access": m["corpus_access"],
               "licence": m["upstream"]["licence"],
               "gated": bool(m["upstream"].get("output_terms")),
               "output_terms": m["upstream"].get("output_terms"),
               "blocker": m.get("blocker"),
               "requires": req, "labels": m.get("labels"),
               "cost": {"billing": cost.get("billing"),
                        "provider": cost.get("provider"),
                        "in": tph.get("input"), "out": tph.get("output")},
               **_status(m, runs)}
        (engines if m.kind == "engine" else judges).append(row)
    return {"pack": {"name": PACK.name, "title": PACK.title,
                     "n_works": PACK.n_works, "domain": PACK.domain},
            "questions": _questions(),
            "engines": engines, "judges": judges,
            "keys": sorted(keys),
            "run": ({"cd": str(HUB), "python": sys.executable,
                     "pack": str(PACK.path)} if local else
                    {"cd": "conjecture", "python": "python",
                     "pack": f"/path/to/{PACK.name}/pack.yaml"}),
            "has_findings": (PACK.outputs_dir / "panel"
                             / "findings.html").is_file()}


def data_json() -> dict:
    db = sqlite3.connect(f"file:{PACK.audit_db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cands = [dict(r) for r in db.execute(
        "SELECT * FROM candidates ORDER BY candidate_id")]
    db.close()
    merge = _load(PACK.merge_dir / "cluster_verdicts.json", {})
    board = _load(PACK.scoreboard, {})
    bench = PACK.bench_dir
    runs = [_load(f, {}) for f in sorted(PACK.runs_dir.glob("*.json"))]

    novel = [c for c in cands if c["certified"] and not c["is_restatement"]]
    return {
        "n_candidates": len(cands),
        "certified": sum(1 for c in cands if c["certified"]),
        "convergent": sum(1 for c in cands if c["convergent"]),
        "novel": len(novel),
        "mechanical_pass": sum(1 for c in cands if c["mechanical_pass"]),
        "by_level": dict(sorted(Counter(c["causal_level"]
                                        for c in cands).items())),
        "by_seed": dict(sorted(Counter(c["seed_id"]
                                       for c in cands).items())),
        "engines": {e["engine"]: {"candidates": e["candidates"],
                                  "certified": e["certified"],
                                  "novel": e["novelty_yield"],
                                  "mean_cites": e["mean_citations"]}
                    for e in board.get("engines", [])},
        "hypotheses": _hypotheses_per_engine(),
        "total_citations": sum(len(h.get("cited_work_ids") or [])
                               for p in runs for h in p.get("hypotheses", [])),
        "conflicts": len(merge.get("conflicts", [])),
        "convergences": [g for g in merge.get("groups", [])
                         if len(g.get("group", [])) > 1],
        "conflict_list": merge.get("conflicts", []),
        "selfpref": _load(bench / "self_preference.json", {}),
        "taskA": _load(bench / "taskA_results.json", {}),
        "cards": [{"id": c["candidate_id"], "seed": c["seed_id"],
                   "level": c["causal_level"], "statement": c["statement"],
                   "engines": c["engines"], "cites": c["n_citations"],
                   "near": c["nearest_claim"],
                   "sim": c["nearest_similarity"], "conv": c["convergent"],
                   "reason": c["judge_reason"]} for c in novel],
        "declined": [{"id": c["candidate_id"], "seed": c["seed_id"],
                      "statement": c["statement"],
                      "reason": c["judge_reason"]}
                     for c in cands if not c["certified"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, default=PACK.outputs_dir / "panel")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for name, build in (("pack.json", pack_json), ("data.json", data_json)):
        (a.out / name).write_text(json.dumps(build(), indent=1,
                                             ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        print(f"  {name} -> {a.out / name}")


if __name__ == "__main__":
    main()
