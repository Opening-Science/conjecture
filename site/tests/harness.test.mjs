// SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation)
// SPDX-License-Identifier: Apache-2.0
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
const scripts = resolve(dirname(fileURLToPath(import.meta.url)), '../scripts')
const THEME = '@theme {\n--color-black: #1d1d1d;\n--font-body: "Selecta", sans-serif;\n--text-base: 1rem;\n--radius-xl: 0.75rem;\n}\n'
function fixture(t, source) {
  const root = mkdtempSync(join(tmpdir(), 'osf-policy-test-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  for (const path of ['app/assets/css', 'app/pages', 'app/components', 'design/components']) mkdirSync(join(root, path), { recursive: true })
  writeFileSync(join(root, 'app/assets/css/main.css'), THEME)
  writeFileSync(join(root, 'design/allowlist.json'), JSON.stringify({ classes: [], cssValues: [] }))
  writeFileSync(join(root, 'app/pages/index.vue'), source)
  return root
}
function run(name, root) {
  return spawnSync(process.execPath, [join(scripts, name), '--root', root], { encoding: 'utf8' })
}
const rejects = [
  ['arbitrary size', '<template><h1 class="text-[123px]">Title</h1></template>', 'design-check.mjs'],
  ['default palette', '<template><h1 class="text-red-500">Title</h1></template>', 'design-check.mjs'],
  ['CSS font size', '<template><h1>Title</h1></template><style>h1 {font-size:123px;}</style>', 'design-policy.mjs'],
  ['CSS padding', '<template><h1>Title</h1></template><style>h1 {padding:1.5rem;}</style>', 'design-policy.mjs'],
  ['CSS line height', '<template><h1>Title</h1></template><style>h1 {line-height:1.7;}</style>', 'design-policy.mjs'],
  ['unadmitted radius', '<template><h1 class="rounded-3xl">Title</h1></template>', 'design-policy.mjs'],
  ['variant radius', '<template><h1 class="md:hover:rounded-t-3xl">Title</h1></template>', 'design-policy.mjs'],
  ['font family', '<template><h1>Title</h1></template><style>h1 {font-family:serif;}</style>', 'design-policy.mjs'],
  ['shadow', '<template><h1>Title</h1></template><style>h1 {box-shadow:1px 1px black;}</style>', 'design-policy.mjs'],
  ['lab link', '<template><a href="/_lab/variant">Lab</a></template>', 'design-check.mjs'],
]
for (const [name, source, script] of rejects) {
  test(`rejects ${name}`, t => {
    const r = run(script, fixture(t, source))
    assert.equal(r.status, 1, r.stdout + r.stderr)
  })
}
test('accepts token CSS and admitted radii', t => {
  const root = fixture(t, '<template><h1 class="text-base text-black rounded-xl">Title</h1></template><style>h1 {font-size:var(--text-base);padding:calc(var(--spacing) * 30);}</style>')
  for (const script of ['design-check.mjs', 'design-policy.mjs']) {
    const r = run(script, root); assert.equal(r.status, 0, r.stderr)
  }
})
test('rejects a component without a spec', t => {
  const root = fixture(t, '<template><h1>Title</h1></template>')
  writeFileSync(join(root, 'app/components/Unapproved.vue'), '<template><div /></template>')
  const r = run('design-check.mjs', root)
  assert.equal(r.status, 1); assert.match(r.stderr, /component without a spec/)
})
test('rejects a stale exception', t => {
  const root = fixture(t, '<template><h1>Title</h1></template>')
  writeFileSync(join(root, 'design/allowlist.json'), JSON.stringify({ classes: [{ value: 'text-[123px]', reason: 'Unused example' }] }))
  const r = run('design-check.mjs', root)
  assert.equal(r.status, 1); assert.match(r.stderr, /no longer used/)
})
for (const [name, html, expected] of [
  ['one h1 and main', '<main><h1>Title</h1></main>', 0],
  ['duplicate h1', '<main><h1>First</h1><h1>Second</h1></main>', 1],
  ['missing main', '<h1>Title</h1>', 1],
  ['lab leak', '<main><h1>Title</h1><a href="/_lab/example">Lab</a></main>', 1],
]) {
  test(`rendered guard: ${name}`, t => {
    const root = fixture(t, '')
    writeFileSync(join(root, 'index.html'), html)
    const r = spawnSync(process.execPath, [join(scripts, 'output-check.mjs'), root], { encoding: 'utf8' })
    assert.equal(r.status, expected, r.stderr)
  })
}

// ---------------------------------------------------------------------------
// Astro support. An Astro project keeps the copied harness tree at app/ so the
// unmodified, hash-pinned design-check.mjs still governs it, and adds its own
// routes under src/. design-policy.mjs must therefore scan BOTH directories.

function astroFixture(t, pages, allowlist = { classes: [], cssValues: [] }) {
  const root = mkdtempSync(join(tmpdir(), 'osf-astro-test-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  for (const path of ['app/assets/css', 'src/pages/_lab', 'design']) mkdirSync(join(root, path), { recursive: true })
  writeFileSync(join(root, 'app/assets/css/main.css'), THEME)
  writeFileSync(join(root, 'design/allowlist.json'), JSON.stringify(allowlist))
  for (const [name, source] of Object.entries(pages)) {
    mkdirSync(dirname(join(root, name)), { recursive: true })
    writeFileSync(join(root, name), source)
  }
  return root
}
function runWith(script, root, ...extra) {
  return spawnSync(process.execPath, [join(scripts, script), '--root', root, ...extra], { encoding: 'utf8' })
}

for (const [name, source] of [
  ['CSS dimension in an .astro style block', '<h1>T</h1><style>h1 {font-size:42px;}</style>'],
  ['unadmitted radius in an .astro template', '<div class="rounded-3xl">T</div>'],
  ['reserved red token in an .astro template', '<h1 class="text-red-500">T</h1>'],
  ['unadmitted font family in an .astro style block', '<h1>T</h1><style>h1 {font-family:serif;}</style>'],
]) {
  test(`rejects ${name}`, t => {
    const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }))
    assert.equal(r.status, 1, r.stdout + r.stderr)
    assert.match(r.stderr, /index\.astro/)
  })
}

test('accepts a token-only .astro page', t => {
  const source = '---\nconst t = "T"\n---\n<h1 class="text-base text-black rounded-xl">{t}</h1><style>h1 {font-size:var(--text-base);}</style>'
  const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }))
  assert.equal(r.status, 0, r.stderr)
})

