#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MIDI -> WAV 渲染器：直接读 Windows 自带的 DLS 音色库（gm.dls）。

不依赖任何第三方音源、不联网、不开 DAW：
    python tools/dls_render.py song.mid -o out.wav
    python tools/dls_render.py --list                 # 列 128 个 GM 音色

原理：解析 DLS2（乐器 -> 区域 -> 波形采样 + 循环点），按 MIDI 事件做变调采样
播放与包络，混成 44.1k 立体声。够搭编曲结构、听和声与节奏；音色是九十年代
GS 波表，不适合当成品母带。

2026-10-26 利贞建。台账见 docs/上下文台账.md。
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

DEFAULT_DLS = Path(r"C:\Windows\System32\drivers\gm.dls")


# --------------------------------------------------------------------------
# RIFF / DLS
# --------------------------------------------------------------------------
def _chunks(buf: bytes, start: int, end: int):
    off = start
    while off + 8 <= end:
        cid = buf[off:off + 4]
        size = struct.unpack("<I", buf[off + 4:off + 8])[0]
        yield cid, off + 8, size
        off += 8 + size + (size & 1)


@dataclass
class Region:
    key_lo: int
    key_hi: int
    vel_lo: int
    vel_hi: int
    unity: int
    fine: int
    atten: int
    loop_start: int
    loop_len: int
    table: int


@dataclass
class Instrument:
    regions: list[Region] = field(default_factory=list)
    name: str = ""


@dataclass
class Wave:
    data: np.ndarray  # float32 mono, -1..1
    sr: int


