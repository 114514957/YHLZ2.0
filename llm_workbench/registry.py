"""版本注册表：扫描本地 LoRA / adapter，算出「这个版本完整不完整」。

为什么要有这一层（台账 1061 的教训）：
  第一次拉 v9t6 adapter 少了 170,416 字节，但 safetensors 头是完整的——
  只看头能读出 264 张量，**照样是残缺的**。所以完整性必须算：
      8 + header_len + max(offset + len) == 文件大小
  这个判断写在这里，工作台和命令行共用一份，不许各写各的。

目录约定（相对 YH/）：
  models/gguf-lora/*.gguf          已转好的 GGUF LoRA（llama-server 直接吃）
  models/lora/*/adapter_model.safetensors  训练产物（要做版本档案，不能直接服务）
  models/gemma4-gguf/*.gguf        基座 / mmproj
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import struct
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # YH/
GGUF_LORA_DIR = os.path.join(ROOT, "models", "gguf-lora")
ADAPTER_DIR = os.path.join(ROOT, "models", "lora")
BASE_DIR = os.path.join(ROOT, "models", "gemma4-gguf")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REGISTRY_JSON = os.path.join(DATA_DIR, "registry.json")

BASE_GGUF = os.path.join(BASE_DIR, "gemma-4-E4B_q4_0-it.gguf")
MMPROJ_GGUF = os.path.join(BASE_DIR, "gemma-4-E4B-it-mmproj.gguf")

_HASH_CACHE: dict[tuple[str, int, float], str] = {}
_SCAN_CACHE: dict = {"at": 0.0, "data": None}
SCAN_TTL = 15.0            # 秒；页面每次 /api/state 不该重算 1.4 GB
HASH_JSON = os.path.join(DATA_DIR, "hash_cache.json")
_HASH_JSON_LOADED = False


def _load_hash_cache() -> None:
    """把算过的 SHA 落在盘上——1.4 GB 的哈希不该每次开页都重算。"""
    global _HASH_JSON_LOADED
    if _HASH_JSON_LOADED:
        return
    _HASH_JSON_LOADED = True
    try:
        with io.open(HASH_JSON, encoding="utf-8") as f:
            for k, v in json.load(f).items():
                path, size, mtime = k.rsplit("|", 2)
                _HASH_CACHE[(path, int(size), float(mtime))] = v
    except Exception:  # noqa: BLE001
        pass


def _save_hash_cache() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    out = {"%s|%d|%r" % k: v for k, v in _HASH_CACHE.items()}
    tmp = HASH_JSON + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f)
    os.replace(tmp, HASH_JSON)


def _sha256(path: str, limit: int | None = None) -> str:
    _load_hash_cache()
    key = (path, os.path.getsize(path), os.path.getmtime(path))
    if key in _HASH_CACHE:
        return _HASH_CACHE[key]
    h = hashlib.sha256()
    left = limit if limit is not None else -1
    with open(path, "rb") as f:
        while True:
            n = 1 << 20 if left < 0 else min(1 << 20, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            left -= len(b)
    v = h.hexdigest()
    _HASH_CACHE[key] = v
    _save_hash_cache()
    return v


def inspect_safetensors(path: str) -> dict:
    """按 safetensors 格式算完整性。返回 {tensors, header_len, expect, actual, ok, err}。"""
    out = {"tensors": 0, "header_len": 0, "expect": 0, "actual": 0,
           "ok": False, "err": ""}
    try:
        actual = os.path.getsize(path)
        out["actual"] = actual
        with open(path, "rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                out["err"] = "文件不足 8 字节"
                return out
            (hlen,) = struct.unpack("<Q", raw)
            if hlen <= 0 or hlen > 200 * 1024 * 1024:
                out["err"] = "头长度异常：%d" % hlen
                return out
            hdr = f.read(hlen)
        meta = json.loads(hdr.decode("utf-8"))
        meta.pop("__metadata__", None)
        max_end = 0
        for _, info in meta.items():
            offs = info.get("data_offsets") or [0, 0]
            max_end = max(max_end, int(offs[1]))
        out["tensors"] = len(meta)
        out["header_len"] = hlen
        out["expect"] = 8 + hlen + max_end
        out["ok"] = out["expect"] == actual
        if not out["ok"]:
            out["err"] = "缺 %d 字节" % (out["expect"] - actual)
    except Exception as ex:  # noqa: BLE001
        out["err"] = "%s: %s" % (type(ex).__name__, ex)
    return out


def _ver_key(name: str) -> str:
    """从文件名/目录名里抠版本名：yuanheng-v9t6-lora.gguf -> v9t6。

    只剥「yuanheng-」前缀和「-lora.gguf / .gguf」后缀。
    **不剥 -sft / -dpo**：剥了 `v6-sft` 和 `v6-dpo` 会都变成 `v6`，
    列表里出现两个同名版本（2026-11-02 首屏实撞）。
    """
    s = name.lower()
    for pre in ("yuanheng-", "gemma-"):
        if s.startswith(pre):
            s = s[len(pre):]
    for suf in ("-lora.gguf", ".gguf"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def local_base_kind() -> str:
    """本机这个 GGUF 基座是哪一路：qat 还是普通 it。

    llama-server 现在只挂了 `gemma-4-E4B_q4_0-it.gguf` 一个基座，
    文件名里没有 qat 就按普通基座算（台账 1070：本机没有 QAT 权重）。
    """
    name = os.path.basename(BASE_GGUF).lower()
    return "qat" if "qat" in name else "it"


def _base_hint(path: str) -> str:
    """把 adapter_config 里的 base_model_name_or_path 归一成 qat / it / 其它。

    这个字段是训练时自动写下的，比手填靠谱：v7b/v7c/v5 是 QAT，
    v9t6 是普通 it（台账 1070）。
    """
    s = (path or "").strip().lower().rstrip("/")
    if not s:
        return ""
    if "qat" in s:
        return "qat"
    if "gemma-4-e4b-it" in s or "gemma-4-E4B-it" in (path or ""):
        return "it"
    return os.path.basename(s)


def read_adapter_base(adapter_dir: str) -> dict:
    """读 adapter_config.json 里的训练基座。"""
    p = os.path.join(adapter_dir, "adapter_config.json")
    if not os.path.isfile(p):
        return {"path": "", "hint": "", "ok": False}
    try:
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        raw = str(d.get("base_model_name_or_path") or "")
        return {"path": raw, "hint": _base_hint(raw), "ok": bool(raw)}
    except Exception:  # noqa: BLE001
        return {"path": "", "hint": "", "ok": False}


def load_notes() -> dict:
    if not os.path.exists(REGISTRY_JSON):
        return {}
    try:
        with io.open(REGISTRY_JSON, encoding="utf-8") as f:
            return json.load(f).get("versions", {})
    except Exception:  # noqa: BLE001
        return {}


def save_notes(notes: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = REGISTRY_JSON + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump({"versions": notes, "saved_at": int(time.time())}, f,
                  ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRY_JSON)


def scan(force: bool = False) -> dict:
    """扫一遍本地版本，返回 {versions:[], bases:{}, scanned_at}。

    15 秒内复用上次结果；`force=True` 强制重扫（界面上的「重扫版本」）。
    """
    now = time.time()
    if (not force and _SCAN_CACHE["data"] is not None
            and now - _SCAN_CACHE["at"] < SCAN_TTL):
        return _SCAN_CACHE["data"]
    data = _scan_uncached()
    _SCAN_CACHE["at"] = time.time()
    _SCAN_CACHE["data"] = data
    return data


def _scan_uncached() -> dict:
    notes = load_notes()
    versions: list[dict] = []

    # ① GGUF LoRA —— 能直接挂到 llama-server 的「可服务版本」
    if os.path.isdir(GGUF_LORA_DIR):
        for fn in sorted(os.listdir(GGUF_LORA_DIR)):
            if not fn.lower().endswith(".gguf"):
                continue
            p = os.path.join(GGUF_LORA_DIR, fn)
            st = os.stat(p)
            key = _ver_key(fn)
            versions.append({
                "id": "gguf:" + fn,
                "version": key,
                "kind": "gguf-lora",
                "file": fn,
                "path": p,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "sha256_16": _sha256(p)[:16],
                "serviceable": True,
                "integrity": {"ok": True, "err": ""},
                "notes": notes.get(key, {}),
            })

    # ② 训练产物 adapter —— 版本档案，缺 GGUF 就是「未转，不能服务」
    gguf_versions = {v["version"] for v in versions}
    adapter_base: dict[str, dict] = {}
    if os.path.isdir(ADAPTER_DIR):
        for dn in sorted(os.listdir(ADAPTER_DIR)):
            d = os.path.join(ADAPTER_DIR, dn)
            st_path = os.path.join(d, "adapter_model.safetensors")
            if not os.path.isfile(st_path):
                continue
            st = os.stat(st_path)
            info = inspect_safetensors(st_path)
            key = _ver_key(dn)
            b = read_adapter_base(d)
            adapter_base[key] = b
            # 同名就算对上；也认 "v9-gemma-v9t6" 这种带前缀的目录名，
            # 以及 "v7c-sft" 这种「训练产物 → 已转 GGUF 的 v7c」的对应关系。
            # 反查不做：短 key 会误配。
            base = re.sub(r"-(sft|dpo)$", "", key)
            has_gguf = any(c == g or (len(g) >= 3 and c.endswith("-" + g))
                           for c in (key, base) for g in gguf_versions)
            versions.append({
                "id": "adapter:" + dn,
                "version": key,
                "kind": "adapter",
                "file": dn,
                "path": d,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "sha256_16": _sha256(st_path)[:16],
                "serviceable": has_gguf,
                "integrity": {"ok": info["ok"], "err": info["err"],
                              "tensors": info["tensors"],
                              "expect": info["expect"], "actual": info["actual"]},
                "base": {**b, "local": b.get("hint") == local_base_kind()},
                "notes": notes.get(key, {}),
            })

    # ① 的 GGUF 版本回头补基座：按版本名找同源 adapter 继承（v7b ← v7b-sft）
    local_kind = local_base_kind()
    for v in versions:
        if v["kind"] != "gguf-lora" or "base" in v:
            continue
        k = v["version"]
        cand = adapter_base.get(k) or adapter_base.get(k + "-sft") or adapter_base.get(k + "-dpo")
        if not cand:
            for ak, ab in adapter_base.items():
                if ak.endswith("-" + k) or re.sub(r"-(sft|dpo)$", "", ak) == k:
                    cand = ab
                    break
        cand = cand or {"path": "", "hint": "", "ok": False}
        v["base"] = {**cand, "local": cand.get("hint") == local_kind}

    versions.sort(key=lambda v: (not v["serviceable"], -v["mtime"]))
    return {
        "versions": versions,
        "bases": {
            "gguf": BASE_GGUF if os.path.exists(BASE_GGUF) else "",
            "mmproj": MMPROJ_GGUF if os.path.exists(MMPROJ_GGUF) else "",
            "gguf_size": os.path.getsize(BASE_GGUF) if os.path.exists(BASE_GGUF) else 0,
            "local_kind": local_kind,
            "has_qat_weights": any(
                os.path.isfile(os.path.join(ROOT, "models", "gemma4-qat-cfg", n))
                for n in ("model.safetensors", "model-00001-of-00002.safetensors")),
        },
        "scanned_at": int(time.time()),
    }


if __name__ == "__main__":
    d = scan()
    print(json.dumps(d, ensure_ascii=False, indent=2)[:3000])
