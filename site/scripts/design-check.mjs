#!/usr/bin/env node
/**
 * design-check.mjs — style-vocabulary scanner for the OSF website rebuild.
 *
 * Ground truth for design tokens is app/assets/css/main.css (@theme block).
 * This script flags style vocabulary that bypasses those tokens:
 *
 *   (a) raw color literals (#hex, rgb(), rgba(), hsl(), hsla(), oklch(),
 *       lab(), lch(), hwb(), color(), color-mix(), CSS named colors, and
 *       %23-encoded hex inside url() data URIs) in Vue templates and in CSS —
 *       outside main.css's @theme block and @font-face rules
 *   (b) Tailwind arbitrary-value utilities (p-[13px], text-[#fff], ...) that
 *       are not in design/allowlist.json
 *   (c) static style="" attributes that introduce colors or sizes
 *   (d) components without a spec: app/components/**\/*.{vue,ts,tsx} must be
 *       listed in design/components/grandfathered.json OR have a NON-TRIVIAL
 *       design/components/<Name>.md (invariant I3). Grandfathered/spec names
 *       must be unique across the components tree (no basename shadowing).
 *   (e) lab containment: no reference to "_lab" from shipping code — checked
 *       across app/**.{vue,ts}, data/**.ts, and content/**.md
 *   (f) accent-bar borders: width-suffixed single-side borders (border-l-4,
 *       border-s-2, border-x-8, ...) — the border language is 1px hairlines
 *   (g) class vocabulary in SCRIPT string literals: the repo's own idiom keeps
 *       CTA/link class recipes in <script> consts, so string literals in .vue
 *       script blocks and in app/**.ts + data/**.ts run the same token checks
 *       as template class attributes (2026-08-31 — review item B9; script
 *       masking was the harness's biggest bypass)
 *   (h) off-token utilities from Tailwind's DEFAULT theme (2026-08-31 —
 *       review item B10): color utilities must use the @theme palette
 *       (bg-red-500, text-emerald-400, border-slate-200 all fail), text sizes
 *       must be @theme sizes, font families must be @theme fonts, and shadow-*
 *       is rejected outright (the system defines no shadow tokens)
 *
 * app/pages/_lab/ is EXEMPT from checks (a)-(c): it is the quarantined design
 * sandbox where raw --proposal-* values are legal pre-admission.
 *
 * The allowlist (design/allowlist.json) is itself validated: every entry
 * needs a non-empty reason, and entries no longer used anywhere FAIL the run
 * (stale entries silently pre-authorize future use — review item B14).
 *
 * Usage: node scripts/design-check.mjs [--root <dir>]
 * Exit codes: 0 clean, 1 violations found, 2 setup error.
 *
 * Zero dependencies. Not wired into the Netlify build — dev/CI check only.
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, relative, dirname, resolve, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

// ---------------------------------------------------------------------------
// Setup

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const rootFlag = process.argv.indexOf('--root')
const ROOT =
  rootFlag !== -1 && process.argv[rootFlag + 1]
    ? resolve(process.argv[rootFlag + 1])
    : resolve(SCRIPT_DIR, '..')

const APP_DIR = join(ROOT, 'app')
const DATA_DIR = join(ROOT, 'data')
const CONTENT_DIR = join(ROOT, 'content')
const MAIN_CSS = join(ROOT, 'app', 'assets', 'css', 'main.css')
const ALLOWLIST_PATH = join(ROOT, 'design', 'allowlist.json')

if (!existsSync(APP_DIR)) {
  console.error(`design-check: app/ not found under root ${ROOT}`)
  process.exit(2)
}

/** Normalize a CSS-ish value for allowlist comparison: strip whitespace, lowercase. */
const norm = (s) => s.replace(/\s+/g, '').toLowerCase()

