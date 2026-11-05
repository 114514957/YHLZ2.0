#!/usr/bin/env node
/**
 * see_now_bridge — 把 dsh-see-now 当普通 Node 库用，给元亨（Python）一个命令行入口。
 *
 * 为什么要有这一层：dsh-see-now 本体是 DSH 插件（要 Cordis 上下文、sessionController、
 * attachments）。但它的 capture/pipeline/pack/png/tokens 都是纯函数式模块，包本身
 * 不依赖 DSH（package.json 里 dependencies 为 null）。所以元亨不需要 DSH：
 * 直接调这里的 CLI，拿回「一张拼好的 PNG + 帧时间码 + token 估算」。
 *
 * 两个模式：
 *   --probe    合成 3 段画面喂进 pipeline（不碰 ffmpeg），验证打包/编码/token 口径
 *   --capture  真抓屏（需要 ffmpeg；当前本机没有，见 --help 的说明）
 *
 * 输出：最后一行是一行 JSON，便于 Python 侧解析；人看的日志走 stderr。
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const YH_ROOT = resolve(HERE, '..')

// 默认用 research 里解包的 npm 包；正式化时把包放进 YH/vendor/dsh-see-now 并改这里。
const DEFAULT_PKG = resolve(YH_ROOT, 'research', 'seenow-npm', 'package', 'src')

function argOf(argv, name, fallback = undefined) {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}

const argv = process.argv.slice(2)
const mode = argv.includes('--probe') ? 'probe'
  : argv.includes('--raw') ? 'raw'
    : argv.includes('--capture') ? 'capture' : null
const pkgDir = resolve(argOf(argv, '--pkg', DEFAULT_PKG))
const outPath = resolve(argOf(argv, '--out', resolve(YH_ROOT, 'cache', 'tmp', 'see_now.png')))
const quality = argOf(argv, '--quality', 'low')
const seconds = Number(argOf(argv, '--seconds', '6'))
const fps = Number(argOf(argv, '--fps', '12'))
const regionRaw = argOf(argv, '--region', null)
const rawMode = argv.includes('--raw')          // 读字用：原生像素、不缩放不拼图
const ffmpegPath = argOf(argv, '--ffmpeg', process.env.YHLZ_FFMPEG || 'ffmpeg')

const SIZES = {  // 与 runner.js 的 SIZES 同一口径
  low: { long: 798, short: 450 },
  standard: { long: 1050, short: 600 },
  high: { long: 1260, short: 720 },
  ultra: { long: 1596, short: 900 },
}

function log(msg) {
  process.stderr.write(`[see_now_bridge] ${msg}\n`)
}

async function loadModules() {
  const pipeline = await import(`file://${pkgDir}/pipeline.js`)
  const tokens = await import(`file://${pkgDir}/tokens.js`)
  return { createPipeline: pipeline.createPipeline, imageTokens: tokens.imageTokens }
}

function parseRegion(raw) {
  if (!raw || raw === 'off') return null
  const [x, y, w, h] = String(raw).split(',').map(Number)
  if (![x, y, w, h].every((v) => Number.isFinite(v)) || w <= 0 || h <= 0) {
    throw new Error(`--region 需要 "x,y,w,h"，收到：${raw}`)
  }
  return { x, y, w, h }
}

/** 合成画面：纯色块 + 一条随时间移动的亮条，足够触发切点/积分两条判据。 */
function synthFrame(width, height, phase) {
  const buf = Buffer.allocUnsafe(width * height * 3)
  const base = [
    [24, 26, 32], [200, 60, 60], [40, 160, 90], [30, 70, 190], [230, 200, 60], [20, 20, 20],
  ][phase % 6]
  buf.fill(0)
  for (let y = 0; y < height; y += 1) {
    const row = y * width * 3
    for (let x = 0; x < width; x += 1) {
      const i = row + x * 3
      buf[i] = base[0]
      buf[i + 1] = base[1]
      buf[i + 2] = base[2]
    }
  }
  // 一条竖条：位置随相位移动，制造"局部运动"
  const barW = Math.max(8, Math.floor(width / 12))
  const x0 = Math.min(width - barW - 1, Math.floor(((phase * 0.17) % 1) * (width - barW)))
  for (let y = 0; y < height; y += 1) {
    const row = y * width * 3
    for (let x = x0; x < x0 + barW; x += 1) {
      const i = row + x * 3
      buf[i] = 255
      buf[i + 1] = 255
      buf[i + 2] = 255
    }
  }
  return buf
}

