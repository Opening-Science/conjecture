<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: MIT -->

# Tag

## Purpose
A small category/topic label used on post rows, article meta, and as a filter
control on the News and Research index pages. The one genuinely new atom the
blog needs : no pill pattern existed before.

## Anatomy
A single inline element wrapping short text (1 to 2 words). Three visual modes,
one component, selected by a `variant` prop:
- `quiet` : mono text only, no chrome (used inline in ledger rows: "Funding / Sustainability").
- `outline` : mono text inside a `rounded-full` 1px `border-cream` chip (article meta, cards).
- `solid` : mono text on a filled chip; used for the active state of a filter.

Optional `as` prop renders it as a `<button>` (filter) or `<NuxtLink>`/`<span>` (label).

## States
- Default: `text-gray` (quiet/outline); active filter is `bg-black text-white`.
- Hover (interactive only): `outline` → `border-cream-dark`; quiet/filter item → `text-blue` (the production hover blue : the site's single hover colour; not `blue-ink`, 2026-07-23 reconciliation).
- Active (filter selected): `solid`, `bg-black text-white`.
- Focus: visible focus ring : `outline-2 outline-blue` (mandatory; it's a control when interactive).
- Disabled: n/a.

## Responsive behavior
Intrinsic width; wraps naturally in a `flex-wrap gap-6/8` row. No breakpoint changes.

## Accessibility
- As a filter, render `<button>` with `aria-pressed` reflecting active state.
- As a label, render a non-interactive `<span>` (or `<NuxtLink>` if it navigates to a filtered view).
- Text contrast AA: `text-gray` (#6f6e66) on white/cream passes; `text-white` on `bg-black` passes.

## Tokens used (all existing)
`--color-gray`, `--color-black`, `--color-white`, `--color-blue`,
`--color-cream`, `--color-cream-dark`, `--font-mono`, `--text-sm`, `--radius` (rounded-full).

## Proposed new tokens
None.

## Proposed allowlist entries
None (uses `rounded-full`, standard spacing utilities).
