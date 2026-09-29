<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: MIT -->

# Citation

## Purpose
A "cite this" block giving each post a citable, DOI-anchored reference. Makes the
foundation's writing part of the scholarly record : the Cell/Nature and Arc
reference both do this, and it's on-mission for open science.

## Anatomy
Props: `authors`, `year`, `title`, `venue`, `doi`.
- A mono "Cite this" / "Cite as" label.
- The formatted reference string (authors, year, title, venue italicised, DOI as a link).
  Person names are formatted "Last, F. M."; an author with `org: true` (e.g.
  "Open Science Institute") is cited verbatim : never person-ized.
- Optional "Copy citation" button (copies plain-text and, later, BibTeX).

Two placements share the component: the Research right-rail cite box (compact) and
the News in-body citation block (full-width, above the author bios).

## States
- DOI link hover: `text-blue-ink` underline; focus ring visible.
- Copy button: default → on click a brief "Copied" confirmation (aria-live polite).

## Responsive behavior
Compact form in the sticky rail on desktop; full-width block on mobile / in News.

## Accessibility
- The reference is real text (selectable, not an image).
- Copy button is a `<button>` with an accessible label; confirmation announced via `aria-live`.
- AA contrast throughout.

## Tokens used (all existing)
`--color-black/gray/blue-ink/cream`, `--font-mono`, `--text-base/sm`, `--radius-xl`.

## Proposed new tokens
None.

## Proposed allowlist entries
None.
