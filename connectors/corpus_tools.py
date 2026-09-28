"""Corpus-backed replacements for each engine's literature layer.

Every engine ships its own way of reaching the literature — Semantic
Scholar, arXiv, a hosted platform, a PDF pipeline. If we left those in
place, each engine would read a different library and the comparison
would measure retrieval luck rather than architecture. So each connector
replaces exactly one seam: the call the engine makes to find papers,
rewired to our corpus API.

These subclass or match the upstream classes directly, against the real
cloned code, so a signature change upstream breaks the import rather
than silently producing different behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))
VENDOR = HUB / "vendor"

from corpus_api import Corpus  # noqa: E402

_corpus = None


def corpus() -> Corpus:
    global _corpus
    if _corpus is None:
        _corpus = Corpus()
    return _corpus


def as_papers(query: str, limit: int = 10) -> list[dict]:
    """Neutral dict form; each connector reshapes it to its engine's."""
    out = []
    for w in corpus().search(query, limit=limit):
        out.append({
            "work_id": w.work_id, "title": w.title, "year": w.year,
            "abstract": (w.abstract or w.snippet or "")[:1500],
            "doi": w.doi, "type": w.type,
            "citationCount": w.cited_by_count or 0,
        })
    return out


def format_for_prompt(papers: list[dict]) -> str:
    """The plain-text block most engines expect back from a search tool."""
    if not papers:
        return "No papers found in the corpus for that query."
    lines = []
    for i, p in enumerate(papers, 1):
        lines.append(
            f"{i}. [{p['work_id']}] {p['title']} ({p['year']})\n"
            f"   Citations: {p['citationCount']}\n"
            f"   Abstract: {p['abstract'][:900]}")
    return "\n\n".join(lines)


# ── AI-Scientist-v2 ────────────────────────────────────────────────
def ai_scientist_tool():
    """A BaseTool subclass, swapped in for SemanticScholarSearchTool."""
    sys.path.insert(0, str(VENDOR / "AI-Scientist-v2"))
    from ai_scientist.tools.base_tool import BaseTool

    class CorpusSearchTool(BaseTool):
        def __init__(self, max_results: int = 10):
            super().__init__(
                name="SearchSemanticScholar",   # keep the name the prompt uses
                description=("Search the project's mapped literature corpus. "
                             "Provide a search query to find relevant papers."),
                parameters=[{"name": "query", "type": "str",
                             "description": "The search query."}])
            self.max_results = max_results

        def use_tool(self, query: str):
            return format_for_prompt(as_papers(query, self.max_results))

    return CorpusSearchTool()


# ── LLNL Open AI Co-Scientist ──────────────────────────────────────
def co_scientist_search():
    """Matches app.tools.arxiv_search.ArxivSearch.search_papers."""
    class CorpusSearch:
        def __init__(self, max_results: int = 10):
            self.max_results = max_results

        def search_papers(self, query: str, max_results: int | None = None,
                          categories: list | None = None,
                          sort_by: str | None = None, **kw):
            # `categories` is an arXiv taxonomy filter with no analogue in a
            # single-field corpus; accepted so the call site is unchanged,
            # and ignored rather than silently narrowing the results
            papers = as_papers(query, max_results or self.max_results)
            # the shape arxiv_search returns to the agents
            return [{"title": p["title"], "summary": p["abstract"],
                     "published": str(p["year"]), "entry_id": p["work_id"],
                     "doi": p["doi"], "authors": []} for p in papers]

    return CorpusSearch()


# ── HypoGeniC ──────────────────────────────────────────────────────
def hypogenic_paper_infos(queries: list[str], per_query: int = 12
                          ) -> list[dict]:
    """LiteratureAgent takes [{'title':..., 'summary':...}] directly, so
    the whole GROBID/PDF pipeline is bypassed rather than reimplemented."""
    seen, out = set(), []
    for q in queries:
        for p in as_papers(q, per_query):
            if p["work_id"] in seen:
                continue
            seen.add(p["work_id"])
            out.append({"title": p["title"], "summary": p["abstract"],
                        "work_id": p["work_id"], "year": p["year"]})
    return out


# ── FutureHouse Robin ──────────────────────────────────────────────
async def robin_call_platform(queries: dict, fh_client=None, job_name=None):
    """Drop-in for robin.utils.call_platform — the single Edison seam.

    Returns the exact shape its callers index into:
      {"results": [{"hypothesis","query","answer","sources","task_run_id"}],
       "has_errors": bool}
    """
    results = []
    for hypothesis, q in queries.items():
        papers = as_papers(q, 12)
        answer = format_for_prompt(papers)
        results.append({
            "hypothesis": hypothesis,
            "query": q,
            "answer": answer,
            "sources": [p["work_id"] for p in papers],
            "task_run_id": f"corpus:{abs(hash(q)) % 10**10}",
        })
    return {"results": results, "has_errors": False}
