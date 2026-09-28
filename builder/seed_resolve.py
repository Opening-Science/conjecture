"""Stage A — resolve the pack's seed CSV (build.seeds) to OpenAlex work ids.

- DOI rows: batched works fetch by doi filter.
- No-DOI rows: title.search + rapidfuzz confirmation (token_set_ratio >= 90
  against title AND year within +/-1).
Writes data/exports/seed_works.csv and logs unmatched rows for manual review.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, asdict

from rapidfuzz import fuzz
from unidecode import unidecode

import config as C
from openalex import OpenAlex, oa_short_id, title_filter


def _norm(s: str) -> str:
    s = unidecode(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def norm_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi.org/", "")
    return doi


@dataclass
class SeedResolution:
    bib_key: str
    year: str
    first_author: str
    title: str
    doi: str
    work_id: str          # short OpenAlex id, '' if unresolved
    match_method: str     # doi | title_fuzzy | unmatched
    match_score: float    # fuzz score for title matches, 100 for doi


def load_seeds() -> list[dict]:
    if C.SEEDS_CSV is None:
        raise SystemExit("the pack sets no build.seeds: nothing to resolve")
    C.ensure_dirs()
    with open(C.SEEDS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resolve_doi_rows(oa: OpenAlex, rows: list[dict]
                     ) -> dict[str, dict]:
    """Return {normalized_doi: work} for all DOI seed rows, via batched fetch."""
    dois = [norm_doi(r["doi"]) for r in rows if r["doi"].strip()]
    dois = list(dict.fromkeys(dois))  # unique, order-preserving
    found: dict[str, dict] = {}
    for i in range(0, len(dois), C.DOI_BATCH):
        batch = dois[i:i + C.DOI_BATCH]
        filt = "doi:" + "|".join(batch)
        for w in oa.paged("works", filt, select=C.WORK_SELECT):
            wdoi = norm_doi(w.get("doi") or "")
            if wdoi:
                found[wdoi] = w
                # cache each resolved work by id for downstream reuse
                cp = C.CACHE / "works" / f"{oa_short_id(w['id'])}.json"
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_text(json.dumps(w))
        print(f"  DOI batch {i//C.DOI_BATCH + 1}: {len(found)} cumulative hits")
    return found


def resolve_title_row(oa: OpenAlex, row: dict) -> tuple[str, float]:
    """Return (short_work_id, score) best title match, or ('', 0)."""
    title = row["title"]
    try:
        seed_year = int(row["year"])
    except (ValueError, TypeError):
        seed_year = None
    best_id, best_score = "", 0.0
    tnorm = _norm(title)
    for w in oa.paged("works", f"title.search:{title_filter(title)}",
                      select=C.WORK_SELECT, cap=25):
        wtitle = w.get("title") or ""
        score = fuzz.token_set_ratio(tnorm, _norm(wtitle))
        if score < C.FUZZY_TITLE_MIN:
            continue
        wyear = w.get("publication_year")
        if seed_year is not None and wyear is not None:
            if abs(int(wyear) - seed_year) > C.YEAR_TOLERANCE:
                continue
        if score > best_score:
            best_id, best_score = oa_short_id(w["id"]), float(score)
            cp = C.CACHE / "works" / f"{best_id}.json"
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(w))
    return best_id, best_score


def resolve_seeds() -> list[SeedResolution]:
    rows = load_seeds()
    oa = OpenAlex()
    print(f"Loaded {len(rows)} seed rows")

    doi_rows = [r for r in rows if r["doi"].strip()]
    print(f"Resolving {len(doi_rows)} DOI rows (batched)...")
    doi_found = resolve_doi_rows(oa, doi_rows)

    results: list[SeedResolution] = []
    n_no_doi = sum(1 for r in rows if not r["doi"].strip())
    print(f"Resolving {n_no_doi} no-DOI rows via title.search + fuzzy...")
    title_done = 0
    for r in rows:
        doi = norm_doi(r["doi"])
        if doi and doi in doi_found:
            w = doi_found[doi]
            results.append(SeedResolution(
                r["bib_key"], r["year"], r["first_author"], r["title"], doi,
                oa_short_id(w["id"]), "doi", 100.0))
            continue
        if doi and doi not in doi_found:
            # DOI given but not in OpenAlex — try a title fallback before giving up
            wid, score = resolve_title_row(oa, r)
            if wid:
                results.append(SeedResolution(
                    r["bib_key"], r["year"], r["first_author"], r["title"],
                    doi, wid, "title_fuzzy", score))
            else:
                results.append(SeedResolution(
                    r["bib_key"], r["year"], r["first_author"], r["title"],
                    doi, "", "unmatched", 0.0))
            continue
        # no DOI at all -> title fuzzy
        wid, score = resolve_title_row(oa, r)
        title_done += 1
        if title_done % 10 == 0:
            print(f"  title-matched {title_done}/{n_no_doi}")
        if wid:
            results.append(SeedResolution(
                r["bib_key"], r["year"], r["first_author"], r["title"], "",
                wid, "title_fuzzy", score))
        else:
            results.append(SeedResolution(
                r["bib_key"], r["year"], r["first_author"], r["title"], "",
                "", "unmatched", 0.0))

    oa.close()
    return results


def write_outputs(results: list[SeedResolution]) -> dict:
    out_csv = C.EXPORTS / "seed_works.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))

    resolved = [r for r in results if r.work_id]
    unmatched = [r for r in results if not r.work_id]
    # de-dup work ids (some seeds may map to the same OpenAlex work)
    unique_ids = sorted({r.work_id for r in resolved})
    (C.EXPORTS / "seed_work_ids.json").write_text(json.dumps(unique_ids))

    with open(C.EXPORTS / "seed_unmatched.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        w.writeheader()
        for r in unmatched:
            w.writerow(asdict(r))

    stats = {
        "seeds_total": len(results),
        "resolved": len(resolved),
        "unique_work_ids": len(unique_ids),
        "unmatched": len(unmatched),
        "by_doi": sum(1 for r in resolved if r.match_method == "doi"),
        "by_title": sum(1 for r in resolved if r.match_method == "title_fuzzy"),
    }
    return stats


def main() -> None:
    results = resolve_seeds()
    stats = write_outputs(results)
    print("\n=== Stage A: seed resolution ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    target = C.MIN_RESOLVED
    if target:
        print(f"  target >= {target}: "
              f"{'PASS' if stats['resolved'] >= target else 'BELOW TARGET'}")
    if stats["unmatched"]:
        print(f"  unmatched dumped to {C.EXPORTS / 'seed_unmatched.csv'}")


if __name__ == "__main__":
    main()
