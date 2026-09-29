#!/usr/bin/env node
/**
 * design-tokens.mjs — regenerates the design-system token artifacts from the
 * canonical source of truth, app/assets/css/main.css.
 *
 * Outputs (both fully overwritten on every run — never hand-edit them):
 *   design/system/tokens.json        DTCG-format design tokens
 *   design/system/css-variables.css  plain :root custom properties
 *
 * Everything except the Tailwind default breakpoints (which main.css does not
 * override and therefore cannot be parsed from it) is parsed directly out of
 * main.css: the @theme block, the responsive html font-size steps in
 * @layer base, and the custom container utilities in @layer utilities.
 * Deterministic by construction: same input file -> byte-identical output.
 *
 * Run: npm run design:tokens
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const CSS_PATH = path.join(root, 'app', 'assets', 'css', 'main.css')
const OUT_DIR = path.join(root, 'design', 'system')

const css = readFileSync(CSS_PATH, 'utf8')

/* ---------------------------------------------------------------- parsing */

/** Returns the body of the first `marker { ... }` block (brace-balanced). */
function extractBlock(source, marker) {
  const start = source.indexOf(marker)
  if (start === -1) throw new Error(`Block not found in main.css: ${marker}`)
  const open = source.indexOf('{', start)
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(open + 1, i)
    }
  }
  throw new Error(`Unbalanced braces after ${marker}`)
}

// @theme custom properties, in source order (Map preserves insertion order).
const themeBlock = extractBlock(css, '@theme')
const themeVars = new Map()
for (const m of themeBlock.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
  themeVars.set(m[1], m[2].replace(/\s+/g, ' ').trim())
}

const remToPx = (rem) => parseFloat(rem) * 16
const spacingPx = remToPx(themeVars.get('spacing')) // 0.0625rem -> 1px

/** Resolves a CSS length expression from main.css to pixels (or null). */
function resolvePx(expr) {
  const e = expr.trim()
  let m = e.match(/^calc\(var\(--spacing\)\s*\*\s*([\d.]+)\)$/)
  if (m) return parseFloat(m[1]) * spacingPx
  m = e.match(/^var\(--([\w-]+)\)$/)
  if (m && themeVars.has(m[1])) return resolvePx(themeVars.get(m[1]))
  m = e.match(/^([\d.]+)rem$/)
  if (m) return remToPx(m[1])
  m = e.match(/^([\d.]+)px$/)
  if (m) return parseFloat(m[1])
  return null
}

