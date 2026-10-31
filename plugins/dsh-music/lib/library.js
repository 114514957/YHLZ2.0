/**
 * dsh-music — library layer.
 *
 * Everything here is plain Node: resolve paths, call `music_cli.py`, turn its
 * output into tool values. No DSH imports, so the file can be unit-tested with
 * `node test/smoke.mjs`.
 */

import { execFile } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const PLUGIN_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')
/** plugins/dsh-music -> YH */
export const YH_ROOT = resolve(PLUGIN_DIR, '..', '..')

const DEFAULTS = {
  python: resolve(YH_ROOT, '.venv', 'Scripts', 'python.exe'),
  cli: resolve(YH_ROOT, 'tools', 'music_cli.py'),
  cwd: YH_ROOT,
  timeouts: { list: 15000, info: 15000, play: 15000, send: 60000 },
}

const TOOL_LIST = 'music_list'
const TOOL_INFO = 'music_info'
const TOOL_PLAY = 'music_play'
const TOOL_SEND = 'music_send'

function readFileJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return undefined
  }
}

/** Merge config.json (plugin dir) with the bundle-row config; row wins. */
export function loadConfig(rowConfig = {}) {
  const file = readFileJson(resolve(PLUGIN_DIR, 'config.json')) ?? {}
  const merged = { ...DEFAULTS, ...file, ...rowConfig }
  merged.timeouts = { ...DEFAULTS.timeouts, ...(file.timeouts ?? {}), ...(rowConfig.timeouts ?? {}) }
  if (!isAbsolute(merged.python)) merged.python = resolve(YH_ROOT, merged.python)
  if (!isAbsolute(merged.cli)) merged.cli = resolve(YH_ROOT, merged.cli)
  return merged
}

export class Library {
  constructor(rowConfig = {}) {
    this.cfg = loadConfig(rowConfig)
  }

  /** Run the python CLI; resolves stdout, rejects with a readable message. */
  run(args, kind = 'list') {
    const timeout = Number(this.cfg.timeouts?.[kind] ?? 15000)
    return new Promise((resolvePromise, reject) => {
      execFile(
        this.cfg.python,
        [this.cfg.cli, ...args],
        { cwd: this.cfg.cwd, timeout, windowsHide: true, maxBuffer: 8 * 1024 * 1024 },
        (error, stdout, stderr) => {
          const out = String(stdout ?? '').trim()
          const err = String(stderr ?? '').trim()
          if (error) {
            const reason = err || out || error.message
            reject(new Error(`music_cli ${args[0]} failed: ${reason}`))
            return
          }
          resolvePromise({ out, err })
        },
      )
    })
  }

  async list({ query = '', limit = 20 } = {}) {
    const q = String(query ?? '').trim()
    const n = Math.max(1, Math.min(200, Number(limit) || 20))
    const args = ['list', '--json', '--limit', String(n)]
    if (q) args.push('--query', q)
    const { out } = await this.run(args, 'list')
    const songs = JSON.parse(out || '[]')
    return { count: songs.length, songs, query: q }
  }

  async info(handle) {
    const { out } = await this.run(['info', String(handle), '--json'], 'info')
    return JSON.parse(out || '{}')
  }

  async play(handle) {
    const { out } = await this.run(['play', String(handle)], 'play')
    return { output: out }
  }

  async send(handle) {
    const { out } = await this.run(['send', String(handle)], 'send')
    return { output: out }
  }

