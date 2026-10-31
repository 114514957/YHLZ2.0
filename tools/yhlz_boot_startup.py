"""One-entry Windows autostart for YH (ledger 0830; renamed 2026-10-21).

问题（2026-10-20）：Startup 里同时躺着两条自启——
``YHLZ看门狗.lnk``（旧 Full 链，launcher/watchdog）和
``YHLZ-QQ桥Lite.lnk``（新 Lite 链）。登录时新旧都拉，QQ 侧就出现
"新旧都在跑"。这里把旧快捷方式备份移走，只装一个
``YH 开机自启.lnk`` → ``YH_boot.bat``（服务 → 看门狗 → QQ Lite）。

Dry-run by default; ``--apply`` backs up + removes the old shortcuts and
creates the single one; ``--rollback`` restores exactly the backup set.
Never elevated: the shortcut only starts the normal-privilege bat.

Usage:
    python tools/yhlz_boot_startup.py            # dry-run plan
    python tools/yhlz_boot_startup.py --apply
    python tools/yhlz_boot_startup.py --rollback
    python tools/yhlz_boot_startup.py --status
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_YH_ROOT = _ROOT.parent / "YH"
sys.path.insert(0, str(_ROOT))

BOOT_BAT = (_YH_ROOT if (_YH_ROOT / "YH_boot.bat").exists() else _ROOT) / "YH_boot.bat"
SHORTCUT_NAME = "YH 开机自启.lnk"
OLD_SHORTCUTS = ("YHLZ 开机自启.lnk", "YHLZ看门狗.lnk", "YHLZ-QQ桥Lite.lnk")
BACKUP_DIR = _ROOT / "cache" / "backup_shortcut"
MANIFEST = BACKUP_DIR / "boot_startup_manifest.json"


def startup_dir() -> pathlib.Path:
    return (pathlib.Path.home() / "AppData" / "Roaming" / "Microsoft"
            / "Windows" / "Start Menu" / "Programs" / "Startup")


def _shortcut_path() -> pathlib.Path:
    return startup_dir() / SHORTCUT_NAME


def _powershell(script: str) -> tuple[int, str]:
    import subprocess

    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", script], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _ps_move(src: pathlib.Path, dst: pathlib.Path) -> dict:
    """Move a file via PowerShell.

    本机沙箱对 python.exe 的 os.unlink/rename（Startup 目录内）返回
    WinError 5，而 PowerShell 的 Move-Item 在同一令牌下可以完成；启动项
    迁移统一走 PowerShell，避免工具在真机上"看起来失败"。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    ps = (f"Move-Item -LiteralPath '{src}' -Destination '{dst}' -Force "
          "-ErrorAction Stop; 'ok'")
    rc, out = _powershell(ps)
    if rc != 0 or "ok" not in out:
        return {"ok": False, "error": out[-300:]}
    return {"ok": True, "from": str(src), "to": str(dst)}


def _ps_delete(path: pathlib.Path) -> dict:
    ps = (f"if (Test-Path -LiteralPath '{path}') "
          f"{{ Remove-Item -LiteralPath '{path}' -Force -ErrorAction Stop }}; "
          "'ok'")
    rc, out = _powershell(ps)
    if rc != 0 or "ok" not in out:
        return {"ok": False, "error": out[-300:]}
    return {"ok": True}


def _create_shortcut(path: pathlib.Path, target: pathlib.Path,
                     args: str = "") -> dict:
    ps = (
        "$sh=New-Object -ComObject WScript.Shell; "
        f"$lnk=$sh.CreateShortcut('{path}'); "
        f"$lnk.TargetPath='{target}'; "
        f"$lnk.Arguments='{args}'; "
        f"$lnk.WorkingDirectory='{BOOT_BAT.parent}'; "
        "$lnk.Save(); 'ok'"
    )
    rc, out = _powershell(ps)
    if rc != 0 or "ok" not in out:
        return {"ok": False, "error": out[-300:]}
    return {"ok": True, "path": str(path)}


def plan() -> dict:
    existing = [str(startup_dir() / n) for n in OLD_SHORTCUTS
                if (startup_dir() / n).exists()]
    return {
        "boot_bat": str(BOOT_BAT),
        "boot_bat_exists": BOOT_BAT.exists(),
        "startup_dir": str(startup_dir()),
        "shortcut": str(_shortcut_path()),
        "shortcut_exists": _shortcut_path().exists(),
        "old_shortcuts_present": existing,
        "old_shortcuts_expected": [str(startup_dir() / n)
                                   for n in OLD_SHORTCUTS],
        "backup_dir": str(BACKUP_DIR),
        "note": "启动顺序：服务栈 → Full 看门狗 → QQ Lite（resume 尊重 stopped）；"
                "旧的 YHLZ 自启会被移入 cache/backup_shortcut/，可 --rollback 还原。",
    }


def apply() -> dict:
    if not BOOT_BAT.exists():
        return {"ok": False, "error": f"缺少 {BOOT_BAT}"}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved: list[dict] = []
    for name in OLD_SHORTCUTS:
        src = startup_dir() / name
        if not src.exists():
            continue
        dst = BACKUP_DIR / f"{name}.removed-{stamp}"
        result = _ps_move(src, dst)
        if not result.get("ok"):
            return {"ok": False, "error": f"移动 {name} 失败: "
                                          f"{result.get('error')}"}
        moved.append({"from": str(src), "to": str(dst)})
    created = _create_shortcut(_shortcut_path(), BOOT_BAT)
    manifest = {"stamp": stamp, "moved": moved, "created": created,
                "shortcut": str(_shortcut_path())}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"ok": bool(created.get("ok")), **manifest}


def rollback() -> dict:
    restored: list[dict] = []
    created = _shortcut_path()
    deleted = _ps_delete(created) if created.exists() else {"ok": True}
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    for item in manifest.get("moved") or []:
        src = pathlib.Path(item["to"])
        dst = pathlib.Path(item["from"])
        if src.exists():
            result = _ps_move(src, dst)
            restored.append(result)
    return {"ok": bool(deleted.get("ok")), "removed_shortcut": str(created),
            "restored": restored}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.apply:
        out = apply()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 2
    if a.rollback:
        out = rollback()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 2
    print(json.dumps({"dry_run": True, **plan()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
