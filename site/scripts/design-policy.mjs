// SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation)
// SPDX-License-Identifier: Apache-2.0
// Additional, deliberately bounded policy checks alongside the upstream scanner.
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { resolve, join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name)
  if (i < 0) return fallback
  const value = process.argv[i + 1]
  // Swallowing the next flag as a value made a typo scan nothing and pass.
  if (!value || value.startsWith('--')) throw new Error(`${name} needs a value`)
  return value
}
const given = arg('--root', null)
const root = given ? resolve(given) : resolve(dirname(fileURLToPath(import.meta.url)), '..')

// Nuxt keeps source under app/; an Astro project adds its routes and layouts
// under src/ while keeping the copied harness tree at app/ verbatim, so the
// hash-pinned upstream scanner still governs it. Default to EVERY conventional
// directory that exists rather than the first one: picking only app/ would
// silently leave an Astro project's src/ pages unchecked. --src overrides with
// a comma-separated list.
const CONVENTIONAL_SRC = ['app', 'src']
const named = arg('--src', null)
// Normalise so './src', 'src/' and an absolute path inside the project all
// produce the same prefix the _lab exemption is compared against below.
const srcDirs = (named ? named.split(',').map(d => d.trim()).filter(Boolean) : CONVENTIONAL_SRC.filter(d => existsSync(join(root, d))))
  .map(d => relative(root, resolve(root, d)).replaceAll('\\', '/'))