class DLS:
    def __init__(self, path: Path):
        self.buf = path.read_bytes()
        buf = self.buf
        if buf[:4] != b"RIFF" or buf[8:12] != b"DLS ":
            raise ValueError("not a DLS file: %s" % path)
        self.root = list(_chunks(buf, 12, len(buf)))
        self.wvpl_data = None
        self.ptbl: list[int] = []
        self.instruments: list[Instrument] = []
        self.waves: dict[int, Wave] = {}
        self._parse()

    def _find(self, cid, chunks=None, type_tag=None):
        for c, body, size in (chunks or self.root):
            if c == cid and (type_tag is None or self.buf[body:body + 4] == type_tag):
                return body, size
        return None

    def _parse(self):
        buf = self.buf
        wv = self._find(b"LIST", type_tag=b"wvpl")
        if wv is None:
            raise ValueError("no wvpl")
        self.wvpl_data = wv[0] + 4

        pt = self._find(b"ptbl")
        if pt is None:
            raise ValueError("no ptbl")
        body, size = pt
        n = (size - 8) // 4
        self.ptbl = list(struct.unpack("<%dI" % n, buf[body + 8:body + 8 + 4 * n]))

        lins = self._find(b"LIST", type_tag=b"lins")
        if lins is None:
            raise ValueError("no lins")
        for cid, b, s in _chunks(buf, lins[0] + 4, lins[0] + lins[1]):
            if cid != b"LIST" or buf[b:b + 4] != b"ins ":
                continue
            self.instruments.append(self._parse_instrument(b + 4, b + s))

    def _parse_instrument(self, start, end) -> Instrument:
        buf = self.buf
        inst = Instrument()
        for cid, b, s in _chunks(buf, start, end):
            if cid == b"LIST" and buf[b:b + 4] == b"lrgn":
                for cid2, b2, s2 in _chunks(buf, b + 4, b + s):
                    if cid2 == b"rgn ":
                        inst.regions.append(self._parse_region(b2, b2 + s2))
                    elif cid2 == b"LIST" and buf[b2:b2 + 4] == b"rgn ":
                        inst.regions.append(self._parse_region(b2 + 4, b2 + s2))
            elif cid == b"LIST" and buf[b:b + 4] == b"INFO":
                for cid3, b3, s3 in _chunks(buf, b + 4, b + s):
                    if cid3 == b"INAM":
                        inst.name = buf[b3:b3 + s3].split(b"\x00")[0].decode("latin1", "replace")
        return inst

    def _parse_region(self, start, end) -> Region:
        buf = self.buf
        kl = kh = 0
        vl, vh = 0, 127
        unity, fine, atten = 60, 0, 0
        loop_start = loop_len = 0
        table = 0
        for cid, b, s in _chunks(buf, start, end):
            if cid == b"rgnh" and s >= 12:
                kl, kh, vl, vh, _opt, _kg = struct.unpack("<HHHHHH", buf[b:b + 12])
            elif cid == b"wsmp" and s >= 16:
                _cb, unity, fine, atten, _flags, nloop = struct.unpack("<IHHII", buf[b:b + 16])
                if nloop and s >= 32:
                    _lcb, _ltype, loop_start, loop_len = struct.unpack("<IIII", buf[b + 16:b + 32])
            elif cid == b"wlnk" and s >= 12:
                _o, _pg, _ch, table = struct.unpack("<HHII", buf[b:b + 12])
        return Region(kl, kh, vl, vh, unity, fine, atten, loop_start, loop_len, table)

    def wave(self, table: int) -> Wave | None:
        if table in self.waves:
            return self.waves[table]
        if table < 0 or table >= len(self.ptbl):
            return None
        w = self.wvpl_data + self.ptbl[table]
        buf = self.buf
        if buf[w:w + 4] != b"LIST" or buf[w + 8:w + 12] != b"wave":
            return None
        size = struct.unpack("<I", buf[w + 4:w + 8])[0]
        fmt = None
        raw = None
        for cid, b, s in _chunks(buf, w + 12, w + 8 + size):
            if cid == b"fmt ":
                fmt = struct.unpack("<HHIIHH", buf[b:b + 16])
            elif cid == b"data":
                raw = buf[b:b + s]
        if fmt is None or raw is None:
            return None
        tag, ch, sr, _avg, align, bits = fmt
        if tag != 1:  # 只吃 PCM
            return None
        if bits == 16:
            a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif bits == 8:
            a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            return None
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        wv = Wave(a, sr)
        self.waves[table] = wv
        return wv

    def region_for(self, inst_idx: int, note: int, vel: int) -> tuple[Region, Wave] | None:
        if inst_idx < 0 or inst_idx >= len(self.instruments):
            return None
        best = None
        for r in self.instruments[inst_idx].regions:
            if r.key_lo <= note <= r.key_hi and r.vel_lo <= vel <= r.vel_hi:
                w = self.wave(r.table)
                if w is not None:
                    best = (r, w)
                    break
        if best is None:  # 音域越界：夹到最近的区域
            cands = [r for r in self.instruments[inst_idx].regions if self.wave(r.table)]
            if not cands:
                return None
            r = min(cands, key=lambda x: min(abs(note - x.key_lo), abs(note - x.key_hi)))
            best = (r, self.wave(r.table))
        return best


# --------------------------------------------------------------------------
# MIDI (SMF)
# --------------------------------------------------------------------------
def _varlen(data: bytes, i: int) -> tuple[int, int]:
    v = 0
    while True:
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def parse_midi(path: Path):
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    _fmt, ntrk, div = struct.unpack(">HHH", data[8:14])
    i = 14
    tracks = []
    for _ in range(ntrk):
        if data[i:i + 4] != b"MTrk":
            break
        ln = struct.unpack(">I", data[i + 4:i + 8])[0]
        tracks.append(_parse_track(data[i + 8:i + 8 + ln]))
        i += 8 + ln
    return div, tracks


