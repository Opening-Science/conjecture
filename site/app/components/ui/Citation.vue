<script setup lang="ts">
// Citation — a "cite this" block giving each post a citable, DOI-anchored
// reference (design/components/Citation.md). Two placements share the component:
// compact = Research right-rail box; block (default) = News in-body full-width.
import { computed, ref } from 'vue'

type AuthorLike = string | { name: string; org?: boolean }

const props = withDefaults(
  defineProps<{
    authors?: AuthorLike[]
    year?: string | number
    title: string
    venue?: string
    doi?: string
    /** Compact rail box (Research) vs full-width block (News). */
    compact?: boolean
  }>(),
  {
    authors: () => [],
    year: undefined,
    venue: undefined,
    doi: undefined,
    compact: false,
  },
)

// "Martin Etzrodt" -> "Etzrodt, M." ; single-token names pass through;
// institutional authors (org flag, e.g. "Open Science Institute") stay verbatim.
function formatAuthor(a: AuthorLike): string {
  const name = (typeof a === 'string' ? a : a.name).trim()
  if (typeof a !== 'string' && a.org) return name
  const parts = name.split(/\s+/)
  if (parts.length < 2) return name
  const last = parts[parts.length - 1]
  const initials = parts
    .slice(0, -1)
    .map((p) => `${p[0]}.`)
    .join(' ')
  return `${last}, ${initials}`
}

const authorsText = computed(() => props.authors.map(formatAuthor).join(', '))

const doiUrl = computed(() => {
  if (!props.doi) return undefined
  return props.doi.includes('://') ? props.doi : `https://doi.org/${props.doi}`
})

// Full plain-text reference (used for the clipboard copy and screen readers).
const referenceText = computed(() => {
  const segments = [
    authorsText.value,
    props.year != null ? `(${props.year}).` : '',
    `${props.title}.`,
    props.venue ? `${props.venue}.` : '',
    doiUrl.value ?? '',
  ]
  return segments.filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()
})

const copied = ref(false)
let resetTimer: ReturnType<typeof setTimeout> | undefined

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(referenceText.value)
    copied.value = true
    if (resetTimer) clearTimeout(resetTimer)
    resetTimer = setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    // Clipboard unavailable (e.g. insecure context) — leave the reference text visible to copy manually.
  }
}

const copyBtnClass =
  'font-mono text-sm text-blue-ink underline cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
// break-all: DOI URLs are long unbroken strings — without it they overflow the
// compact rail box (seen on the live deploy).
const doiLinkClass =
  'break-all text-blue-ink underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
</script>

<template>
  <!-- Compact rail box (Research) -->
  <div v-if="compact" class="rounded-xl border border-cream bg-white p-16">
    <p class="font-mono text-sm text-gray">Cite as</p>
    <p class="mt-8 text-sm text-black">
      <!-- {{ ' ' }} — Vue condenses the trailing space at the template boundary away -->
      <template v-if="authorsText">{{ authorsText }}{{ ' ' }}</template>
      <template v-if="year != null">({{ year }}).{{ ' ' }}</template>
      {{ title }}.
      <span v-if="venue" class="italic">{{ venue }}. </span>
      <a v-if="doiUrl" :href="doiUrl" rel="noopener" target="_blank" :class="doiLinkClass">{{ doiUrl }}</a>
    </p>
    <button type="button" class="mt-12" :class="copyBtnClass" @click="copy">
      {{ copied ? 'Copied' : 'Copy citation' }}
    </button>
    <span class="sr-only" aria-live="polite">{{ copied ? 'Citation copied to clipboard' : '' }}</span>
  </div>

  <!-- Full-width in-body block (News) -->
  <div v-else class="border-t border-cream pt-24">
    <p class="font-mono text-sm tracking-[2%] text-gray uppercase">Cite this</p>
    <p class="mt-12 text-base text-black">
      <!-- {{ ' ' }} — Vue condenses the trailing space at the template boundary away -->
      <template v-if="authorsText">{{ authorsText }}{{ ' ' }}</template>
      <template v-if="year != null">({{ year }}).{{ ' ' }}</template>
      {{ title }}.
      <span v-if="venue" class="italic">{{ venue }}. </span>
      <a v-if="doiUrl" :href="doiUrl" rel="noopener" target="_blank" :class="doiLinkClass">{{ doiUrl }}</a>
    </p>
    <button type="button" class="mt-12" :class="copyBtnClass" @click="copy">
      {{ copied ? 'Copied' : 'Copy citation' }}
    </button>
    <span class="sr-only" aria-live="polite">{{ copied ? 'Citation copied to clipboard' : '' }}</span>
  </div>
</template>