const allowedClasses = new Set()
const allowedCssValues = new Set()
const allowlistUse = new Map() // entry value -> hit count
if (existsSync(ALLOWLIST_PATH)) {
  let parsed
  try {
    parsed = JSON.parse(readFileSync(ALLOWLIST_PATH, 'utf8'))
  } catch (err) {
    console.error(`design-check: cannot parse ${ALLOWLIST_PATH}: ${err.message}`)
    process.exit(2)
  }
  for (const [list, target, key] of [
    [parsed.classes ?? [], allowedClasses, (e) => e.value],
    [parsed.cssValues ?? [], allowedCssValues, (e) => norm(e.value)],
  ]) {
    for (const entry of list) {
      if (!entry.reason || !String(entry.reason).trim()) {
        console.error(`design-check: allowlist entry ${JSON.stringify(entry.value)} has no reason — every entry needs a justification`)
        process.exit(2)
      }
      target.add(key(entry))
      allowlistUse.set(key(entry), 0)
    }
  }
} else {
  console.error(`design-check: warning — ${ALLOWLIST_PATH} not found, treating allowlist as empty`)
}

const classAllowed = (token) => {
  if (!allowedClasses.has(token)) return false
  allowlistUse.set(token, (allowlistUse.get(token) ?? 0) + 1)
  return true
}
const cssValueAllowed = (value) => {
  const k = norm(value)
  if (!allowedCssValues.has(k)) return false
  allowlistUse.set(k, (allowlistUse.get(k) ?? 0) + 1)
  return true
}

// ---------------------------------------------------------------------------
// Tokens from @theme — the ground truth check (h) validates against.

const themeTokens = { colors: new Set(), textSizes: new Set(), fonts: new Set(), radii: new Set(), shadows: new Set() }
if (existsSync(MAIN_CSS)) {
  const css = readFileSync(MAIN_CSS, 'utf8')
  // Brace-balanced extraction: the lazy /@theme{...\n}/ regex would truncate
  // at the first "\n}" — a nested block inside @theme (Tailwind v4 allows
  // @keyframes there) would silently cut the token set and false-flag every
  // token declared after it (review finding).
  let theme = ''
  const at = css.indexOf('@theme')
  if (at !== -1) {
    const open = css.indexOf('{', at)
    if (open !== -1) {
      let depth = 0
      for (let i = open; i < css.length; i++) {
        if (css[i] === '{') depth++
        else if (css[i] === '}') {
          depth--
          if (depth === 0) {
            theme = css.slice(open + 1, i)
            break
          }
        }
      }
    }
  }
  for (const m of theme.matchAll(/--color-([a-z0-9-]+)\s*:/g)) themeTokens.colors.add(m[1])
  for (const m of theme.matchAll(/--text-([a-z0-9]+)\s*:/g)) themeTokens.textSizes.add(m[1])
  for (const m of theme.matchAll(/--font-([a-z0-9-]+)\s*:/g)) {
    if (!m[1].startsWith('weight-')) themeTokens.fonts.add(m[1])
  }
  for (const m of theme.matchAll(/--radius-([a-z0-9]+)\s*:/g)) themeTokens.radii.add(m[1])
  for (const m of theme.matchAll(/--shadow-([a-z0-9-]+)\s*:/g)) themeTokens.shadows.add(m[1])
} else {
  console.error('design-check: warning — main.css not found, check (h) disabled')
}

// Tailwind default palette names — a suffix built from one of these that is
// NOT an @theme color is a default-theme leak.
const TW_DEFAULT_COLOR_NAMES = new Set([
  'slate', 'gray', 'zinc', 'neutral', 'stone', 'red', 'orange', 'amber', 'yellow',
  'lime', 'green', 'emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet',
  'purple', 'fuchsia', 'pink', 'rose', 'white', 'black',
])
// Structural (non-color) suffixes that color-family utilities legitimately take.
const NON_COLOR_SUFFIXES = new Set(['none', 'auto', 'current', 'inherit', 'transparent'])
const TEXT_STRUCTURAL = new Set([
  'left', 'right', 'center', 'justify', 'start', 'end', 'wrap', 'nowrap',
  'balance', 'pretty', 'ellipsis', 'clip',
])
const FONT_STRUCTURAL = new Set(['bold', 'light', 'medium', 'normal', 'semibold', 'thin', 'extralight', 'extrabold', 'black', 'italic', 'stretch'])
// Families whose suffix is a color when it isn't structural.
const COLOR_FAMILIES = new Set([
  'bg', 'border', 'outline', 'ring', 'fill', 'stroke', 'decoration', 'divide',
  'from', 'via', 'to', 'accent', 'caret', 'placeholder',
])

