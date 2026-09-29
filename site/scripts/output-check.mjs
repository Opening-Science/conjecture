// SPDX-FileCopyrightText: 2026 Open Science Stiftung (Open Science Foundation)
// SPDX-License-Identifier: Apache-2.0
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { resolve, join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const root = process.argv[2] ? resolve(process.argv[2]) : resolve(dirname(fileURLToPath(import.meta.url)), '../.output/public')
if (!existsSync(root)) throw new Error('Missing static output')
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)])
}
const errors = []; let pages = 0
for (const file of walk(root)) {
  const name = relative(root, file).replaceAll('\\', '/')
  if (/(^|\/)_(?:lab)(\/|\.)/.test(name)) errors.push(`Lab output: ${name}`)
  if (!/\.(?:html|js|json|xml|txt)$/.test(file)) continue
  const text = readFileSync(file, 'utf8')
  if (/\/_lab(?:\/|["'])/.test(text) || text.includes('__OSF_LAB_PROBE__')) errors.push(`Lab reference: ${name}`)
  if (!file.endsWith('.html') || ['200.html', '404.html'].includes(name)) continue
  pages++
  const h1 = (text.match(/<h1\b/gi) ?? []).length
  const main = (text.match(/<main\b/gi) ?? []).length
  if (h1 !== 1 || main !== 1) errors.push(`${name}: expected one h1 and main, found ${h1} and ${main}`)
}
if (!pages) errors.push('No rendered content pages found')
if (errors.length) { console.error(errors.join('\n')); process.exit(1) }
console.log(`output-check: ${pages} content pages, one h1/main each, no lab output`)