// Responsive root font-size steps from @layer base.
const baseBlock = extractBlock(css, '@layer base')
const rootFontSteps = []
{
  const base = baseBlock.match(/html\s*\{[^}]*?font-size:\s*([\d.]+)px/)
  if (base) rootFontSteps.push({ minWidth: null, px: parseFloat(base[1]) })
  const stepRe =
    /@media \(min-width:\s*([\d.]+rem)\)\s*\{\s*html\s*\{\s*font-size:\s*([\d.]+)px/g
  for (const m of baseBlock.matchAll(stepRe)) {
    rootFontSteps.push({ minWidth: m[1], px: parseFloat(m[2]) })
  }
}

// Custom container utilities from @layer utilities. The first occurrence of a
// class is its base (mobile) rule; later occurrences are media overrides.
const utilBlock = extractBlock(css, '@layer utilities')
const containers = new Map()
for (const m of utilBlock.matchAll(/\.(container[\w-]*|page-grid)\s*\{([^}]*)\}/g)) {
  const [, name, body] = m
  const maxWidth = body.match(/max-width:\s*([^;]+);/)?.[1]
  const padding = body.match(/padding-inline:\s*([^;]+);/)?.[1]
  if (!containers.has(name)) {
    containers.set(name, { maxWidth, paddingMobile: padding, paddingDesktop: null })
  } else if (padding) {
    containers.get(name).paddingDesktop = padding
  }
}

// Tailwind v4 default breakpoints — main.css defines no --breakpoint-*
// overrides, so the framework defaults apply. Kept here (not parsed) because
// they exist only inside the Tailwind package, not in main.css. Any
// --breakpoint-* token later added to @theme overrides the default.
const DEFAULT_BREAKPOINTS = [
  ['sm', '40rem'],
  ['md', '48rem'],
  ['lg', '64rem'],
  ['xl', '80rem'],
  ['2xl', '96rem'],
]
const breakpoints = DEFAULT_BREAKPOINTS.map(([name, def]) => [
  name,
  themeVars.get(`breakpoint-${name}`) ?? def,
])

/* ----------------------------------------------------------- tokens.json */

const GENERATED_NOTE =
  'GENERATED from app/assets/css/main.css @theme — regenerate via npm run design:tokens; do not hand-edit. main.css is the canonical design source.'

const px = (n) => `${n}px`
const dimension = (value, description) => {
  const t = { $type: 'dimension', $value: value }
  if (description) t.$description = description
  return t
}

const tokens = {
  $description: GENERATED_NOTE,
  color: {},
  fontFamily: {},
  fontWeight: {},
  fontSize: {
    $description:
      'Paired --text-* size/line-height tokens. text-lg is intentionally UNSET (--text-lg: initial) to replicate the production quirk that `text-lg` generates no CSS.',
  },
  rootFontSize: {
    $description:
      'Responsive html font-size steps from @layer base. All rem-based tokens scale with these.',
  },
  spacing: {},
  radius: {},
  breakpoint: {
    $description:
      'Tailwind v4 defaults — not overridden in @theme; listed for reference.',
  },
  container: {
    $description:
      'Custom container utilities from @layer utilities (px values resolved at the 16px root step) plus @theme --container-* tokens.',
  },
}

const unsetTokens = []
for (const [name, value] of themeVars) {
  if (value === 'initial') {
    unsetTokens.push(`--${name}`)
    continue
  }
  if (name.startsWith('color-')) {
    tokens.color[name.slice('color-'.length)] = { $type: 'color', $value: value }
  } else if (name.startsWith('font-weight-')) {
    tokens.fontWeight[name.slice('font-weight-'.length)] = {
      $type: 'fontWeight',
      $value: Number(value),
    }
  } else if (name.startsWith('font-')) {
    tokens.fontFamily[name.slice('font-'.length)] = {
      $type: 'fontFamily',
      $value: value.split(',').map((f) => f.trim().replace(/^"|"$/g, '')),
    }
  } else if (name.endsWith('--line-height')) {
    // Consumed alongside its size token in the branch below.
  } else if (name.startsWith('text-')) {
    const short = name.slice('text-'.length)
    const lineHeight = themeVars.get(`${name}--line-height`)
    const entry = {
      fontSize: dimension(value, `${resolvePx(value)}px at 16px root`),
    }
    if (lineHeight && lineHeight !== 'initial') {
      entry.lineHeight = { $type: 'number', $value: Number(lineHeight) }
    }
    tokens.fontSize[short] = entry
  } else if (name === 'spacing') {
    tokens.spacing.base = dimension(
      value,
      `${spacingPx}px at 16px root — NOT the Tailwind default 0.25rem; every numeric utility (p-30, gap-40, mt-100 …) is that many pixels`,
    )
  } else if (name.startsWith('spacing-')) {
    tokens.spacing[name.slice('spacing-'.length)] = dimension(
      value,
      `${resolvePx(value)}px at 16px root`,
    )
  } else if (name.startsWith('radius-')) {
    tokens.radius[name.slice('radius-'.length)] = dimension(
      value,
      `${resolvePx(value)}px at 16px root`,
    )
  } else if (name.startsWith('container-')) {
    tokens.container[name.slice('container-'.length)] = dimension(
      value,
      `@theme --${name} (max-w-* scale), ${resolvePx(value)}px at 16px root`,
    )
  } else if (name.startsWith('breakpoint-')) {
    // Overrides land in the breakpoints list above; nothing extra to do.
  } else {
    throw new Error(`Unrecognized @theme token: --${name} (extend the generator)`)
  }
}
if (unsetTokens.length) {
  tokens.$description += ` Unset (value: initial) and therefore token-less: ${unsetTokens.join(', ')}.`
}

for (const [i, step] of rootFontSteps.entries()) {
  const bp = step.minWidth
    ? breakpoints.find(([, v]) => v === step.minWidth)?.[0] ?? step.minWidth
    : 'base'
  tokens.rootFontSize[bp] = dimension(
    px(step.px),
    step.minWidth ? `from ${step.minWidth}` : 'default (smallest viewports)',
  )
  if (i === rootFontSteps.length - 1 && !step.minWidth) {
    throw new Error('Expected media-query font-size steps in @layer base')
  }
}

for (const [name, value] of breakpoints) {
  tokens.breakpoint[name] = dimension(value, `${remToPx(value)}px`)
}

for (const [name, def] of containers) {
  const entry = {
    // Resolve BEFORE stringifying: px(undefined) would produce the string
    // "nullpx" and ?? would never fire (review B15).
    maxWidth: dimension(resolvePx(def.maxWidth ?? '') != null ? px(resolvePx(def.maxWidth ?? '')) : null),
  }
  if (def.maxWidth == null) delete entry.maxWidth
  if (def.paddingMobile) {
    entry.paddingInline = dimension(px(resolvePx(def.paddingMobile)))
  }
  if (def.paddingDesktop) {
    entry.paddingInlineLg = dimension(
      px(resolvePx(def.paddingDesktop)),
      'from breakpoint lg (64rem)',
    )
  }
  if (name === 'page-grid') {
    entry.$description = '12-column grid, column-gap 24px'
    delete entry.maxWidth
    entry.columnGap = dimension('24px')
  }
  tokens.container[name] = entry
}

/* ------------------------------------------------------ css-variables.css */

const cssLines = [
  '/*',
  ' * GENERATED from app/assets/css/main.css @theme — regenerate via',
  ' * npm run design:tokens; do not hand-edit.',
  ' *',
  ' * Plain custom-property export of the canonical theme tokens, for use',
  ' * outside Tailwind (prototypes, emails, external tools). main.css remains',
  ' * the single source of truth.',
  ' */',
  ':root {',
]
for (const [name, value] of themeVars) {
  if (value === 'initial') continue // deliberately unset (see tokens.json note)
  cssLines.push(`  --${name}: ${value};`)
}
cssLines.push('}', '')

/* ------------------------------------------------------------------ write */

const tokensPath = path.join(OUT_DIR, 'tokens.json')
const cssPath = path.join(OUT_DIR, 'css-variables.css')
const nextTokens = `${JSON.stringify(tokens, null, 2)}\n`
const nextCss = cssLines.join('\n')

// --check: fail (exit 1) when the committed docs have drifted from main.css —
// run in CI so tokens.json / css-variables.css can never silently lag the
// @theme block (review B15). No files are written in this mode.
if (process.argv.includes('--check')) {
  const read = (p) => {
    try { return readFileSync(p, 'utf8') } catch { return null }
  }
  const drift = []
  if (read(tokensPath) !== nextTokens) drift.push(path.relative(root, tokensPath))
  if (read(cssPath) !== nextCss) drift.push(path.relative(root, cssPath))
  if (drift.length) {
    console.error(`design-tokens --check: DRIFT in ${drift.join(', ')} — run npm run design:tokens and commit the result`)
    process.exit(1)
  }
  console.log('design-tokens --check: generated docs match main.css')
  process.exit(0)
}

mkdirSync(OUT_DIR, { recursive: true })
writeFileSync(tokensPath, nextTokens)
writeFileSync(cssPath, nextCss)
console.log(`Wrote ${path.relative(root, tokensPath)} and ${path.relative(root, cssPath)}`)