async function runProbe() {
  const { createPipeline, imageTokens } = await loadModules()
  const size = SIZES[quality] || SIZES.low
  const width = size.long
  const height = size.short
  const p = createPipeline({ width, height, fps })
  const totalFrames = 36           // 3 秒 @12fps
  const t0 = Date.now()
  for (let k = 0; k < totalFrames; k += 1) {
    // 每 12 帧换一段"画面"，模拟三次切窗口
    const phase = Math.floor(k / 12) * 2
    p.push({ t: k / fps, buf: synthFrame(width, height, phase) })
  }
  const { stats, sheets } = p.finish()
  const ms = Date.now() - t0
  if (!sheets.length) {
    log('probe: pipeline 没有出图（判据把合成帧全滤掉了）')
    console.log(JSON.stringify({ ok: false, mode: 'probe', stats }))
    return 2
  }
  const sheet = sheets[sheets.length - 1]
  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, sheet.png)
  const result = {
    ok: true,
    mode: 'probe',
    png: outPath,
    bytes: sheet.png.length,
    size: [sheet.w, sheet.h],
    tokens: imageTokens(sheet.w, sheet.h),
    frames: sheet.frames.map((f) => ({ t: f.t, tier: f.tier, via: f.via })),
    spans: [sheet.from, sheet.to],
    stats,
    ms,
    ffmpeg: null,
  }
  log(`probe ok: ${sheet.w}x${sheet.h}, ${sheet.frames.length} frames, ${result.tokens} tokens, ${ms}ms`)
  console.log(JSON.stringify(result))
  return 0
}

/** 读字模式：一帧、原生像素、不缩放不拼图。区域越小，字在模型眼里越大。 */
async function runRaw() {
  const region = parseRegion(regionRaw)   // 不给 region = 整屏原生（OCR 用）
  mkdirSync(dirname(outPath), { recursive: true })
  const args = ['-hide_banner', '-v', 'error', '-nostdin',
    '-f', 'gdigrab', '-framerate', '5']
  if (region) {
    args.push('-offset_x', String(region.x), '-offset_y', String(region.y),
              '-video_size', `${region.w}x${region.h}`)
  }
  args.push('-i', 'desktop', '-frames:v', '1', '-y', outPath)
  const started = Date.now()
  const code = await new Promise((resolve) => {
    const child = spawn(ffmpegPath, args, { stdio: ['ignore', 'ignore', 'pipe'] })
    let err = ''
    child.stderr.on('data', (d) => { err += String(d) })
    child.on('error', () => resolve(-1))
    child.on('close', (c) => { if (c !== 0) log(`ffmpeg: ${err.slice(0, 200)}`); resolve(c) })
  })
  if (code !== 0 || !existsSync(outPath)) {
    console.log(JSON.stringify({ ok: false, mode: 'raw', error: `ffmpeg exit=${code}` }))
    return 3
  }
  const png = readFileSync(outPath)
  const w = png.readUInt32BE(16)
  const h = png.readUInt32BE(20)
  const result = { ok: true, mode: 'raw', png: outPath, bytes: png.length,
                   size: [w, h], tokens: null,
                   region: region ? region : 'desktop', ms: Date.now() - started }
  log(`raw ok: ${w}x${h} (${region ? `${region.w}x${region.h} region` : 'full desktop'} native), ${png.length} bytes`)
  console.log(JSON.stringify(result))
  return 0
}

