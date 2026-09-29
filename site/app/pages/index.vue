<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import hub from '~/data/hub.json'

useSeoMeta({
  title: 'Conjecture: the Open Science Foundation hypothesis hub',
  description: 'Conjecture runs open AI hypothesis engines over a field\'s own literature under identical conditions and audits every hypothesis with a model family that did not write it.',
})

const built = hub.engines.filter(e => e.built && e.id !== 'reference').length
const ran = hub.engines.filter(e => e.ran > 0).length
const designed = hub.engines.filter(e => !e.built).length
const pack = hub.pack
</script>

<template>
  <div class="container-main space-y-80 py-80 lg:space-y-100 lg:py-120">
    <header class="max-w-800">
      <h1 class="text-4xl text-black">Conjecture</h1>
    </header>
    <section class="max-w-800 space-y-30">
      <SectionIntro eyebrow="The Open Science Foundation hypothesis hub" headline="Which hypothesis engine should a field trust?">
        <p>Open systems that generate scientific hypotheses are multiplying, and almost none has been compared with another on the same literature. Conjecture runs them side by side on a field's own corpus, with one prompt and one output format, and ends every run with an audit by a model family that did not write the hypotheses.</p>
      </SectionIntro>
      <a :href="`/panel/${pack.name}/index.html`" :class="CTA_CLASS">Explore the biophoton pack</a>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">How a run works</h2>
      <div class="prose text-1xl text-black">
        <ol>
          <li><strong>Corpus.</strong> A seed bibliography is expanded by citation into the field's literature, and its open-access papers are mined for the sentences in which the field says what it does not know.</li>
          <li><strong>Questions.</strong> The open questions the field states about itself become structured briefs that every engine receives identically.</li>
          <li><strong>Generation.</strong> Each engine answers through one read-only corpus interface, without web access.</li>
          <li><strong>Merge.</strong> Hypotheses are clustered across engines. Independent arrival at the same claim is a signal; incompatible claims define an experiment that would settle them.</li>
          <li><strong>Verification.</strong> Each hypothesis is decomposed into steps and audited against the papers it cites, then certified or declined by judges from a model family that did not generate it.</li>
          <li><strong>Output.</strong> Experiment cards, a scoreboard and an audit database with the queries that regenerate every published number.</li>
        </ol>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Why it is built this way</h2>
      <div class="prose text-1xl text-black">
        <ul>
          <li><strong>One interface.</strong> Engines read the literature only through the corpus API, as a command line or as an MCP server, so a difference in output is a difference in the engine.</li>
          <li><strong>One prompt, one output format.</strong> What may differ is architecture and model family, never the question or the evidence.</li>
          <li><strong>Certify or decline.</strong> Following the discipline of theoria, a hypothesis whose load-bearing step fails is declined, and the failing step is named.</li>
          <li><strong>Cross-family verification.</strong> In the biophoton pack's first run, both judge families passed their own family's hypotheses more often: the Claude judges by {{ pack.selfpref.claude }} points, the Codex judge by {{ pack.selfpref.codex }}. A self-verified certification rate is not a measurement.</li>
        </ul>
      </div>
      <div class="flex flex-wrap gap-8">
        <Tag variant="outline">AGPL-3.0-or-later</Tag>
        <Tag variant="outline">Open research</Tag>
        <Tag variant="outline">Model Context Protocol</Tag>
      </div>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Status</h2>
      <p class="text-1xl text-gray">{{ built }} engines are built and pass conformance on a fictional toy corpus, and {{ ran }} of them have run on the biophoton pack. {{ designed }} more are designed and wait on an API key or an adapter.</p>
      <NuxtLink to="/engines/" :class="CTA_CLASS">See engines and judges</NuxtLink>
    </section>
  </div>
</template>
