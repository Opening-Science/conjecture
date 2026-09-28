"""The shared generation prompt.

Every backend receives this identical text for a given seed. That is the
whole point: if the prompt varied per engine we would be comparing
prompt engineering, not engines. Differences that remain are the
engine's architecture (single pass, tournament, reflection) and the
model family behind it, which is what the scoreboard is trying to
measure.

Engines are told to retrieve through the corpus CLI rather than being
handed a fixed context, so retrieval behaviour is part of what is being
compared — but they all start from the same entry queries and none of
them can reach the open web.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent

# <<DOMAIN>> and <<CAUSAL_LEVELS>> come from the pack (pack.yaml) and are
# filled in before hashing, so config_hash identifies the rendered template
TEMPLATE_BASE = """You are a research hypothesis generator working on \
<<DOMAIN>>.

# Your corpus

You have read-only access to a mapped corpus of {n_works:,} works \
(titles, abstracts and full text where held). Query it ONLY through this \
CLI, from the directory {hub}:

    {py} corpus_api.py search "QUERY TERMS" --limit 8
    {py} corpus_api.py get W2141663490
    {py} corpus_api.py statements W2141663490
    {py} corpus_api.py neighbors W2141663490

Run several searches with different phrasings before you conclude \
anything. You have no web access; a claim you cannot ground in this \
corpus does not belong in your output. Work ids look like W2141663490 \
and appear in every search result.

# The question you are answering

{seed_id}. {title}

The field states this question in its own words. Verbatim, with sources:

{quotes}

What the field says would settle it: {settle}

Corpus entry points already retrieved for you (search further yourself):

{entry}

# Claims already on the register

These scoped claims are ALREADY catalogued with explicit nulls. Restating \
one of them is worth nothing. Your job is to advance past them: sharpen \
one into a decisive measurable form the register does not contain, expose \
a hidden assumption one of them depends on, or propose a claim that would \
discriminate between two of them.

{registry}

# What to produce

Between 4 and 7 hypotheses. Each must be:

- FALSIFIABLE: state it so that a specific result would kill it.
- SCOPED: name the population/preparation, the condition, the outcome \
measured. A claim that omits its scope cannot be tested and will be \
rejected.
- GROUNDED: every hypothesis cites work_ids you actually retrieved. \
Citations that do not exist in the corpus invalidate the hypothesis.
- MEASURABLE NOW OR NEARLY: name the instrument class and spectral band \
the experiment needs. "Someone should investigate" is not an experiment.

Decompose your reasoning into steps. Each step is justified as:
  "citation"    - rests on specific retrieved works (list their work_ids)
  "computation" - a calculation or derivation stated so it can be checked
  "given"       - restates something from the seed brief itself
Every step will be independently audited; a step that cannot be \
justified will be struck, and a hypothesis whose load-bearing step is \
struck will be declined.

Assign each hypothesis a causal level:
<<CAUSAL_LEVELS>>

# Output format

Return ONLY a JSON object, no prose before or after, matching:

{{"hof_version": "1.0",
 "run": {{"engine": "{engine}", "seed_id": "{seed_id}", \
"backend": "{backend}", "config_hash": "{config_hash}", \
"corpus_calls": <how many searches you actually ran>}},
 "hypotheses": [
  {{"id": "{seed_id}-1",
    "statement": "<the falsifiable claim, one sentence>",
    "scope": {{"population": "...", "condition": "...", \
"comparator": "...", "outcome": "..."}},
    "null_hypothesis": "<what a negative result looks like>",
    "estimand": "<the number that decides it>",
    "causal_level": "L1|L2|L3|L4|L5|L6",
    "rationale": [
      {{"step": "...", "justification_type": "citation", \
"work_ids": ["W..."]}},
      {{"step": "...", "justification_type": "computation"}}
    ],
    "cited_work_ids": ["W...", "W..."],
    "proposed_experiment": "<the measurement that would settle it>",
    "required_instrument": "<detector class and band>",
    "engine_native_score": <your own 0-1 confidence>,
    "novelty_self_claim": "<what is new about this, vs the register>"
  }}
 ]}}
"""


# How the engine reaches the corpus. "cli" is the text above, verbatim
# (run 1's config hashes are over it); "mcp" swaps in the MCP tool names
# for engines that are handed mcp_server.py instead of a shell.
CLI_ACCESS = """\
You have read-only access to a mapped corpus of {n_works:,} works \
(titles, abstracts and full text where held). Query it ONLY through this \
CLI, from the directory {hub}:

    {py} corpus_api.py search "QUERY TERMS" --limit 8
    {py} corpus_api.py get W2141663490
    {py} corpus_api.py statements W2141663490
    {py} corpus_api.py neighbors W2141663490
"""
MCP_ACCESS = """\
You have read-only access to a mapped corpus of {n_works:,} works \
(titles, abstracts and full text where held). Query it ONLY through the \
MCP tools of the "corpus" server:

    search(query="QUERY TERMS", limit=8)
    get_work(work_id="W2141663490")
    statements(work_id="W2141663490")
    neighbors(work_id="W2141663490")

Do not read files or run shell commands to reach the literature.
"""
ACCESS_MODES = {"cli": CLI_ACCESS, "mcp": MCP_ACCESS}


def template(access: str = "cli") -> str:
    import sys
    sys.path.insert(0, str(HUB))
    from pack import PACK
    if access not in ACCESS_MODES:
        raise ValueError(f"corpus access {access!r}: the shared prompt "
                         f"covers {sorted(ACCESS_MODES)}")
    levels = "\n".join("  " + line for line in
                       PACK.causal_levels.splitlines())
    tmpl = (TEMPLATE_BASE.replace("<<DOMAIN>>", PACK.domain)
            .replace("<<CAUSAL_LEVELS>>", levels))
    return tmpl.replace(CLI_ACCESS, ACCESS_MODES[access])


def build(seed_id: str, engine: str, backend: str,
          python_bin: str | None = None,
          access: str = "cli") -> tuple[str, str]:
    """Return (prompt, config_hash) for a seed."""
    import sys
    sys.path.insert(0, str(HUB))
    from hof import config_hash
    from pack import PACK

    seed = json.loads((PACK.seeds_dir / f"{seed_id}.json").read_text())
    quotes = "\n".join(
        f'  - "{q["quote"]}"  [{q["source"]}]' for q in seed["quotes"]) \
        or "  (none extracted)"
    entry = "\n".join(
        f'  - {w["work_id"]} ({w["year"]}) {w["title"][:110]}'
        for w in seed["entry_points"][:14])
    registry = "\n".join(
        f'  - {c["id"]} [{c["level"]}] {c["claim"][:190]}'
        for c in seed["registry_all_claim_statements"]) \
        or "  (none yet)"
    settle = seed.get("what_would_settle_it") or "(not stated)"

    python_bin = python_bin or sys.executable
    n_works = PACK.n_works
    tmpl = template(access)
    chash = config_hash(tmpl, seed_id, engine)
    prompt = tmpl.format(
        n_works=n_works, hub=HUB, py=python_bin, seed_id=seed_id,
        title=seed["title"], quotes=quotes, settle=settle, entry=entry,
        registry=registry, engine=engine, backend=backend,
        config_hash=chash)
    return prompt, chash


if __name__ == "__main__":
    import sys
    p, h = build(sys.argv[1] if len(sys.argv) > 1 else "Q5",
                 "demo", "demo")
    print(p)
    print(f"\n[config_hash {h}, {len(p)} chars]")
