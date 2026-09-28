"""Stage C — normalize the cached OpenAlex entities into SQLite + exports.

Reads universe_ids.json + the work cache, fetches author/institution
entities as needed, and writes the schema from spec §4 (Stage C). Emits
parquet + CSV exports alongside the SQLite DB. Idempotent: drops and rebuilds.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

import pandas as pd
from tqdm import tqdm

import config as C
from openalex import OpenAlex, oa_short_id

SCHEMA = """
CREATE TABLE works(
  work_id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER, type TEXT,
  cited_by_count INTEGER, oa_status TEXT, is_oa INTEGER, oa_url TEXT,
  lang TEXT, is_seed INTEGER, hop INTEGER
);
CREATE TABLE authors(
  author_id TEXT PRIMARY KEY, display_name TEXT, orcid TEXT,
  works_count INTEGER, cited_by_count INTEGER, mean_citedness_2y REAL,
  last_institution_id TEXT, country TEXT
);
CREATE TABLE institutions(
  inst_id TEXT PRIMARY KEY, display_name TEXT, type TEXT, country TEXT, ror TEXT
);
CREATE TABLE work_authors(
  work_id TEXT, author_id TEXT, position TEXT, is_corresponding INTEGER,
  raw_affiliation_string TEXT
);
CREATE TABLE topics(
  work_id TEXT, topic_id TEXT, topic_name TEXT, domain TEXT, field TEXT,
  subfield TEXT, score REAL
);
CREATE TABLE concepts(
  work_id TEXT, concept_id TEXT, concept_name TEXT, level INTEGER, score REAL
);
CREATE TABLE citation_edges(src_work_id TEXT, dst_work_id TEXT);
CREATE INDEX idx_wa_work ON work_authors(work_id);
CREATE INDEX idx_wa_author ON work_authors(author_id);
CREATE INDEX idx_edge_src ON citation_edges(src_work_id);
CREATE INDEX idx_edge_dst ON citation_edges(dst_work_id);
CREATE INDEX idx_topics_work ON topics(work_id);
"""


def load_universe() -> dict[str, dict]:
    return json.loads((C.EXPORTS / "universe_ids.json").read_text())


def main() -> None:
    universe = load_universe()
    universe_set = set(universe)
    oa = OpenAlex()

    if C.DB_PATH.exists():
        C.DB_PATH.unlink()
    con = sqlite3.connect(C.DB_PATH)
    con.executescript(SCHEMA)
    cur = con.cursor()

    author_ids: set[str] = set()
    inst_ids: set[str] = set()
    inst_from_authorship: dict[str, dict] = {}

    print(f"Normalizing {len(universe)} works...")
    n_missing = 0
    for sid, meta in tqdm(universe.items(), desc="works"):
        w = oa.get_cached("works", sid)
        if not w:
            n_missing += 1
            continue
        oa_status = (w.get("open_access") or {}).get("oa_status")
        is_oa = 1 if (w.get("open_access") or {}).get("is_oa") else 0
        oa_url = (w.get("open_access") or {}).get("oa_url")
        cur.execute(
            "INSERT OR REPLACE INTO works VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, (w.get("doi") or "").replace("https://doi.org/", ""),
             w.get("title"), w.get("publication_year"), w.get("type"),
             w.get("cited_by_count"), oa_status, is_oa, oa_url,
             w.get("language"), 1 if meta["hop"] == 0 else 0, meta["hop"]))

        # authorships
        for a in (w.get("authorships") or []):
            au = a.get("author") or {}
            aid = oa_short_id(au.get("id") or "")
            if not aid:
                continue
            author_ids.add(aid)
            raw_aff = "; ".join(a.get("raw_affiliation_strings") or [])
            is_corr = 1 if a.get("is_corresponding") else 0
            cur.execute(
                "INSERT INTO work_authors VALUES (?,?,?,?,?)",
                (sid, aid, a.get("author_position"), is_corr, raw_aff))
            for inst in (a.get("institutions") or []):
                iid = oa_short_id(inst.get("id") or "")
                if iid:
                    inst_ids.add(iid)
                    inst_from_authorship.setdefault(iid, {
                        "display_name": inst.get("display_name"),
                        "type": inst.get("type"),
                        "country": inst.get("country_code"),
                        "ror": inst.get("ror"),
                    })

        # topics
        for t in (w.get("topics") or []):
            cur.execute(
                "INSERT INTO topics VALUES (?,?,?,?,?,?,?)",
                (sid, oa_short_id(t.get("id") or ""), t.get("display_name"),
                 (t.get("domain") or {}).get("display_name"),
                 (t.get("field") or {}).get("display_name"),
                 (t.get("subfield") or {}).get("display_name"),
                 t.get("score")))
        # concepts (legacy taxonomy, kept for continuity)
        for cc in (w.get("concepts") or []):
            cur.execute(
                "INSERT INTO concepts VALUES (?,?,?,?,?)",
                (sid, oa_short_id(cc.get("id") or ""), cc.get("display_name"),
                 cc.get("level"), cc.get("score")))

        # citation edges — keep only edges to works inside the universe
        for r in (w.get("referenced_works") or []):
            dst = oa_short_id(r)
            if dst in universe_set:
                cur.execute("INSERT INTO citation_edges VALUES (?,?)", (sid, dst))

    con.commit()
    print(f"  works inserted; {n_missing} cached-null works skipped")

    # --- authors (batched entity fetch for richer fields) ----------------
    print(f"Fetching {len(author_ids)} author entities (batched)...")
    author_objs = oa.entities_by_ids(
        "authors", sorted(author_ids), select=C.AUTHOR_SELECT)
    for aid in tqdm(sorted(author_ids), desc="authors"):
        a = author_objs.get(aid)
        if not a:
            cur.execute("INSERT OR REPLACE INTO authors VALUES (?,?,?,?,?,?,?,?)",
                        (aid, None, None, None, None, None, None, None))
            continue
        lki = a.get("last_known_institutions") or []
        last_inst, country = None, None
        if lki:
            last_inst = oa_short_id(lki[0].get("id") or "")
            country = lki[0].get("country_code")
            inst_ids.add(last_inst)
            inst_from_authorship.setdefault(last_inst, {
                "display_name": lki[0].get("display_name"),
                "type": lki[0].get("type"),
                "country": lki[0].get("country_code"),
                "ror": lki[0].get("ror"),
            })
        stats = a.get("summary_stats") or {}
        cur.execute(
            "INSERT OR REPLACE INTO authors VALUES (?,?,?,?,?,?,?,?)",
            (aid, a.get("display_name"), a.get("orcid"), a.get("works_count"),
             a.get("cited_by_count"), stats.get("2yr_mean_citedness"),
             last_inst, country))
    con.commit()

    # --- institutions ----------------------------------------------------
    print(f"Writing {len(inst_ids)} institutions...")
    for iid in sorted(inst_ids):
        info = inst_from_authorship.get(iid, {})
        cur.execute("INSERT OR REPLACE INTO institutions VALUES (?,?,?,?,?)",
                    (iid, info.get("display_name"), info.get("type"),
                     info.get("country"), info.get("ror")))
    con.commit()

    # --- exports (parquet + csv) -----------------------------------------
    print("Exporting parquet + csv...")
    for table in ["works", "authors", "institutions", "work_authors",
                  "topics", "concepts", "citation_edges"]:
        df = pd.read_sql_query(f"SELECT * FROM {table}", con)
        df.to_parquet(C.EXPORTS / f"{table}.parquet", index=False)
        df.to_csv(C.EXPORTS / f"{table}.csv", index=False)

    # --- summary ---------------------------------------------------------
    counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["works", "authors", "institutions", "work_authors",
                        "topics", "citation_edges"]}
    hop_counts = dict(cur.execute(
        "SELECT hop, COUNT(*) FROM works GROUP BY hop").fetchall())
    con.close()
    oa.close()

    print("\n=== Stage C: DB build ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"  works by hop: {hop_counts}")

    with open(C.RUN_LOG, "a", encoding="utf-8") as f:
        f.write("\n## Stage C — DB build\n\n")
        for k, v in counts.items():
            f.write(f"- {k}: {v}\n")
        f.write(f"- works by hop: {hop_counts}\n")
        f.write(f"- OpenAlex requests: {oa.n_requests}\n")


if __name__ == "__main__":
    main()
