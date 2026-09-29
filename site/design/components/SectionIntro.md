<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: MIT -->

# SectionIntro

The landing page's section-intro element, extracted as a reusable unit
(owner-directed 2026-07-28, wireframe gate "section-intro element", Variant B).

## What it is

A three-part section opener, identical to `SustainabilitySection` on the
landing page:

1. **Eyebrow** : blue mono, uppercase, `tracking-[2%]` (`text-xl` mobile,
   `lg:text-sm`). The short section label.
2. **Headline** : `text-3xl` black `h2`. The substantive line.
3. **Body** (default slot, optional) : `text-xl` black, `max-w-800` measure.

Internal rhythm is `space-y-30`, matching the landing element. The component is
presentational (renders a `<div>`); the page wraps it in a `<section>` and adds
any following content (cards, a CTA) as siblings.

## Props / slots

- `eyebrow: string` (required) : the blue label.
- `headline: string` (required) : the `h2` line.
- default slot : the finer body; omit for an eyebrow + headline only.

## When to use

One **available option**, not a mandate. Use it where a section leads with an
intro, the same rhythm the landing uses for Mission / Values / Sustainability.
Do **not** force it onto data lists or two-column functional blocks (e.g. the
Institute People / Governance columns) : those keep a plain `h2`.

First adopted on `/institute` (What we do, Three pillars, Fellowships). The
pillar pages (`/institute/<pillar>`) apply the same visual pattern **inline** at
page-header level (h1 headline, and a linked "Open Science Institute · Pillar"
breadcrumb as the blue eyebrow) : the component itself is h2 + plain-string
eyebrow, so the header case is styled by hand rather than reusing it. The lower
project dossiers on those pages keep their own distinct treatment.

## Tokens / vocabulary

Existing tokens only: `text-blue`, `text-3xl`, `text-xl`, `font-mono`,
`font-bold`, `uppercase`, `tracking-[2%]` (allowlisted), `max-w-800`,
`space-y-30`. No new tokens or allowlist entries.

## Proposed new tokens

None.

## Proposed allowlist entries

None.