if (!srcDirs.length) throw new Error(`No source directory found under ${root} (looked for ${CONVENTIONAL_SRC.join(', ')})`)
for (const dir of srcDirs) {
  // A directory that is missing or outside the project would walk to nothing
  // and report a convincing "clean" having read no files at all.
  if (!dir || dir.startsWith('..')) throw new Error(`Source directory outside the project: ${dir || '.'}`)
  if (!existsSync(join(root, dir))) throw new Error(`Source directory not found: ${dir}`)
}
const themeFile = join(root, arg('--theme', existsSync(join(root, 'app')) ? 'app/assets/css/main.css' : `${srcDirs[0]}/styles/main.css`))
if (!existsSync(themeFile)) throw new Error(`Missing canonical stylesheet: ${relative(root, themeFile) || themeFile}`)
const theme = readFileSync(themeFile, 'utf8')
if (!/@theme\s*\{/.test(theme) || !/--color-[\w-]+\s*:/.test(theme)) throw new Error('Missing canonical theme or palette')
const radii = new Set([...theme.matchAll(/--radius-([\w-]+)\s*:/g)].map(m => m[1]))
const allow = JSON.parse(readFileSync(join(root, 'design/allowlist.json'), 'utf8'))
const allowed = new Set((allow.classes ?? []).map(x => x.value))
// Same normalisation as design-check.mjs, so an admitted declaration is
// admitted by both scanners rather than only by one of them.
const norm = value => value.replace(/\s+/g, '').toLowerCase()
const allowedCssValues = new Set((allow.cssValues ?? []).map(x => norm(x.value)))
const errors = []
const clean = text => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[\s\S]*?-->/g, '')
const report = (file, message) => errors.push(`${relative(root, file)}: ${message}`)
function walk(dir) {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { withFileTypes: true }).flatMap(e => {
    const path = join(dir, e.name)
    if (e.isSymbolicLink()) { report(path, 'Source symlinks are not supported'); return [] }
    return e.isDirectory() ? walk(path) : /\.(vue|astro|css|ts|tsx)$/.test(path) ? [path] : []
  })
}
function checkCSS(file, css) {
  // The canonical stylesheet preserves production base rules verbatim. Its
  // distribution hash is verified separately; editing it requires review.
  if (file === themeFile) return
  for (const m of clean(css).matchAll(/([\w-]+)\s*:\s*([^;{}]+)(?:;|(?=\}))/g)) {
    const property = m[1].toLowerCase(), value = m[2].trim()
    const geometry = /^(?:min-|max-)?(?:width|height)$/.test(property)
    const dimensional = geometry || /^(?:font-size|line-height|letter-spacing|word-spacing|text-indent|text-underline-offset|border(?:-[\w]+)?-(?:width|radius)|border-radius|margin(?:-[\w]+)?|padding(?:-[\w]+)?|(?:row-|column-)?gap)$/.test(property)
    if (dimensional && /(?:\d|\.\d)(?:px|r?em|vh|vw|vmin|vmax|ch|ex|pt|cm|mm|in)\b/i.test(value)) {
      report(file, `Raw CSS dimension in ${property}: ${value}; use a token`)
    }
    if (dimensional && !geometry && /\d%/.test(value)) report(file, `Raw CSS percentage in ${property}: ${value}`)
    if (property === 'line-height' && /^(?:\d*\.)?\d+$/.test(value) && Number(value) !== 0) report(file, `Raw line-height: ${value}`)
    if (property === 'font-family' && !/^(?:var\(--font-[\w-]+\)|inherit)$/.test(value)) report(file, `Unadmitted font family: ${value}`)
    if (property === 'box-shadow' && value !== 'none') report(file, 'The OSF theme defines no shadow tokens')
  }
}
// Mirrors design-check.mjs checks (a) and (c). That scanner resolves its tree
// as <root>/app and is byte-identical to the recorded upstream source, so it
// cannot be repointed at src/. These patterns are copied deliberately and must
// be kept in step with it; they run only where it does not.
const HEX_RE = /#[0-9a-fA-F]{3,8}\b/g
const COLOR_FN_RE = /\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color-mix|color)\(/g
const NAMED_COLORS =
  'aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|blanchedalmond|blueviolet|brown|burlywood|cadetblue|chartreuse|chocolate|coral|cornflowerblue|cornsilk|crimson|darkblue|darkcyan|darkgoldenrod|darkgray|darkgreen|darkkhaki|darkmagenta|darkolivegreen|darkorange|darkorchid|darkred|darksalmon|darkseagreen|darkslateblue|darkslategray|darkturquoise|darkviolet|deeppink|deepskyblue|dimgray|dodgerblue|firebrick|floralwhite|forestgreen|fuchsia|gainsboro|ghostwhite|goldenrod|gold|greenyellow|honeydew|hotpink|indianred|indigo|ivory|khaki|lavenderblush|lavender|lawngreen|lemonchiffon|lightblue|lightcoral|lightcyan|lightgoldenrodyellow|lightgray|lightgreen|lightpink|lightsalmon|lightseagreen|lightskyblue|lightslategray|lightsteelblue|lightyellow|limegreen|lime|linen|magenta|maroon|mediumaquamarine|mediumblue|mediumorchid|mediumpurple|mediumseagreen|mediumslateblue|mediumspringgreen|mediumturquoise|mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|navajowhite|navy|oldlace|olivedrab|olive|orangered|orange|orchid|palegoldenrod|palegreen|paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|powderblue|purple|rebeccapurple|rosybrown|royalblue|saddlebrown|salmon|sandybrown|seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|snow|springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|wheat|whitesmoke|yellowgreen'
const NAMED_COLOR_DECL_RE = new RegExp(`:\\s*(${NAMED_COLORS})\\b`, 'gi')
function checkColors(file, text) {
  for (const re of [HEX_RE, COLOR_FN_RE, NAMED_COLOR_DECL_RE]) {
    re.lastIndex = 0
    for (const m of text.matchAll(re)) {
      const literal = m[0].replace(/^:\s*/, '')
      if (allowedCssValues.has(norm(literal))) continue
      report(file, `Raw color literal: ${literal}; use a --color-* token`)
    }
  }
}
const labPrefixes = srcDirs.map(d => `${d}/pages/_lab/`)
// design-check.mjs resolves its tree as <root>/app and cannot be repointed: it
// is byte-identical to the recorded upstream source. Checks it already performs
// there (static style attributes, arbitrary utilities, lab references) are left
// to it, so the two scanners can never contradict each other on the same file.
// Outside app/ nothing else would see them, which is the Astro gap.
const upstreamScans = rel => rel === 'app' || rel.startsWith('app/')
// Mirrors design-check.mjs check (c): a lookbehind excludes :style and
// v-bind:style, and the alternation keeps a value containing the other quote.
const STYLE_ATTR_RE = /(?<![:\w])style\s*=\s*(?:"([^"]*)"|'([^']*)')/g
for (const file of srcDirs.flatMap(d => walk(join(root, d)))) {
  const rel = relative(root, file).replaceAll('\\', '/')
  if (labPrefixes.some(prefix => rel.startsWith(prefix))) continue
  const source = clean(readFileSync(file, 'utf8'))
  if (file.endsWith('.css')) {
    checkCSS(file, source)
    if (!upstreamScans(rel) && file !== themeFile) checkColors(file, source)
  }
  else {
    for (const style of source.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)) checkCSS(file, style[1])
    // A static inline style bypasses the class vocabulary entirely. Astro has
    // no :style binding, so style="…" is its usual escape hatch. A dynamic
    // binding (:style, style={…}) resolves only at runtime and still needs the
    // rendered review the scanner cannot replace.
    if (!upstreamScans(rel)) {
      for (const attr of source.matchAll(STYLE_ATTR_RE)) {
        for (const declaration of (attr[1] ?? attr[2] ?? '').split(';')) {
          const value = declaration.trim()
          // The trailing semicolon closes the declaration for the shared parser.
          if (value && !allowedCssValues.has(norm(value))) checkCSS(file, `${value};`)
        }
      }
    }
    // Static class tokens, including Vue script recipes. As with the upstream
    // scanner, dynamically assembled classes require rendered verification.
    const withoutLineComments = source.replace(/(^|\n)\s*\/\/[^\n]*/g, '$1')
    for (const m of withoutLineComments.matchAll(/\brounded(?:-[\w]+)*\b/g)) {
      const token = m[0]
      const suffix = token.replace(/^rounded(?:-(?:t|r|b|l|s|e|tl|tr|bl|br|ss|se|es|ee))?(?:-|$)/, '')
      if (['full', 'none'].includes(suffix) || radii.has(suffix) || allowed.has(token)) continue
      if (withoutLineComments[m.index + token.length] === '-' && withoutLineComments[m.index + token.length + 1] === '[') {
        // Arbitrary utilities are handled by the upstream allowlist scanner,
        // where it runs. Outside app/ it would see nothing, so resolve the
        // whole token here and hold it to the same allowlist.
        if (upstreamScans(rel)) continue
        const arbitrary = withoutLineComments.slice(m.index).match(/^rounded(?:-[\w]+)*-\[[^\]\s]*\]/)
        if (arbitrary && allowed.has(arbitrary[0])) continue
        report(file, `Radius outside @theme: ${arbitrary ? arbitrary[0] : token}`)
        continue
      }
      report(file, `Radius outside @theme: ${token}`)
    }
    if (/\b(?:text|bg|border|ring|fill|stroke)-red\b/.test(withoutLineComments)) report(file, 'The red token is reserved for OpenTwin, outside this OSF starter')
    // design-check.mjs check (e) keeps the quarantined lab unreferenced, but
    // only under app/. Shipping code elsewhere needs the same containment.
    if (!upstreamScans(rel) && /_lab\b/.test(withoutLineComments)) report(file, 'Reference to the design lab from shipping code')
    if (!upstreamScans(rel)) {
      checkColors(file, source)
      // The upstream allowlist scanner vets arbitrary utilities, but only under
      // app/. Elsewhere an unadmitted arbitrary value would simply ship.
      // rounded-[…] is already reported by the radius branch above.
      for (const m of withoutLineComments.matchAll(/\b(?!rounded\b)[a-z][\w-]*-\[[^\]\s]*\]/g)) {
        if (!allowed.has(m[0])) report(file, `Arbitrary utility outside the allowlist: ${m[0]}`)
      }
    }
  }
}
if (errors.length) { console.error(errors.join('\n')); process.exit(1) }
console.log(`design-policy: clean (${srcDirs.join(', ')} — CSS dimensions, inline styles, colors, font families, radii, shadows and scoped red)`)
