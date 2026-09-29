<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# OSF web design reference

The canonical source is app/assets/css/main.css. Generated tokens.json and
css-variables.css are descriptions of that source, not independent themes.
This reference describes the seven-component starter, not the whole website.

## Tokens and layout

Selecta is the body and heading family. ABCDiatypeSemiMono is the CSS alias
for ABC Diatype Semi Mono, used for labels, metadata and buttons. Supply
licensed files separately; system fallback changes metrics and fidelity.
The root size is 13.2px, then 13.6px, 14px, 15px, 16px and 17px at the
existing responsive steps. text-lg deliberately generates no size utility.
Use the exact type scale in tokens.json and main.css.

Spacing uses --spacing: 0.0625rem. Thus p-30 is 30px at a 16px root, and
scales with that root. Common rhythms are space-y-30, gap-24, gap-40,
space-y-80 lg:space-y-100, and py-80 lg:py-120. Page examples reuse these
patterns. Use the canonical containers; max-w-800 is a measure within them.
Numeric utilities exist beyond these examples, so visual review must still
check rhythm. The scanner is not a finite allowlist of every spacing class.

Black is #1d1d1d; white is #fff. Cream-light and cream are surfaces, gray
and cream-darker are secondary text subject to contrast review. Blue is the
existing interaction and identity accent. Blue-ink is for readable static
blue text and citation links. Red is scoped to OpenTwin and is unavailable
for ordinary OSF compositions. No shadows or gradients are admitted.

Radii use the admitted md, xl and 2xl theme tokens, rounded-full for pills,
and the actively allowlisted rounded-[9px] button recipe. Do not use default
Tailwind radii outside that vocabulary.

## Components and recipes

- SectionIntro: optional blue mono eyebrow, h2 and body slot. It is a section
  opener, not a page header. The upstream accent eyebrow has a known contrast
  limitation on white; retain it only as the existing identity treatment.
- PostList: typographic list with optional featured lead, dates and tags.
  Pass show-tags=false for the current website's date-only listing pattern.
  Provide real routes without trailing slashes; the component appends one.
- MediaCarousel: caller-supplied media with navigation and pause controls.
  It honors reduced motion at mount. Images, videos and rights are external.
- Tag: quiet, outline and solid styles; optional button or NuxtLink rendering.
- Citation: compact or full-width citation, with clipboard action. Supply
  factual citation metadata. The component does not validate DOI provenance.
- LicenseNotice: displays a content licence supplied by the author. Only use
  it when that content is actually offered under the displayed terms.
- SkipLink: first focusable element in the header, targeting main-content.

CTA_CLASS in app/utils/ui.ts is the shared primary action recipe. Use it for
links or buttons as appropriate. The page examples compose existing header,
prose, section and CTA patterns. No general AppHeader/AppFooter, logo sketch,
CMS, analytics, people data or foundation navigation is exported.

## States and verification

Use existing focus-visible outlines. Prose links hover yellow. Primary
buttons hover button-hover. The existing interactive link pattern uses blue;
static citation links use blue-ink. Do not add a page cross-fade: the current
website removed its transition after a navigation failure. No page transition
is configured in this starter.

Check visible focus, keyboard navigation, text contrast, loaded fonts and
reduced motion in the actual page. Exact token reuse is necessary but cannot
prove accessibility or visual conformity. Read design/VISUAL-VERIFICATION.md.

The starter adds an accessibility stylesheet that disables CSS animation,
transitions and smooth scrolling under prefers-reduced-motion. It does not
alter the upstream theme. MediaCarousel also checks reduced motion at mount.
