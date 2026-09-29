<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Fonts supplied separately

The canonical CSS expects Selecta Regular, Medium and Bold and ABC Diatype
Semi Mono Regular and Bold at the filenames in its `@font-face` declarations.
No fonts are included. Obtain webfont licences for your own use and domain,
then provide the files through your authorised local or deployment process.
This directory ignores font files in git. Never force-add them to the package.

Without these files the browser falls back to system fonts. That is useful
for a functional smoke check, but cannot establish OSF typography fidelity.
Verify loaded font faces and requests before visual review. Distribution of
this source grants no font, logo or trademark rights.
