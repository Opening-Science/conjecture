<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Visual verification

Install gstack browse in your agent environment and set BROWSE to its resolved
executable path. The harness does not bundle or silently install a browser.
Start npm run dev, then run the following with that executable:

```sh
"$BROWSE" viewport 1440x1000
"$BROWSE" goto http://localhost:3000
"$BROWSE" screenshot /tmp/osf-desktop.png
"$BROWSE" viewport 390x844
"$BROWSE" screenshot /tmp/osf-mobile.png
```

Repeat for every new route. Compare with the closest upstream reference at
opening.science or an approved local reference. Record route, viewport,
browser, font availability, interaction state, differences and resolution.
For a pixel comparison, use identical content and state. For different pages,
compare typography, container geometry, rhythm and colors rather than claiming
pixel equality. Keep screenshots out of this source distribution if they
include restricted artwork or content.

Confirm Selecta and ABCDiatypeSemiMono faces actually load from the supplied
licensed webfonts. A successful build without fonts is only a functional
check. Review text wrapping and horizontal overflow. Tab through every action
and activate links. Check one h1/main, visible focus, ARIA state on interactive
components, contrast and reduced motion. Recheck after any visual correction.

Known upstream limitation: the SectionIntro accent-blue eyebrow has inadequate
contrast for ordinary small text on white. It is retained as an existing
identity treatment. Do not claim that every inherited pattern meets WCAG AA;
address any required accessible alternative through design-extend.
