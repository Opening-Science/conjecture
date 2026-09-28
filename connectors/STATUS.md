# Engine and judge status: what is built, what conforms, what has run

The tables are generated: `conformance/conformance.py --status` reads
every `engine.yaml` / `judge.yaml` and the latest conformance result for
each, and rewrites them. Do not edit between the markers.

Kept honest by construction:

- **Designed, no adapter** means a manifest exists (upstream pinned,
  licence, what it needs) but no `adapter.py`. For connector engines,
  the connector's fit to upstream is checked separately by
  `connectors/verify_bindings.py`.
- **Conformance** is a run on the toy pack, a fictional field no engine
  can know from outside: HOF that validates, every citation in the toy
  corpus, corpus calls seen by the hub, nothing fetched from outside. It
  shows an engine can be scored, not that it is good. A result goes stale
  when the manifest or adapter changes after it.
- **Commits** in conformance results made before the hub moved to its own
  repository (2026-09-28) refer to Opening-Science/biophoton-knowledge-graph,
  where the hub was developed.
- **Has run on pack** counts what is actually in the named pack's
  `state/runs/` (engines) or `state/judge/verdicts.*.json` (judges). No engine is reported as having run
  unless it has.

<!-- BEGIN GENERATED: conformance/conformance.py --status -->
| Engine | Access | Invocation | Upstream | Licence | Conformance (toy pack) | Has run on pack `biophotons` | Blocker |
|---|---|---|---|---|---|---|---|
| Claude subagent, single agent + corpus CLI (`baseline-claude`) | cli | handoff | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | **yes**, 42 hypotheses on 7 questions | - |
| Codex, single agent + corpus over MCP (`codex-mcp`) | mcp | self-driving | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | no | - |
| Codex, single agent + corpus CLI (`codex-solo`) | cli | self-driving | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | **yes**, 40 hypotheses on 7 questions | - |
| Reference adapter (no model) (`reference`) | mcp | self-driving | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | no | - |
| Sakana AI Scientist v2 (ideation stage) (`ai-scientist-v2`) | connector `ai_scientist_tool` | self-driving | SakanaAI/AI-Scientist-v2 @ 96bd516 | The AI Scientist Source Code License 1.0 (not OSI open source) | designed, no adapter | no | API key; licence gate on output |
| LLNL Open AI Co-Scientist (`co-scientist`) | connector `co_scientist_search` | self-driving | LLNL/open-ai-co-scientist @ c8342c0 | MIT | designed, no adapter | no | OpenRouter key. As shipped, its search results never reach its agents; the connector wires them into the prompts, and that part is unrun. |
| HypoGeniC (ChicagoHAI) (`hypogenic`) | connector `hypogenic_paper_infos` | self-driving | ChicagoHAI/hypothesis-generation @ bd37a31 | MIT | designed, no adapter | no | API key |
| OpenScientist (LBNL) (`openscientist`) | none | external | https://openscientist.io | Apache-2.0 | designed, no adapter | no | a platform, not a library; needs the corpus ingested into its Postgres mirror |
| FutureHouse Robin (fork) (`robin`) | connector `robin_call_platform` | self-driving | Future-House/robin @ 4a5cce3 | Apache-2.0 | designed, no adapter | no | API key for the local reasoning calls |
| SciAgents (MIT Buehler lab) (`sciagents`) | none | self-driving | lamm-mit/SciAgentsDiscovery @ c5c3045 | Apache-2.0 | designed, no adapter | no | needs a .graphml and node-embedding export of the pack, not a search swap |

| Judge | Invocation | Upstream | Licence | Conformance (toy pack) | Has run on pack `biophotons` | Blocker |
|---|---|---|---|---|---|---|
| Claude judges (subagents) (`claude-subagent`) | handoff | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | **yes**, 78 verdicts | - |
| Codex judge (`codex`) | self-driving | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | **yes**, 78 verdicts | - |
| Reference judge (no model) (`reference`) | self-driving | native | n/a (native to the hub) | **pass**, 2026-09-28 @ 0c1f007 | no | - |
| theoria (arithmetic and derivation verifier) (`theoria`) | external | zaladbar/theoria @ 1721216 | Apache-2.0 | designed, no adapter | **yes**, 1 verdict | takes claims, not candidates; runs through judge/theoria_adapter.py and is not yet under this contract |
<!-- END GENERATED -->

## Notes

1. **Claude subagents is real inference but not a standalone script.** It
   runs through agents dispatched inside a Claude Code session, because a
   nested `claude -p` cannot authenticate from inside one. The hypotheses
   it produced are genuine; the engine is not reproducible by someone
   running the repo without that session. With an Anthropic API key it
   becomes a normal scripted engine.

2. **Co-Scientist has a defect we must fix, not inherit.** As shipped, its
   arXiv results never reach its agents — the search runs and the output
   is discarded. Swapping the search alone would therefore change nothing.
   The connector has to wire retrieval into the agent prompts as well;
   that part is written but unrun.

3. **Codex engines now run isolated from the user's Codex setup.** A
   user's `~/.codex/config.toml` can enable plugins (a browser, literature
   search) that would give an engine a way around the corpus. Since the
   adapter contract, every Codex adapter runs `codex exec` with
   `--ignore-user-config` and the model pinned in its manifest. The biophoton
   pack's run 1 predates this; its transcripts were audited on 2026-09-28: all 325
   commands Codex ran across Q1-Q7 were `corpus_api.py` calls, with no web
   search, MCP tool, curl or wget.

## What "verified binding" proves, and what it does not

It proves a connector matches the upstream interface *today*: the class
we subclass is really their abstract base, the parameters we accept are a
superset of what their call sites pass, the dict we return has the keys
their code indexes. Run it again after any `git pull` in `vendor/`, and
update the pinned commit in the engine's manifest.

It does not prove the engine produces good hypotheses, or that it runs at
all. That needs a key, an adapter, and a conformance run.