def _parse_track(body: bytes):
    i = 0
    tick = 0
    status = 0
    out = []
    while i < len(body):
        dt, i = _varlen(body, i)
        tick += dt
        b = body[i]
        if b & 0x80:
            status = b
            i += 1
        else:
            if status == 0:
                break
        if status == 0xFF:
            mtype = body[i]
            i += 1
            ln, i = _varlen(body, i)
            payload = body[i:i + ln]
            i += ln
            if mtype == 0x51 and ln == 3:
                tempo = (payload[0] << 16) | (payload[1] << 8) | payload[2]
                out.append((tick, "tempo", tempo))
            continue
        if status in (0xF0, 0xF7):
            ln, i = _varlen(body, i)
            i += ln
            continue
        kind = status & 0xF0
        ch = status & 0x0F
        if kind in (0xC0, 0xD0):
            d1 = body[i]
            i += 1
            out.append((tick, "program" if kind == 0xC0 else "chanpress", (ch, d1)))
            continue
        d1 = body[i]
        d2 = body[i + 1]
        i += 2
        if kind == 0x90 and d2 > 0:
            out.append((tick, "noteon", (ch, d1, d2)))
        elif kind == 0x80 or (kind == 0x90 and d2 == 0):
            out.append((tick, "noteoff", (ch, d1, 0)))
        elif kind == 0xB0:
            out.append((tick, "cc", (ch, d1, d2)))
        elif kind == 0xE0:
            out.append((tick, "bend", (ch, ((d2 << 7) | d1) - 8192)))
    return out


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
def render(midi: Path, dls: DLS, sr: int = 44100, gain_db: float = 0.0,
           drum_inst: int = 128, release: float = 0.18, verbose=True) -> np.ndarray:
    div, tracks = parse_midi(midi)
    ppq = div if div < 0x8000 else 480

    # 合并事件并换算秒
    tempo_events = []
    for tr in tracks:
        for tick, kind, val in tr:
            if kind == "tempo":
                tempo_events.append((tick, val))
    uniq = {}
    for tick, val in tempo_events:
        uniq[tick] = val
    tempos = sorted(uniq.items())
    if not tempos:
        tempos = [(0, 500000)]

    def tick_to_sec(tick: float) -> float:
        sec = 0.0
        last_tick = 0
        cur = tempos[0][1]
        for t, v in tempos:
            if t > tick:
                break
            sec += (t - last_tick) / ppq * (cur / 1e6)
            last_tick = t
            cur = v
        sec += (tick - last_tick) / ppq * (cur / 1e6)
        return sec

    evs = []
    for tr in tracks:
        for tick, kind, val in tr:
            if kind in ("noteon", "program", "cc", "bend", "chanpress"):
                evs.append((tick, kind, val))
    evs.sort(key=lambda e: e[0])

    program = {ch: 0 for ch in range(16)}
    volume = {ch: 100 for ch in range(16)}
    pan = {ch: 64 for ch in range(16)}
    bend = {ch: 0 for ch in range(16)}
    active: dict[tuple[int, int], list] = {}
    notes = []

    for tick, kind, val in evs:
        t = tick_to_sec(tick)
        if kind == "program":
            ch, p = val
            program[ch] = p
        elif kind == "cc":
            ch, cc, v = val
            if cc == 7:
                volume[ch] = v
            elif cc == 10:
                pan[ch] = v
        elif kind == "bend":
            ch, v = val
            bend[ch] = v
        elif kind == "noteon":
            ch, note, vel = val
            active.setdefault((ch, note), []).append((t, vel, program[ch],
                                                      volume[ch], pan[ch], bend[ch]))
        elif kind == "noteoff":
            ch, note, _ = val
            stack = active.get((ch, note))
            if stack:
                st = stack.pop(0)
                notes.append((st[0], t, ch, note, st[1], st[2], st[3], st[4], st[5]))

    if not notes:
        raise ValueError("MIDI 里没有音符")

    end_time = max(n[1] for n in notes) + release
    total = int(np.ceil(end_time * sr)) + sr // 10
    mix = np.zeros((total, 2), dtype=np.float32)

    for (t0, t1, ch, note, vel, prog, vol, pn, bnd) in notes:
        idx = drum_inst if ch == 9 else prog
        got = dls.region_for(idx, note, vel)
        if got is None:
            continue
        r, w = got
        if w.sr != sr:
            base_ratio = w.sr / sr
        else:
            base_ratio = 1.0
        bend_semi = (bnd / 8192.0) * 2.0
        semis = (note - r.unity) + r.fine / 100.0 + bend_semi
        ratio = base_ratio * (2.0 ** (semis / 12.0))

        dur = max(0.02, t1 - t0)
        n_out = int((dur + release) * sr)
        if n_out <= 1:
            continue
        pos = np.arange(n_out, dtype=np.float64) * ratio
        src_len = len(w.data)
        if r.loop_len > 8 and r.loop_start + r.loop_len <= src_len:
            ls, ll = r.loop_start, r.loop_len
            over = pos >= (ls + ll)
            pos = np.where(over, ls + np.mod(pos - ls, ll), pos)
        else:
            keep = pos < (src_len - 2)
            if not keep.any():
                continue
            n_out = int(keep.sum())
            pos = pos[:n_out]

        i0 = pos.astype(np.int64)
        frac = (pos - i0).astype(np.float32)
        s0 = w.data[i0]
        s1 = w.data[np.minimum(i0 + 1, src_len - 1)]
        sig = s0 + (s1 - s0) * frac

        # 包络：5ms 起、80ms 衰减到 0.85、松键后线性 release
        att = min(int(0.005 * sr), n_out // 4 or 1)
        env = np.full(n_out, 0.85, dtype=np.float32)
        env[:att] = np.linspace(0.0, 0.85, att, dtype=np.float32)
        dec = min(int(0.08 * sr), max(1, n_out - att))
        env[att:att + dec] = np.linspace(0.85, 0.85, dec, dtype=np.float32)  # 平直，靠 loop
        rel_n = min(int(release * sr), n_out)
        if rel_n > 1:
            env[-rel_n:] *= np.linspace(1.0, 0.0, rel_n, dtype=np.float32)
        sig = sig * env

        g = (vel / 127.0) ** 1.6 * (vol / 127.0) ** 0.5 * 0.45
        l = (np.clip(pn, 0, 127) / 127.0)
        pan_l = np.cos(l * np.pi / 2)
        pan_r = np.sin(l * np.pi / 2)
        start = int(t0 * sr)
        stop = min(total, start + n_out)
        if stop <= start:
            continue
        seg = sig[:stop - start]
        mix[start:stop, 0] += seg * g * pan_l * 1.414
        mix[start:stop, 1] += seg * g * pan_r * 1.414

    if gain_db:
        mix *= 10 ** (gain_db / 20.0)
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.99:
        mix *= 0.99 / peak
    if verbose:
        print(f"[render] notes={len(notes)} dur={end_time:.2f}s peak={peak:.3f}")
    return mix


def main() -> int:
    ap = argparse.ArgumentParser(description="MIDI -> WAV，用系统自带 gm.dls 音色")
    ap.add_argument("midi", nargs="?", help="输入 .mid")
    ap.add_argument("-o", "--out", help="输出 .wav")
    ap.add_argument("--dls", default=str(DEFAULT_DLS))
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--gain", type=float, default=0.0, help="总增益 dB")
    ap.add_argument("--list", action="store_true", help="列出乐器编号与名称")
    args = ap.parse_args()

    dls = DLS(Path(args.dls))
    if args.list:
        for i, inst in enumerate(dls.instruments):
            print(f"{i:3d}  {inst.name or '(no name)'}  regions={len(inst.regions)}")
        return 0
    if not args.midi or not args.out:
        ap.error("需要 midi 与 -o")
    audio = render(Path(args.midi), dls, sr=args.sr, gain_db=args.gain)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), audio, args.sr, subtype="PCM_16")
    print(f"[ok] {out}  {len(audio)/args.sr:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
