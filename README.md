# Conjecture: the Open Science Foundation hypothesis hub

A hub for AI hypothesis generation that stays honest about what it
produces. It takes the questions a field says it cannot answer, runs
several AI hypothesis-generation engines over that field's own
literature, merges what they produce, and then tries to break every
candidate before publishing any of it.

The hub is field-agnostic. A **domain pack** hydrates it with one field:
a corpus, its open questions, the prompt framing, and the pack's run
history. The first pack is
[conjecture-pack-biophotons](https://github.com/Opening-Science/conjecture-pack-biophotons)
(ultra-weak photon emission from living systems). Engines and judges plug
in through one adapter contract, and any agent that speaks MCP can read a
pack's corpus with no custom code.

(Not to be confused with Conjecture, the AI-safety company. This is the
Open Science Foundation's hypothesis hub; the PyPI name is
`conjecture-hub`.) Free software under the AGPL-3.0-or-later.

```
seeds            generation           merge          certification        output
the pack's  →   N engines, one   →   cluster    →   decompose, audit  →  experiment
questions       shared prompt,       across         every step,          cards +
+ registry      one corpus API,      engines,       certify or           scoreboard
gaps            no web access        keep who       decline              + audit.db
                                     found what
```

## Why it is built this way

**One interface.** Engines see the corpus only through `corpus_api.py`
(SQLite FTS5 over the pack's works: titles, abstracts, full text where
the pack holds it), as a CLI or as an MCP server.
No engine gets web access or a private retrieval path, so a difference
in output is a difference in the engine, not in what it was allowed to
read. This is the project's version of the single declared interface
standard that makes heterogeneous parts comparable.

**One prompt.** Every engine receives identical text for a given seed
(`engines/prompt.py`). Varying the prompt per engine would mean
comparing prompt engineering. What is allowed to differ is architecture
(single pass, tournament, reflection) and model family.

**One output shape.** The Hypothesis Output Format (`schema/`) mirrors
the verified registry `hypotheses_v2`, so scoring is a join rather than
an interpretation. Validation is semantic as well as structural: a cited
`work_id` that does not exist in the corpus fails the payload, because
fluent invention should never reach a judge.

**Certify or decline.** Certification follows the discipline of
[theoria](https://github.com/zaladbar/theoria): reasoning is decomposed
into steps, each step is audited independently, and one failed
load-bearing step declines the hypothesis. A citation step must resolve
to a work that exists in this corpus *and* actually assert what the step
claims — misattribution is the failure being hunted. A free mechanical
stage runs first, so a whole class of failures never costs judge budget.

**Blinding.** The verified evidence in `hypothesis_evidence` is never
shown to an engine or a judge. That is what lets rediscovery of registry
claims be measured honestly rather than leaked.

## Layout

| Path | What it is |
|---|---|
| `pack.py` | Loads the domain pack (`pack.yaml`): corpus paths, questions and entry queries, prompt framing, measurement areas. |
| `corpus_api.py` | The one read-only interface. Python API + CLI. |
| `mcp_server.py` | The same four calls as an MCP server (stdio), for any MCP-speaking agent. |
| `tests/` | `python -m unittest discover tests` from this directory: runs on the toy pack; set `CONJECTURE_PACK` to test against a real pack and its runs. |
| `schema/hof.schema.json`, `hof.py` | Output contract and its validator. |
| `build_seeds.py` | The questions as structured briefs, into the pack's `seeds/`. |
| `engines/prompt.py` | The shared generation prompt. |
| `contract.py`, `schema/adapter.schema.json` | The adapter contract: manifests, discovery, the hub-side run loop. |
| `engines/<name>/` | One engine each: `engine.yaml`, and `adapter.py` once built. |
| `judge/<name>/` | One judge each: `judge.yaml` and `adapter.py`. |
| `run_engine.py`, `run_judge.py` | Run any engine over the questions, any judge over the chunks. |
| `mcp_client.py` | Minimal MCP client, used by adapters that reach the corpus over MCP. |
| `builder/` | The corpus builder: seed bibliography to field map to the knowledgebase a pack serves (`builder/run.py`). |
| `panel/` | The run panel: a local web app over the active pack (`server.py`), and a read-only static export of it (`export.py`). |
| `conformance/` | Toy pack and conformance runner; results feed `connectors/STATUS.md`. |
| `merge/merge.py` | Cross-engine clustering, provenance kept. |
| `judge/certify.py` | Mechanical checks then the judged audit. |
| `scoreboard/score.py` | Metrics into the pack's `audit.db`. |
| `scoreboard/build_page.py` | The public site section. |
| `run_pipeline.py` | Sequences the deterministic stages. |

## Domain packs

The hub code knows nothing about any one field. Everything field-specific
comes from one `pack.yaml`: where the corpus lives, the open-questions
document and its per-question entry queries, the domain sentence and
causal levels the prompt uses, the setting the arithmetic verifier is
told about, the measurement areas experiment cards map to, and where
rendered outputs go. `CONJECTURE_PACK=/path/to/pack.yaml` hydrates the
hub with a field. Template text from the pack is filled in before hashing, so
`config_hash` identifies the rendered prompt.

A `pack.yaml` can extend another and override only what differs:

```yaml
# a maintainer's workspace: the published pack, with the full-text corpus
extends: pack/pack.yaml
corpus:
  knowledgebase: literature/knowledgebase.sqlite
```

Dicts merge key by key and anything else replaces; each path resolves
against the file that sets it. Runs, questions and outputs stay where
the base pack puts them.

The pack also owns its run state (`state:` in `pack.yaml`): seeds,
engine runs and their transcripts, merge clusters, judge chunks and
verdicts, `audit.db`, `scoreboard.json` and the verifier bench. The hub
directory holds code only, so one hub can serve several packs and a
pack's history travels with the pack.

## Adding an engine or a judge

Every engine and judge is a directory with a manifest and an adapter:

```
engines/<name>/engine.yaml    what it is: upstream repo and pinned commit,
                              licence, corpus access (cli, mcp, connector),
                              invocation, model, required commands and keys,
                              network policy, cost
engines/<name>/adapter.py     def generate(req) -> str | dict
judge/<name>/judge.yaml
judge/<name>/adapter.py       def judge(req) -> str | list
```

The adapter does one thing: an engine turns `req.prompt` (or `req.seed`,
for engines with their own prompting) into an answer, raw text or a HOF
dict; a judge turns `req.items` into verdicts. The hub does everything
else identically for all of them: builds the shared prompt, starts the
corpus server (`req.mcp`) and logs every call, extracts and normalises
HOF, checks every citation against the corpus, and saves the run. An
adapter that needs an agent outside the hub (a Claude Code subagent)
raises `contract.Pending` with the task and collects the answer on the
next call. A manifest without `adapter.py` is a designed engine; it
still appears in the status table with its blocker. Adapters kept
outside the hub are found through `CONJECTURE_ADAPTER_PATH`.

Before an adapter counts as built it has to pass conformance on the toy
pack, a fictional field of 50 works no engine can know from outside:
HOF that validates, every citation in the toy corpus, corpus calls seen
by the hub, and nothing fetched from outside. Judges must return one
schema-valid verdict per candidate.

```bash
../.venv/bin/python run_engine.py --list
../.venv/bin/python conformance/conformance.py --offline          # no model needed
../.venv/bin/python conformance/conformance.py codex-mcp --judge codex --status
```

## Plugging in an agent over MCP

An agent that speaks the Model Context Protocol needs no connector: point
it at `mcp_server.py` and it gets `search`, `get_work`, `statements` and
`neighbors`, returning exactly what the CLI prints. The tools are
annotated read-only and closed-world, so agent runtimes can run them
without a human approving each call. Set `CONJECTURE_CALL_LOG` to have
the hub record every call, independent of what the engine reports.

```bash
codex exec -s read-only \
  -c 'mcp_servers.corpus.command="python"' \
  -c 'mcp_servers.corpus.args=["mcp_server.py"]' \
  -c 'mcp_servers.corpus.env={CONJECTURE_CALL_LOG="runs/calls.jsonl"}' \
  "..." < /dev/null
```

Verified with Codex CLI 0.153 on 2026-09-24: tool discovery, `search`
and `get_work` returned the CLI's results and both calls were logged.

## Running it

```bash
pip install -r requirements.txt
python -m unittest discover tests                    # toy pack, no corpus needed
python conformance/conformance.py --offline          # adapter conformance

export CONJECTURE_PACK=/path/to/pack.yaml            # e.g. the biophoton pack
python build_seeds.py
python run_engine.py codex-solo --all                # self-driving
python run_engine.py baseline-claude                 # prints tasks; dispatch
                                                     # agents, rerun to collect
python run_pipeline.py                               # merge + mechanical
python run_judge.py codex                            # and/or Claude judges
python judge/collect_verdicts.py
python run_pipeline.py --score                       # audit.db + page
python connectors/fetch_vendor.py                    # upstream engines, pinned
```

Python 3.11+. Engines bring their own requirements: the Codex adapters
need the Codex CLI, the Claude adapters a Claude Code session.

## Building a pack's corpus

```bash
pip install -r requirements-builder.txt
export OPENALEX_API_KEY=... OPENALEX_MAILTO=you@example.org
python builder/run.py --list
python builder/run.py                  # every stage; each is cached or resumable
```

From a seed bibliography (a CSV of `bib_key,year,first_author,title,doi`),
the builder resolves the seeds in OpenAlex, expands them by citation into
the field's universe (two hops, pruned by how many seeds a work links
to), builds the field map, fetches abstracts, ranks and indexes every
paper, harvests the open-access PDFs politely, extracts their text and
mines the sentences where the field states what it does not know, and
joins it all into the knowledgebase the corpus API serves. It writes to
the pack's own `corpus.knowledgebase` and `corpus.fieldmap`; working
directories and the field's vocabulary come from the pack's `build:`
block (see `builder/config.py`). A rebuild keeps a pack's curated tables,
such as its claim register.

The builder is the one that built the biophoton pack: rerun from that
pack's cache, stages C to K reproduce its field map, paper index and
knowledgebase table for table. Credentials come from the environment
only, and the API key is redacted from any error. Clustering, contact
data and a pack's claim curation are deliberately not part of it.

Its dependencies are in `requirements-builder.txt`, separate from the
hub's because only the builder needs them.

## The run panel

```bash
python panel/server.py              # http://127.0.0.1:8787, for the active pack
python panel/export.py --out site/  # a read-only copy any static host can serve
```

The panel shows the active pack: its questions, every engine and judge
with its status (from the manifests and conformance results), the cost
of a run at a chosen depth, the command list for it, the results, the
per-candidate ledger and the verification measurements. Everything is
built from the pack and the manifests; nothing in the panel names a
field or an engine. A pack can add its own write-up of what its runs
found as `outputs/panel/findings.html`, which the Verification page
shows after the hub's own sections.

The local server can also start runs. It binds to 127.0.0.1 only, runs
only a whitelist derived from the manifests (one job per built,
self-driving engine or judge), keeps API keys in the hub's `.env` (mode
0600) and never starts theoria without an explicit list of claims. It
is a local instrument, not a service: do not expose it. The export
cannot start anything, so it is the version to put on a website; it
carries no local paths, and never the licensed fonts (drop those into
`panel/fonts/` locally; the CSS falls back without them).

