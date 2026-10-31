#!/usr/bin/env node
/**
 * dsh-music installer — wires this plugin into a DSH profile.
 *
 *   node plugins/dsh-music/install.mjs                 # desktop profile
 *   node plugins/dsh-music/install.mjs --profile web
 *   node plugins/dsh-music/install.mjs --dry-run       # show the plan, touch nothing
 *   node plugins/dsh-music/install.mjs --uninstall
 *
 * What it changes (all inside your DSH profile, all backed up first):
 *   1. profiles/<p>/package.json  dependencies["dsh-music"] = "link:<plugin dir>"
 *   2. profiles/<p>/package.json  dsh.profile.bundles  += "dsh-music"
 *   3. profiles/<p>/node_modules/dsh-music  ->  junction to <plugin dir>
 *
 * The junction matters: DSH resolves the bundle by bare package name, so the
 * package has to be visible from the profile's node_modules. Nothing is copied.
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN_DIR = resolve(dirname(fileURLToPath(import.meta.url)))
const PKG_NAME = 'dsh-music'

const argv = process.argv.slice(2)
const dryRun = argv.includes('--dry-run')
const uninstall = argv.includes('--uninstall')
const argOf = (name) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : undefined
}
const profile = argOf('--profile') ?? 'desktop'

const profileDir = argOf('--profile-dir')
  ? resolve(argOf('--profile-dir'))
  : join(homedir(), '.dsh', 'profiles', profile)
const pkgPath = join(profileDir, 'package.json')
const linkPath = join(profileDir, 'node_modules', PKG_NAME)

function fail(message) {
  console.error(`[dsh-music] ${message}`)
  process.exit(1)
}

function ok(message) {
  console.log(`[dsh-music] ${message}`)
}

if (!existsSync(pkgPath)) fail(`profile not found: ${pkgPath}`)

const raw = readFileSync(pkgPath, 'utf8')
let pkg
try {
  pkg = JSON.parse(raw)
} catch (error) {
  fail(`profile package.json is not valid JSON: ${error.message}`)
}

const before = JSON.stringify(pkg)
pkg.dependencies = pkg.dependencies ?? {}
pkg.dsh = pkg.dsh ?? {}
pkg.dsh.profile = pkg.dsh.profile ?? {}
pkg.dsh.profile.bundles = pkg.dsh.profile.bundles ?? []

const hasDep = Object.prototype.hasOwnProperty.call(pkg.dependencies, PKG_NAME)
const hasBundle = pkg.dsh.profile.bundles.includes(PKG_NAME)

if (uninstall) {
  if (hasDep) delete pkg.dependencies[PKG_NAME]
  pkg.dsh.profile.bundles = pkg.dsh.profile.bundles.filter((b) => b !== PKG_NAME)
  ok(`${dryRun ? '[dry-run] would remove' : 'removing'} dependency + bundle row`)
  if (!dryRun) {
    backup(pkgPath)
    writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf8')
    if (existsSync(linkPath)) rmSync(linkPath, { recursive: true, force: true })
    ok('removed. Restart DSH (or press F5) to unload the plugin.')
  }
  process.exit(0)
}

// ---- plan -------------------------------------------------------------------
pkg.dependencies[PKG_NAME] = `link:${PLUGIN_DIR}`
if (!hasBundle) pkg.dsh.profile.bundles.push(PKG_NAME)
const changed = JSON.stringify(pkg) !== before

ok(`profile          : ${profileDir}`)
ok(`plugin dir       : ${PLUGIN_DIR}`)
ok(`dependency       : ${hasDep ? 'already present (link will be refreshed)' : 'will add'} link:${PLUGIN_DIR}`)
ok(`bundle row       : ${hasBundle ? 'already present' : 'will add'} ${PKG_NAME}`)
ok(`node_modules link: ${existsSync(linkPath) ? 'exists (will verify)' : 'will create junction'}`)

if (dryRun) {
  ok('dry-run: nothing written')
  process.exit(0)
}

if (changed) {
  backup(pkgPath)
  writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n', 'utf8')
  ok('profile package.json updated (backup kept next to it)')
} else {
  ok('profile package.json already up to date')
}

mkdirSync(join(profileDir, 'node_modules'), { recursive: true })
try {
  if (existsSync(linkPath)) rmSync(linkPath, { recursive: true, force: true })
  symlinkSync(PLUGIN_DIR, linkPath, 'junction')
} catch (error) {
  fail(`could not create the junction ${linkPath}: ${error.message}（如果 DSH 正在运行，先关掉再试）`)
}

// ---- verify -----------------------------------------------------------------
const reread = JSON.parse(readFileSync(pkgPath, 'utf8'))
const problems = []
// 8.3 short paths survive in package.json verbatim, so compare file ids, not
// strings; a fresh write uses whatever form this process resolved.
const sameDir = (a, b) => {
  try {
    const ia = statSync(a, { bigint: true }).ino
    const ib = statSync(b, { bigint: true }).ino
    return ia !== 0n && ia === ib
  } catch {
    return String(a).toLowerCase() === String(b).toLowerCase()
  }
}
const depRaw = String(reread.dependencies?.[PKG_NAME] ?? '')
const depPath = depRaw.startsWith('link:') ? depRaw.slice(5) : depRaw
if (!depPath || !sameDir(depPath, PLUGIN_DIR)) problems.push('dependency missing')
if (!reread.dsh?.profile?.bundles?.includes(PKG_NAME)) problems.push('bundle row missing')
// Windows junctions are mount points: realpathSync() on them returns the link
// path itself, so prove the link by reading a file *through* it.
try {
  const viaLink = readFileSync(join(linkPath, 'package.json'), 'utf8')
  const direct = readFileSync(join(PLUGIN_DIR, 'package.json'), 'utf8')
  if (viaLink !== direct) problems.push('junction does not resolve to this plugin')
} catch {
  problems.push('junction unreadable')
}
if (!existsSync(join(PLUGIN_DIR, 'lib', 'index.js'))) problems.push('lib/index.js missing')

if (problems.length > 0) fail(`verification failed: ${problems.join('; ')}`)

ok('verified: dependency + bundle row + junction')
ok('next: restart DSH (or press F5), then ask the model to call music_list')

function backup(path) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const dir = join(dirname(path), `_backup-${PKG_NAME}-${stamp}`)
  mkdirSync(dir, { recursive: true })
  copyFileSync(path, join(dir, 'package.json'))
  ok(`backup           : ${dir}`)
}
