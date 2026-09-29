<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# The Conjecture website

Composed from the Open Science Foundation website harness (the `starter`
of Opening-Science/Open-Science-Foundation-brand-guide at commit
`ca73478`, version 0.2.0): its canonical stylesheet, seven admitted
components and checks, unchanged. The pages in `app/pages/` and the data
step are this project's. The harness's own README, AGENTS.md and design
rules still govern the design; read them before changing a page.

Four pages (home, engines and judges, packs, get started) plus the active
pack's read-only run panel under `/panel/<pack>/`. Engine and judge
listings, pack figures and questions are generated from the hub's
manifests and the pack, never typed.

## Build

```sh
CONJECTURE_PACK=/path/to/pack.yaml python scripts/hub-data.py   # from site/..
npm ci
npm run design:check && npm run design:tokens:check && npm test && npm run typecheck
npm run generate          # static site in .output/public
```

Licensed fonts (Selecta; ABC Diatype Semi Mono) are not included: put
the woff2 files in `public/fonts/` locally (git ignores them) or let the
deploy workflow fetch them. Without them the site uses fallback fonts and
is not typographically faithful.

## Deploy

`.github/workflows/site.yml`, run by hand, builds the site with the
biophoton pack and deploys it to GitHub Pages. Nothing publishes on push.

## Copy

The OSF brand rules apply: factual copy, no em or en dashes, the Open
Science Foundation (OSF) kept distinct from the Open Science Institute
(OSI). Pack text shown on the site is normalised for dashes at build
time; the pack's files are not changed.
