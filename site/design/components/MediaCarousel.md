<!-- SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation) -->
<!-- SPDX-License-Identifier: MIT -->

# MediaCarousel

## Purpose
An auto-advancing gallery of image / video slides with a **dotted progress
indicator**. First use: the `/institute` Etherlaken hero (owner-directed
2026-07-23) : cycling the campus renderings and the drone video in one frame,
in place of the single static figure. Reuses the site's existing motion
appetite (the hero sketch, the autoplay location/pilot videos) rather than
introducing new animation.

## Anatomy
Props: `slides: { type: 'image' | 'video', src, alt? }[]`, `intervalMs?`
(image dwell, default 5000), `label?` (region label).
- **Frame**: `aspect-video`, `rounded-xl`, `overflow-hidden`, `bg-cream`
  placeholder. A horizontal flex **track** holds all slides (`w-full
  shrink-0`); the active one is shown via `translateX(-index * 100%)` with a
  500ms ease-out transition (instant under reduced motion). All media is
  `object-cover` (fills the 16:9 frame; the square drone video is scaled and
  centre-cropped).
- **Dotted progress bar**: a centered row of dots, one per slide. Inactive =
  `w-8 h-8 bg-cream-dark` circle; **active = `w-24 h-8 bg-black` pill**
  (`rounded-full`, `transition-all`). Each dot is a `<button>` that jumps to
  its slide.

## States / behavior
- **Auto-advance**: image slides advance after `intervalMs` (default 3500ms);
  video slides autoplay muted while active and advance on their `ended` event
  (no timer). The slide transition is 300ms ease-out.
- **Touch swipe**: a horizontal drag past ~40px on the frame goes prev/next
  (no `preventDefault`, so vertical page scroll still works).
- **Keyboard**: with focus inside the carousel (e.g. on a dot), `←`/`→`
  navigate prev/next.
- **Pause** on hover and on focus entering the carousel (`mouseenter`/
  `focusin`), and for the duration of a touch; resume on leave/end.
- **Reduced motion**: no autoplay, no auto-advance, no slide transition : the
  dots still navigate manually (instant).
- Every dot has a visible focus ring (`outline-2 outline-blue`).

## Responsive behavior
- Fluid: `w-full aspect-video` at every width; the dots wrap-free row stays
  centered. No breakpoint-specific rules.

## Accessibility
- Region: `role="group"` + `aria-roledescription="carousel"` + `aria-label`.
- Video is `muted playsinline` (decorative); images carry `alt` from the data.
- Dot buttons: `aria-label="Show slide N of M"`, active gets
  `aria-current="true"`.
- Auto-rotation pauses on focus, so keyboard users aren't moved out from under.

## Tokens used (all existing)
`--color-cream/cream-dark/cream-darker/black`, `--radius-xl`, `rounded-full`,
`aspect-video`, `object-cover`, the spacing scale (`w-8/w-24/h-8/gap-8/mt-16`),
standard transitions. The track transform is a dynamic `:style` (percentage,
no token/color literal).

## Proposed new tokens
None.

## Proposed allowlist entries
None : no bracketed arbitrary values.
