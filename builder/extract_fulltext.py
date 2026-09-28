"""Extract full text from every PDF in literature/ into a searchable store.

Stage J. Walks the harvested corpus (literature/papers/), the hand-collected
material (books/, curated/), and pulls per-page text with PyMuPDF into
literature/fulltext.sqlite. Resumable: a PDF is skipped when its (path, size)
is already in the store, so this can run repeatedly while the harvester is
still filling the folder.

Beyond raw text, two derived layers are computed at extraction time because
they need the page structure that is thrown away afterwards:

  * quality flags -- scanned/no-text-layer PDFs (n_chars per page collapses),
    references-only extractions, non-English text. Downstream analysis must
    know which works are silently absent from term statistics.
  * statement mining -- sentences that mark open problems, limitations,
    controversies, and future-work directions, with the page they came from.
    These are the raw material for the open-research-questions synthesis, and
    mining them here keeps provenance exact.

Curated/ and books/ files are mapped to their OpenAlex work ids via
curated.csv, so the closed-access items land in the knowledgebase under the
same key as their metadata.

Outputs: literature/fulltext.sqlite
  fulltext(work_id, file, group_name, n_pages, n_chars, chars_per_page,
           quality, lang_guess, text)
  statements(work_id, page, kind, sentence)
  fulltext_fts  FTS5 over fulltext.text (external content)

Usage:
  python extract_fulltext.py            # incremental
  python extract_fulltext.py --rebuild  # drop and re-extract everything
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import fitz  # PyMuPDF
from tqdm import tqdm

import config as C

LIT = C.LIT
DB = LIT / "fulltext.sqlite"

GROUPS = ("papers", "books", "curated")

# A work id is carried in harvested filenames; curated files get theirs from
# curated.csv (matched on the file column).
WID_RE = re.compile(r"(W\d{6,})")

MIN_CHARS_PER_PAGE = 120     # below this a page is imagery, not a text layer
MAX_STATEMENTS_PER_WORK = 60
MIN_SENT = 60                # chars; shorter "sentences" are headings/artifacts
MAX_SENT = 600

# Statement markers, grouped by what they signal. Deliberately high-precision
# phrasings: the synthesis step reads every hit, so recall can be sacrificed
# for a list a human can actually read through.
STATEMENT_KINDS = {
    "open_question": (
        r"open (?:research )?questions?\b", r"remains? (?:an )?open\b",
        r"remains? (?:unknown|unclear|unresolved|elusive|controversial|"
        r"to be (?:determined|elucidated|established|clarified))",
        r"is (?:still|not yet) (?:unknown|unclear|understood|resolved)",
        r"not (?:yet |fully |completely )?understood",
        r"poorly understood", r"unanswered questions?",
        r"unclear whether", r"unknown whether",
        r"yet to be (?:determined|elucidated|established|identified|"
        r"demonstrated|confirmed)",
    ),
    "future_work": (
        r"future (?:work|studies|research|investigations?|experiments?)\b",
        r"further (?:work|studies|research|investigations?|experiments?) "
        r"(?:is|are|will be|would be|should|must|may be) (?:needed|required|"
        r"necessary|warranted)",
        r"further (?:work|studies|research|investigations?) should",
        r"should be (?:investigated|explored|examined|addressed) in future",
        r"warrants? further", r"deserves? further",
    ),
    "limitation": (
        r"(?:a|the|one|main|major|key|important) limitations? of",
        r"limitations? of (?:this|the present|our) (?:study|work|approach|"
        r"method)", r"this study (?:is|was) limited",
        r"caution (?:is|should be|must be)", r"should be interpreted with",
    ),
    "controversy": (
        r"controvers", r"(?:hotly|highly|much|widely) debated",
        r"(?:subject|matter) of (?:intense |ongoing |much )?debate",
        r"conflicting (?:results|reports|findings|evidence)",
        r"contradictory (?:results|reports|findings|evidence)",
        r"(?:could|can|did) not (?:be )?replicat", r"failed to replicate",
        r"irreproducib", r"lack of reproducibility", r"skeptic",
    ),
    "measurement_gap": (
        r"(?:absence|lack) of (?:standardi[sz]|calibrat|traceab)",
        r"no (?:standard|standardi[sz]ed|accepted) (?:protocol|method|"
        r"procedure)", r"not (?:been )?standardi[sz]ed",
        r"calibration (?:is|remains|has been) (?:difficult|challenging|"
        r"lacking|rare)", r"difficult to (?:compare|reproduce)",
        r"(?:hampers?|hinders?|prevents?|precludes?) (?:direct )?"
        r"comparison", r"inter-?laboratory", r"between-laborator",
    ),
}
# Metrology vocabulary alone is not a gap statement -- "the detection limit
# was 3 counts/s" is an instrument spec. These fire as measurement_gap only
# when the same sentence also carries problem language.
# The general measurement vocabulary is the hub's; a pack adds its own
# instrument terms as build.gap_terms (regex alternatives).
METROLOGY_TERMS = re.compile("|".join((
    r"detection limit", r"signal-to-noise", r"traceab",
    r"absolute (?:calibration|quantification)",
    r"measurement uncertaint", r"quantum efficiency", *C.GAP_TERMS)), re.I)
PROBLEM_WORDS = re.compile(
    r"\black\b|lacking|difficult|challeng|limit(?:s|ed|ing)? (?:the|our|"
    r"any)|hamper|hinder|prevent|preclude|impossib|poorly|remains?|"
    r"unknown|unclear|no consensus|not (?:been )?(?:standardi[sz]ed|"
    r"established|reported|compared)|rarely|seldom|varies widely|"
    r"inconsistent|needed|required|missing", re.I)
COMPILED = {k: [re.compile(p, re.I) for p in pats]
            for k, pats in STATEMENT_KINDS.items()}

# crude sentence splitter that survives "Fig. 3", "et al.", "approx. 5"
ABBREV = re.compile(
    r"\b(?:fig|figs|ref|refs|eq|eqs|et al|e\.g|i\.e|vs|approx|ca|cf|"
    r"dr|prof|no|vol|pp)\.$", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")

REFS_HEAD = re.compile(r"^\s*(references|bibliography|literature cited)\s*$",
                       re.I | re.M)

CYRILLIC = re.compile(r"[Ѐ-ӿ]")
CJK = re.compile(r"[一-鿿぀-ヿ]")


def sentences(text: str):
    parts, buf = [], ""
    for chunk in SENT_SPLIT.split(text):
        buf = f"{buf} {chunk}".strip() if buf else chunk
        if ABBREV.search(buf):
            continue
        parts.append(buf)
        buf = ""
    if buf:
        parts.append(buf)
    return parts


def mine_statements(pages: list[str]) -> list[tuple[int, str, str]]:
    """(page, kind, sentence) for every marker hit, capped per work."""
    out = []
    refs_seen = False
    for pno, ptext in enumerate(pages, start=1):
        if REFS_HEAD.search(ptext):
            refs_seen = True
        if refs_seen:
            continue          # reference lists are marker soup; skip them
        clean = " ".join(ptext.split())
        for sent in sentences(clean):
            if not (MIN_SENT <= len(sent) <= MAX_SENT):
                continue
            hit = None
            for kind, pats in COMPILED.items():
                if any(p.search(sent) for p in pats):
                    hit = kind
                    break
            if (hit is None and METROLOGY_TERMS.search(sent)
                    and PROBLEM_WORDS.search(sent)):
                hit = "measurement_gap"
            if hit:
                out.append((pno, hit, sent))
            if len(out) >= MAX_STATEMENTS_PER_WORK:
                return out
    return out


def guess_lang(text: str) -> str:
    sample = text[:6000]
    if CJK.search(sample):
        return "cjk"
    if CYRILLIC.search(sample):
        return "cyrillic"
    return "latin"


def quality_of(n_pages: int, n_chars: int, text: str) -> str:
    cpp = n_chars / max(n_pages, 1)
    if n_chars < 500:
        return "no-text-layer"
    if cpp < MIN_CHARS_PER_PAGE:
        return "mostly-scanned"
    if REFS_HEAD.search(text[: len(text) // 4]):
        return "references-heavy"
    return "ok"


def curated_wids() -> dict[str, str]:
    """file basename -> work_id, from curated.csv where a DOI matched."""
    import csv as _csv
    out: dict[str, str] = {}
    path = LIT / "curated.csv"
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            m = WID_RE.search(row.get("corpus_relation") or "")
            if m:
                out[Path(row["file"]).name] = m.group(1)
    return out


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS fulltext(
        work_id TEXT,
        file    TEXT PRIMARY KEY,
        group_name TEXT,
        bytes   INTEGER,
        n_pages INTEGER,
        n_chars INTEGER,
        chars_per_page REAL,
        quality TEXT,
        lang_guess TEXT,
        text    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ft_wid ON fulltext(work_id);
    CREATE TABLE IF NOT EXISTS statements(
        work_id TEXT, file TEXT, page INTEGER, kind TEXT, sentence TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_st_wid ON statements(work_id);
    CREATE INDEX IF NOT EXISTS idx_st_kind ON statements(kind);
    CREATE VIRTUAL TABLE IF NOT EXISTS fulltext_fts USING fts5(
        text, content='fulltext', content_rowid='rowid',
        tokenize='porter unicode61'
    );
    """)