## Writing a pack

A pack is a directory with a `pack.yaml` (see the biophoton pack for a
complete one, and `conformance/toy_pack/` for the smallest). It names:

- a knowledgebase: SQLite with `works` and a `works_fts` FTS5 index
  (`work_id, title, abstract, body`), `statements`, and, for scoring
  against a register, `hypotheses_v2` and its evidence tables;
- optionally a field map with `citation_edges`, for the neighbours call;
- the open-questions document and entry queries per question;
- the prompt framing: domain sentence, causal levels, verifier setting;
- measurement areas for experiment cards;
- where outputs and run state go.

`conformance/toy_pack/build.py` builds a complete knowledgebase in about
150 lines and is the quickest reference for the schema.

## Metrics

| Metric | Meaning |
|---|---|
| Rediscovery | Registry claims an engine reached blind. Validation, not the prize. |
| Grounding | Citations that exist and are judged to support the step citing them. |
| Certification rate | Share surviving certify-or-decline. |
| **Novelty yield** | Certified, grounded, and not a restatement. The prize. |
| Cost | Wall-clock and corpus calls per certified hypothesis. |
| Auditability | Provenance the engine emits natively. |

## What this is not

Certified means *the reasoning survived audit*, not *true*. Everything
here is a proposal for an experiment. No claim a run produces has been
tested by running it, and the pipeline is explicitly designed to
make the untested status visible rather than to produce confident-looking
output.

Engines that need API keys (LLNL Co-Scientist, HypoGeniC, Robin,
SciAgents, OpenScientist, AI Scientist v2) have manifests but no adapter
yet; `connectors/STATUS.md` lists what each is waiting for. The engines
that ran need no key, which is why they ran first.

## Licence

The hub is free software under the GNU Affero General Public License,
version 3 or later (`LICENSE`). Copyleft throughout, and chosen over the
GPL because the hub is meant to be run as a service too: whoever offers a
modified hub over a network (the panel, the MCP server) must offer its
source to the people using it. Its copyleft dependencies (PyMuPDF,
AGPL-3.0; Unidecode, GPL-2.0-or-later) are compatible with that, as are
the MIT and Apache-2.0 upstream engines it adapts.

One upstream is not: the AI Scientist v2 ships under a use-restricted
licence that the AGPL does not allow to be combined into one program, so
an adapter for it must run it as a separate process (as the hub already
does with engines it reaches over a CLI or MCP), never import it.

Packs choose their own licence for their data; the biophoton pack's is
CC BY-SA 4.0.
