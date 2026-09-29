<script setup lang="ts">
// SectionIntro — the landing page's section-intro element, extracted as a
// reusable unit (design/components/SectionIntro.md; owner-directed 2026-07-28).
// Blue mono eyebrow → black headline (h2) → finer body via the default slot,
// mirroring the former homepage #sustainability section verbatim. It is ONE available option for a
// section opener, not mandatory: use it where a section leads with an intro
// (as on the landing), not for data lists or two-column functional blocks.
defineProps<{ eyebrow: string; headline: string }>()
</script>

<template>
  <div class="space-y-30">
    <p class="font-mono text-xl font-bold tracking-[2%] text-blue uppercase lg:text-sm">{{ eyebrow }}</p>
    <h2 class="text-3xl text-black">{{ headline }}</h2>
    <div v-if="$slots.default" class="max-w-800 text-xl text-black">
      <slot />
    </div>
  </div>
</template>
