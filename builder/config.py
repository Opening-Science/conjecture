"""Configuration for the corpus builder, from the active pack.

The builder turns a seed bibliography into the corpus a pack's engines
read: an OpenAlex field map (fieldmap.sqlite, citation edges) and a
full-text knowledgebase (knowledgebase.sqlite: works, works_fts,
statements). Where those land is the pack's own `corpus:` block; how
they are built is its `build:` block; every threshold not set there
keeps the default below, which is what built the biophoton pack.

    build:
      seeds: path/to/seeds.csv          # bib_key,year,first_author,title,doi
      min_resolved: 240                 # optional: report a seed-matching target
      paths:                            # working directories (defaults: under workdir)
        workdir: build                  # everything below defaults inside it
        cache: ...                      # OpenAlex entity cache (large, resumable)
        exports: ...                    # stage outputs between steps
        literature: ...                 # PDFs, manifest.csv, fulltext.sqlite
        index: ...                      # full_paper_index.sqlite
      core_topic_hints: [...]           # topic-name substrings marking the core
      gap_terms: [...]                  # extra measurement-gap terms for mining
      author_merge_whitelist: [...]     # surname-initial keys safe to merge
      references: [...]                 # curated works outside the universe
      user_agent: ...                   # identifies the harvest to servers
      expansion: {hops: 2, hop1_min_links: 2, hop2_min_links: 3,
                  hard_cap_works: 40000, forward_max_works_per_batch: 3000}
      seed_match: {fuzzy_title_min: 90, year_tolerance: 1}

Credentials never come from the pack: OPENALEX_API_KEY and
OPENALEX_MAILTO are read from the environment only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

from pack import PACK, read_raw  # noqa: E402

_B = read_raw(PACK.path).get("build") or {}
_P = _B.get("paths") or {}
_X = _B.get("expansion") or {}
_M = _B.get("seed_match") or {}


def _path(key: str, default: Path) -> Path:
    v = _P.get(key)          # already absolute: read_raw resolves build paths
    return Path(v) if v else default


# --- identity / OpenAlex auth --------------------------------------------
# As of early 2026 OpenAlex uses usage-based pricing with API keys: without
# one a harvest is limited to ~1,000 list calls a day. The key and the
# courtesy mailto come from the environment only, never from a file in a
# repository, and the key is redacted from any error (see openalex.py).
OPENALEX_BASE = "https://api.openalex.org"
API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip() or None
MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip() or None
USER_AGENT = _B.get("user_agent") or (
    "conjecture-hub corpus builder "
    "(+https://github.com/Opening-Science/conjecture)")

# --- paths ---------------------------------------------------------------
WORKDIR = _path("workdir", PACK.path.parent / "build")
CACHE = _path("cache", WORKDIR / "cache")
EXPORTS = _path("exports", WORKDIR / "exports")
LIT = _path("literature", WORKDIR / "literature")
INDEX_DIR = _path("index", WORKDIR / "index")
RUN_LOG = _path("run_log", WORKDIR / "run_log.md")
SEEDS_CSV = Path(_B["seeds"]) if _B.get("seeds") else None
DB_PATH = PACK.fieldmap or (WORKDIR / "fieldmap.sqlite")
KB_PATH = PACK.knowledgebase
MIN_RESOLVED = _B.get("min_resolved")


def ensure_dirs() -> None:
    for d in (CACHE, EXPORTS, LIT, INDEX_DIR, DB_PATH.parent, KB_PATH.parent,
              RUN_LOG.parent):
        d.mkdir(parents=True, exist_ok=True)


# --- OpenAlex request tuning ---------------------------------------------
WORK_SELECT = (
    "id,doi,title,publication_year,type,cited_by_count,authorships,"
    "primary_topic,topics,concepts,referenced_works,related_works,"
    "open_access,primary_location,locations,corresponding_author_ids,language"
)
AUTHOR_SELECT = (
    "id,display_name,orcid,works_count,cited_by_count,"
    "summary_stats,last_known_institutions,affiliations"
)
PER_PAGE = 200          # OpenAlex max
SLEEP_BETWEEN = 0.20    # polite pacing (~5 req/s, comfortably under the ceiling)
MAX_RETRIES = 8
RETRY_MAX_WAIT = 120    # cap on exponential backoff between retries (s)
TIMEOUT = 40.0

# --- expansion caps and prune thresholds ---------------------------------
HOPS = int(_X.get("hops", 2))                      # 1 or 2 citation hops
if HOPS not in (1, 2):
    raise ValueError(f"build.expansion.hops must be 1 or 2, not {HOPS}")
HARD_CAP_WORKS = int(_X.get("hard_cap_works", 40_000))
HOP1_MIN_LINKS = int(_X.get("hop1_min_links", 2))  # hop-1 kept iff links >= 2 seeds
HOP2_MIN_LINKS = int(_X.get("hop2_min_links", 3))  # stricter for the noisier ring
# forward citations per batch of 50 sources, sorted by cited_by_count and
# truncated, so a batch holding hyper-cited works cannot page 100k+ citers
FORWARD_MAX_WORKS_PER_BATCH = int(_X.get("forward_max_works_per_batch", 3000))

# --- seed matching -------------------------------------------------------
FUZZY_TITLE_MIN = int(_M.get("fuzzy_title_min", 90))  # rapidfuzz token_set_ratio
YEAR_TOLERANCE = int(_M.get("year_tolerance", 1))     # +/- years for a title match
DOI_BATCH = 50          # DOIs per batched works request

# --- field vocabulary (the pack's; empty means "no topical signal") ------
CORE_TOPIC_HINTS = tuple(h.lower() for h in _B.get("core_topic_hints") or ())
GAP_TERMS = tuple(_B.get("gap_terms") or ())
AUTHOR_MERGE_WHITELIST = frozenset(_B.get("author_merge_whitelist") or ())
REFERENCES = list(_B.get("references") or [])

ensure_dirs()     # as before the move: every stage may assume its directories
