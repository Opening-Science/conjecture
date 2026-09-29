<script setup lang="ts">
// Tag — small category/topic label (design/components/Tag.md).
// Three visual modes (quiet | outline | solid) in one atom. Optionally renders
// as a filter <button> (aria-pressed) or a <NuxtLink>; otherwise a plain <span>.
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** Visual mode. quiet = mono text only; outline = bordered chip; solid = filled chip. */
    variant?: 'quiet' | 'outline' | 'solid'
    /** Render element. 'span' (label), 'button' (filter), 'link' (navigates). */
    as?: 'span' | 'button' | 'link'
    /** Filter selected state — reflected in aria-pressed and forces the solid look. */
    active?: boolean
    /** Destination when as="link". */
    to?: string
  }>(),
  {
    variant: 'quiet',
    as: 'span',
    active: false,
    to: undefined,
  },
)

const interactive = computed(() => props.as === 'button' || props.as === 'link')

// A filter button expresses selection through the solid look; unselected filters
// read as outline chips. Non-button tags honour the passed variant verbatim.
const effectiveVariant = computed<'quiet' | 'outline' | 'solid'>(() => {
  if (props.as === 'button') return props.active ? 'solid' : 'outline'
  return props.variant
})

const chipBase = 'inline-flex items-center rounded-full px-12 py-3 font-mono text-sm'

const variantClass = computed(() => {
  switch (effectiveVariant.value) {
    case 'solid':
      return `${chipBase} bg-black text-white`
    case 'outline':
      return `${chipBase} border border-cream text-gray${interactive.value ? ' transition-colors hover:border-cream-dark' : ''}`
    case 'quiet':
    default:
      return `font-mono text-sm text-gray${interactive.value ? ' transition-colors hover:text-blue' : ''}`
  }
})

const focusClass = computed(() =>
  interactive.value
    ? 'cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
    : '',
)
</script>

<template>
  <button
    v-if="as === 'button'"
    type="button"
    :aria-pressed="active"
    :class="[variantClass, focusClass]"
  >
    <slot />
  </button>
  <NuxtLink
    v-else-if="as === 'link'"
    :to="to"
    :class="[variantClass, focusClass]"
  >
    <slot />
  </NuxtLink>
  <span v-else :class="variantClass">
    <slot />
  </span>
</template>