  /** ToolDefinitions handed to ctx.tools.register(). */
  tools() {
    const lib = this
    return [
      {
        name: TOOL_LIST,
        description:
          '列出元亨歌库里的成品歌（按时间倒序）。可用 query 过滤标题/标签/来源，limit 限制条数。' +
          'handle 可用的形式：歌曲 id（song_2026...）、列表序号、标题片段、标签。',
        parameters: {
          type: 'object',
          properties: {
            query: { type: 'string', description: '过滤词：标题片段、标签或来源，留空列全部' },
            limit: { type: 'integer', minimum: 1, maximum: 200, description: '最多返回几首，默认 20' },
          },
        },
        output: {
          schema: {
            type: 'object',
            properties: {
              count: { type: 'integer' },
              text: { type: 'string' },
            },
            required: ['count', 'text'],
          },
          render: (_args, value) => [{ type: 'text', text: String(value?.text ?? '') }],
        },
        timeoutMs: 20000,
        isConcurrencySafe: () => true,
        async execute(args) {
          const { count, songs, query } = await lib.list(args ?? {})
          return { count, text: renderList(songs, query) }
        },
      },
      {
        name: TOOL_INFO,
        description: '看某首歌的详情：标题、id、文件绝对路径、标签、创建时间、来源。',
        parameters: {
          type: 'object',
          properties: { handle: { type: 'string', description: '歌曲 id、序号、标题片段或标签' } },
          required: ['handle'],
        },
        output: {
          schema: {
            type: 'object',
            properties: { text: { type: 'string' } },
            required: ['text'],
          },
          render: (_args, value) => [{ type: 'text', text: String(value?.text ?? '') }],
        },
        timeoutMs: 20000,
        isConcurrencySafe: () => true,
        async execute(args) {
          const item = await lib.info(args?.handle ?? '')
          return { text: renderInfo(item) }
        },
      },
      {
        name: TOOL_PLAY,
        description: '在本机扬声器上播放一首成品歌（立刻返回，不等待播完）。',
        parameters: {
          type: 'object',
          properties: { handle: { type: 'string', description: '歌曲 id、序号、标题片段或标签' } },
          required: ['handle'],
        },
        output: {
          schema: {
            type: 'object',
            properties: { text: { type: 'string' } },
            required: ['text'],
          },
          render: (_args, value) => [{ type: 'text', text: String(value?.text ?? '') }],
        },
        timeoutMs: 20000,
        isConcurrencySafe: () => false,
        async execute(args) {
          const { output } = await lib.play(args?.handle ?? '')
          return { text: output || '已发起播放。' }
        },
      },
      {
        name: TOOL_SEND,
        description:
          '把一首成品歌通过 QQ 私聊发给老爹（需要 NapCat 在线；成品歌才可发，生成只在工作台做）。',
        parameters: {
          type: 'object',
          properties: { handle: { type: 'string', description: '歌曲 id、序号、标题片段或标签' } },
          required: ['handle'],
        },
        output: {
          schema: {
            type: 'object',
            properties: { text: { type: 'string' } },
            required: ['text'],
          },
          render: (_args, value) => [{ type: 'text', text: String(value?.text ?? '') }],
        },
        timeoutMs: 70000,
        isConcurrencySafe: () => false,
        async execute(args) {
          const { output } = await lib.send(args?.handle ?? '')
          return { text: output || '已发起发送。' }
        },
      },
    ]
  }
}

export function renderList(songs, query = '') {
  const items = Array.isArray(songs) ? songs : []
  if (items.length === 0) {
    return query ? `歌库里没有匹配「${query}」的歌。` : '歌库是空的。'
  }
  const lines = [`歌库共 ${items.length} 首${query ? `（匹配「${query}」）` : ''}：`]
  items.forEach((song, index) => {
    const tags = song.tags?.length ? `  #${song.tags.join(' #')}` : ''
    const created = song.created ? `  ${song.created}` : ''
    const missing = song.exists ? '' : '  [文件缺失]'
    lines.push(`${index + 1}. 《${song.title ?? song.id}》  ${song.id}${created}${tags}${missing}`)
  })
  return lines.join('\n')
}

export function renderInfo(item) {
  if (!item || !item.id) return '没找到这首歌。'
  const tags = item.tags?.length ? item.tags.join('、') : '（无）'
  const lines = [
    `《${item.title ?? item.id}》  ${item.id}`,
    `  文件：${item.path ?? '（缺失）'}`,
    `  标签：${tags}`,
    `  创建：${item.created || '—'}   来源：${item.source || '—'}   对象：${item.target || '—'}`,
  ]
  if (item.path_state === 'remapped') lines.push('  （索引里是旧路径，实际文件在重排后的位置）')
  return lines.join('\n')
}

export const TOOL_NAMES = [TOOL_LIST, TOOL_INFO, TOOL_PLAY, TOOL_SEND]
export { existsSync }
