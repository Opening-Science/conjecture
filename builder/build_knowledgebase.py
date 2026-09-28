"""Join the full-text corpus to the field map in one queryable database.

Stage K. Everything the analysis needs sits in four places -- the works/
authors/topics tables (fieldmap.sqlite), the clustering exports (optional),
the ranked abstract index, and the extracted full text (fulltext.sqlite).
This stage denormalizes them into the pack's knowledgebase (corpus.
knowledgebase in pack.yaml) so a single query can ask questions like "who
are the most-published living authors in the core strand whose papers we
hold in full text, and what do those papers say is unsolved?". It is what
the hub's corpus API serves to engines.

Tables:
  works           one row per work in the universe, with cluster, sub-strand,
                  rank score, abstract, full-text status and quality
  authors         canonical authors with openness, output, activity span
  work_authors    link table (canonical ids)
  statements      mined open-question/limitation/gap sentences (from stage J)
  works_fts       FTS5 over title+abstract+fulltext (porter-stemmed)

Rebuilds do not destroy what later stages wrote. The database is built into
a temporary file; then every table this stage does not own (the hypothesis
registry and its adversarially verified evidence, which a pack curates
with its own tools) and the
outside-universe rows that ingest_reference_works.py adds to `works` are
carried over from the previous build (rowids included, because the
verification audit trail addresses evidence rows by rowid), and only then
is the file swapped in. hypothesis_inventory.py refuses to rescan over
verified rows by design, so a rebuild that dropped them could not be
repaired by rerunning it.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd

import config as C

LIT = C.LIT
FT_DB = LIT / "fulltext.sqlite"
KB = C.KB_PATH
KB_TMP = KB.with_name(KB.name + ".building")
IDX_DB = C.INDEX_DIR / "full_paper_index.sqlite"

# tables this stage rebuilds from scratch; everything else in the previous
# build belongs to a later stage and is carried over verbatim
OWNED = {"works", "authors", "work_authors", "statements", "works_fts"}

def load_communities() -> pd.DataFrame | None:
    """work_id -> cluster assignments, if a clustering stage has run.

    Clustering is optional for the hub: engines never read it. When an
    export exists, `community` is the coupling numbering, and a v2 export's
    CPM clustering rides along as `community_v2` (+ per-node `stability`).
    Without one the columns stay empty.
    """
    v2 = C.EXPORTS / "work_communities_v2.csv"
    if v2.exists():
        df = pd.read_csv(v2)
        cols = ["work_id", "coupling_community"]
        for extra in ("community_v2", "stability"):
            if extra in df.columns:
                cols.append(extra)
        print(f"  communities from {v2.name} ({', '.join(cols[1:])})")
        return df[cols].rename(columns={"coupling_community": "community"})
    for fname, col in (("work_communities_normalized.csv", "community_norm"),
                       ("work_communities.csv", "coupling_community")):
        path = C.EXPORTS / fname
        if path.exists():
            df = pd.read_csv(path)
            if col in df.columns:
                print(f"  communities from {fname}:{col}")
                return df[["work_id", col]].rename(columns={col: "community"})
    print("  no clustering export: community left empty")
    return None


def carry_over(out: sqlite3.Connection, old: Path) -> tuple[list[str], int]:
    """Copy later stages' tables and outside-universe works from `old`."""
    if not old.exists():
        return [], 0
    out.execute("ATTACH DATABASE ? AS old", (str(old),))
    tables = [(n, s) for n, s in out.execute(
        "SELECT name, sql FROM old.sqlite_master "
        "WHERE type = 'table' AND sql IS NOT NULL")
        if n not in OWNED and not n.startswith("works_fts_")
        and not n.startswith("sqlite_")]
    for name, sql in tables:
        out.execute(sql)
        # rowids are copied explicitly: the verification audit trail
        # (verification/*.jsonl) addresses hypothesis_evidence by rowid
        info = out.execute(f'PRAGMA old.table_info("{name}")').fetchall()
        cols = ", ".join(f'"{r[1]}"' for r in info)
        has_int_pk = any(r[5] and r[2].upper() == "INTEGER" for r in info)
        lead = "" if has_int_pk else "rowid, "
        out.execute(f'INSERT INTO "{name}" ({lead}{cols}) '
                    f'SELECT {lead}{cols} FROM old."{name}"')
    names = [n for n, _ in tables]
    if names:
        marks = ",".join("?" * len(names))
        for (sql,) in out.execute(
                "SELECT sql FROM old.sqlite_master WHERE type = 'index' "
                f"AND sql IS NOT NULL AND tbl_name IN ({marks})", names):
            out.execute(sql)

    # works that ingest_reference_works.py placed outside the mapped
    # universe: searchable, excluded from every field-map count
    n_ref = 0
    old_cols = [r[1] for r in out.execute("PRAGMA old.table_info(works)")]
    if "outside_universe" in old_cols:
        out.execute("ALTER TABLE works ADD COLUMN outside_universe INTEGER "
                    "DEFAULT 0")
        new_cols = [r[1] for r in out.execute("PRAGMA table_info(works)")]
        cols = ", ".join(f'"{c}"' for c in old_cols if c in new_cols)
        n_ref = out.execute(
            f"INSERT INTO works ({cols}) SELECT {cols} FROM old.works "
            "WHERE outside_universe = 1").rowcount
        out.execute(
            "INSERT INTO works_fts (work_id, title, abstract, body) "
            "SELECT work_id, title, abstract, body FROM old.works_fts "
            "WHERE work_id IN (SELECT work_id FROM old.works "
            "WHERE outside_universe = 1)")
    out.commit()
    out.execute("DETACH DATABASE old")
    return names, n_ref


