<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Project page

## Structure

Use the starter's home page as the example composition. One main landmark,
one left-aligned h1, no rule under the page header, and no visible standfirst.
The description belongs in SEO metadata. Follow with an existing SectionIntro,
a primary CTA using CTA_CLASS, and a plain h2 plus prose section. Optional
Tag labels use an existing variant. All slots receive approved user content.

## Implementation and verification

Use container-main, max-w-800 and the existing spacing pairs from index.vue.
Do not introduce a component for a page that can be composed from these
patterns. Keep explicit, visible focus states on links. Run the documented
checks and visual comparison at 1440px and 390px.