test('scans src/ even when app/ also exists', t => {
  // Defaulting to the first conventional directory would leave an Astro
  // project's routes silently unchecked.
  const root = astroFixture(t, { 'src/pages/index.astro': '<div class="rounded-3xl">T</div>' })
  const r = run('design-policy.mjs', root)
  assert.equal(r.status, 1, r.stdout)
  assert.match(r.stderr, /src\/pages\/index\.astro/)
})

test('exempts src/pages/_lab/ from the .astro checks', t => {
  const root = astroFixture(t, { 'src/pages/_lab/variant.astro': '<div class="rounded-3xl" style="padding:2rem">T</div>' })
  const r = run('design-policy.mjs', root)
  assert.equal(r.status, 0, r.stderr)
})

// Static inline styles bypass the class vocabulary in both file types. A
// dynamic binding (:style, style={…}) is out of reach and needs rendered review.
for (const [name, file, source] of [
  ['an .astro template', 'src/pages/index.astro', '<div style="padding: 2rem">T</div>'],
  ['a .vue template', 'src/pages/index.vue', '<template><div style="font-size: 19px">T</div></template>'],
]) {
  test(`rejects a raw inline style in ${name}`, t => {
    const r = run('design-policy.mjs', astroFixture(t, { [file]: source }))
    assert.equal(r.status, 1, r.stdout + r.stderr)
  })
}

// Discriminating pair: the binding carries a declaration the static form is
// rejected for, so only the :style / v-bind:style guard can tell them apart.
for (const [name, source, expected] of [
  ['a :style binding', '<template><div :style="{ padding: 2 }">T</div></template>', 0],
  ['a v-bind:style binding', '<template><div v-bind:style="padding: 2rem">T</div></template>', 0],
  ['the equivalent static attribute', '<template><div style="padding: 2rem">T</div></template>', 1],
]) {
  test(`dynamic style handling: ${name}`, t => {
    const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.vue': source }))
    assert.equal(r.status, expected, r.stdout + r.stderr)
  })
}

test('checks an inline style whose value contains the other quote', t => {
  const source = `<div style="font-family: 'Comic Sans MS', cursive; padding: 42px">T</div>`
  const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }))
  assert.equal(r.status, 1, r.stdout)
  assert.match(r.stderr, /font family/)
  assert.match(r.stderr, /padding/)
})

test('honours an admitted cssValues entry for an inline style', t => {
  const allow = { classes: [], cssValues: [{ value: 'max-width: 65ch', reason: 'Legacy embed' }] }
  const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': '<div style="max-width: 65ch">T</div>' }, allow))
  assert.equal(r.status, 0, r.stderr)
})

// design-check.mjs owns app/. Reporting inline styles there too would make the
// two scanners disagree, and would newly fail existing Nuxt projects that the
// upstream scanner passes. Tightening app/ is a decision for design-check, not
// a side effect of adding Astro support. `font-family: serif` is the
// discriminating case: design-check ignores it, this scanner would not.
for (const [name, body, allow] of [
  // design-check fails unused allowlist entries, so each case carries only what it needs.
  ['a declaration the upstream scanner ignores', 'font-family: serif', { classes: [], cssValues: [] }],
  ['a declaration the upstream scanner admits', 'max-width: 65ch', { classes: [], cssValues: [{ value: 'max-width: 65ch', reason: 'Legacy embed' }] }],
]) {
  test(`leaves inline styles under app/ to the upstream scanner: ${name}`, t => {
    const root = astroFixture(t, { 'app/pages/index.vue': `<template><div style="${body}">T</div></template>` }, allow)
    assert.equal(run('design-policy.mjs', root).status, 0, 'design-policy must not report inside app/')
    assert.equal(run('design-check.mjs', root).status, 0, 'design-check must agree')
  })
}

