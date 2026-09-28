"""The one interface every hypothesis engine sees.

Engines get NO web access and no direct database handle. They see the
pack's corpus only through the four calls below, which makes runs
reproducible (same query, same rows) and makes engines comparable (none
of them can bring outside knowledge in through a private retrieval
path). This is the project's equivalent of OpenTwin's single declared
interface standard.

Read-only by construction: every connection is opened with mode=ro.

    from corpus_api import Corpus
    c = Corpus()
    c.search("delayed luminescence gated acquisition", limit=10)
    c.get_work("W2141663490")
    c.statements("W2141663490", kind="open_problem")
    c.neighbors("W2141663490")

CLI (useful for connectors written in other languages: they shell out
and parse JSON on stdout):

    python corpus_api.py search "singlet oxygen 1270 nm" --limit 5
    python corpus_api.py get W2141663490
    python corpus_api.py statements W2141663490
    python corpus_api.py neighbors W2141663490
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pack import PACK

KB_DB = PACK.knowledgebase
FM_DB = PACK.fieldmap

# FTS5 syntax characters that would otherwise turn a natural-language
# query into a syntax error or an unintended operator
_FTS_SPECIAL = re.compile(r'[\"\'()*:^\-]')


@dataclass
class Work:
    work_id: str
    title: str
    year: int | None
    doi: str | None
    type: str | None
    abstract: str | None
    cited_by_count: int | None
    is_oa: bool
    has_fulltext: bool
    snippet: str | None = None
    rank: float | None = None

    def brief(self) -> dict:
        """Compact form for prompts: enough to cite, not enough to bloat."""
        return {"work_id": self.work_id, "title": self.title,
                "year": self.year, "type": self.type,
                "text": (self.snippet or self.abstract or "")[:900]}


def _sanitize(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Every term is quoted, so no user string can inject FTS operators;
    terms are ANDed, which is what a retrieval caller expects.
    """
    terms = [t for t in _FTS_SPECIAL.sub(" ", query).split() if len(t) > 1]
    if not terms:
        raise ValueError(f"query has no usable terms: {query!r}")
    return " AND ".join(f'"{t}"' for t in terms)


class Corpus:
    def __init__(self, kb_db: Path = KB_DB, fm_db: Path | None = FM_DB):
        if not kb_db.exists():
            raise FileNotFoundError(f"knowledgebase not found: {kb_db}")
        self.kb = sqlite3.connect(f"file:{kb_db}?mode=ro", uri=True)
        self.kb.row_factory = sqlite3.Row
        self.fm = None
        if fm_db is not None and fm_db.exists():
            self.fm = sqlite3.connect(f"file:{fm_db}?mode=ro", uri=True)
            self.fm.row_factory = sqlite3.Row

    # -- the four calls -------------------------------------------------

    def search(self, query: str, limit: int = 10, *, core_only: bool = False,
               year_max: int | None = None, fulltext: bool = True
               ) -> list[Work]:
        """Full-text search over title, abstract and body.

        year_max exists for novelty scoring: an engine can be restricted
        to literature published before a cutoff so that "new" hypotheses
        can be checked against what came after.
        """
        match = _sanitize(query)
        cols = "w.work_id, w.title, w.year, w.doi, w.type, w.abstract, " \
               "w.cited_by_count, w.is_oa, w.has_fulltext"
        where = ["works_fts MATCH ?"]
        params: list = [match]
        if core_only:
            where.append("w.core_topic = 1")
        if year_max is not None:
            where.append("w.year <= ?")
            params.append(year_max)
        snippet_col = ("snippet(works_fts, 3, '', '', ' … ', 24)"
                       if fulltext else
                       "snippet(works_fts, 2, '', '', ' … ', 24)")
        sql = (f"SELECT {cols}, {snippet_col} AS snip, bm25(works_fts) AS r "
               "FROM works_fts JOIN works w ON w.work_id = works_fts.work_id "
               f"WHERE {' AND '.join(where)} ORDER BY r LIMIT ?")
        params.append(limit)
        out = []
        for row in self.kb.execute(sql, params):
            out.append(Work(
                work_id=row["work_id"], title=row["title"],
                year=int(row["year"]) if row["year"] else None,
                doi=row["doi"], type=row["type"], abstract=row["abstract"],
                cited_by_count=row["cited_by_count"],
                is_oa=bool(row["is_oa"]),
                has_fulltext=bool(row["has_fulltext"]),
                snippet=row["snip"], rank=row["r"]))
        return out

    def get_work(self, work_id: str) -> Work | None:
        row = self.kb.execute(
            "SELECT work_id, title, year, doi, type, abstract, "
            "cited_by_count, is_oa, has_fulltext FROM works "
            "WHERE work_id = ?", (work_id,)).fetchone()
        if row is None:
            return None
        return Work(
            work_id=row["work_id"], title=row["title"],
            year=int(row["year"]) if row["year"] else None,
            doi=row["doi"], type=row["type"], abstract=row["abstract"],
            cited_by_count=row["cited_by_count"], is_oa=bool(row["is_oa"]),
            has_fulltext=bool(row["has_fulltext"]))

    def statements(self, work_id: str, kind: str | None = None,
                   limit: int = 50) -> list[dict]:
        """Mined statements (open problems, limitations, future work)."""
        sql = "SELECT page, kind, sentence FROM statements WHERE work_id = ?"
        params: list = [work_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.kb.execute(sql, params)]

    def neighbors(self, work_id: str, limit: int = 15) -> list[Work]:
        """Works citing or cited by this one, inside the mapped universe."""
        if self.fm is None:
            return []
        rows = self.fm.execute(
            "SELECT dst_work_id AS other FROM citation_edges "
            "WHERE src_work_id = ? UNION "
            "SELECT src_work_id AS other FROM citation_edges "
            "WHERE dst_work_id = ? LIMIT ?",
            (work_id, work_id, limit)).fetchall()
        out = []
        for r in rows:
            w = self.get_work(r["other"])
            if w:
                out.append(w)
        return out

    # -- convenience for the harness -----------------------------------

    def search_many(self, queries: list[str], limit: int = 6,
                    **kw) -> list[Work]:
        """Union of several searches, deduplicated, best rank first."""
        seen: dict[str, Work] = {}
        for q in queries:
            try:
                hits = self.search(q, limit=limit, **kw)
            except ValueError:
                continue
            for w in hits:
                if w.work_id not in seen or (w.rank or 0) < (
                        seen[w.work_id].rank or 0):
                    seen[w.work_id] = w
        return sorted(seen.values(), key=lambda w: w.rank or 0)


