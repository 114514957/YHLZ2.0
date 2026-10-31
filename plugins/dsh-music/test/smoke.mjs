/**
 * Offline checks for dsh-music: paths resolve, the CLI answers, rendering works.
 * Run:  node plugins/dsh-music/test/smoke.mjs
 */

import { existsSync } from 'node:fs'
import { Library, loadConfig, renderInfo, renderList, TOOL_NAMES } from '../lib/library.js'

let failed = 0
function check(name, condition, detail = '') {
  if (condition) {
    console.log(`PASS  ${name}`)
  } else {
    failed += 1
    console.log(`FAIL  ${name}${detail ? ` — ${detail}` : ''}`)
  }
}

const cfg = loadConfig({})
check('python exists', existsSync(cfg.python), cfg.python)
check('cli exists', existsSync(cfg.cli), cfg.cli)

const lib = new Library({})
const tools = lib.tools()
check('four tools', tools.length === 4 && tools.map((t) => t.name).join(',') === TOOL_NAMES.join(','),
  tools.map((t) => t.name).join(','))

const listed = await lib.list({ limit: 3 })
check('list returns rows', listed.count > 0 && listed.count <= 3, `count=${listed.count}`)
check('rows have id+title', listed.songs.every((s) => s.id && s.title),
  JSON.stringify(listed.songs[0] ?? null))
check('render list has a title bracket', renderList(listed.songs).includes('《'))

const first = listed.songs[0]
const detail = await lib.info(first.id)
check('info resolves a file', detail.exists === true, JSON.stringify(detail))
check('render info mentions the path', renderInfo(detail).includes('文件：'))

let threw = false
try {
  await lib.info('this-song-does-not-exist-xyz')
} catch {
  threw = true
}
check('unknown handle throws', threw)

console.log(failed === 0 ? '\nALL PASS' : `\n${failed} FAILED`)
process.exit(failed === 0 ? 0 : 1)
