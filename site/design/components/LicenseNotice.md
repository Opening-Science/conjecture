<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: MIT -->

# LicenseNotice

## Purpose
A Creative Commons license statement on every post. Central to an *open* science
foundation : it makes the reuse terms explicit and machine-readable. Deliberately
**quiet**: a single muted line, not a filled panel (owner decision 2026-07-22 :
the earlier `rounded-2xl bg-cream` block read as too heavy on the article page).

## Anatomy
Props: `license` (default `'CC BY 4.0'`), `href` (default the CC BY 4.0 deed).
- One line, on a `border-t border-cream` hairline: `font-mono text-sm text-gray`
  reading "Licensed under **{license}** : free to share and adapt with
  attribution.", where `{license}` is the deed link.
- No panel fill, no heading label, no separate full-name line : the short code +
  half-sentence carry it; the deed link has the detail.

Both the Research and News articles use this single treatment (the previous
`size: 'block' | 'inline'` split is removed).

## States
- Link hover: `text-blue-ink` underline. Link focus: visible ring.

## Responsive behavior
Single line; wraps naturally on narrow widths. No size variants.

## Accessibility
- The license link points to the canonical CC deed URL; includes
  `rel="license noopener noreferrer"` (noopener/noreferrer added 2026-07-23 :
  it opens in a new tab) and an sr-only "opens in a new tab".
- AA contrast (`text-gray` on white passes).

## Tokens used (all existing)
`--color-cream/blue-ink/gray`, `--font-mono`, `--text-sm`, spacing scale.

## Proposed new tokens
None.

## Proposed allowlist entries
None.

## Changelog

- 2026-07-27 : License-aware. The deed URL and the closing clause are derived
  from the license code (a small known-license map) so CC0 links to the public
  domain deed and drops the "with attribution" line. An explicit `href` still
  overrides; unknown codes fall back to CC BY 4.0. No new tokens or vocabulary.
