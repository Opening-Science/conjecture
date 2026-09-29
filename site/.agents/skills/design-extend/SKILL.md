---
name: design-extend
description: Extend the OSF website starter through reuse checks, reviewed lab variants and separately approved component specifications.
---

<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Extend the admitted design vocabulary

Read [AGENTS.md](../../../AGENTS.md) and the current theme and component specs.

## Reuse check

Search the existing seven components, tokens and page patterns first. If they
express the brief, compose the result and run verification. Copying or
parameterizing an admitted component without changing its visual vocabulary
does not require inventing a new design treatment.

## Explore and select

For a real gap, build 3 to 4 variants in app/pages/_lab/<slug>.vue. Existing
tokens come first. Proposed values belong only in labeled --proposal-* custom
properties. Do not reference the lab from shipping code. The Nuxt config
removes lab routes from production and the output guard checks containment.
Use gstack browse to capture each variant at 1440px and 390px, compare it
against existing patterns, and explain the differences.

Gate 1: present variants and wait for the human to select or revise one.

## Specify and approve

Write design/components/<PascalCaseName>.md. Include purpose, anatomy,
props/slots, interaction states, responsive behavior, accessibility, existing
tokens, proposed tokens and any justified allowlist entries. Explain why
existing vocabulary cannot serve each addition.

Gate 2: wait for explicit approval of that specification. Keep this distinct
from selecting a visual variant.

## Admit and verify

On a codex/ branch, add approved tokens to main.css, run design:tokens, add
approved exceptions, implement the element and update its documentation.
Remove the lab page. Run all checks in AGENTS.md and the visual loop. Open a
focused PR with the spec, code, regenerated tokens and verification evidence.
A local approval does not grant upstream OSF admission. Request that through
the upstream design process. Do not merge or publish unless authorized.
