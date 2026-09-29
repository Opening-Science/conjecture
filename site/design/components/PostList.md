<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: MIT -->

# PostList

## Purpose
The index treatment for the News and Research section pages : Variant A "Ledger"
(chosen at Gate 1). A typographic, card-free list that suits OSF's text-forward,
image-light content. One component serves both sections; content differs, layout
does not.

## Anatomy
- Optional section header (rendered by the page, not this component): h1 + one-line description over a `border-black` rule.
- **Featured item** (first/most-recent post): larger : mono meta line (date · tags; reading time deliberately not shown, owner decision 2026-07-22), a `text-4xl` title, summary, author line; separated by `border-cream`.
- **Rows** (`PostList` maps the rest): a 3-column grid at desktop (`date | title+summary | tags`), stacked at mobile, each row a `<NuxtLink>` to the post, `border-cream` divider between rows.
- Optional **filter row** (Tag components in `outline`/`solid`) when the page shows more than one category : but with the two-section decision, each page is single-category, so the filter is usually absent.

Props: `posts` (typed content list), `featured?: boolean`, `showFilter?: boolean`,
`showTags?: boolean` (default `true`).

`showTags: false` drops the per-row tag column AND the tags from the featured
meta line. /news passes it (owner review 2026-08-27: its tags were incidental
keywords); /research keeps the default, because there the tags are the three
institute themes and carry real taxonomic meaning.

## States
- Row hover: title → `text-blue` (transition-colors) : the production hover blue, the site's single hover colour (nav, Values tabs). Not `blue-ink`; that token is reserved for static readable-blue text (2026-07-23 reconciliation).
- Row focus: visible focus ring on the row link (`outline-2 outline-blue`).

## Responsive behavior
- Desktop (`lg`): rows are `grid-cols-[10rem_1fr_auto]`, tags right-aligned. With
  `showTags: false` the third track collapses to zero width and the summary runs wider.
- Mobile: single column; date above title, tags below summary.

## Accessibility
- One `<h1>` per index page (supplied by the page, not repeated here).
- Post titles are `<h2>`/`<h3>` in document order; the whole row is the link with an accessible name from the title.
- AA contrast with token colors throughout.

## Tokens used (all existing)
`--text-5xl/4xl/3xl/2xl/1xl/sm`, `--color-black/gray/blue/cream/cream-dark`,
`--font-mono`, spacing scale, `container-main`.

## Proposed new tokens
None.

## Proposed allowlist entries
- `grid-cols-[10rem_1fr_auto]` : fixed ledger row grid (date column / content / tags). Justification: one-off editorial layout; not a reusable spacing value.
