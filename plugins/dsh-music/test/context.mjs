/**
 * Integration check for lib/index.js: a fake Cordis context must receive four
 * tool registrations, and the tools must be callable end to end.
 * Run:  node plugins/dsh-music/test/context.mjs
 */

import { apply, name } from '../lib/index.js'

let failed = 0
function check(label, condition, detail = '') {
  if (condition) console.log(`PASS  ${label}`)
  else {
    failed += 1
    console.log(`FAIL  ${label}${detail ? ` — ${detail}` : ''}`)
  }
}

const registered = []
const effects = []
const ctx = {
  get: (service) => (service === 'tools' ? { register: (tool) => registered.push(tool) } : undefined),
  effect: (fn) => {
    effects.push(fn)
    fn()
  },
}

const plugin = apply(ctx, {})

check('plugin name', name === 'dsh-music')
check('four tools registered', registered.length === 4, registered.map((t) => t.name).join(','))
check('effects used (Cordis-owned)', effects.length === 4, String(effects.length))
check('apply returns handle', typeof plugin === 'object' && Array.isArray(plugin.registered))

for (const tool of registered) {
  check(`${tool.name}: has description`, typeof tool.description === 'string' && tool.description.length > 10)
  check(`${tool.name}: has parameters object`, tool.parameters?.type === 'object')
  check(`${tool.name}: has execute`, typeof tool.execute === 'function')
  check(`${tool.name}: has output.render`, typeof tool.output?.render === 'function')
}

if (failed === 0) {
  const list = registered.find((t) => t.name === 'music_list')
  const value = await list.execute({ limit: 2 }, {})
  check('music_list executes', typeof value.text === 'string' && value.text.includes('歌库'),
    JSON.stringify(value).slice(0, 120))
  const rendered = list.output.render({}, value)
  check('render returns text parts', Array.isArray(rendered) && rendered[0]?.type === 'text')
}

console.log(failed === 0 ? '\nALL PASS' : `\n${failed} FAILED`)
process.exit(failed === 0 ? 0 : 1)
