"""Merge engine outputs into candidates, keeping provenance.

Two engines proposing the same hypothesis is a signal, not a
duplication problem — independent arrival is weak evidence that the
hypothesis is findable from the literature rather than invented. So we
cluster rather than discard, and every candidate records which engines
reached it.

Measured on this project's first run, lexical similarity does not work
for the cross-engine case: the highest TF-IDF cosine between any
Claude and Codex hypothesis on the same seed was 0.10, and the pair it
ranked highest was not the pair that a reader recognises as the same
idea (both engines independently proposed a circulated luminescent
transfer standard, in almost disjoint vocabulary). Scientific
hypotheses restate the same claim with different nouns, which is
exactly what a bag of words cannot see.

So the split is: TF-IDF handles same-engine repetition, where the
vocabulary really is shared, and semantic clustering across engines is
delegated to a model, one task per seed rather than per pair (a seed
holds around a dozen hypotheses, so one call sees them all and can
group them; pairwise judging would cost an order of magnitude more and
see less).

    python merge.py --prepare      # cluster + write clustering tasks
    python merge.py --apply        # fold in adjudicated clusters
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

RUNS = PACK.runs_dir
OUT = PACK.merge_dir
SIM_THRESHOLD = 0.45


def load_runs() -> list[dict]:
    """Every hypothesis from every engine run, flattened with provenance."""
    items = []
    for path in sorted(RUNS.glob("Q*.*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = payload.get("run", {})
        for h in payload.get("hypotheses", []):
            items.append({
                "src_file": path.name,
                "engine": run.get("engine", "?"),
                "backend": run.get("backend", "?"),
                "seed_id": run.get("seed_id", path.name.split(".")[0]),
                "hyp": h,
            })
    return items


def text_of(item: dict) -> str:
    h = item["hyp"]
    scope = h.get("scope") or {}
    return " ".join([
        h.get("statement", ""),
        scope.get("population", ""), scope.get("condition", ""),
        scope.get("outcome", ""), h.get("estimand", "") or "",
    ])


def cluster(items: list[dict]) -> tuple[list[list[int]], list[dict]]:
    """Union-find clustering over TF-IDF cosine within a seed.

    Only same-seed pairs are considered: two hypotheses answering
    different questions are not duplicates even if they read alike.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    texts = [text_of(i) for i in items]
    if len(texts) < 2:
        return [[i] for i in range(len(items))], []
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2),
                          min_df=1).fit_transform(texts)
    sim = cosine_similarity(vec)

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]["seed_id"] != items[j]["seed_id"]:
                continue
            s = float(sim[i][j])
            # same-engine near-duplicates merge without adjudication: an
            # engine repeating itself is not a convergence signal, and
            # within one engine the vocabulary really is shared
            if items[i]["engine"] == items[j]["engine"] and s >= SIM_THRESHOLD:
                pairs.append({
                    "i": i, "j": j, "similarity": round(s, 3),
                    "seed_id": items[i]["seed_id"],
                    "a_engine": items[i]["engine"],
                    "b_engine": items[j]["engine"],
                    "a": items[i]["hyp"]["statement"],
                    "b": items[j]["hyp"]["statement"],
                })
                union(i, j)
    groups: dict[int, list[int]] = {}
    for idx in range(len(items)):
        groups.setdefault(find(idx), []).append(idx)
    return list(groups.values()), pairs


def apply_clusters(items: list[dict], parent_clusters: list[list[int]],
                   verdict_path: Path) -> list[list[int]]:
    """Fold model-adjudicated cross-engine groups into the clusters."""
    if not verdict_path.exists():
        return parent_clusters
    key_to_index = {f"{it['hyp'].get('id')}#{it['engine']}": n
                    for n, it in enumerate(items)}
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for cl in parent_clusters:          # keep the same-engine merges
        for other in cl[1:]:
            union(cl[0], other)
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    groups = []
    if isinstance(raw, dict):
        # either {"groups": [...], "conflicts": [...]} or {seed: [...]}
        if "groups" in raw:
            groups = raw["groups"]
        else:
            for v in raw.values():
                groups.extend(v.get("groups", v) if isinstance(v, dict)
                              else v)
    else:
        groups = raw
    for g in groups:
        members = g.get("group") if isinstance(g, dict) else g
        idxs = [key_to_index[k] for k in (members or [])
                if k in key_to_index]
        for other in idxs[1:]:
            union(idxs[0], other)
    out: dict[int, list[int]] = {}
    for idx in range(len(items)):
        out.setdefault(find(idx), []).append(idx)
    return list(out.values())


