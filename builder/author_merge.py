"""Canonical author mapping to repair OpenAlex disambiguation splits.

OpenAlex splits some prolific authors across several ids (spec §10 flagged
Van Wijk and Popp). Blind name-based merging is dangerous: for common surnames
(Li, Wang, Yang, Lee) a 'surname + first-initial' key collides across genuinely
different people, and shared-field co-authorship/institution links them
spuriously. So we take the spec-faithful conservative path:

  * MERGE only a curated whitelist of verified core-author splits. The name key
    uses the FIRST NAME's initial, which already separates e.g. Roeland Van Wijk
    ('wijk r') from Eduard Van Wijk ('wijk e') — so whitelisting 'wijk e' merges
    the three Eduard records without touching Roeland.
  * FLAG every other same-key multi-id group to author_splits_flagged.json for
    manual eyeballing (spec §10), but map each id to itself (no merge).

This never fabricates a merge; broader disambiguation stays a manual follow-up.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from unidecode import unidecode

import config as C


def _name_key(display_name: str) -> str | None:
    if not display_name:
        return None
    parts = unidecode(display_name).lower().replace(".", " ").split()
    parts = [p for p in parts if p not in {"van", "von", "de", "der", "den"}]
    if not parts:
        return None
    # surname = last token; first initial = first token's first char
    surname = parts[-1]
    first_initial = parts[0][0] if parts[0] else ""
    return f"{surname} {first_initial}"


def build_canonical_map(con: sqlite3.Connection) -> dict[str, str]:
    cur = con.cursor()
    authors = cur.execute(
        "SELECT author_id, display_name, works_count FROM authors").fetchall()

    # in-universe works per author + institutions + coauthors + seed works
    wa = cur.execute(
        "SELECT work_id, author_id FROM work_authors").fetchall()
    works_by_author = defaultdict(set)
    authors_by_work = defaultdict(set)
    for wid, aid in wa:
        works_by_author[aid].add(wid)
        authors_by_work[wid].add(aid)
    coauthors = defaultdict(set)
    for wid, aset in authors_by_work.items():
        for a in aset:
            coauthors[a] |= aset
    inst_by_author = defaultdict(set)
    for aid, iid in cur.execute(
        "SELECT author_id, last_institution_id FROM authors").fetchall():
        if iid:
            inst_by_author[aid].add(iid)
    seed_ids = {r[0] for r in cur.execute(
        "SELECT work_id FROM works WHERE is_seed=1").fetchall()}

    # Curated whitelist of verified core-author splits to merge (name keys),
    # from the pack's build.author_merge_whitelist.
    MERGE_WHITELIST = C.AUTHOR_MERGE_WHITELIST

    # group by name key
    groups: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for aid, name, wc in authors:
        k = _name_key(name)
        if k:
            groups[k].append((aid, name or "", wc or 0))

    canonical: dict[str, str] = {}
    merges: list[dict] = []
    flagged: list[dict] = []
    for k, members in groups.items():
        if len(members) < 2:
            canonical[members[0][0]] = members[0][0]
            continue
        members_sorted = sorted(
            members,
            key=lambda m: (len(works_by_author[m[0]]), m[2]), reverse=True)
        if k in MERGE_WHITELIST:
            canon_id = members_sorted[0][0]
            for aid, name, wc in members_sorted:
                canonical[aid] = canon_id
            merges.append({
                "canonical": canon_id, "name_key": k,
                "merged_ids": [m[0] for m in members_sorted],
                "names": sorted({m[1] for m in members}),
            })
        else:
            # keep separate; flag for manual review if it looks like a split
            # (>=2 records that share a seed work — strong same-person hint)
            for aid, name, wc in members_sorted:
                canonical[aid] = aid
            share_seed = any(
                works_by_author[a[0]] & works_by_author[b[0]] & seed_ids
                for i, a in enumerate(members_sorted)
                for b in members_sorted[i + 1:])
            if share_seed:
                flagged.append({
                    "name_key": k,
                    "ids": [m[0] for m in members_sorted],
                    "names": sorted({m[1] for m in members}),
                })

    for aid, name, wc in authors:
        canonical.setdefault(aid, aid)

    (C.EXPORTS / "author_merges.json").write_text(json.dumps(merges, indent=2))
    (C.EXPORTS / "author_splits_flagged.json").write_text(
        json.dumps(flagged, indent=2))
    return canonical


def canonical_display_names(con: sqlite3.Connection,
                            canon: dict[str, str]) -> dict[str, str]:
    cur = con.cursor()
    names = dict(cur.execute(
        "SELECT author_id, display_name FROM authors").fetchall())
    # for each canonical id use its own display name
    return {cid: names.get(cid, cid) for cid in set(canon.values())}


if __name__ == "__main__":
    con = sqlite3.connect(C.DB_PATH)
    m = build_canonical_map(con)
    merges = json.loads((C.EXPORTS / "author_merges.json").read_text())
    flagged = json.loads((C.EXPORTS / "author_splits_flagged.json").read_text())
    print(f"Built canonical map for {len(set(m.values()))} canonical authors "
          f"from {len(m)} raw ids.")
    print(f"Merged (whitelist) {len(merges)} groups:")
    for g in merges:
        print(f"  {g['name_key']}: {len(g['merged_ids'])} ids <- {g['names']}")
    print(f"Flagged {len(flagged)} possible splits for manual review "
          f"(share a seed work; NOT merged). Examples:")
    for g in flagged[:10]:
        print(f"  {g['name_key']}: {g['names']}")