async function runCapture() {
  const { createPipeline, imageTokens } = await loadModules()
  const size = SIZES[quality] || SIZES.low
  const width = size.long
  const height = size.short
  const region = parseRegion(regionRaw)
  const p = createPipeline({ width, height, fps })
  const started = Date.now()
  let frames = 0
  try {
    // 自己拼 ffmpeg 参数（不用上游 captureArgs / spawnFrames）：
    //  Windows 的 gdigrab 输出 bgra，而上游只写 `scale=…`，一旦带 region
    //  就报 "Impossible to convert between the formats"（实测 -22/-40）；
    //  在 -vf 前面补 format=bgra 之后稳定（3 帧 798x450 rgb24 = 3,231,900 B）。
    //  另：region 只能走 gdigrab（ddagrab 不吃 -offset_x/-video_size）。
    const args = ['-hide_banner', '-v', 'error', '-nostdin',
      '-f', 'gdigrab', '-framerate', String(fps)]
    if (region) {
      args.push('-offset_x', String(region.x), '-offset_y', String(region.y),
                '-video_size', `${region.w}x${region.h}`)
    }
    args.push('-i', 'desktop',
              '-vf', `format=bgra,scale=${width}:${height}:flags=area`,
              '-an', '-sn', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-')

    const child = spawn(ffmpegPath, args, { stdio: ['ignore', 'pipe', 'pipe'] })
    const need = width * height * 3
    let pending = Buffer.alloc(0)
    const stopAt = Date.now() + Math.max(1000, seconds * 1000)
    const timer = setTimeout(() => { try { child.kill() } catch { /* ignore */ } }, Math.max(1000, seconds * 1000))

    const done = new Promise((resolve) => {
      child.stdout.on('data', (chunk) => {
        pending = pending.length ? Buffer.concat([pending, chunk]) : chunk
        while (pending.length >= need) {
          const buf = pending.subarray(0, need)
          pending = pending.subarray(need)
          p.push({ t: frames / fps, buf })
          frames += 1
        }
      })
      child.stderr.on('data', (d) => {
        const line = String(d).trim()
        if (line) log(`ffmpeg: ${line.slice(0, 200)}`)
      })
      child.on('error', (err) => { log(`spawn: ${err?.message ?? err}`); resolve({ error: err }) })
      child.on('close', (code) => { clearTimeout(timer); resolve({ code }) })
    })
    const outcome = await done
    if (frames === 0) {
      throw new Error(`ffmpeg 没出帧（exit=${outcome?.code}）`)
    }
  } catch (error) {
    log(`capture failed: ${error?.message ?? error}`)
    console.log(JSON.stringify({
      ok: false, mode: 'capture', error: String(error?.message ?? error),
      hint: '需要一个可用的 ffmpeg：设 YHLZ_FFMPEG 或把 ffmpeg.exe 放进 PATH',
    }))
    return 3
  }
  const { stats, sheets } = p.finish()
  if (!sheets.length) {
    console.log(JSON.stringify({ ok: false, mode: 'capture', frames, stats, error: 'no sheet' }))
    return 2
  }
  const sheet = sheets[sheets.length - 1]
  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, sheet.png)
  const result = {
    ok: true,
    mode: 'capture',
    png: outPath,
    bytes: sheet.png.length,
    size: [sheet.w, sheet.h],
    tokens: imageTokens(sheet.w, sheet.h),
    frames: sheet.frames.map((f) => ({ t: f.t, tier: f.tier, via: f.via })),
    spans: [sheet.from, sheet.to],
    captured: frames,
    stats,
    ms: Date.now() - started,
    ffmpeg: ffmpegPath,
  }
  log(`capture ok: ${sheet.w}x${sheet.h}, ${sheet.frames.length}/${frames} frames kept`)
  console.log(JSON.stringify(result))
  return 0
}

if (!mode) {
  process.stderr.write(
    'usage: node see_now_bridge.mjs --probe|--capture|--raw [--pkg DIR] [--out PNG]\n' +
    '            [--quality low|standard|high|ultra] [--seconds N] [--fps N]\n' +
    '            [--region x,y,w,h] [--ffmpeg PATH]\n' +
    '\n--probe   no ffmpeg (synthetic frames)\n' +
    '--capture ffmpeg, change-filtered sheet\n' +
    '--raw     ffmpeg, ONE native-resolution crop (photographic text reading; needs --region)\n')
  process.exit(1)
}

const code = mode === 'probe' ? await runProbe()
  : mode === 'raw' ? await runRaw()
    : await runCapture()
process.exit(code)