def build_candidates(items: list[dict], clusters: list[list[int]]
                     ) -> list[dict]:
    out = []
    for n, idxs in enumerate(sorted(clusters,
                                    key=lambda c: items[c[0]]["seed_id"]), 1):
        members = [items[i] for i in idxs]
        # the fullest-cited member represents the cluster
        lead = max(members, key=lambda m: len(m["hyp"].get(
            "cited_work_ids", [])))
        engines = sorted({m["engine"] for m in members})
        cand = {
            "candidate_id": f"C{n:03d}",
            "seed_id": lead["seed_id"],
            "engines": engines,
            "convergent": len(engines) > 1,
            "n_members": len(members),
            "members": [{"engine": m["engine"], "src": m["src_file"],
                         "hyp_id": m["hyp"].get("id"),
                         "statement": m["hyp"].get("statement")}
                        for m in members],
            "hypothesis": lead["hyp"],
        }
        out.append(cand)
    return out


CLUSTER_PROMPT = """You are grouping generated scientific hypotheses that \
say the SAME THING in different words.

For one research question you are given every hypothesis produced by \
several independent engines. Group only hypotheses that make \
substantially the same claim: same measurand, same population or \
preparation, same predicted direction. Two hypotheses that merely share \
a topic, or that propose different measurements of the same phenomenon, \
are NOT the same claim and must stay in separate groups. Splitting is \
the safe error here; merging distinct claims destroys information.

Report two things.

1. GROUPS. Every id appears in exactly one group; singletons are \
expected and normal.

2. CONFLICTS. Pairs that assert INCOMPATIBLE things about the same \
question — where one being right makes the other wrong. These are the \
most valuable output of the whole exercise, because a pair of \
contradictory hypotheses about the same measurand defines a \
discriminating experiment. Report them even when the two came from the \
same engine.

Return ONLY JSON:

{"groups": [{"group": ["Q5-2#baseline-claude", "Q5-4#codex-solo"], \
"same_claim": "<one clause naming the shared claim>"}],
 "conflicts": [{"pair": ["Q1-5#baseline-claude", "Q1-4#codex-solo"], \
"incompatibility": "<what exactly they disagree about>", \
"discriminating_measurement": "<the measurement that would decide \
between them, if one is implied>"}]}

Hypotheses:
"""


def cluster_tasks(items: list[dict]) -> dict[str, list[dict]]:
    """One clustering task per seed: all its hypotheses in one view."""
    by_seed: dict[str, list[dict]] = {}
    for idx, it in enumerate(items):
        by_seed.setdefault(it["seed_id"], []).append({
            "key": f"{it['hyp'].get('id')}#{it['engine']}",
            "index": idx,
            "engine": it["engine"],
            "statement": it["hyp"].get("statement"),
            "scope": it["hyp"].get("scope"),
            "estimand": it["hyp"].get("estimand"),
        })
    return by_seed


def main() -> None:
    global SIM_THRESHOLD
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--threshold", type=float, default=SIM_THRESHOLD)
    a = ap.parse_args()
    SIM_THRESHOLD = a.threshold

    items = load_runs()
    if not items:
        raise SystemExit("no engine runs found in runs/")
    clusters, pairs = cluster(items)
    clusters = apply_clusters(items, clusters, OUT / "cluster_verdicts.json")
    cands = build_candidates(items, clusters)
    OUT.mkdir(exist_ok=True)
    (OUT / "candidates.json").write_text(
        json.dumps(cands, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "adjudication_pairs.json").write_text(
        json.dumps(pairs, indent=1, ensure_ascii=False), encoding="utf-8")
    tasks = cluster_tasks(items)
    (OUT / "cluster_tasks.json").write_text(
        json.dumps(tasks, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "cluster_prompt.md").write_text(CLUSTER_PROMPT, encoding="utf-8")
    print(f"  {len(tasks)} per-seed clustering tasks -> cluster_tasks.json")

    by_engine: dict[str, int] = {}
    for i in items:
        by_engine[i["engine"]] = by_engine.get(i["engine"], 0) + 1
    conv = sum(1 for c in cands if c["convergent"])
    print(f"  {len(items)} hypotheses from {len(by_engine)} engines "
          f"{by_engine}")
    print(f"  -> {len(cands)} candidates ({conv} convergent across engines)")
    print(f"  {len(pairs)} cross-engine pairs above {SIM_THRESHOLD} "
          "written for adjudication")


if __name__ == "__main__":
    main()
