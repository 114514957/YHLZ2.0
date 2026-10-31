"""QQ Bridge Lite P0 audit — Gate 0 static isolation evidence (offline).

Read-only. Loads the Lite profile, proves the bridge state paths move under
YHLZ_QQ_PROFILE/YHLZ_QQ_STATE_DIR without changing Full defaults, and proves
the bridge module set does not import or call the Full launcher/watchdog
(ensure_stack, _spawn_ollama/_spawn_llama/_spawn_daemon).

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_p0_audit.py
    ... --out artifacts\\qq_lite\\p0_<run_id>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.qq_bridge_state import (  # noqa: E402
    PROFILE_ENV, STATE_DIR_ENV, is_scoped, profile as state_profile,
)
from backend.yhlz_paths import BOT_UIN, MASTER_UIN, QQWATCH_CONFIG  # noqa: E402

LITE_MODULES = (
    "tools/qq_bot.py",
    "tools/qq_bridge_service.py",
    "tools/qq_bridge_watchdog.py",
    "tools/qq_bridge_control.py",
    "tools/qq_bridge_p1_fake_echo.py",
    "tools/qq_bridge_p2_stub_bridge.py",
    "tools/qq_bridge_p2_matrix.py",
    "tools/qq_dev_runner.py",
    "tools/qq_dev_worker.py",
    "tools/qq_dev_fake_agent.py",
    "tools/qq_bridge_p3_matrix.py",
    "backend/qq_bridge_state.py",
    "backend/qq_bridge_lock.py",
    "backend/qq_account_lock.py",
    "backend/qq_bridge_notices.py",
    "backend/qq_dev_jobs.py",
    "backend/qq_dev_git.py",
    "backend/qq_group_store.py",
    "backend/qq_stickers.py",
    "backend/qq_connection.py",
    "backend/qq_delivery.py",
    "backend/qq_delivery_store.py",
    "backend/qq_outbox.py",
    "backend/qq_send_adapter.py",
)
INVENTORY = (
    ("bridge", "tools/qq_bot.py"),
    ("bridge", "tools/qq_bridge_service.py"),
    ("bridge", "tools/qq_bridge_watchdog.py"),
    ("bridge", "tools/qq_bridge_control.py"),
    ("bridge", "tools/qq_bridge_p0_audit.py"),
    ("bridge", "tools/qq_bridge_p1_fake_echo.py"),
    ("p2-evidence", "tools/qq_bridge_p2_stub_bridge.py"),
    ("p2-evidence", "tools/qq_bridge_p2_matrix.py"),
    ("dev-p3", "tools/qq_dev_runner.py"),
    ("dev-p3", "tools/qq_dev_worker.py"),
    ("dev-p3", "tools/qq_dev_fake_agent.py"),
    ("dev-p3", "tools/qq_bridge_p3_matrix.py"),
    ("dev-p3", "backend/qq_dev_jobs.py"),
    ("dev-p3", "backend/qq_dev_git.py"),
    ("dev-p3", "backend/test_qq_dev_p3.py"),
    ("chat-p4", "backend/qq_group_store.py"),
    ("chat-p4", "backend/qq_stickers.py"),
    ("chat-p4", "tools/qq_bridge_p4_matrix.py"),
    ("chat-p4", "backend/test_qq_bridge_p4.py"),
    ("state", "backend/qq_bridge_state.py"),
    ("state", "backend/qq_bridge_lock.py"),
    ("state", "backend/qq_account_lock.py"),
    ("state", "backend/qq_bridge_notices.py"),
    ("bridge", "backend/qq_connection.py"),
    ("bridge", "backend/qq_delivery.py"),
    ("bridge", "backend/qq_delivery_store.py"),
    ("bridge", "backend/qq_outbox.py"),
    ("bridge", "backend/qq_send_adapter.py"),
    ("config", "backend/yhlz_paths.py"),
    ("config", "config/qq_bridge_lite.json"),
    ("config", "config/qqwatch.json"),
    ("legacy-qq-restart", "tools/qq_bot_restart.py"),
    ("legacy-full", "tools/yhlz_launcher.py"),
    ("legacy-full", "tools/yhlz_watchdog.py"),
    ("legacy-full", "tools/napcat_watch.py"),
    ("dev-p3-later", "tools/dev_runner.py"),
    ("dev-p3-later", "tools/dsh_worker.py"),
    ("startup", "qqwatch-run.bat"),
)
FORBIDDEN = re.compile(
    r"ensure_stack|_spawn_ollama|_spawn_llama|_spawn_daemon|_spawn_napcat"
    r"|yhlz_launcher|yhlz_watchdog|napcat_watch")
KILL_LOGIC = re.compile(
    r"taskkill|TerminateProcess|process_iter|os\.kill\(")

PROBE = r"""
import importlib.util, json, os, sys
repo = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "QQBotProbe", os.path.join(repo, "tools", "qq_bot.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
bad = sorted(m for m in ("yhlz_launcher", "yhlz_watchdog", "napcat_watch")
             if m in sys.modules)
print("@@PROBE@@" + json.dumps({
    "status": str(mod.QQ_STATUS), "lock": str(mod._bridge_path(
        "bridge.lock", __import__("pathlib").Path("legacy-lock"))),
    "media": str(mod.MEDIA_DIR), "stickers": str(mod.STICKER_DIR),
    "group_daily": str(mod.GROUP_DAILY_STATE), "state": str(mod.QQ_STATE),
    "profile": mod._bridge_profile(), "state_dir": str(mod._bridge_state_dir()),
    "bad_modules": bad, "has_ensure_stack": hasattr(mod, "ensure_stack"),
    "has_spawn": any(hasattr(mod, n) for n in
                     ("_spawn_ollama", "_spawn_llama", "_spawn_daemon")),
}))
"""


def _sha256(p: pathlib.Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return ""


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=_ROOT, capture_output=True,
                             text=True, timeout=20)
        return out.stdout.strip()
    except Exception:
        return ""


def _git_info(rel: str) -> dict:
    tracked = bool(_git(["ls-files", "--error-unmatch", rel]))
    dirty = bool(_git(["status", "--porcelain", "--", rel]))
    return {"tracked": tracked, "dirty": dirty}


def _probe(env: dict) -> dict:
    run_env = dict(os.environ)
    run_env.pop(PROFILE_ENV, None)
    run_env.pop(STATE_DIR_ENV, None)
    run_env.update(env)
    out = subprocess.run([sys.executable, "-c", PROBE, str(_ROOT)],
                         cwd=_ROOT, capture_output=True, text=True, timeout=120,
                         env=run_env)
    for line in (out.stdout or "").splitlines():
        if line.startswith("@@PROBE@@"):
            return json.loads(line[len("@@PROBE@@"):])
    raise RuntimeError(f"probe failed rc={out.returncode}: {out.stderr[-400:]}")


def _fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _ps_json(script: str) -> list:
    tmp = _ROOT / "cache" / "tmp" / f"p0_ps_{int(time.time()*1000)}.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    wrapped = (f"$ErrorActionPreference='SilentlyContinue'; {script} | "
               f"ConvertTo-Json -Compress | Set-Content -Encoding UTF8 "
               f"'{tmp}'")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", wrapped], capture_output=True, timeout=60)
        if tmp.exists():
            data = json.loads(tmp.read_text(encoding="utf-8-sig") or "[]")
            return data if isinstance(data, list) else [data]
    except Exception:
        pass
    finally:
        tmp.unlink(missing_ok=True)
    return []


def _startup_items() -> list:
    items = _ps_json(
        "$sh=New-Object -ComObject WScript.Shell; "
        "$items=@(); "
        "foreach ($f in Get-ChildItem "
        "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\" "
        "-Filter *.lnk) { $s=$sh.CreateShortcut($f.FullName); "
        "$items += [pscustomobject]@{kind='startup_folder'; name=$f.Name; "
        "target=$s.TargetPath; args=$s.Arguments} }; $items")
    tasks = _ps_json(
        "Get-ScheduledTask | Where-Object { $_.TaskName -match "
        "'qq|yhlz|napcat|元亨' } | Select-Object TaskName,State | "
        "ForEach-Object { [pscustomobject]@{kind='scheduled_task'; "
        "name=$_.TaskName; state=$_.State} }")
    return items + tasks


def _run_keys() -> list:
    import winreg

    out = []
    for hive, path in ((winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run"),
                       (winreg.HKEY_LOCAL_MACHINE,
                        r"Software\Microsoft\Windows\CurrentVersion\Run")):
        try:
            with winreg.OpenKey(hive, path) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    if re.search(r"qq|yhlz|napcat", f"{name} {value}",
                                 re.IGNORECASE):
                        out.append({"kind": "run_key", "name": name,
                                    "value": str(value)})
                    i += 1
        except OSError:
            continue
    return out


def _static_scan() -> dict:
    hits: dict[str, list] = {}
    kill_hits: dict[str, list] = {}
    for rel in LITE_MODULES:
        p = _ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        found = [f"{i}:{ln.strip()[:120]}" for i, ln in
                 enumerate(text.splitlines(), 1) if FORBIDDEN.search(ln)]
        kills = [f"{i}:{ln.strip()[:120]}" for i, ln in
                 enumerate(text.splitlines(), 1)
                 if KILL_LOGIC.search(ln) and "p0-audit-allow" not in ln]
        if found:
            hits[rel] = found
        if kills:
            kill_hits[rel] = kills
    return {"forbidden_refs": hits, "kill_logic_refs": kill_hits}


def _redact(text: str, secret: str) -> str:
    return str(text).replace(secret, "<bot_uin>") if secret else str(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    run_id = time.strftime("p0_%Y%m%dT%H%M%S")
    ap.add_argument("--out", default=str(_ROOT / "artifacts" / "qq_lite" / run_id))
    a = ap.parse_args()
    out_dir = pathlib.Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = out_dir.name

    config_path = _ROOT / "config" / "qq_bridge_lite.json"
    config: dict = {}
    config_error = ""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        config_error = f"{type(exc).__name__}: {exc}"
    token_fields = [k for k, v in config.items()
                    if "token" in k.lower() and v]

    full = _probe({})
    lite = _probe({PROFILE_ENV: "lite"})
    env_dir = out_dir / "state_env_probe"
    env_probe = _probe({STATE_DIR_ENV: str(env_dir)})

    scan = _static_scan()
    onebot = QQWATCH_CONFIG / f"onebot11_{BOT_UIN}.json"
    onebot_info = {
        "path": _redact(str(onebot), BOT_UIN),
        "exists": onebot.exists(),
        "sha256": _sha256(onebot) if onebot.exists() else "",
    }
    inventory = []
    for role, rel in INVENTORY:
        p = _ROOT / rel
        entry = {"role": role, "path": rel, "exists": p.exists(),
                 "sha256": _sha256(p) if p.exists() else ""}
        entry.update(_git_info(rel))
        inventory.append(entry)

    lite_dir = lite["state_dir"]
    full_dir = full["state_dir"]
    gate0 = {
        "config_loadable": bool(config) and not config_error,
        "config_master_ok": config.get("master_uins") == [MASTER_UIN],
        "config_token_fields": token_fields,
        "forbidden_refs": scan["forbidden_refs"],
        "kill_logic_refs": scan["kill_logic_refs"],
        "runtime_bad_modules": lite.get("bad_modules", []),
        "runtime_has_ensure_stack": bool(lite.get("has_ensure_stack")),
        "runtime_has_spawn": bool(lite.get("has_spawn")),
        "full_paths_unchanged": full["status"].endswith(
            "cache\\tmp\\qq_bridge_status.json"),
        "lite_paths_scoped": "cache\\qq_bridge\\lite" in lite["status"],
        "env_override_applied": str(env_dir) in env_probe["status"],
        "full_vs_lite_dirs_differ": full_dir != lite_dir,
    }
    gate0["pass"] = all((
        gate0["config_loadable"], gate0["config_master_ok"],
        not token_fields, not scan["forbidden_refs"],
        not scan["kill_logic_refs"], not lite.get("bad_modules", []),
        not lite.get("has_ensure_stack"), not lite.get("has_spawn"),
        gate0["full_paths_unchanged"], gate0["lite_paths_scoped"],
        gate0["env_override_applied"], gate0["full_vs_lite_dirs_differ"],
    ))

    manifest = {
        "run_id": run_id,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "profile_audited": "lite",
        "auditor_default_profile": state_profile(),
        "auditor_scoped": is_scoped(),
        "config": {"path": "config/qq_bridge_lite.json",
                   "loadable": gate0["config_loadable"],
                   "error": config_error,
                   "master_uins": config.get("master_uins", []),
                   "token_fields": token_fields},
        "state_paths": {"full": full, "lite": lite, "env_override": env_probe},
        "onebot": onebot_info,
        "uin_fingerprints": {"bot": _fingerprint(BOT_UIN),
                             "master": _fingerprint(MASTER_UIN)},
        "inventory": inventory,
        "startup": _startup_items() + _run_keys(),
        "legacy_restart": {"path": "tools/qq_bot_restart.py",
                           "kills_by_filename": True,
                           "lite_allowed": False},
        "account_consumer_lock": "not_implemented_p2",
        "send_adapter_default_transport": "fake_success_pending_p1_hardening",
        "gate0": gate0,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "import_audit.json").write_text(
        json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "profile_check.json").write_text(
        json.dumps({"config": manifest["config"],
                    "state_paths": manifest["state_paths"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[p0] run_id={run_id} out={out_dir}")
    for key, value in gate0.items():
        print(f"[p0] {key} = {value}")
    print(f"[p0] gate0_pass = {gate0['pass']}")
    return 0 if gate0["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
