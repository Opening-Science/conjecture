<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import hub from '~/data/hub.json'

useSeoMeta({
  title: 'Engines and judges: Conjecture',
  description: 'Every hypothesis engine and judge Conjecture adapts, with its corpus access, licence and status, generated from the adapter manifests.',
})

type Adapter = (typeof hub.engines)[number]

const ACCESS: Record<string, string> = {
  cli: 'command line', mcp: 'MCP server', connector: 'connector',
  handed: 'handed the evidence', none: 'not yet designed',
}

function status(a: Adapter): string {
  if (a.ran > 0) return `ran on ${hub.pack.name}, ${a.ran} hypotheses`
  if (a.state === 'ready') return a.conformance === 'pass' ? 'ready, conformance passed' : 'ready'
  if (a.state === 'needs') return 'needs a local requirement'
  return a.blocker ? `designed, not yet built (${a.blocker.replace(/\.$/, '')})` : 'designed, not yet built'
}

const engines = [...hub.engines].sort((a, b) => Number(b.built) - Number(a.built) || b.ran - a.ran)
const judges = [...hub.judges].sort((a, b) => Number(b.built) - Number(a.built))
</script>

<template>
  <div class="container-main space-y-80 py-80 lg:space-y-100 lg:py-120">
    <header class="max-w-800">
      <h1 class="text-4xl text-black">Engines and judges</h1>
    </header>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Engines</h2>
      <p class="text-1xl text-gray">Each engine answers the same brief through the same corpus interface. Built adapters have passed conformance: on a fictional corpus that no model can know from outside, they return valid output, cite only works in the corpus and fetch nothing from elsewhere.</p>
      <div class="prose text-1xl text-black">
        <ul>
          <li v-for="e in engines" :key="e.id">
            <strong>{{ e.name }}.</strong> {{ e.summary }}<br>
            Corpus access: {{ ACCESS[e.access] ?? e.access }}. Licence: {{ e.licence }}. Status: {{ status(e) }}.
          </li>
        </ul>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Judges</h2>
      <p class="text-1xl text-gray">A candidate is certified only if every judge family certifies it. Judges audit each reasoning step against the abstracts of the works it cites.</p>
      <div class="prose text-1xl text-black">
        <ul>
          <li v-for="j in judges" :key="j.id">
            <strong>{{ j.name }}.</strong> {{ j.summary }}<br>
            Runs as: {{ j.invocation }}. Status: {{ status(j) }}.
          </li>
        </ul>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Add an engine</h2>
      <div class="prose text-1xl text-black">
        <p>An engine is a directory with a manifest and an adapter. The manifest records where the engine comes from and at which commit, its licence, how it reaches the corpus, what it needs to run and what it costs. The adapter has one entry point that turns a question into an answer; the hub builds the prompt, serves the corpus, logs every corpus call and checks every citation.</p>
        <pre><code>engines/my-engine/engine.yaml
engines/my-engine/adapter.py     def generate(req) -> str | dict</code></pre>
        <p>An engine counts as built once it passes conformance. Any agent that speaks the Model Context Protocol can read a pack's corpus without an adapter of its own.</p>
      </div>
      <NuxtLink to="/start/" :class="CTA_CLASS">Get started</NuxtLink>
    </section>
  </div>
</template>
