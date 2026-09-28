"""Stage E — open-science overlay (spec §6).

Per work: OA status, preprint presence, open-data/code/hardware signal (scanned
from the abstract). Per canonical author: an Openness Score in [0,1] as a
weighted mean of OA share (0.4), preprint rate (0.2), open-signal rate (0.25),
and open-infrastructure presence (0.15) -- components kept, not just composite.

Abstracts are fetched once (batched, select=abstract_inverted_index) into a
separate cache so the main work cache is untouched.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

import pandas as pd
from tqdm import tqdm

import config as C
from openalex import OpenAlex, oa_short_id
from author_merge import build_canonical_map

ABS_CACHE = C.CACHE / "abstracts"

PREPRINT_HOSTS = (
    "arxiv", "biorxiv", "medrxiv", "chemrxiv", "preprints.org", "ssrn",
    "researchsquare", "research square", "osf.io", "hal.", "zenodo",
    "techrxiv", "authorea", "vixra", "qeios", "preprint",
)
OPEN_SIGNAL_PATTERNS = {
    "github": r"github\.com",
    "gitlab": r"gitlab\.com",
    "zenodo": r"zenodo\b",
    "osf": r"osf\.io",
    "figshare": r"figshare\b",
    "dryad": r"dryad\b|datadryad",
    "dataverse": r"dataverse\b",
    "protocols_io": r"protocols\.io",
    "data_availability": r"data (are |is )?availab|availability of data|"
                         r"publicly available|openly available",
    "code_availability": r"code (is |are )?availab|source code|available on ",
    "open_hardware": r"open[- ]?hardware|open[- ]?source hardware|oshw",
}
OPEN_SIGNAL_RE = {k: re.compile(v, re.I) for k, v in OPEN_SIGNAL_PATTERNS.items()}


def reconstruct_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort()
    return " ".join(w for _, w in pos)


def fetch_abstracts(oa: OpenAlex, work_ids: list[str]) -> None:
    ABS_CACHE.mkdir(parents=True, exist_ok=True)
    missing = [w for w in work_ids if not (ABS_CACHE / f"{w}.json").exists()]
    print(f"Abstracts: {len(work_ids) - len(missing)} cached, "
          f"{len(missing)} to fetch")
    for i in tqdm(range(0, len(missing), 50), desc="abstracts"):
        batch = missing[i:i + 50]
        got = set()
        for w in oa.paged("works", "openalex_id:" + "|".join(batch),
                          select="id,abstract_inverted_index"):
            sid = oa_short_id(w["id"])
            text = reconstruct_abstract(w.get("abstract_inverted_index"))
            (ABS_CACHE / f"{sid}.json").write_text(json.dumps(text))
            got.add(sid)
        for sid in batch:
            if sid not in got:
                (ABS_CACHE / f"{sid}.json").write_text(json.dumps(""))


def work_open_signals(w: dict, abstract: str) -> dict:
    oa_obj = w.get("open_access") or {}
    # preprint: any location that is submittedVersion or on a preprint host
    has_preprint = False
    for loc in (w.get("locations") or []):
        if (loc.get("version") == "submittedVersion"):
            has_preprint = True
            break
        src = (loc.get("source") or {})
        host = " ".join(str(x or "").lower() for x in [
            src.get("display_name"), src.get("host_organization_name"),
            (loc.get("landing_page_url") or ""), (loc.get("pdf_url") or "")])
        if any(h in host for h in PREPRINT_HOSTS):
            has_preprint = True
            break
    signals = [k for k, rgx in OPEN_SIGNAL_RE.items() if rgx.search(abstract)]
    return {
        "oa_status": oa_obj.get("oa_status"),
        "is_oa": 1 if oa_obj.get("is_oa") else 0,
        "has_preprint": 1 if has_preprint else 0,
        "open_signal": 1 if signals else 0,
        "signal_terms": ",".join(signals),
    }


def main() -> None:
    con = sqlite3.connect(C.DB_PATH)
    cur = con.cursor()
    oa = OpenAlex()

    universe = list(pd.read_sql_query("SELECT work_id FROM works", con)["work_id"])
    fetch_abstracts(oa, universe)

    # per-work signals
    cur.execute("DROP TABLE IF EXISTS work_openness")
    cur.execute("""CREATE TABLE work_openness(
        work_id TEXT PRIMARY KEY, oa_status TEXT, is_oa INTEGER,
        has_preprint INTEGER, open_signal INTEGER, signal_terms TEXT)""")
    print("Scanning per-work open signals...")
    for wid in tqdm(universe, desc="works"):
        w = oa.get_cached("works", wid)
        if not w:
            continue
        ap = ABS_CACHE / f"{wid}.json"
        abstract = json.loads(ap.read_text()) if ap.exists() else ""
        s = work_open_signals(w, abstract)
        cur.execute("INSERT OR REPLACE INTO work_openness VALUES (?,?,?,?,?,?)",
                    (wid, s["oa_status"], s["is_oa"], s["has_preprint"],
                     s["open_signal"], s["signal_terms"]))
    con.commit()

    # per-canonical-author aggregation
    print("Aggregating per-author openness...")
    canon = build_canonical_map(con)
    wa = pd.read_sql_query("SELECT work_id, author_id FROM work_authors", con)
    wa["canon"] = wa["author_id"].map(canon).fillna(wa["author_id"])
    wo = pd.read_sql_query("SELECT * FROM work_openness", con)
    wo_map = wo.set_index("work_id")
    authors = pd.read_sql_query(
        "SELECT author_id, orcid, last_institution_id FROM authors", con)
    orcid_map = dict(zip(authors["author_id"], authors["orcid"]))
    inst_map = dict(zip(authors["author_id"], authors["last_institution_id"]))
    ror = dict(pd.read_sql_query(
        "SELECT inst_id, ror FROM institutions", con).values)

    by_author = wa.groupby("canon")["work_id"].apply(list)

    cur.execute("DROP TABLE IF EXISTS author_openness")
    cur.execute("""CREATE TABLE author_openness(
        author_id TEXT PRIMARY KEY, n_works INTEGER, oa_share REAL,
        preprint_rate REAL, open_signal_rate REAL, infra_score REAL,
        openness REAL)""")

    for canon_id, wids in tqdm(by_author.items(), desc="authors"):
        sub = wo_map.reindex([w for w in wids if w in wo_map.index])
        n = len(sub)
        if n == 0:
            continue
        oa_share = float(sub["is_oa"].mean())
        preprint_rate = float(sub["has_preprint"].mean())
        open_rate = float(sub["open_signal"].mean())
        # infra: orcid present + ROR-linked institution + any open deposit
        orcid_present = 1.0 if (orcid_map.get(canon_id)) else 0.0
        iid = inst_map.get(canon_id)
        ror_present = 1.0 if (iid and ror.get(iid)) else 0.0
        deposit = 1.0 if (sub["open_signal"].sum() > 0 or
                          sub["has_preprint"].sum() > 0) else 0.0
        infra = (orcid_present + ror_present + deposit) / 3.0
        openness = (0.40 * oa_share + 0.20 * preprint_rate +
                    0.25 * open_rate + 0.15 * infra)
        cur.execute("INSERT OR REPLACE INTO author_openness VALUES "
                    "(?,?,?,?,?,?,?)",
                    (canon_id, n, round(oa_share, 4), round(preprint_rate, 4),
                     round(open_rate, 4), round(infra, 4), round(openness, 4)))
    con.commit()

    # exports + summary
    ao = pd.read_sql_query("SELECT * FROM author_openness", con)
    ao.to_parquet(C.EXPORTS / "author_openness.parquet", index=False)
    wo.to_parquet(C.EXPORTS / "work_openness.parquet", index=False)
    summary = {
        "works_scored": int(len(wo)),
        "oa_share_works": round(float(wo["is_oa"].mean()), 3),
        "works_with_preprint": int(wo["has_preprint"].sum()),
        "works_with_open_signal": int(wo["open_signal"].sum()),
        "authors_scored": int(len(ao)),
        "mean_author_openness": round(float(ao["openness"].mean()), 3),
    }
    print("\n=== Stage E: openness ===")
    print(json.dumps(summary, indent=2))
    with open(C.RUN_LOG, "a", encoding="utf-8") as f:
        f.write("\n## Stage E — openness\n\n```json\n")
        f.write(json.dumps(summary, indent=2) + "\n```\n")
    con.close()
    oa.close()


if __name__ == "__main__":
    main()