def main() -> None:
    C.ensure_dirs()
    if KB_TMP.exists():
        KB_TMP.unlink()
    out = sqlite3.connect(KB_TMP)

    # --- works ------------------------------------------------------------
    idx = sqlite3.connect(IDX_DB)
    works = pd.read_sql_query(
        "SELECT work_id, doi, title, authors, year, type, cited_by_count, "
        "link_count, primary_topic, core_topic, oa_status, is_oa, is_seed, "
        "hop, paper_rank_score, abstract, link FROM papers", idx)
    idx.close()

    comm = load_communities()
    if comm is not None:
        works = works.merge(comm, on="work_id", how="left")
    else:
        works["community"] = None
    sub_csv = C.EXPORTS / "community0_subclusters.csv"
    if sub_csv.exists():          # a pack's own sub-strand split, if any
        sub = pd.read_csv(sub_csv)
        works = works.merge(sub.rename(columns={"subcluster": "core_strand"}),
                            on="work_id", how="left")
    else:
        works["core_strand"] = None

    ft = sqlite3.connect(FT_DB)
    fts = pd.read_sql_query(
        "SELECT work_id, file, n_pages, n_chars, quality, lang_guess "
        "FROM fulltext WHERE work_id != ''", ft)
    # a work can appear twice (harvested + curated copy); keep the best copy
    fts["q_rank"] = fts["quality"].map(
        {"ok": 0, "references-heavy": 1, "mostly-scanned": 2,
         "no-text-layer": 3}).fillna(4)
    fts = (fts.sort_values(["work_id", "q_rank"])
              .drop_duplicates("work_id")
              .drop(columns="q_rank")
              .rename(columns={"file": "fulltext_file",
                               "quality": "fulltext_quality"}))
    works = works.merge(fts, on="work_id", how="left")
    works["has_fulltext"] = works["fulltext_file"].notna().astype(int)
    works.to_sql("works", out, index=False)

    # --- authors ----------------------------------------------------------
    fm = sqlite3.connect(C.DB_PATH)
    from author_merge import build_canonical_map
    canon = build_canonical_map(fm)
    wa = pd.read_sql_query(
        "SELECT work_id, author_id, position, is_corresponding "
        "FROM work_authors", fm)
    wa["author_id"] = wa["author_id"].map(lambda a: canon.get(a, a))
    wa = wa.drop_duplicates(["work_id", "author_id"])
    wa.to_sql("work_authors", out, index=False)

    au = pd.read_sql_query(
        "SELECT a.author_id, a.display_name, a.orcid, a.works_count, "
        "a.cited_by_count, i.display_name AS institution, a.country "
        "FROM authors a LEFT JOIN institutions i "
        "ON i.inst_id = a.last_institution_id", fm)
    au["author_id"] = au["author_id"].map(lambda a: canon.get(a, a))
    au = au.sort_values("works_count", ascending=False) \
           .drop_duplicates("author_id")
    op_path = C.EXPORTS / "author_openness.parquet"
    if op_path.exists():          # stage E, optional
        op = pd.read_parquet(op_path)
        op["author_id"] = op["author_id"].map(lambda a: canon.get(a, a))
        op = op.drop_duplicates("author_id")
        au = au.merge(op[["author_id", "openness"]].rename(
            columns={"openness": "openness_score"}), on="author_id",
            how="left")
    else:
        au["openness_score"] = None
    # activity span inside the universe, for telling active from historical
    span = (wa.merge(works[["work_id", "year"]], on="work_id")
              .groupby("author_id")["year"].agg(["min", "max", "count"])
              .rename(columns={"min": "first_year", "max": "last_year",
                               "count": "n_works_universe"}))
    au = au.merge(span, on="author_id", how="left")
    au.to_sql("authors", out, index=False)

    # --- statements --------------------------------------------------------
    st = pd.read_sql_query(
        "SELECT work_id, file, page, kind, sentence FROM statements "
        "WHERE work_id != ''", ft)
    st.to_sql("statements", out, index=False)
    ft.close()
    fm.close()

    # --- search index -----------------------------------------------------
    out.executescript("""
    CREATE INDEX idx_w_comm ON works(community);
    CREATE INDEX idx_w_strand ON works(core_strand);
    CREATE INDEX idx_wa_w ON work_authors(work_id);
    CREATE INDEX idx_wa_a ON work_authors(author_id);
    CREATE INDEX idx_st_w ON statements(work_id);
    CREATE VIRTUAL TABLE works_fts USING fts5(
        work_id UNINDEXED, title, abstract, body,
        tokenize='porter unicode61');
    """)
    ft = sqlite3.connect(FT_DB)
    body = {wid: t for wid, t in ft.execute(
        "SELECT work_id, text FROM fulltext WHERE work_id != ''")}
    ft.close()
    cur = out.cursor()
    for r in works.itertuples():
        cur.execute("INSERT INTO works_fts VALUES (?,?,?,?)",
                    (r.work_id, r.title or "", r.abstract or "",
                     body.get(r.work_id, "")))
    out.commit()

    # --- what later stages own, from the previous build -------------------
    carried, n_ref = carry_over(out, KB)
    out.close()
    os.replace(KB_TMP, KB)

    n_ft = int(works["has_fulltext"].sum())
    print("=== build_knowledgebase ===")
    print(f"  works       : {len(works):,} ({n_ft:,} with full text)")
    print(f"  authors     : {len(au):,}")
    print(f"  statements  : {len(st):,}")
    print(f"  carried over: {', '.join(carried) or 'nothing'}"
          f"{f'; {n_ref} outside-universe works' if n_ref else ''}")
    print(f"  db          : {KB} ({KB.stat().st_size/1e9:.2f} GB)")


if __name__ == "__main__":
    main()
