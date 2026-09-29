<script setup lang="ts">
// LicenseNotice — a quiet, one-line Creative Commons statement on every post
// (design/components/LicenseNotice.md). Deliberately minimal: a single muted
// line on a hairline rule, not a filled panel (owner design decision
// 2026-07-22 — the block panel read as too heavy on the article page).
//
// License-aware (added 2026-07-27 for the first real research item, a CC0
// dataset): the deed URL and the closing clause are derived from the license
// code so CC0 does not link to the CC-BY deed or claim attribution is required.
// An explicit `href` still overrides. Unknown codes fall back to CC BY 4.0.
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** Short license code, e.g. "CC BY 4.0" or "CC0 1.0". */
    license?: string
    /** Canonical deed URL. Overrides the code lookup when set. */
    href?: string
  }>(),
  {
    license: 'CC BY 4.0',
    href: undefined,
  },
)

const FALLBACK = {
  href: 'https://creativecommons.org/licenses/by/4.0/',
  note: 'Free to share and adapt with attribution.',
}

const KNOWN: Record<string, { href: string; note: string }> = {
  'CC BY 4.0': FALLBACK,
  'CC0 1.0': {
    href: 'https://creativecommons.org/publicdomain/zero/1.0/',
    note: 'Dedicated to the public domain, free to use without attribution.',
  },
}

const deedHref = computed(() => props.href ?? KNOWN[props.license]?.href ?? FALLBACK.href)
const note = computed(() => KNOWN[props.license]?.note ?? FALLBACK.note)

const linkClass =
  'text-blue-ink underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
</script>

<template>
  <p class="border-t border-cream pt-16 font-mono text-sm text-gray">
    Licensed under
    <a :href="deedHref" rel="license noopener noreferrer" target="_blank" :class="linkClass">{{ license }}</a>.
    {{ note }}<span class="sr-only"> (link opens in a new tab)</span>
  </p>
</template>