MAX_LIMIT = 50


def call(c: Corpus, name: str, args: dict):
    """Run one of the four calls by name and return JSON-ready data.

    The CLI and the MCP server (mcp_server.py) both go through here, so an
    engine sees identical data whichever way it reaches the corpus.
    """
    if name == "search":
        limit = min(int(args.get("limit") or 10), MAX_LIMIT)
        return [asdict(w) for w in c.search(
            args["query"], limit=limit,
            core_only=bool(args.get("core_only")),
            year_max=args.get("year_max"))]
    if name == "get_work":
        w = c.get_work(args["work_id"])
        return asdict(w) if w else None
    if name == "statements":
        return c.statements(args["work_id"], kind=args.get("kind"))
    if name == "neighbors":
        return [asdict(w) for w in c.neighbors(args["work_id"])]
    raise KeyError(f"unknown call: {name}")


def dumps(res) -> str:
    return json.dumps(res, indent=1, default=str)


def log_call(tool: str, args: dict, n_chars: int, error: str | None) -> None:
    """Append one line to $CONJECTURE_CALL_LOG, if set.

    Both the CLI and the MCP server log here, so a run's corpus usage is
    recorded by the hub rather than self-reported by the engine.
    """
    path = os.environ.get("CONJECTURE_CALL_LOG")
    if not path:
        return
    rec = {"t": round(time.time(), 3), "tool": tool, "args": args,
           "chars": n_chars, "error": error}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        # a read-only engine sandbox may refuse the write; the answer
        # must still reach the engine, and the adapter recovers the call
        # from the engine's transcript instead (engines/codex_cli.py)
        pass


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--core-only", action="store_true")
    s.add_argument("--year-max", type=int)
    g = sub.add_parser("get")
    g.add_argument("work_id")
    st = sub.add_parser("statements")
    st.add_argument("work_id")
    st.add_argument("--kind")
    nb = sub.add_parser("neighbors")
    nb.add_argument("work_id")
    a = ap.parse_args()
    if a.cmd == "search":
        name, args = "search", {"query": a.query, "limit": a.limit,
                                "core_only": a.core_only,
                                "year_max": a.year_max}
    elif a.cmd == "get":
        name, args = "get_work", {"work_id": a.work_id}
    elif a.cmd == "statements":
        name, args = "statements", {"work_id": a.work_id, "kind": a.kind}
    else:
        name, args = "neighbors", {"work_id": a.work_id}
    try:
        text = dumps(call(Corpus(), name, args))
    except Exception as e:
        log_call(name, args, 0, str(e))
        raise
    log_call(name, args, len(text), None)
    print(text)


if __name__ == "__main__":
    _main()
