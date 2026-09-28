"""Build the full, ranked, searchable paper index for the entire field universe.

Every work in fieldmap.sqlite (all 18k), with abstract, DOI, authors, OA status,
a composite paper-importance rank, and an FTS5 full-text search index over title
and abstract. No PDFs, no network (abstracts are cached from the openness stage).

Paper rank (each term normalized to [0,1] across the corpus):
  0.30 citations       log-scaled cited_by_count
  0.25 seed proximity  seeds = 1.0; others = normalized universe link count
  0.20 core topic      primary topic matches the pack's build.core_topic_hints
  0.15 recency         newer work scores higher
  0.10 openness        OA + preprint + open-data signal

Outputs under outputs/index/:
  full_paper_index.sqlite   papers table (ranked) + papers_fts (FTS5)
  full_paper_index_ranked.csv   compact ranked list (no abstract column)
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

import config as C

ABS_CACHE = C.CACHE / "abstracts"
OUT_DIR = C.INDEX_DIR
OUT_DB = OUT_DIR / "full_paper_index.sqlite"
OUT_CSV = OUT_DIR / "full_paper_index_ranked.csv"
CORE_HINTS = C.CORE_TOPIC_HINTS


def norm(s: pd.Series, log: bool = False) -> pd.Series:
    x = np.log1p(s.astype(float)) if log else s.astype(float)
    lo, hi = x.min(), x.max()
    return (x - lo) / (hi - lo) if hi > lo else pd.Series(0.0, index=s.index)


def read_abstract(wid: str) -> str:
    p = ABS_CACHE / f"{wid}.json"
    if p.exists():
        try:
            return json.loads(p.read_text()) or ""
        except Exception:
            return ""
    return ""


def main():
    con = sqlite3.connect(C.DB_PATH)
    works = pd.read_sql_query(
        "SELECT work_id, doi, title, year, type, cited_by_count, oa_status, "
        "is_oa, is_seed, hop FROM works", con)
    print(f"Full universe: {len(works)} works")

    # universe link counts (seed connectivity from the 2-hop expansion)
    uni = json.loads((C.EXPORTS / "universe_ids.json").read_text())
    works["link_count"] = works["work_id"].map(
        lambda w: (uni.get(w) or {}).get("links") or 0)

    # primary topic per work + core-topic flag
    topics = pd.read_sql_query("SELECT work_id, topic_name, score FROM topics", con)
    prim = (topics.sort_values("score", ascending=False)
            .drop_duplicates("work_id").set_index("work_id")["topic_name"])
    works["primary_topic"] = works["work_id"].map(prim).fillna("")
    works["core_topic"] = works["primary_topic"].str.lower().apply(
        lambda t: int(any(h in t for h in CORE_HINTS)))

    # per-work openness signals
    try:
        wo = pd.read_sql_query(
            "SELECT work_id, has_preprint, open_signal FROM work_openness",
            con).set_index("work_id")
        works = works.join(wo, on="work_id")
    except Exception:
        works["has_preprint"] = 0
        works["open_signal"] = 0
    works[["has_preprint", "open_signal"]] = works[
        ["has_preprint", "open_signal"]].fillna(0)

    # author list per work (top 6 by position)
    wa = pd.read_sql_query(
        "SELECT wa.work_id, wa.position, a.display_name "
        "FROM work_authors wa JOIN authors a ON a.author_id=wa.author_id", con)
    order = {"first": 0, "middle": 1, "last": 2}
    wa["ord"] = wa["position"].map(order).fillna(1)
    wa = wa.sort_values(["work_id", "ord"])
    authors = (wa.groupby("work_id")["display_name"]
               .apply(lambda s: "; ".join([x for x in s if pd.notna(x)][:6])))
    works["authors"] = works["work_id"].map(authors).fillna("")
    con.close()

    # --- composite rank -------------------------------------------------
    seed = works["is_seed"] == 1
    s_cite = norm(works["cited_by_count"].fillna(0), log=True)
    s_link = norm(works["link_count"].fillna(0))
    s_link = s_link.where(~seed, 1.0)                # seeds get max proximity
    s_core = works["core_topic"].astype(float)
    yr = works["year"].fillna(works["year"].median())
    s_recent = norm(yr)
    s_open = (works["is_oa"].fillna(0) + works["has_preprint"] +
              works["open_signal"]) / 3.0
    works["paper_rank_score"] = (0.30 * s_cite + 0.25 * s_link +
                                 0.20 * s_core + 0.15 * s_recent +
                                 0.10 * s_open).round(4)
    works = works.sort_values("paper_rank_score", ascending=False).reset_index(drop=True)
    works.insert(0, "rank", range(1, len(works) + 1))

    works["abstract"] = works["work_id"].map(read_abstract)
    works["openalex_url"] = "https://openalex.org/" + works["work_id"]
    works["link"] = works["doi"].apply(
        lambda d: (d if str(d).startswith("http")
                   else f"https://doi.org/{d}") if d else "")

    # --- write DB + FTS -------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_DB.exists():
        OUT_DB.unlink()
    db = sqlite3.connect(OUT_DB)
    cols = ["rank", "work_id", "doi", "title", "authors", "year", "type",
            "cited_by_count", "link_count", "primary_topic", "core_topic",
            "oa_status", "is_oa", "is_seed", "hop", "has_preprint",
            "open_signal", "paper_rank_score", "abstract", "openalex_url", "link"]
    works[cols].to_sql("papers", db, index=False)
    db.executescript(
        "CREATE INDEX idx_rank ON papers(rank);"
        "CREATE INDEX idx_doi ON papers(doi);"
        "CREATE INDEX idx_seed ON papers(is_seed);"
        "CREATE INDEX idx_topic ON papers(primary_topic);")
    n_fts = 0
    try:
        db.executescript(
            "CREATE VIRTUAL TABLE papers_fts USING fts5("
            "  work_id UNINDEXED, title, authors, abstract);"
            "INSERT INTO papers_fts (work_id, title, authors, abstract) "
            "  SELECT work_id, title, authors, abstract FROM papers;")
        n_fts = db.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0]
    except sqlite3.OperationalError as e:
        print(f"  NOTE: FTS5 unavailable ({e}); skipped search index.")
    db.commit()
    db.close()

    # compact ranked CSV (no abstract, to keep it small)
    works[[c for c in cols if c != "abstract"]].to_csv(OUT_CSV, index=False)

    print("=== build_full_index ===")
    print(f"  papers indexed: {len(works)}")
    print(f"  with DOI: {(works['doi'] != '').sum()}")
    print(f"  with abstract: {(works['abstract'].str.len() > 0).sum()}")
    print(f"  full-text index rows: {n_fts}")
    print(f"  top 5 by paper rank:")
    for r in works.head(5).itertuples():
        print(f"    {r.rank}. [{r.paper_rank_score}] {str(r.title)[:60]} "
              f"({r.year}, {r.cited_by_count}c)")
    print(f"  wrote {OUT_DB.name} + {OUT_CSV.name}")


if __name__ == "__main__":
    main()