/**
 * Check (h): does a single class token reach outside the @theme vocabulary?
 * Returns a reason string, or null when the token is fine. Deliberately
 * conservative: only patterns that UNAMBIGUOUSLY name default-theme values
 * are flagged, so structural utilities (flex, gap-20, border-b) never hit.
 */
function offTokenReason(rawToken) {
  if (themeTokens.colors.size === 0) return null
  // strip variants (hover:, lg:, focus-visible:, ...) and the ! prefix
  const token = rawToken.replace(/^!/, '').split(':').pop().replace(/^!/, '')
  if (token.includes('[')) return null // arbitrary values are check (b)'s job

  // shadow-*: the system defines no shadow tokens.
  const shadow = token.match(/^shadow(?:-(.+))?$/)
  if (shadow) {
    const sfx = shadow[1]
    if (sfx && themeTokens.shadows.has(sfx)) return null
    if (sfx === 'none') return null
    return `shadow utility — the design system defines no shadow tokens`
  }

  // font-<family>: must be an @theme font or a weight/style keyword.
  const font = token.match(/^font-([a-z-]+)$/)
  if (font && !themeTokens.fonts.has(font[1]) && !FONT_STRUCTURAL.has(font[1])) {
    return `font family outside @theme (--font-*)`
  }

  const m = token.match(/^([a-z]+)-(.+)$/)
  if (!m) return null
  const [, family, suffix] = m

  // text-: size, alignment/structural, or color.
  if (family === 'text') {
    if (themeTokens.textSizes.has(suffix)) return null
    if (TEXT_STRUCTURAL.has(suffix)) return null
    if (themeTokens.colors.has(suffix)) return null
    if (NON_COLOR_SUFFIXES.has(suffix)) return null
    if (/^([a-z]+)-(\d{2,3})(?:\/\d+)?$/.test(suffix) || TW_DEFAULT_COLOR_NAMES.has(suffix) || /^(xs|sm|base|lg|xl|\dxl)$/.test(suffix)) {
      return `text size/colour outside @theme (--text-* / --color-*)`
    }
    return null
  }

  if (!COLOR_FAMILIES.has(family)) return null
  const bare = suffix.replace(/\/\d+$/, '') // strip opacity modifier
  if (themeTokens.colors.has(bare)) return null
  if (NON_COLOR_SUFFIXES.has(bare)) return null
  // name-shade (red-500) or a bare default palette name that is not a token
  const shade = suffix.match(/^([a-z]+)-(\d{2,3})(?:\/\d+)?$/)
  if (shade && TW_DEFAULT_COLOR_NAMES.has(shade[1])) {
    return `default-theme colour — use an @theme --color-* token`
  }
  if (TW_DEFAULT_COLOR_NAMES.has(bare) && !themeTokens.colors.has(bare)) {
    return `default-theme colour — use an @theme --color-* token`
  }
  return null
}

// ---------------------------------------------------------------------------
// Helpers

function walk(dir, match, out = []) {
  if (!existsSync(dir)) return out
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) walk(full, match, out)
    else if (match(full)) out.push(full)
  }
  return out
}

function lineOf(text, index) {
  let line = 1
  for (let i = 0; i < index; i++) if (text[i] === '\n') line++
  return line
}

function maskRange(text, start, end) {
  return text.slice(0, start) + text.slice(start, end).replace(/[^\n]/g, ' ') + text.slice(end)
}

function maskMatches(text, re) {
  let out = text
  for (const m of text.matchAll(re)) {
    out = maskRange(out, m.index, m.index + m[0].length)
  }
  return out
}

