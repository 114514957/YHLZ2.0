"""QQ Bridge Lite service entry (P1/P2, 2026-10-06).

Owns profile startup: resolve config, set profile env before importing the
bridge, create state dir / pid lock / account mutex / log, then run the
bridge. Never imports the Full launcher/watchdog and never starts
daemon/models/NapCat.

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_service.py --profile lite --check
    .venv\\Scripts\\python.exe tools\\qq_bridge_service.py --profile lite
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
DEFAULT_CONFIG = _ROOT / "config" / "qq_bridge_lite.json"
OWNER_UINS = ("2258374446",)
DESIRED_FILE = "desired_state.json"


class ProfileError(RuntimeError):
    """Fail-closed profile validation error."""


def load_profile(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"profile 不存在: {path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ProfileError(f"profile 无法解析: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise ProfileError("profile 必须是 JSON 对象")
    tokens = [k for k, v in data.items() if "token" in k.lower() and v]
    if tokens:
        raise ProfileError(f"profile 不得包含 token 字段: {tokens}")
    return data


def resolve(args: argparse.Namespace, cfg: dict) -> dict:
    from backend.yhlz_paths import MASTER_UIN

    profile = (getattr(args, "profile", None)
               or os.getenv("YHLZ_QQ_PROFILE", "").strip()
               or str(cfg.get("profile") or "lite"))
    state_dir = (getattr(args, "state_dir", None)
                 or os.getenv("YHLZ_QQ_STATE_DIR", "").strip()
                 or str(cfg.get("state_dir") or "")
                 or str(_ROOT / "cache" / "qq_bridge" / profile))
    masters = [str(m) for m in (getattr(args, "master", None) or [])]
    if not masters:
        env = os.getenv("YHLZ_QQ_MASTER_UINS", "").strip()
        masters = [m.strip() for m in env.split(",") if m.strip()]
    if not masters:
        masters = [str(m) for m in (cfg.get("master_uins") or [])]
    if not masters:
        masters = [str(MASTER_UIN)]
    if len(masters) != 1 or masters[0] != OWNER_UINS[0]:
        raise ProfileError(
            f"owner 只能且必须是 {OWNER_UINS[0]}，收到 {masters}；"
            "--master 不能静默追加第二个主人")
    voice = getattr(args, "voice", None)
    if voice is None:
        env = os.getenv("YHLZ_QQ_ENABLE_VOICE", "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            voice = True
        elif env in ("0", "false", "no", "off"):
            voice = False
        else:
            voice = bool(cfg.get("enable_voice", False))
    conversation = (getattr(args, "conversation", None)
                    or str(cfg.get("conversation") or "") or "optional")
    uin = (getattr(args, "uin", None)
           or os.getenv("YHLZ_QQ_BOT_UIN", "").strip())
    cfg_uin = str(cfg.get("uin") or "")
    if not uin and cfg_uin and "<" not in cfg_uin:
        uin = cfg_uin
    onebot = (getattr(args, "onebot_config", None)
              or os.getenv("YHLZ_QQ_ONEBOT_CONFIG", "").strip() or "")
    cfg_onebot = str(cfg.get("onebot_config") or "")
    if not onebot and cfg_onebot and "<" not in cfg_onebot:
        onebot = cfg_onebot
    return {
        "profile": profile,
        "state_dir": state_dir,
        "masters": masters,
        "voice": bool(voice),
        "conversation": conversation,
        "uin": uin or None,
        "onebot_config": onebot or None,
        "config": cfg,
    }


def _fp(value: str) -> str:
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def read_desired(state_dir: pathlib.Path) -> str:
    try:
        data = json.loads((state_dir / DESIRED_FILE).read_text(encoding="utf-8"))
        value = str(data.get("desired") or "").strip().lower()
        return value if value in ("running", "stopped") else "running"
    except Exception:
        return "running"


def write_desired(state_dir: pathlib.Path, value: str) -> None:
    value = "stopped" if str(value).lower() == "stopped" else "running"
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / (DESIRED_FILE + ".tmp")
    tmp.write_text(json.dumps({"desired": value, "updated_at": time.time()},
                              ensure_ascii=False), encoding="utf-8")
    tmp.replace(state_dir / DESIRED_FILE)


def _apply_timing_env(cfg: dict) -> None:
    limits = cfg.get("limits") if isinstance(cfg.get("limits"), dict) else {}
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    mapping = {
        "YHLZ_QQ_PING_INTERVAL": str(cfg.get("heartbeat_seconds") or 10),
        "YHLZ_QQ_PONG_TIMEOUT": str(cfg.get("pong_timeout_seconds") or 5),
        "YHLZ_QQ_STATUS_INTERVAL": str(cfg.get("status_interval_seconds") or 5),
        "YHLZ_QQ_INBOX_LIMIT": str(cfg.get("inbox_limit") or 128),
        "YHLZ_QQ_CHAT_CONCURRENCY": str(cfg.get("chat_concurrency") or 2),
        "YHLZ_QQ_GROUP_USER_COOLDOWN": str(
            limits.get("group_user_cooldown_seconds") or 30),
        "YHLZ_QQ_GROUP_CHAN_PER_MIN": str(
            limits.get("group_chan_per_minute") or 6),
        "YHLZ_QQ_GROUP_CHAN_GAP": str(
            limits.get("group_chan_gap_seconds") or 20),
        "YHLZ_QQ_GROUP_DAILY_LIMIT": str(
            limits.get("group_daily_limit") or 120),
        "YHLZ_QQ_PRIVATE_USER_COOLDOWN": str(
            limits.get("private_user_cooldown_seconds") or 30),
        "YHLZ_QQ_PROFILE_REFRESH": str(
            profiles.get("refresh_seconds") or 600),
        "YHLZ_QQ_PROFILE_MIN_MSGS": str(
            profiles.get("min_messages") or 1),
        "YHLZ_QQ_PROFILE_INJECT": "1" if profiles.get("inject", True) else "0",
    }
    for key, value in mapping.items():
        os.environ.setdefault(key, value)


def _wake_names_from(cfg_wake: dict) -> list:
    raw = (cfg_wake or {}).get("names") or ["元亨", "利贞"]
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[,，;；\s]+", raw)]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw]
    else:
        parts = []
    out: list[str] = []
    for name in parts:
        if name and name not in out:
            out.append(name)
    return out or ["元亨", "利贞"]


def _apply_wake_env(cfg: dict) -> None:
    """唤醒闸门配置（2026-10-08）：config.wake → 环境变量（不覆盖已有值）。"""
    wake = cfg.get("wake") if isinstance(cfg.get("wake"), dict) else {}
    try:
        topic_min = max(1, int(wake.get("topic_min_chars") or 4))
    except Exception:  # noqa: BLE001
        topic_min = 4
    mapping = {
        "YHLZ_QQ_WAKE": "1" if bool(wake.get("enabled", True)) else "0",
        "YHLZ_QQ_WAKE_MODE": str(wake.get("mode") or "lively"),
        "YHLZ_QQ_WAKE_NAMES": ",".join(_wake_names_from(wake)),
        "YHLZ_QQ_WAKE_TOPICS": "1" if bool(wake.get("topics", True)) else "0",
        "YHLZ_QQ_WAKE_MEMORY": "1" if bool(wake.get("memory", True)) else "0",
        "YHLZ_QQ_WAKE_TOPIC_MIN": str(topic_min),
        "YHLZ_QQ_WAKE_MASTER": ("1" if bool(wake.get("master_always", True))
                                else "0"),
        "YHLZ_QQ_WAKE_SILENCE": "1" if bool(wake.get("silence", True)) else "0",
    }
    raw_groups = cfg.get("groups") or []
    if isinstance(raw_groups, str):
        raw_groups = re.split(r"[,，;；\s]+", raw_groups)
    groups = [str(g).strip() for g in raw_groups if str(g).strip()] \
        if isinstance(raw_groups, (list, tuple)) else []
    if groups:
        mapping["YHLZ_QQ_GROUPS"] = ",".join(groups)
    raw_at = wake.get("at_only_groups") or []
    if isinstance(raw_at, str):
        raw_at = re.split(r"[,，;；\s]+", raw_at)
    at_only = [str(g).strip() for g in raw_at if str(g).strip()] \
        if isinstance(raw_at, (list, tuple)) else []
    if at_only:
        mapping["YHLZ_QQ_WAKE_AT_ONLY_GROUPS"] = ",".join(at_only)
    for key, value in mapping.items():
        os.environ.setdefault(key, value)


def _apply_dev_env(cfg: dict, state_dir: pathlib.Path) -> None:
    raw_ws = str(cfg.get("dev_workspace") or "").strip()
    if not raw_ws:
        ws_path = state_dir / "dev_workspace"
    else:
        p = pathlib.Path(raw_ws)
        ws_path = p if p.is_absolute() else (_ROOT / p)
    mapping = {
        "YHLZ_QQ_DEV_DB": str(state_dir / "dev_jobs.db"),
        "YHLZ_QQ_DEV_WORKSPACE": str(ws_path),
        "YHLZ_QQ_DEV_TARGET": str(_ROOT),
        "YHLZ_QQ_DEV_BACKEND": str(cfg.get("dev_backend") or "dsh"),
        "YHLZ_QQ_DEV_TIMEOUT": str(cfg.get("dev_timeout_seconds") or 1800),
        "YHLZ_DEV_AGENT": str(cfg.get("dev_agent") or "yhlz-dev"),
    }
    if str(cfg.get("dev_model") or "").strip():
        mapping["YHLZ_DEV_MODEL"] = str(cfg["dev_model"]).strip()
    for key, value in mapping.items():
        os.environ.setdefault(key, value)


def run_service(resolved: dict) -> int:
    from backend.qq_account_lock import AccountLock, lock_info
    from backend.qq_bridge_lock import LockError, acquire_pid_lock, \
        make_info, release_pid_lock

    # ledger 0815：桥也可能从带畸形 NO_PROXY（`[::1]`）的父进程继承环境——
    # 那会让所有 httpx 调用抛 InvalidURL（daemon 侧已因此全哑过一次）。
    try:
        from backend.env_loader import ensure_env_loaded, sanitize_proxy_env

        ensure_env_loaded()
        for _change in sanitize_proxy_env():
            print(f"[service] env: {_change}", flush=True)
    except Exception:
        pass
    state_dir = pathlib.Path(resolved["state_dir"])
    if read_desired(state_dir) == "stopped":
        print("[service] desired_state=stopped，退出（不会拉起桥）", flush=True)
        return 0
    info = make_info(resolved["profile"],
                     entry=str(pathlib.Path(__file__).resolve()), role="bridge")
    try:
        acquire_pid_lock(state_dir / "bridge.lock", info)
    except LockError as exc:
        print(f"[service] 启动失败：{exc}", flush=True)
        return 3
    account = None
    try:
        log = open(state_dir / "bridge.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = log
        sys.stderr = log

        os.environ["YHLZ_QQ_PROFILE"] = resolved["profile"]
        os.environ["YHLZ_QQ_STATE_DIR"] = str(state_dir)
        os.environ["YHLZ_QQ_ENABLE_VOICE"] = "1" if resolved["voice"] else "0"
        daemon_url = str((resolved.get("config") or {}).get("daemon_url") or "").strip()
        if daemon_url:
            # 利贞桥指向 harness worker，而不是元亨的 8321 daemon。
            os.environ["DAEMON"] = daemon_url
            print(f"[service] DAEMON={daemon_url}", flush=True)
        _apply_timing_env(resolved.get("config") or {})
        _apply_wake_env(resolved.get("config") or {})
        _apply_dev_env(resolved.get("config") or {}, state_dir)
        sys.path.insert(0, str(_ROOT / "tools"))
        sys.path.insert(0, str(_ROOT))

        import qq_bot  # imported only after profile env is fixed

        cfg = pathlib.Path(resolved["onebot_config"]) if resolved["onebot_config"] \
            else qq_bot._find_onebot_config(resolved["uin"])
        settings = qq_bot._ws_settings(cfg)
        if not settings:
            raise ProfileError(f"OneBot 配置无启用的 ws server: {cfg}")

        account = AccountLock(settings["uin"])
        if not account.acquire():
            print(f"[service] 账号锁 {lock_info(settings['uin'])['name']} "
                  f"被占用，fail closed（拒绝第二个消费者）", flush=True)
            return 4
        info["account_lock"] = lock_info(settings["uin"])
        info["uin_fingerprint"] = _fp(settings["uin"])

        url = f"ws://{settings['host']}:{settings['port']}"
        if settings.get("token"):
            url += f"?access_token={settings['token']}"
        bridge = qq_bot.QQBridge(url, settings["uin"], cfg,
                                 masters=set(resolved["masters"]))
        bridge.conversation = resolved["conversation"]
        info["instance_id"] = bridge.instance_id
        (state_dir / "bridge.pid").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"=== qq_bridge_service start {time.strftime('%Y-%m-%d %H:%M:%S')} "
              f"pid={os.getpid()} instance={bridge.instance_id} ===", flush=True)
        print(f"[service] profile={resolved['profile']} state_dir={state_dir} "
              f"ws={settings['host']}:{settings['port']} "
              f"uin={info['uin_fingerprint']} "
              f"voice={'on' if resolved['voice'] else 'text-only'} "
              f"conversation={resolved['conversation']}", flush=True)
        import asyncio

        asyncio.run(bridge.run())
        return 0
    finally:
        if account is not None:
            account.release()
        release_pid_lock(state_dir / "bridge.lock", info)
        (state_dir / "bridge.pid").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QQ Bridge Lite service (P1/P2)")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="profile JSON (非敏感配置)")
    ap.add_argument("--master", action="append", default=None)
    ap.add_argument("--conversation", default=None)
    ap.add_argument("--uin", default=None)
    ap.add_argument("--onebot-config", default=None)
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--voice", dest="voice", action="store_true", default=None)
    ap.add_argument("--no-voice", dest="voice", action="store_false")
    ap.add_argument("--check", action="store_true",
                    help="只解析并校验 profile，不启动桥")
    args = ap.parse_args(argv)
    try:
        cfg = load_profile(pathlib.Path(args.config))
        resolved = resolve(args, cfg)
    except ProfileError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.check:
        public = {k: v for k, v in resolved.items() if k != "config"}
        print(json.dumps({"ok": True, **public}, ensure_ascii=False))
        return 0
    return run_service(resolved)


if __name__ == "__main__":
    raise SystemExit(main())
