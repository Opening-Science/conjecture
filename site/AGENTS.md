<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# OSF website composition rules

Read design/system/ai-design-system.md and the relevant design/page-specs file.
This Nuxt 4 / Vue 3 / Tailwind 4 starter carries a reviewed subset of the OSF
website system. app/assets/css/main.css is the local canonical snapshot.
The upstream authority is Opening-Science/homepage. Update snapshots through
reviewed package releases; do not silently fetch its default branch.

## Compose first

Use only the admitted theme, components and documented patterns. Reuse the
seven components in app/components and their specs. No new colors, fonts,
sizes, radii, shadows, spacing values or breakpoints. Numeric spacing uses
0.0625rem per unit; text-lg is unset. Use container-main, container-narrow,
container-wide or container-institute. Do not introduce arbitrary utilities
without an approved, actively used allowlist entry and justification.

One left-aligned h1 and one main per page. No decorative header rule or
right-aligned standfirst; descriptions go in useSeoMeta. Links and buttons
need visible focus. Follow the existing hover patterns. Check contrast and
reduced motion. The imported SectionIntro blue eyebrow is an inherited
contrast limitation, not a general accessible body-text color. Do not claim
unqualified WCAG compliance from the token checker.

Use factual copy and no long dashes. Distinguish the Open Science Foundation
(OSF) from the Open Science Institute (OSI). Do not invent endorsements,
people, citations or project claims. OSF naming and marks require the
appropriate permission; the code licence does not grant branding rights.

## Extend only when needed

Read [.agents/skills/design-extend/SKILL.md](.agents/skills/design-extend/SKILL.md).
A new design element needs lab variants, a human variant selection, a spec,
and separate human spec approval before implementation. No change to the
canonical theme or allowlist before that approval. Never weaken a check to
make generated work pass. Upstream admission is separate from a downstream
project approval; do not label local additions as OSF-approved automatically.

## Verify before completion

Run npm run design:check, npm run design:tokens:check, npm test,
npm run typecheck and npm run generate. Inspect every generated route at
1440px and 390px with gstack browse, following [visual verification](design/VISUAL-VERIFICATION.md).
Check fonts actually load, keyboard operation, one h1/main, no overflow and
reduced motion. Report missing dependencies and unverified claims.

scripts/design-policy.mjs also serves the Astro path in ../ASTRO.md: it scans
.astro files, checks static inline style attributes and covers every
conventional source directory that exists. Keep that behaviour when editing it.

The static scanner is bounded: dynamically constructed classes, arbitrary
JavaScript styles and all possible CSS syntax are not fully interpreted.
Rendered review remains mandatory. The canonical stylesheet retains approved
production dimensions; its integrity is checked in the distribution repo.
Treat edits to it, the checker and the allowlist as governed changes.

Keep font binaries, media, secrets and deployment credentials out of this
source package. Supply licensed fonts separately. Preserve the MIT notice for
upstream source and the Apache notice for starter tooling. Do not publish or
send content unless the user's task authorizes it.

## Upstream checker messages

The unchanged upstream checker may mention design/DESIGN-EVOLUTION.md or
design/components/README.md. Those upstream documents are not bundled here.
Use the local [design-extend workflow](.agents/skills/design-extend/SKILL.md)
and the admitted specs in design/components instead. These messages do not
allow bypassing the two human approval gates.