function maskAtRuleBlocks(css, atRule) {
  let out = css
  const re = new RegExp(`@${atRule}\\b`, 'g')
  for (const m of css.matchAll(re)) {
    const open = css.indexOf('{', m.index)
    if (open === -1) continue
    let depth = 0
    let end = -1
    for (let i = open; i < css.length; i++) {
      if (css[i] === '{') depth++
      else if (css[i] === '}') {
        depth--
        if (depth === 0) {
          end = i + 1
          break
        }
      }
    }
    if (end !== -1) out = maskRange(out, m.index, end)
  }
  return out
}

const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g
// Extended 2026-08-31 (review B13): lab()/lch()/hwb()/color()/color-mix() now count.
const COLOR_FN_RE = /\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color-mix|color)\(/g
const SIZE_RE = /(^|[\s:(,])-?(?:\d+\.?\d*|\.\d+)(px|r?em|vh|vw|vmin|vmax|%|ch|ex|pt|cm|mm|in)\b/
// CSS named colors (the ones that read as colors, not CSS keywords).
const NAMED_COLORS =
  'aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|blanchedalmond|blueviolet|brown|burlywood|cadetblue|chartreuse|chocolate|coral|cornflowerblue|cornsilk|crimson|darkblue|darkcyan|darkgoldenrod|darkgray|darkgreen|darkkhaki|darkmagenta|darkolivegreen|darkorange|darkorchid|darkred|darksalmon|darkseagreen|darkslateblue|darkslategray|darkturquoise|darkviolet|deeppink|deepskyblue|dimgray|dodgerblue|firebrick|floralwhite|forestgreen|fuchsia|gainsboro|ghostwhite|goldenrod|gold|greenyellow|honeydew|hotpink|indianred|indigo|ivory|khaki|lavenderblush|lavender|lawngreen|lemonchiffon|lightblue|lightcoral|lightcyan|lightgoldenrodyellow|lightgray|lightgreen|lightpink|lightsalmon|lightseagreen|lightskyblue|lightslategray|lightsteelblue|lightyellow|limegreen|lime|linen|magenta|maroon|mediumaquamarine|mediumblue|mediumorchid|mediumpurple|mediumseagreen|mediumslateblue|mediumspringgreen|mediumturquoise|mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|navajowhite|navy|oldlace|olivedrab|olive|orangered|orange|orchid|palegoldenrod|palegreen|paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|powderblue|purple|rebeccapurple|rosybrown|royalblue|saddlebrown|salmon|sandybrown|seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|snow|springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|wheat|whitesmoke|yellowgreen'
const NAMED_COLOR_DECL_RE = new RegExp(`:\\s*(${NAMED_COLORS})\\b`, 'gi')

const HINTS = {
  class:
    'arbitrary Tailwind value — use a token utility (@theme in app/assets/css/main.css), or add to design/allowlist.json "classes" with a justification',
  color:
    'raw color literal — use a --color-* token utility (@theme in app/assets/css/main.css), or add to design/allowlist.json "cssValues" with a justification',
  style:
    'static style attribute with color/size — use token utilities instead, or add the declaration to design/allowlist.json "cssValues" with a justification',
  spec:
    'component without a spec — new components enter via /design-extend: write design/components/<Name>.md (see design/DESIGN-EVOLUTION.md invariant I3)',
  'spec-trivial':
    'spec file exists but is empty/trivial — a spec documents anatomy and rules (see design/components/README.md); touch-ing a file is not admission',
  'spec-collision':
    'component basename appears more than once under app/components/ — spec/grandfathered matching is by name, so shadowing a governed name evades review; rename one of them',
  'accent-border':
    'accent-bar border — the border language is 1px hairlines only (border, border-t/b/l/r); a thick side border is new decorative vocabulary and requires /design-extend',
  lab:
    'reference to the design lab from shipping code — app/pages/_lab/ is quarantined and must never be linked or imported (invariant I4)',
  'off-token':
    'utility from Tailwind’s default theme — the site’s vocabulary is the @theme tokens only (colors, text sizes, fonts; no shadows)',
  'allowlist-stale':
    'allowlist entry no longer used anywhere — remove it (stale entries silently pre-authorize future use)',
}

const violations = []
function report(file, line, kind, value) {
  violations.push({ file: relative(ROOT, file), line, kind, value })
}

// ---------------------------------------------------------------------------
// Class-token checks shared by templates (b/f/h) and script literals (g).

function checkClassToken(file, line, token) {
  if (/(?:^|[:!])border-[lrtbxyse]-\d+$/.test(token) && !classAllowed(token)) {
    report(file, line, 'accent-border', token)
    return
  }
  if (/\[[^\]]+\]/.test(token) && /(^\[|[-:]\[)/.test(token)) {
    if (!classAllowed(token)) report(file, line, 'class', token)
    return
  }
  const reason = offTokenReason(token)
  if (reason && !classAllowed(token)) report(file, line, 'off-token', `${token} (${reason})`)
}

// CSS property names and similar prose words that share a shape with class
// utilities. A Tailwind class never EQUALS a CSS property name, so a string
// literal mentioning "font-family" or "text-align" is prose, not a recipe —
// without this list the off-token check flags documentation strings
// (review finding: CLASSY_RE failed closed on prose and open on bare tokens).
const CSS_PROPERTY_WORDS = new Set([
  'font-family', 'font-size', 'font-weight', 'font-style', 'font-stretch',
  'text-align', 'text-decoration', 'text-transform', 'text-overflow',
  'text-indent', 'text-shadow', 'text-wrap', 'border-color', 'border-width',
  'border-style', 'border-radius', 'outline-color', 'outline-width',
  'outline-offset', 'outline-style', 'background-color', 'box-shadow',
])

/**
 * Check (g): scan string literals in script/TS source for class vocabulary.
 * No pre-gate on the literal: every token of every string runs the same
 * precise per-token checks the template scan uses (arbitrary values,
 * accent borders, off-token utilities). The checks are exact-match by
 * construction, so prose and URLs cannot false-positive — except CSS
 * property names, excluded above. This also closes the old gate's
 * fail-open for single no-dash tokens like a bare 'shadow' const.
 */
function scanScriptLiterals(file, text, offsetBase = 0, fullText = text) {
  // strip comments so commented-out recipes don't flag
  let src = maskMatches(text, /\/\*[\s\S]*?\*\//g)
  src = maskMatches(src, /(^|[^:])\/\/[^\n]*/gm)
  for (const m of src.matchAll(/'([^'\n]*)'|"([^"\n]*)"|`([^`]*)`/g)) {
    const literal = m[1] ?? m[2] ?? m[3] ?? ''
    if (literal.length < 3 || literal.includes('://')) continue
    const litStart = offsetBase + m.index + 1
    for (const tok of literal.matchAll(/[^\s"'`,{}()?$]+/g)) {
      const bareTok = tok[0].replace(/^!/, '').split(':').pop()
      if (CSS_PROPERTY_WORDS.has(bareTok)) continue
      checkClassToken(file, lineOf(fullText, litStart + tok.index), tok[0])
    }
  }
}

// ---------------------------------------------------------------------------
// Check (a) for CSS text: raw colors outside @theme (main.css only) / @font-face.

function scanCssColors(file, cssText) {
  let text = maskMatches(cssText, /\/\*[\s\S]*?\*\//g) // strip comments
  // The @theme mask is a privilege of the canonical token file ONLY — a
  // component <style> block cannot smuggle hex through its own @theme
  // (review B13).
  if (resolve(file) === MAIN_CSS) text = maskAtRuleBlocks(text, 'theme')
  text = maskAtRuleBlocks(text, 'font-face')
  // Decode %23-hex inside url(...) so data-URI SVG colors are visible to the
  // scan (masking keeps offsets stable: the decoded copy is only searched).
  for (const u of text.matchAll(/url\(([^)]*)\)/g)) {
    for (const enc of u[1].matchAll(/%23([0-9a-fA-F]{3,8})\b/g)) {
      const hex = `#${enc[1]}`
      if (!cssValueAllowed(hex)) report(file, lineOf(text, u.index), 'color', `${hex} (url-encoded)`)
    }
  }
  for (const m of text.matchAll(HEX_RE)) {
    if (!cssValueAllowed(m[0])) report(file, lineOf(text, m.index), 'color', m[0])
  }
  for (const m of text.matchAll(COLOR_FN_RE)) {
    const close = text.indexOf(')', m.index)
    const literal = close === -1 ? m[0] : text.slice(m.index, close + 1)
    if (literal.includes('var(')) continue // token-based, e.g. rgb(var(--x))
    if (!cssValueAllowed(literal)) report(file, lineOf(text, m.index), 'color', literal)
  }
  for (const m of text.matchAll(NAMED_COLOR_DECL_RE)) {
    if (!cssValueAllowed(m[1])) report(file, lineOf(text, m.index), 'color', m[1])
  }
}

// ---------------------------------------------------------------------------
// Vue template checks

function scanVueTemplate(file, source) {
  const tOpen = source.indexOf('<template')
  const tClose = source.lastIndexOf('</template>')
  if (tOpen === -1 || tClose === -1) return

  const contentStart = source.indexOf('>', tOpen) + 1
  let text = maskRange(maskRange(source, tClose, source.length), 0, contentStart)
  text = maskMatches(text, /<!--[\s\S]*?-->/g)

  // --- Checks (b)/(f)/(h): utilities in class / :class attributes.
  const classAttrRe = /:?class\s*=\s*(?:"([^"]*)"|'([^']*)')/g
  for (const attr of text.matchAll(classAttrRe)) {
    const value = attr[1] ?? attr[2] ?? ''
    const valueStart = attr.index + attr[0].indexOf(value)
    for (const tok of value.matchAll(/[^\s"'`,{}()?]+/g)) {
      checkClassToken(file, lineOf(text, valueStart + tok.index), tok[0])
    }
    text = maskRange(text, valueStart, valueStart + value.length)
  }

  // --- Check (c): static style="" attributes introducing colors/sizes.
  const styleAttrRe = /(?<![:\w])style\s*=\s*(?:"([^"]*)"|'([^']*)')/g
  for (const attr of text.matchAll(styleAttrRe)) {
    const value = attr[1] ?? attr[2] ?? ''
    const valueStart = attr.index + attr[0].indexOf(value)
    for (const decl of value.split(';')) {
      const d = decl.trim()
      if (!d) continue
      HEX_RE.lastIndex = COLOR_FN_RE.lastIndex = NAMED_COLOR_DECL_RE.lastIndex = 0
      const introduces =
        HEX_RE.test(d) || COLOR_FN_RE.test(d) || NAMED_COLOR_DECL_RE.test(d) ||
        (SIZE_RE.test(d) && !d.includes('var('))
      if (introduces && !cssValueAllowed(d)) {
        report(file, lineOf(text, valueStart), 'style', d)
      }
    }
    text = maskRange(text, valueStart, valueStart + value.length)
  }

  // --- Check (a): remaining raw color literals in the template.
  for (const m of text.matchAll(HEX_RE)) {
    if (!cssValueAllowed(m[0])) report(file, lineOf(text, m.index), 'color', m[0])
  }
  for (const m of text.matchAll(COLOR_FN_RE)) {
    const close = text.indexOf(')', m.index)
    const literal = close === -1 ? m[0] : text.slice(m.index, close + 1)
    if (literal.includes('var(')) continue
    if (!cssValueAllowed(literal)) report(file, lineOf(text, m.index), 'color', literal)
  }
}

/** <style> blocks inside .vue files are plain CSS — same rules as .css files. */
function scanVueStyleBlocks(file, source) {
  for (const m of source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) {
    const content = m[1]
    const contentStart = m.index + m[0].indexOf(content)
    let text = maskRange(source, 0, contentStart)
    text = maskRange(text, contentStart + content.length, text.length)
    scanCssColors(file, text)
  }
}

/** Check (g) inside a .vue file: every <script> block's string literals. */
function scanVueScriptBlocks(file, source) {
  for (const m of source.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) {
    const content = m[1]
    const contentStart = m.index + m[0].indexOf(content)
    scanScriptLiterals(file, content, contentStart, source)
  }
}

// ---------------------------------------------------------------------------
// Check (d): every component has a real spec (or is grandfathered), and
// component basenames are unique. Check (e): lab containment.

const LAB_SEG = join('pages', '_lab') + '/'
const isLabFile = (f) => f.includes('/' + LAB_SEG) || f.includes('\\' + LAB_SEG.replace('/', '\\'))

function specIsTrivial(path) {
  const text = readFileSync(path, 'utf8')
  const sections = (text.match(/^#{1,3} /gm) ?? []).length
  return text.trim().length < 200 || sections < 2
}

function scanGovernance(componentFiles, labScanFiles) {
  const specsDir = join(ROOT, 'design', 'components')
  const grandfatheredPath = join(specsDir, 'grandfathered.json')
  let grandfathered = new Set()
  if (existsSync(grandfatheredPath)) {
    try {
      grandfathered = new Set(JSON.parse(readFileSync(grandfatheredPath, 'utf8')).components ?? [])
    } catch (err) {
      console.error(`design-check: cannot parse ${grandfatheredPath}: ${err.message}`)
      process.exit(2)
    }
  }
  const seen = new Map() // basename -> first file
  for (const file of componentFiles) {
    const name = basename(file).replace(/\.(vue|tsx?|jsx?)$/, '')
    if (seen.has(name)) {
      report(file, 1, 'spec-collision', `${name} (also ${relative(ROOT, seen.get(name))})`)
      continue
    }
    seen.set(name, file)
    if (grandfathered.has(name)) continue
    const spec = join(specsDir, `${name}.md`)
    if (!existsSync(spec)) report(file, 1, 'spec', name)
    else if (specIsTrivial(spec)) report(file, 1, 'spec-trivial', name)
  }
  for (const file of labScanFiles) {
    if (isLabFile(file)) continue
    const source = readFileSync(file, 'utf8')
    for (const m of source.matchAll(/_lab\b/g)) {
      report(file, lineOf(source, m.index), 'lab', '_lab')
    }
  }
}

// ---------------------------------------------------------------------------
// Run

const vueFiles = walk(APP_DIR, (f) => f.endsWith('.vue'))
// All CSS under app/ — not just assets/css (review B12).
const cssFiles = walk(APP_DIR, (f) => f.endsWith('.css'))
const scriptFiles = [
  ...walk(APP_DIR, (f) => f.endsWith('.ts') || f.endsWith('.tsx')),
  ...walk(DATA_DIR, (f) => f.endsWith('.ts')),
]
const componentFiles = walk(join(APP_DIR, 'components'), (f) => /\.(vue|tsx?)$/.test(f))
const labScanFiles = [
  ...vueFiles,
  ...scriptFiles,
  ...walk(CONTENT_DIR, (f) => f.endsWith('.md')),
]

for (const file of vueFiles) {
  if (isLabFile(file)) continue // quarantined sandbox — checks (a)-(c),(g) do not apply
  const source = readFileSync(file, 'utf8')
  scanVueTemplate(file, source)
  scanVueStyleBlocks(file, source)
  scanVueScriptBlocks(file, source)
}
for (const file of cssFiles) {
  scanCssColors(file, readFileSync(file, 'utf8'))
}
for (const file of scriptFiles) {
  if (isLabFile(file)) continue
  const source = readFileSync(file, 'utf8')
  scanScriptLiterals(file, source)
}
scanGovernance(componentFiles, labScanFiles)

// Allowlist hygiene (review B14): unused entries fail the run.
for (const [value, hits] of allowlistUse) {
  if (hits === 0) report(ALLOWLIST_PATH, 1, 'allowlist-stale', value)
}

if (violations.length === 0) {
  console.log(
    `design-check: clean — ${vueFiles.length} .vue + ${cssFiles.length} .css + ${scriptFiles.length} .ts files, 0 violations`
  )
  process.exit(0)
}

violations.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line)
for (const v of violations) {
  console.error(`${v.file}:${v.line}  ${v.value}`)
  console.error(`    → ${HINTS[v.kind]}`)
}
console.error(`\ndesign-check: ${violations.length} violation(s) found`)
process.exit(1)
