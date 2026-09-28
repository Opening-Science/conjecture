"""Stage B — 2-hop backward+forward citation expansion with pruning.

hop-1: union of seed references (backward) + works citing seeds (forward),
       pruned to candidates linking to >=2 seeds.
hop-2: expand backward+forward only from the pruned hop-1 core, pruned at
       >=3 links. Respect HARD_CAP_WORKS. Every prune/cap is logged.

Request efficiency (OpenAlex moved to usage-based pricing in 2026, ~10k list
calls/day on a free key): the forward direction is BATCHED -- one
`cites:W1|W2|...|W50` query covers 50 sources at once, and each returned work's
`referenced_works` is intersected with the source set to get its exact
link-count. Backward + related links come from cached source metadata (zero
extra calls). Every returned work is cached, so a rerun is free/resumable.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from tqdm import tqdm

import config as C
from openalex import OpenAlex, oa_short_id

LOG_LINES: list[str] = []

CITES_BATCH = 50  # source ids per batched cites query


def log(msg: str) -> None:
    print(msg)
    LOG_LINES.append(msg)


def load_seed_ids() -> list[str]:
    return json.loads((C.EXPORTS / "seed_work_ids.json").read_text())


def _cache_work(sid: str, w: dict) -> None:
    cp = C.CACHE / "works" / f"{sid}.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(w))


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def backward_and_related_links(oa: OpenAlex, source_ids: list[str],
                               link_count: dict[str, int]) -> None:
    """Add +1 per (source references candidate) and (source lists candidate
    as related). Reads cached source metadata only -- no network calls beyond
    fetching the source works themselves (batched, mostly already cached)."""
    source_works = oa.works_by_ids(source_ids)
    n_ref = 0
    for sid, w in source_works.items():
        if not w:
            continue
        for r in (w.get("referenced_works") or []):
            link_count[oa_short_id(r)] += 1
            n_ref += 1
        for r in (w.get("related_works") or []):
            link_count[oa_short_id(r)] += 1
    return n_ref


def forward_links_batched(oa: OpenAlex, source_ids: list[str],
                          source_set: set[str], link_count: dict[str, int],
                          hop_name: str) -> tuple[int, int]:
    """Batched forward citation. One `cites:W1|...|W50` query per batch, sorted
    cited_by_count:desc and truncated at FORWARD_MAX_WORKS_PER_BATCH so a batch
    with hyper-cited sources cannot page its whole citing set. Each candidate's
    exact link-count = |referenced_works ∩ source_set|. Per-batch citer-id lists
    are cached so a rerun does not re-page. Returns (distinct_citers, n_capped)."""
    seen: set[str] = set()
    n_capped = 0
    cache_dir = C.CACHE / "fwdbatch"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cap = C.FORWARD_MAX_WORKS_PER_BATCH
    batches = list(_chunks(source_ids, CITES_BATCH))

    for batch in tqdm(batches, desc=f"{hop_name} forward-cites (batched)"):
        key = hashlib.md5("|".join(sorted(batch)).encode()).hexdigest()
        cp = cache_dir / f"{hop_name}_{key}.json"
        if cp.exists():
            citer_ids = json.loads(cp.read_text())
        else:
            citer_ids = []
            n = 0
            for w in oa.paged("works", "cites:" + "|".join(batch),
                              select=C.WORK_SELECT,
                              sort="cited_by_count:desc", cap=cap):
                cid = oa_short_id(w["id"])
                _cache_work(cid, w)
                citer_ids.append(cid)
                n += 1
            if n >= cap:
                n_capped += 1
                log(f"    [{hop_name}] forward-cite CAP hit on a batch: kept "
                    f"top {cap} by cited_by_count")
            cp.write_text(json.dumps(citer_ids))

        for cid in citer_ids:
            if cid in seen:
                continue
            seen.add(cid)
            w = oa.get_cached("works", cid)
            if not w:
                continue
            refs = {oa_short_id(r) for r in (w.get("referenced_works") or [])}
            k = len(refs & source_set)
            if k:
                link_count[cid] += k
    return len(seen), n_capped


def expand_hop(oa: OpenAlex, source_ids: list[str], seed_set: set[str],
               min_links: int, hop_name: str, already: set[str]
               ) -> tuple[list[str], dict[str, int]]:
    link_count: dict[str, int] = defaultdict(int)

    n_ref = backward_and_related_links(oa, source_ids, link_count)
    log(f"  [{hop_name}] backward+related: {len(source_ids)} sources -> "
        f"{n_ref} ref-links, {len(link_count)} distinct candidates so far")

    n_citers, n_capped = forward_links_batched(
        oa, source_ids, set(source_ids), link_count, hop_name)
    log(f"  [{hop_name}] forward (batched): {n_citers} distinct citing works "
        f"({n_capped} batches hit the per-batch cap)")

    candidates = {k: v for k, v in link_count.items()
                  if k and k not in seed_set and k not in already}
    kept = {k: v for k, v in candidates.items() if v >= min_links}
    log(f"  [{hop_name}] prune >= {min_links} links: "
        f"{len(candidates)} candidates -> {len(kept)} kept, "
        f"{len(candidates) - len(kept)} dropped")
    return list(kept.keys()), kept


def enforce_cap(universe: dict[str, dict], link_scores: dict[str, int]
                ) -> dict[str, dict]:
    if len(universe) <= C.HARD_CAP_WORKS:
        return universe
    seeds = {k: v for k, v in universe.items() if v["hop"] == 0}
    non_seed = [(k, v) for k, v in universe.items() if v["hop"] != 0]
    non_seed.sort(key=lambda kv: link_scores.get(kv[0], 0), reverse=True)
    room = C.HARD_CAP_WORKS - len(seeds)
    kept_non_seed = dict(non_seed[:room])
    log(f"  HARD_CAP_WORKS={C.HARD_CAP_WORKS} hit: dropped "
        f"{len(non_seed) - len(kept_non_seed)} lowest-link-density works")
    return {**seeds, **kept_non_seed}


def main() -> None:
    oa = OpenAlex()
    if not C.API_KEY:
        log("WARNING: no OpenAlex API key (OPENALEX_API_KEY). The keyless "
            "budget is only ~1,000 calls/day and may be exhausted. Get a free "
            "key at openalex.org/settings/api.")
    seed_ids = load_seed_ids()
    seed_set = set(seed_ids)
    log(f"=== Stage B: {C.HOPS}-hop expansion (batched, key-aware) ===")
    log(f"Seeds: {len(seed_ids)}")

    oa.works_by_ids(seed_ids)  # ensure seed works cached

    universe: dict[str, dict] = {sid: {"hop": 0, "links": None}
                                 for sid in seed_ids}
    link_scores: dict[str, int] = {}

    hop1_ids, hop1_links = expand_hop(
        oa, seed_ids, seed_set, C.HOP1_MIN_LINKS, "hop1", set(universe))
    for k, v in hop1_links.items():
        universe[k] = {"hop": 1, "links": v}
        link_scores[k] = v
    log(f"After hop-1: universe = {len(universe)} works ({len(hop1_ids)} new)")

    if C.HOPS >= 2:
        hop2_ids, hop2_links = expand_hop(
            oa, hop1_ids, seed_set, C.HOP2_MIN_LINKS, "hop2", set(universe))
        for k, v in hop2_links.items():
            universe[k] = {"hop": 2, "links": v}
            link_scores[k] = v
        log(f"After hop-2: universe = {len(universe)} works "
            f"({len(hop2_ids)} new)")

    universe = enforce_cap(universe, link_scores)

    log(f"Fetching/caching {len(universe)} universe works...")
    oa.works_by_ids(list(universe))

    (C.EXPORTS / "universe_ids.json").write_text(json.dumps(dict(universe)))
    log(f"Wrote universe_ids.json ({len(universe)} works). "
        f"OpenAlex requests this run: {oa.n_requests}")

    with open(C.RUN_LOG, "a", encoding="utf-8") as f:
        f.write("\n## Stage B — expansion (batched)\n\n")
        for line in LOG_LINES:
            f.write(line + "\n")
    oa.close()


if __name__ == "__main__":
    main()
