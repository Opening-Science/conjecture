<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
useSeoMeta({
  title: 'Get started: Conjecture',
  description: 'Install Conjecture, load a pack, run engines and judges, plug in any MCP agent and build a corpus of your own.',
})
</script>

<template>
  <div class="container-main space-y-80 py-80 lg:space-y-100 lg:py-120">
    <header class="max-w-800">
      <h1 class="text-4xl text-black">Get started</h1>
    </header>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Install the hub and a pack</h2>
      <div class="prose text-1xl text-black">
        <p>Conjecture needs Python 3.11 or later. The biophoton pack's corpus is a release asset; its fetch script downloads and verifies it with the GitHub command line tool.</p>
        <pre><code>git clone https://github.com/Opening-Science/conjecture
git clone https://github.com/Opening-Science/conjecture-pack-biophotons
(cd conjecture-pack-biophotons &amp;&amp; python corpus/fetch.py)

cd conjecture
pip install -r requirements.txt
export CONJECTURE_PACK=../conjecture-pack-biophotons/pack.yaml
python -m unittest discover tests</code></pre>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Open the run panel</h2>
      <div class="prose text-1xl text-black">
        <p>The run panel shows a pack's questions, engines, results, the ledger of every verdict and the verification measurements. Run locally, it can also start engines and judges and keeps API keys on your machine only.</p>
        <pre><code>python panel/server.py              # http://127.0.0.1:8787
python panel/export.py --out site/  # a read-only copy for any static host</code></pre>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Run engines and judges</h2>
      <div class="prose text-1xl text-black">
        <pre><code>python run_engine.py --list
python run_engine.py codex-solo --all
python run_pipeline.py               # merge and mechanical checks
python run_judge.py codex
python judge/collect_verdicts.py
python run_pipeline.py --score       # audit database and results page</code></pre>
        <p>Adapters that need an agent outside the hub, such as a Claude Code session, print their task and collect the answer on the next call.</p>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Plug in any agent over MCP</h2>
      <div class="prose text-1xl text-black">
        <p>An agent that speaks the Model Context Protocol needs no adapter to read a pack's corpus. The server exposes four read-only tools, <code>search</code>, <code>get_work</code>, <code>statements</code> and <code>neighbors</code>, and records every call.</p>
        <pre><code>{"mcpServers": {"corpus": {
  "command": "python",
  "args": ["/path/to/conjecture/mcp_server.py"],
  "env": {"CONJECTURE_PACK": "/path/to/pack.yaml",
          "CONJECTURE_CALL_LOG": "/path/to/calls.jsonl"}}}}</code></pre>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Build a corpus for your field</h2>
      <div class="prose text-1xl text-black">
        <p>Start from a seed bibliography. The corpus builder resolves it in OpenAlex, expands it by citation, harvests open-access full text politely and builds the knowledgebase the corpus API serves.</p>
        <pre><code>pip install -r requirements-builder.txt
export OPENALEX_API_KEY=... OPENALEX_MAILTO=you@example.org
python builder/run.py --list
python builder/run.py</code></pre>
      </div>
      <a href="https://github.com/Opening-Science/conjecture" :class="CTA_CLASS">Read the source</a>
    </section>
  </div>
</template>
