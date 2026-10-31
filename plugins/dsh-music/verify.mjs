#!/usr/bin/env node
/**
 * dsh-music verifier — checks an installed profile without booting DSH.
 *
 *   node plugins/dsh-music/verify.mjs                  # desktop profile
 *   node plugins/dsh-music/verify.mjs --profile headless
 *   node plugins/dsh-music/verify.mjs --profile-dir <dir>
 *
 * It answers: is the plugin wired into the profile, does the junction resolve,
 * and does the underlying CLI still work? It cannot call the tool through DSH —
 * that needs a booted harness (GUI: press F5 and ask; CLI: `dsh headless "…"`).
 */

import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN_DIR = resolve(dirname(fileURLToPath(import.meta.url)))
const argv = process.argv.slice(2)
const argOf = (name) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : undefined
}
const profile = argOf('--profile') ?? 'desktop'
const profileDir = argOf('--profile-dir')
  ? resolve(argOf('--profile-dir'))
  : join(homedir(), '.dsh', 'profiles', profile)
const linkPath = join(profileDir, 'node_modules', 'dsh-music')

let bad = 0
const ok = (label, detail = '') => console.log(`OK    ${label}${detail ? ` — ${detail}` : ''}`)
const no = (label, detail = '') => {
  bad += 1
  console.log(`MISS  ${label}${detail ? ` — ${detail}` : ''}`)
}

console.log(`profile : ${profileDir}`)
console.log(`plugin  : ${PLUGIN_DIR}\n`)

const pkgPath = join(profileDir, 'package.json')
/** The profile may keep the long path while this file resolved a short (8.3)
 *  one, and realpathSync does NOT expand 8.3 — compare NTFS file ids instead. */
const sameDir = (a, b) => {
  try {
    const ia = statSync(a, { bigint: true }).ino
    const ib = statSync(b, { bigint: true }).ino
    return ia !== 0n && ia === ib
  } catch {
    return a.toLowerCase() === b.toLowerCase()
  }
}
if (!existsSync(pkgPath)) {
  no('profile package.json', pkgPath)
} else {
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'))
  const dep = String(pkg.dependencies?.['dsh-music'] ?? '')
  const depPath = dep.startsWith('link:') ? dep.slice(5) : dep
  if (depPath && sameDir(depPath, PLUGIN_DIR)) ok('dependency row')
  else no('dependency row', dep || 'null')
  if (pkg.dsh?.profile?.bundles?.includes('dsh-music')) ok('bundle row')
  else no('bundle row')
}

if (existsSync(join(linkPath, 'package.json'))) {
  const viaLink = readFileSync(join(linkPath, 'package.json'), 'utf8')
  const direct = readFileSync(join(PLUGIN_DIR, 'package.json'), 'utf8')
  if (viaLink === direct) ok('node_modules junction')
  else no('node_modules junction', 'resolves to a different package')
} else {
  no('node_modules junction', linkPath)
}

const py = join(PLUGIN_DIR, '..', '..', '.venv', 'Scripts', 'python.exe')
const cli = join(PLUGIN_DIR, '..', '..', 'tools', 'music_cli.py')
if (existsSync(py) && existsSync(cli)) {
  try {
    const out = execFileSync(py, [cli, 'list', '--limit', '1', '--json'], {
      cwd: resolve(PLUGIN_DIR, '..', '..'),
      timeout: 20000,
      encoding: 'utf8',
    }).trim()
    const songs = JSON.parse(out || '[]')
    ok('cli answers', `${songs.length} song(s) in the sample`)
  } catch (error) {
    no('cli answers', String(error?.message ?? error).slice(0, 160))
  }
} else {
  no('cli / python present')
}

console.log(
  bad === 0
    ? '\nWIRING OK — now boot DSH (GUI: press F5) and ask: 列一下歌库'
    : `\n${bad} problem(s). Run: node plugins/dsh-music/install.mjs [--profile ${profile}]`,
)
process.exit(bad === 0 ? 0 : 1)
