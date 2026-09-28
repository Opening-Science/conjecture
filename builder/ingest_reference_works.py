"""Make curated out-of-universe works retrievable by the corpus API.

A pack may deliberately keep some works out of the mapped field: in the
biophoton pack, two metrology papers that are not biophoton literature and
would corrupt the field's boundary if they joined the citation universe.
That is right for the field map and wrong for the engines, which may be
asked a question whose own brief cites them.

So these works are inserted into the knowledgebase with
`outside_universe = 1`. They are searchable — an engine asking about
detector calibration finds them — and every count that describes the
mapped field excludes them, so the universe stays exactly what it was.

    python ingest_reference_works.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import fitz  # PyMuPDF

import config as C

LIT = C.LIT
KB = C.KB_PATH

# the pack's curated works: build.references in pack.yaml, each with
# work_id, doi, title, authors, year, type and file (under literature/curated)
REFERENCES = C.REFERENCES


def text_of(pdf: Path) -> tuple[str, int, int]:
    doc = fitz.open(pdf)
    pages = [p.get_text() for p in doc]
    body = "\n".join(pages)
    return body, len(pages), len(body)


def main() -> None:
    kb = sqlite3.connect(KB)
    cols = [r[1] for r in kb.execute("PRAGMA table_info(works)")]
    if "outside_universe" not in cols:
        kb.execute("ALTER TABLE works ADD COLUMN outside_universe INTEGER "
                   "DEFAULT 0")
        print("  added works.outside_universe")

    for ref in REFERENCES:
        pdf = LIT / "curated" / ref["file"]
        if not pdf.exists():
            print(f"  MISSING {pdf.name} — skipped")
            continue
        body, n_pages, n_chars = text_of(pdf)
        # the abstract is the first substantial block after the title page
        abstract = " ".join(body.split())[:2000]
        row = dict(
            work_id=ref["work_id"], doi=ref["doi"], title=ref["title"],
            authors=ref["authors"], year=float(ref["year"]), type=ref["type"],
            cited_by_count=0, is_oa=1, oa_status="gold", is_seed=0,
            abstract=abstract, has_fulltext=1,
            fulltext_file=str(pdf.relative_to(LIT)),
            n_pages=float(n_pages), n_chars=float(n_chars),
            fulltext_quality="curated", lang_guess="en",
            core_topic=0, outside_universe=1)
        keys = [k for k in row if k in cols or k == "outside_universe"]
        kb.execute(
            f"INSERT OR REPLACE INTO works ({','.join(keys)}) "
            f"VALUES ({','.join('?' * len(keys))})",
            [row[k] for k in keys])
        # make it findable: the FTS table is what the corpus API searches
        kb.execute("DELETE FROM works_fts WHERE work_id = ?",
                   (ref["work_id"],))
        kb.execute("INSERT INTO works_fts (work_id, title, abstract, body) "
                   "VALUES (?,?,?,?)",
                   (ref["work_id"], ref["title"], abstract, body))
        print(f"  ingested {ref['work_id']}: {n_pages} pages, "
              f"{n_chars:,} chars")
    kb.commit()

    n_all, n_out = kb.execute(
        "SELECT COUNT(*), COALESCE(SUM(outside_universe),0) FROM works"
    ).fetchone()
    print(f"  works table: {n_all:,} rows, {n_out} marked outside the "
          f"mapped universe -> universe remains {n_all - n_out:,}")


if __name__ == "__main__":
    main()
