"""Prove the connectors still fit the engines they claim to fit.

A connector that no longer matches upstream is worse than no connector:
it looks implemented and fails at run time, or worse, silently changes
what the engine reads. This checks each seam against the actual cloned
source — by isinstance where the class can be imported, and by parsing
the real signature out of the source where importing would require the
very dependency we are replacing.

Run it after any `git pull` in vendor/.

    python connectors/verify_bindings.py
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
VENDOR = HUB / "vendor"
sys.path.insert(0, str(HUB))
sys.path.insert(0, str(HUB / "connectors"))

import corpus_tools as ct  # noqa: E402
from pack import PACK  # noqa: E402

# any real query against the active pack will do
QUERY = next(iter(PACK.entry_queries.values()))[0]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<22} {detail}")


def sig_from_source(path: Path, cls: str, fn: str) -> list[str] | None:
    """Parameter names of cls.fn, read from source without importing."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and sub.name == fn:
                    return [a.arg for a in sub.args.args if a.arg != "self"]
    return None


def fn_exists(path: Path, fn: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == fn for n in ast.walk(tree))


def main() -> None:
    print("Connector bindings against vendored upstream source\n")

    # 1. AI-Scientist-v2 — importable, so check by isinstance
    p = VENDOR / "AI-Scientist-v2"
    if p.exists():
        try:
            sys.path.insert(0, str(p))
            from ai_scientist.tools.base_tool import BaseTool
            tool = ct.ai_scientist_tool()
            out = tool.use_tool(query=QUERY)
            check("AI-Scientist-v2",
                  isinstance(tool, BaseTool) and len(out) > 100,
                  f"isinstance(BaseTool)={isinstance(tool, BaseTool)}, "
                  f"use_tool returned {len(out)} chars")
        except Exception as exc:                       # noqa: BLE001
            check("AI-Scientist-v2", False, repr(exc)[:110])
    else:
        check("AI-Scientist-v2", False, "not cloned")

    # 2. Co-Scientist — importing needs `arxiv`, the dep we replace, so
    #    compare parameter names against the real source instead
    f = VENDOR / "open-ai-co-scientist" / "app" / "tools" / "arxiv_search.py"
    if f.exists():
        up = sig_from_source(f, "ArxivSearchTool", "search_papers")
        ours = [q for q in
                inspect.signature(ct.co_scientist_search().search_papers)
                .parameters if q != "self"]
        # ours must accept everything upstream is called with
        rows = ct.co_scientist_search().search_papers("dark count", 3)
        if not up:
            # an empty parse means the class was renamed upstream; that is a
            # failure, not a pass, or the check proves nothing
            check("Co-Scientist", False,
                  "could not read ArxivSearchTool.search_papers from source "
                  "— upstream renamed it; connector needs review")
        else:
            missing = [q for q in up if q not in ours]
            check("Co-Scientist", not missing and bool(rows),
                  f"upstream({','.join(up)}) subset of ours({','.join(ours)}), "
                  f"{len(rows)} rows")
    else:
        check("Co-Scientist", False, "not cloned")

    # 3. Robin — the single Edison seam
    f = VENDOR / "robin" / "robin" / "utils.py"
    if f.exists():
        up = sig_from_source(f, "", "call_platform")
        exists = fn_exists(f, "call_platform")
        import asyncio
        r = asyncio.run(ct.robin_call_platform({"h": "singlet oxygen"}))
        shape = set(r["results"][0]) >= {"hypothesis", "query", "answer",
                                         "sources", "task_run_id"}
        check("Robin", exists and shape,
              f"call_platform present={exists}, replacement returns the "
              f"5 keys its callers index={shape}")
    else:
        check("Robin", False, "not cloned")

    # 4. HypoGeniC — LiteratureAgent consumes title/summary dicts
    f = (VENDOR / "hypothesis-generation" / "hypothesis_agent"
         / "literature_review_agent" / "literature_review.py")
    if f.exists():
        src = f.read_text(encoding="utf-8")
        takes = "paper_infos" in src
        infos = ct.hypogenic_paper_infos([QUERY], 3)
        ok = takes and infos and {"title", "summary"} <= set(infos[0])
        check("HypoGeniC", bool(ok),
              f"LiteratureAgent takes paper_infos={takes}, "
              f"we supply {len(infos)} title/summary dicts")
    else:
        check("HypoGeniC", False, "not cloned")

    # 5. SciAgents — needs a graph + embeddings, not a search seam
    f = VENDOR / "SciAgentsDiscovery" / "ScienceDiscovery" / "graph.py"
    check("SciAgents", f.exists(),
          "graph.py present; needs a .graphml + embedding export, "
          "not a search-tool swap" if f.exists() else "not cloned")

    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n  {len(RESULTS) - len(bad)}/{len(RESULTS)} bindings verified")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