test('rejects a lab reference from shipping code outside app/', t => {
  const source = "---\nimport Draft from './_lab/Draft.astro'\n---\n<main><h1>T</h1><Draft /></main>"
  const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }))
  assert.equal(r.status, 1, r.stdout)
  assert.match(r.stderr, /design lab/)
})

for (const [name, source, allow, expected] of [
  ['an arbitrary radius outside app/', '<div class="rounded-[13px]">T</div>', undefined, 1],
  ['an admitted arbitrary radius', '<div class="rounded-[9px]">T</div>', { classes: [{ value: 'rounded-[9px]', reason: 'production-verbatim' }], cssValues: [] }, 0],
]) {
  test(`arbitrary radius: ${name}`, t => {
    // Under app/ these are the upstream allowlist scanner's business; outside
    // it nothing else runs, so deferring would let them ship unchecked.
    const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }, allow))
    assert.equal(r.status, expected, r.stdout + r.stderr)
  })
}

for (const [name, extra] of [
  ['a source directory that does not exist', ['--src', 'srcc']],
  ['a flag given no value', ['--src', '--root']],
  ['a source directory outside the project', ['--src', '../elsewhere']],
]) {
  test(`refuses to report clean for ${name}`, t => {
    const root = astroFixture(t, { 'src/pages/index.astro': '<div class="rounded-3xl">T</div>' })
    const r = runWith('design-policy.mjs', root, ...extra)
    assert.notEqual(r.status, 0, r.stdout + r.stderr)
  })
}

for (const form of ['app,src', 'app,src/', './src']) {
  test(`keeps the lab exempt for --src ${form}`, t => {
    const root = astroFixture(t, { 'src/pages/_lab/variant.astro': '<div class="rounded-3xl" style="padding: 42px">T</div>' })
    const r = runWith('design-policy.mjs', root, '--src', form)
    assert.equal(r.status, 0, r.stdout + r.stderr)
  })
}

test('accepts an explicit --theme outside the default location', t => {
  const root = astroFixture(t, { 'src/pages/index.astro': '<h1 class="rounded-xl">T</h1>', 'design/theme.css': THEME })
  const r = runWith('design-policy.mjs', root, '--src', 'src', '--theme', 'design/theme.css')
  assert.equal(r.status, 0, r.stdout + r.stderr)
})

test('a Nuxt project with only app/ resolves exactly as before', t => {
  // Pins the compatibility claim: no src/, default flags, same violation.
  const root = mkdtempSync(join(tmpdir(), 'osf-nuxt-test-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  for (const path of ['app/assets/css', 'app/pages', 'design']) mkdirSync(join(root, path), { recursive: true })
  writeFileSync(join(root, 'app/assets/css/main.css'), THEME)
  writeFileSync(join(root, 'design/allowlist.json'), JSON.stringify({ classes: [], cssValues: [] }))
  writeFileSync(join(root, 'app/pages/index.vue'), '<template><h1 class="rounded-3xl">T</h1></template>')
  const r = run('design-policy.mjs', root)
  assert.equal(r.status, 1, r.stdout)
  assert.match(r.stdout + r.stderr, /clean \(app\b|rounded-3xl/)
})

// Colours and arbitrary utilities are design-check's checks (a)-(c). It reads
// app/ only, so outside it these would otherwise ship unvetted.
for (const [name, source] of [
  ['a hex literal in a template', '<div style="color: #ff00ff">T</div>'],
  ['a hex literal in an svg attribute', '<svg><rect fill="#00ff00" /></svg>'],
  ['a colour function', '<div><style>p {color: rgb(1 2 3);}</style></div>'],
  ['a CSS named colour', '<div><style>p {color: rebeccapurple;}</style></div>'],
  ['an arbitrary utility', '<div class="text-[123px]">T</div>'],
]) {
  test(`rejects ${name} outside app/`, t => {
    const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }))
    assert.equal(r.status, 1, r.stdout + r.stderr)
  })
}

test('admits a colour and an arbitrary utility through the allowlist', t => {
  const allow = {
    classes: [{ value: 'grid-cols-[10rem_1fr]', reason: 'Ledger row grid' }],
    cssValues: [{ value: '#1d1d1d', reason: 'Select arrow data URI' }],
  }
  const source = '<div class="grid-cols-[10rem_1fr]" data-icon="#1d1d1d">T</div>'
  const r = run('design-policy.mjs', astroFixture(t, { 'src/pages/index.astro': source }, allow))
  assert.equal(r.status, 0, r.stdout + r.stderr)
})

test('leaves colours under app/ to the upstream scanner', t => {
  // design-check reports this one; design-policy must not double-report it.
  const root = astroFixture(t, { 'app/pages/index.vue': '<template><div style="color: #ff00ff">T</div></template>' })
  assert.equal(run('design-policy.mjs', root).status, 0, 'design-policy must stay out of app/')
  assert.equal(run('design-check.mjs', root).status, 1, 'design-check must catch it')
})
