<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
import hub from '~/data/hub.json'

useSeoMeta({
  title: 'Packs: Conjecture',
  description: 'Domain packs hydrate Conjecture with a field: its corpus, its open questions and the history of every run. The first pack covers ultra-weak photon emission.',
})

const pack = hub.pack
const nf = new Intl.NumberFormat('en')
</script>

<template>
  <div class="container-main space-y-80 py-80 lg:space-y-100 lg:py-120">
    <header class="max-w-800">
      <h1 class="text-4xl text-black">Packs</h1>
    </header>
    <section class="max-w-800 space-y-30">
      <SectionIntro eyebrow="The first pack" :headline="pack.title">
        <p>{{ nf.format(pack.n_works) }} works, mapped by citation from a seed bibliography, with open-access full text mined for the field's own statements of what it does not know. {{ pack.questions.length }} open questions, stated in the literature's own words.</p>
      </SectionIntro>
      <div class="prose text-1xl text-black">
        <ol>
          <li v-for="[id, title] in pack.questions" :key="id">{{ title }}</li>
        </ol>
      </div>
      <a :href="`/panel/${pack.name}/index.html`" :class="CTA_CLASS">Open the pack in the run panel</a>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Run 1</h2>
      <p class="text-1xl text-gray">{{ pack.engines_run.length }} engines with the same architecture on two model families produced {{ pack.hypotheses }} hypotheses. After merging, {{ pack.candidates }} candidates were audited; {{ pack.certified }} were certified, {{ pack.novel }} of them not restating the field's claim register, and {{ pack.conflicts }} pairs of incompatible claims define experiments that would settle them. Certified means the reasoning survived audit, not that the claim is true.</p>
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Licence and citation</h2>
      <div class="prose text-1xl text-black">
        <p>The pack's own content, from its questions and claim register to its runs, verdicts and outputs, is licensed under <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>: reuse it freely, credit it and share what you derive from it under the same terms. Its scripts are under the AGPL-3.0-or-later. Work metadata and abstracts come from OpenAlex under CC0; quoted excerpts remain with their publishers.</p>
      </div>
      <Citation :authors="[{ name: 'Open Science Foundation', org: true }]" :year="2026" title="Conjecture pack: biophotons" venue="github.com/Opening-Science/conjecture-pack-biophotons" />
    </section>
    <section class="max-w-800 space-y-24">
      <h2 class="text-3xl text-black">Write a pack</h2>
      <div class="prose text-1xl text-black">
        <p>A pack is a directory with a <code>pack.yaml</code>. It names the corpus, the open questions and an entry query for each, the domain framing of the prompt, the causal levels hypotheses are sorted into, the measurement areas experiment cards map to, and where outputs and run state live. Its <code>build:</code> block holds the seed bibliography and the field's vocabulary, from which the hub's corpus builder grows the corpus.</p>
        <p>The hub never names a field. Point it at a pack with <code>CONJECTURE_PACK=/path/to/pack.yaml</code>.</p>
      </div>
      <NuxtLink to="/start/" :class="CTA_CLASS">Get started</NuxtLink>
    </section>
  </div>
</template>