def extract_one(path: Path) -> tuple[list[str], int]:
    doc = fitz.open(path)
    pages = [page.get_text() for page in doc]
    n = doc.page_count
    doc.close()
    return pages, n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    if args.rebuild and DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    ensure_schema(con)

    done = {row[0]: row[1] for row in
            con.execute("SELECT file, bytes FROM fulltext")}
    cw = curated_wids()

    todo: list[tuple[Path, str]] = []
    for group in GROUPS:
        gdir = LIT / group
        if not gdir.exists():
            continue
        for p in sorted(gdir.glob("*.pdf")):
            if done.get(f"{group}/{p.name}") == p.stat().st_size:
                continue
            todo.append((p, group))

    print(f"{len(done)} already extracted, {len(todo)} to extract")
    n_ok = n_err = 0
    for p, group in tqdm(todo, desc="extract"):
        rel = f"{group}/{p.name}"
        wid = (WID_RE.search(p.name) or WID_RE.search(cw.get(p.name, "")))
        wid = wid.group(1) if wid else ""
        try:
            pages, n_pages = extract_one(p)
        except Exception as e:
            con.execute(
                "INSERT OR REPLACE INTO fulltext VALUES (?,?,?,?,?,?,?,?,?,?)",
                (wid, rel, group, p.stat().st_size, 0, 0, 0.0,
                 f"error-{type(e).__name__}", "", ""))
            n_err += 1
            continue
        text = "\n\f\n".join(pages)
        n_chars = len(text)
        qual = quality_of(n_pages, n_chars, text)
        con.execute("DELETE FROM statements WHERE file=?", (rel,))
        con.execute(
            "INSERT OR REPLACE INTO fulltext VALUES (?,?,?,?,?,?,?,?,?,?)",
            (wid, rel, group, p.stat().st_size, n_pages, n_chars,
             n_chars / max(n_pages, 1), qual, guess_lang(text), text))
        if qual in ("ok", "references-heavy"):
            for pno, kind, sent in mine_statements(pages):
                con.execute("INSERT INTO statements VALUES (?,?,?,?,?)",
                            (wid, rel, pno, kind, sent))
        n_ok += 1
        if (n_ok + n_err) % 200 == 0:
            con.commit()
    con.commit()

    # external-content FTS must be rebuilt to see new rows
    con.execute("INSERT INTO fulltext_fts(fulltext_fts) VALUES ('rebuild')")
    con.commit()

    q = {row[0]: row[1] for row in con.execute(
        "SELECT quality, COUNT(*) FROM fulltext GROUP BY quality")}
    n_st = con.execute("SELECT COUNT(*) FROM statements").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM fulltext").fetchone()[0]
    gb = DB.stat().st_size / 1e9
    con.close()
    print("=== extract_fulltext ===")
    print(f"  extracted now : {n_ok} ok, {n_err} errors")
    print(f"  store         : {total} works, {gb:.2f} GB, {DB.name}")
    print(f"  quality       : {q}")
    print(f"  statements    : {n_st}")


if __name__ == "__main__":
    main()
