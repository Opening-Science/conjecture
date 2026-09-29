<script setup lang="ts">
// PostList — index treatment for News and Research, Variant A "Ledger"
// (design/components/PostList.md; ported from the Gate-1 ledger lab variant).
// Typographic, card-free list: an optional enlarged featured lead + ledger rows.
//
// `showTags` (2026-08-27, extended 2026-08-31): every current caller passes
// :show-tags="false" — rows are date-only across News and Research (owner-
// directed). The prop and the Tag column stay so tags can return per-surface.
import { computed } from 'vue'
import Tag from '../ui/Tag.vue'

interface PostAuthor {
  name: string
  role?: string
  link?: string
}

// Permissive shape matching @nuxt/content page items for the 'news'/'research'
// collections (see content.config.ts) plus the resolved route `path`.
interface Post {
  path?: string
  _path?: string
  title: string
  date: string
  summary: string
  tags?: string[]
  authors?: PostAuthor[]
}

const props = withDefaults(
  defineProps<{
    posts: Post[]
    /** Enlarge the first (most recent) post as a featured lead. */
    featured?: boolean
    /** Render the per-post tag column (and the tags in the featured meta line). */
    showTags?: boolean
  }>(),
  {
    featured: false,
    showTags: true,
  },
)

const featuredPost = computed<Post | undefined>(() =>
  props.featured ? props.posts[0] : undefined,
)
const rows = computed<Post[]>(() =>
  props.featured ? props.posts.slice(1) : props.posts,
)

function hrefOf(p: Post): string {
  // Trailing slash: the form Netlify serves directly (decision D1).
  const base = p.path ?? p._path
  return base ? `${base}/` : '#'
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  // Frontmatter dates are date-only strings, which parse as UTC midnight.
  // Format in UTC too, or every viewer west of UTC sees the previous day and
  // hydration flags a text mismatch against the prerendered HTML.
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

function authorLine(p: Post): string {
  const a = p.authors?.[0]
  if (!a) return ''
  return a.role ? `${a.name}, ${a.role}` : a.name
}

// The non-date remainder of the featured meta line (tags only — reading time
// is deliberately not shown, owner decision 2026-07-22), rendered after the
// machine-readable <time> element.
function metaRest(p: Post): string {
  if (!props.showTags) return ''
  return (p.tags ?? []).join(' / ')
}

const rowLinkClass =
  'group grid gap-8 border-b border-cream py-30 lg:grid-cols-[10rem_1fr_auto] lg:items-baseline lg:gap-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
</script>

<template>
  <div>
    <!-- Empty state -->
    <p v-if="!posts.length" class="border-b border-cream py-40 font-mono text-sm text-gray">
      No posts yet.
    </p>

    <template v-else>
      <!-- Featured lead -->
      <NuxtLink
        v-if="featuredPost"
        :to="hrefOf(featuredPost)"
        class="group block border-b border-cream py-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue"
      >
        <div class="font-mono text-sm text-gray">
          <time :datetime="featuredPost.date">{{ formatDate(featuredPost.date) }}</time><template v-if="metaRest(featuredPost)"> · {{ metaRest(featuredPost) }}</template>
        </div>
        <h2 class="mt-16 max-w-prose text-4xl text-black transition-colors group-hover:text-blue">
          {{ featuredPost.title }}
        </h2>
        <p class="mt-16 max-w-prose text-1xl text-gray">{{ featuredPost.summary }}</p>
        <div v-if="authorLine(featuredPost)" class="mt-16 font-mono text-sm text-gray">
          {{ authorLine(featuredPost) }}
        </div>
      </NuxtLink>

      <!-- Ledger rows -->
      <NuxtLink
        v-for="p in rows"
        :key="hrefOf(p)"
        :to="hrefOf(p)"
        :class="rowLinkClass"
      >
        <div class="font-mono text-sm text-gray"><time :datetime="p.date">{{ formatDate(p.date) }}</time></div>
        <div>
          <h3 class="text-2xl text-black transition-colors group-hover:text-blue">{{ p.title }}</h3>
          <p class="mt-6 max-w-prose text-1xl text-gray">{{ p.summary }}</p>
        </div>
        <div v-if="showTags" class="flex flex-wrap gap-8 lg:justify-end">
          <Tag v-for="t in (p.tags ?? [])" :key="t" variant="quiet">{{ t }}</Tag>
        </div>
      </NuxtLink>
    </template>
  </div>
</template>
