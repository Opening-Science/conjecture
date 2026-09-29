<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# OSF website starter

Nuxt 4 / Vue 3 / Tailwind 4, with seven admitted components and the canonical
OSF website stylesheet. This is an example composition and a basis for new
pages. No fonts, logos, media, analytics or publication credentials are bundled.

## Run

Use Node 22.12 or later. After copying this entire directory, including dotfiles:

```sh
npm ci
npm run dev
```

Read AGENTS.md explicitly in your agent host. Then ask it to read
[the design reference](design/system/ai-design-system.md) and a
[page spec](design/page-specs/project.md), compose your approved content and
complete the verification loop. The included guide page is a second example
built from [its own spec](design/page-specs/guide.md).

Supply [licensed webfonts](public/fonts/README.md) separately for faithful
rendering. Without them, the site runs with fallback fonts and cannot be
claimed visually faithful. Replace example identity, content and SEO before
using it for a real project. Add only your own authorized services and assets.

## Check

```sh
npm run design:check
npm run design:tokens:check
npm test
npm run typecheck
npm run generate
```

CI runs these checks and builds once with a deliberately inserted lab route
to prove it cannot ship. The output guard checks one h1 and main per content
page and rejects lab references. It does not replace browser-based semantics
or accessibility review. Follow [visual verification](design/VISUAL-VERIFICATION.md).

The scanner covers static class vocabulary and selected CSS declarations.
Dynamic style construction and all possible CSS syntax are not fully parsed.
The copied canonical stylesheet contains approved production dimensions and
is exempt from the added dimension scan; changes need design review.

## Licensing

Copied upstream source, CSS, specs and derived token exports retain MIT;
see LICENSE. New starter pages, agent instructions and validation additions
are Apache-2.0; see LICENSE-APACHE-2.0.txt and REUSE.toml. Preserve both notices
when copying the starter. No content, font, logo or trademark rights are
implied by these source-code licences.
