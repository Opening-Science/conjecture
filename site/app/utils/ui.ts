// Shared class recipes — the de-facto tokens the review found copied across
// 13 files with drift between copies (review D24, 2026-08-31). ONE canonical
// string per recipe; compose local additions per call site
// (:class="[CTA_CLASS, 'self-start']"). Values here are governed like any
// other class vocabulary: scripts/design-check.mjs scans .ts string literals.

/**
 * The black CTA box (production-verbatim recipe + the site's focus ring).
 * The cookie banner keeps its own smaller variant (px-17 py-8 text-base,
 * mirror parity) — that one is deliberately not this constant.
 */
export const CTA_CLASS =
  'inline-flex items-center justify-center gap-10 rounded-[9px] bg-button px-20 py-10 font-mono text-xl font-light text-white transition-colors duration-100 cursor-pointer hover:bg-button-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue'
