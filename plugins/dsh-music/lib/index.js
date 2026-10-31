/**
 * dsh-music — the only DSH-aware file.
 *
 * It registers four model tools and nothing else. Every real operation is a
 * shell-out to `YH/tools/music_cli.py`, which owns the song index
 * (`cache/songs/songs.json`) and reuses `backend/song_library.py`. There is no
 * second implementation of "what songs exist" in JavaScript.
 */

import { Library } from './library.js'

export const name = 'dsh-music'

/**
 * @param {import('@deepseek-ai/cordis').Context} ctx
 * @param {Record<string, unknown>} config bundle-row config (optional)
 */
export function apply(ctx, config) {
  const lib = new Library(config ?? {})
  const registered = []

  const tools = (() => {
    try {
      return ctx.get?.('tools')
    } catch {
      return undefined
    }
  })()

  if (!tools || typeof tools.register !== 'function') {
    log('warn', 'tools service unavailable: dsh-music cannot register its tools on this Harness version')
    return { lib, registered }
  }

  for (const tool of lib.tools()) {
    try {
      const register = () => tools.register(tool)
      if (typeof ctx.effect === 'function') ctx.effect(register)
      else register()
      registered.push(tool.name)
    } catch (error) {
      log('warn', `${tool.name} registration failed: ${error?.message ?? error}`)
    }
  }

  log('info', `dsh-music activated: ${registered.join(', ')}`)
  return { lib, registered }
}

function log(level, message) {
  const line = `[dsh-music] ${message}`
  if (level === 'warn') console.warn(line)
  else console.log(line)
}
