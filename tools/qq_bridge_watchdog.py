"""QQ Bridge Lite watchdog (P2, 2026-10-06).

Owns ONLY the Lite profile: verifies bridge ownership, writes/reads the
profile state, recovers the same profile with attempt accounting, and emits
fixed outage notices. It never imports the Full stack starters and never
manages daemon or models.

2026-10-10 扩展（应老爹要求）：账号监管——被踢下线/登出时自动重启 NapCat 走
快速登录（attempt 计数 + 冷却 + 熔断），NapCat 不在时按配置拉起；长时间未登录
（疑似等待扫码）发「需扫码」通知。NapCat 管理的 config 开关见 supervision 段。

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_watchdog.py --profile lite
    .venv\\Scripts\\python.exe tools\\qq_bridge_watchdog.py --once
    .venv\\Scripts\\python.exe tools\\qq_bridge_watchdog.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import socket
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

from backend.qq_bridge_lock import (  # noqa: E402
    LockError, acquire_pid_lock, make_info, owner_matches, read_info,
    release_pid_lock, terminate_owned,
)
from backend.qq_bridge_notices import NoticeStore  # noqa: E402

try:
    from tools.qq_bridge_service import (  # noqa: E402
        ProfileError, load_profile, read_desired, resolve,
    )
except ImportError:  # script execution (tools/ on sys.path)
    from qq_bridge_service import (  # type: ignore  # noqa: E402
        ProfileError, load_profile, read_desired, resolve,
    )

HEALTH_KEYS = ("process_alive", "event_loop_alive", "ws_connected",
               "account_online", "dev_available", "conversation_available")
STABLE_SECONDS = 5.0


def _read_json(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class RealChecker:
    """Read-only checks + owned spawn/terminate for the live Lite profile."""

    def __init__(self, resolved: dict) -> None:
        self.resolved = resolved
        self.entry = str(_ROOT / "tools" / "qq_bridge_service.py")
        self._settings: dict | None = None

    def _settings_read(self) -> dict:
        if self._settings is not None:
            return self._settings
        out: dict = {}
        try:
            import qq_bot

            cfg = pathlib.Path(self.resolved["onebot_config"]) \
                if self.resolved.get("onebot_config") \
                else qq_bot._find_onebot_config(self.resolved.get("uin"))
            s = qq_bot._ws_settings(cfg) or {}
            out = {"host": s.get("host", "127.0.0.1"),
                   "port": int(s.get("port", 3001)),
                   "uin": str(s.get("uin", "")), "token": s.get("token", "")}
        except Exception:
            out = {}
        self._settings = out
        return out

    def bot_uin(self) -> str:
        return str(self.resolved.get("uin") or self._settings_read().get("uin") or "unknown")

    def bridge_pid_info(self, state_dir: pathlib.Path) -> dict:
        return read_info(state_dir / "bridge.pid")

    def bridge_status(self, state_dir: pathlib.Path) -> dict:
        return _read_json(state_dir / "bridge_status.json")

    def onebot_reachable(self) -> bool:
        s = self._settings_read()
        if not s.get("port"):
            return False
        try:
            with socket.create_connection((s["host"], int(s["port"])), timeout=2):
                return True
        except Exception:
            return False

    def napcat_running(self) -> bool:
        """疑似 NapCat/QQ 实例在跑。

        2026-10-10：NapCatWinBootMain 注入后会退出，QQ.exe 命令行亦无特征位；
        保守口径——NapCatWinBootMain 或任意 QQ 客户端进程存在都算"在跑"，
        避免重复拉起第二份（宁可等待登录/提示扫码）。
        """
        try:
            import psutil

            for p in psutil.process_iter(["name"]):
                name = str(p.info.get("name") or "").lower()
                if "napcatwinbootmain" in name or name.startswith("qq"):
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def napcat_owned_alive(self, state_dir: pathlib.Path) -> bool:
        info = read_info(state_dir / "napcat.pid")
        if not info:
            return False
        ok, _ = owner_matches(info)
        return bool(ok)

    def launch_napcat(self, wait_s: float = 15.0) -> dict:
        try:
            from qq_bridge_control import ensure_napcat
        except ImportError:  # script execution
            from tools.qq_bridge_control import ensure_napcat  # type: ignore
        try:
            return ensure_napcat(self.resolved, wait_s=wait_s)
        except Exception as exc:  # noqa: BLE001
            return {"port_open": False, "started": False,
                    "error": type(exc).__name__}

    def restart_napcat(self, wait_s: float = 60.0) -> dict:
        try:
            from qq_bridge_control import stop_napcat
        except ImportError:  # script execution
            from tools.qq_bridge_control import stop_napcat  # type: ignore
        st = pathlib.Path(self.resolved["state_dir"])
        s = self._settings_read()
        try:
            stop = stop_napcat(st, host=s.get("host"), port=s.get("port"))
        except Exception as exc:  # noqa: BLE001
            stop = {"stopped": False, "reason": type(exc).__name__}
        if not stop.get("stopped") and stop.get("survivors"):
            # 2026-10-11 教训：旧实例没清干净时绝不再拉一份（互挤抢号）。
            return {"port_open": self.onebot_reachable(), "started": False,
                    "stop": stop, "skipped": "old_instance_alive"}
        out = self.launch_napcat(wait_s)
        out["stop"] = stop
        return out

    def spawn_bridge(self) -> None:
        env = dict(os.environ)
        env["YHLZ_QQ_PROFILE"] = self.resolved["profile"]
        env["YHLZ_QQ_STATE_DIR"] = str(self.resolved["state_dir"])
        cmd = [sys.executable, self.entry, "--profile", self.resolved["profile"],
               "--config", str(self.resolved.get("config_path") or
                               (_ROOT / "config" / "qq_bridge_lite.json")),
               "--state-dir", str(self.resolved["state_dir"])]
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        subprocess.Popen(cmd, cwd=str(_ROOT), env=env, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True)

    def verify(self, info: dict) -> tuple[bool, str]:
        if not info:
            return False, "missing"
        return owner_matches(info)

    def terminate(self, info: dict) -> tuple[bool, str]:
        return terminate_owned(info, entry=self.entry)

    def try_send_notice(self, text: str, recipient: str) -> str:
        """One-shot fixed-template notice; fail closed while the account lock
        is held by a live bridge (that bridge relays pending notices)."""
        from backend.qq_account_lock import AccountLock

        s = self._settings_read()
        if not s.get("uin"):
            return "locked"
        account = AccountLock(s["uin"])
        if not account.acquire():
            return "locked"
        try:
            import asyncio

            import qq_bot

            url = f"ws://{s['host']}:{s['port']}"
            if s.get("token"):
                url += f"?access_token={s['token']}"
            result = asyncio.run(qq_bot._napcat_call(
                url, "send_private_msg",
                {"user_id": int(recipient), "message": text}, timeout=10))
            if not result:
                return "unknown"
            if str(result.get("status")) == "ok":
                return "confirmed"
            return "unknown"
        except Exception:
            return "unknown"
        finally:
            account.release()


class FakeChecker:
    """Scripted checker for offline tests / evidence (no processes)."""

    def __init__(self, script: dict) -> None:
        self.script = script or {}
        self.calls: dict = {"spawn": 0, "terminate": 0, "notice_sends": [],
                            "ticks": 0}
        self._idx: dict = {}

    def _advance(self, key: str):
        seq = self.script.get(key, [])
        if not isinstance(seq, list):
            seq = [seq]
        if not seq:
            return None
        i = self._idx.get(key, 0)
        value = seq[min(i, len(seq) - 1)]
        self._idx[key] = i + 1
        return value

    def set_script(self, script: dict) -> None:
        self.script = script or {}
        self._idx = {}

    def _next(self, key: str, default=None):
        value = self._advance(key)
        return default if value is None else value

    def bot_uin(self) -> str:
        return str(self.script.get("uin") or "3655185302")

    def verify(self, info: dict) -> tuple[bool, str]:
        ok = bool(self._next("owner_ok", True))
        return ok, "ok" if ok else "pid_reused"

    def bridge_pid_info(self, state_dir: pathlib.Path) -> dict:
        self.calls["ticks"] += 1
        return self._next("bridge_pid_info", {}) or {}

    def bridge_status(self, state_dir: pathlib.Path) -> dict:
        return self._next("bridge_status", {}) or {}

    def onebot_reachable(self) -> bool:
        return bool(self._next("onebot_reachable", True))

    def napcat_running(self) -> bool:
        return bool(self._next("napcat_running", True))

    def napcat_owned_alive(self, state_dir: pathlib.Path) -> bool:
        return bool(self._next("napcat_owned_alive", False))

    def launch_napcat(self, wait_s: float = 15.0) -> dict:
        self.calls["napcat_launch"] = self.calls.get("napcat_launch", 0) + 1
        return self._next("launch_result", {"port_open": False}) or {}

    def restart_napcat(self, wait_s: float = 60.0) -> dict:
        self.calls["napcat_restart"] = self.calls.get("napcat_restart", 0) + 1
        return self._next("restart_result", {"port_open": False}) or {}

    def spawn_bridge(self) -> None:
        self.calls["spawn"] += 1

    def terminate(self, info: dict) -> tuple[bool, str]:
        self.calls["terminate"] += 1
        result = self._next("terminate_result", None)
        if isinstance(result, list) and result:
            outcome = (bool(result[0]), str(result[1] if len(result) > 1 else ""))
        else:
            outcome = (True, "terminated")
        self.calls.setdefault("terminate_results", []).append(outcome)
        return outcome

    def try_send_notice(self, text: str, recipient: str) -> str:
        result = self._next("send_results", "confirmed")
        self.calls["notice_sends"].append(
            {"text": text, "recipient": recipient, "result": result})
        return str(result)


class Watchdog:
    def __init__(self, resolved: dict, *, checker, now=None, log_fn=None,
                 jitter=None, state_dir: pathlib.Path | None = None) -> None:
        self.resolved = resolved
        cfg = resolved.get("config") or {}
        recovery = cfg.get("recovery") or {}
        self.checker = checker
        self.now = now or time.time
        self._log_fn = log_fn
        self._jitter = jitter or (lambda: random.uniform(0.8, 1.2))
        self.state_dir = pathlib.Path(state_dir or resolved["state_dir"])
        self.state_path = self.state_dir / "watchdog_state.json"
        self.log_path = self.state_dir / "watchdog.log"
        self.interval = float(recovery.get("check_interval_seconds", 2))
        self.attempt_timeout = float(recovery.get("attempt_timeout_seconds", 15))
        self.attempt2_delay = float(recovery.get("attempt2_delay_seconds", 2))
        self.stall_seconds = float(recovery.get("stall_seconds", 30))
        self.start_grace = float(recovery.get("start_grace_seconds", 30))
        self.backoff = tuple(float(x) for x in
                             (recovery.get("backoff_seconds") or [15, 30, 60]))
        self.blocked_after = int(recovery.get("blocked_after_failures", 5))
        self.blocked_retry = float(recovery.get("blocked_retry_seconds", 600))
        self.recipient = str((resolved.get("masters") or ["2258374446"])[0])
        self.uin = str(resolved.get("uin") or checker.bot_uin())
        # 账号监管（2026-10-10）：NapCat 存在性 + 被踢自动重登。
        sup = cfg.get("supervision") or {}
        self.auto_start_napcat = bool(sup.get("auto_start_napcat", True))
        self.auto_relogin = bool(sup.get("auto_relogin", True))
        self.napcat_miss_grace = float(
            sup.get("napcat_miss_grace_seconds", 120))
        self.napcat_launch_cooldown = float(
            sup.get("napcat_launch_cooldown_seconds", 300))
        self.napcat_max_attempts = int(sup.get("napcat_max_attempts", 3))
        self.napcat_launch_wait = float(
            sup.get("napcat_launch_wait_seconds", 15))
        self.account_grace = float(
            sup.get("account_offline_grace_seconds", 150))
        self.account_max_attempts = int(sup.get("account_max_attempts", 3))
        self.account_restart_cooldown = float(
            sup.get("account_restart_cooldown_seconds", 300))
        self.account_recover_wait = float(
            sup.get("account_recover_wait_seconds", 60))
        self.account_blocked_retry = float(
            sup.get("account_blocked_retry_seconds", 900))
        self.scan_notice_after = float(
            sup.get("scan_notice_after_seconds", 600))
        self.store = NoticeStore(self.state_dir / "notices.jsonl",
                                 bot_uin=self.uin)
        self.state = _read_json(self.state_path) or self._fresh_state()
        for key, value in self._fresh_state().items():
            self.state.setdefault(key, value)

    def _fresh_state(self) -> dict:
        return {"phase": "starting", "outage_id": "", "attempt": 0,
                "attempt_deadline": 0.0, "next_attempt_at": 0.0,
                "consecutive_failures": 0, "blocked_until": 0.0,
                "seen_bridge": False, "healthy_since": 0.0,
                "stale_since": 0.0, "lost_created": False,
                "updated_at": 0.0,
                # 账号监管（2026-10-10）
                "napcat_missing_since": 0.0, "napcat_last_launch_at": 0.0,
                "napcat_launch_count": 0,
                "account_offline_since": 0.0, "account_attempts": 0,
                "account_last_restart_at": 0.0, "account_blocked_until": 0.0,
                "account_episode_id": "", "account_lost_created": False,
                "account_scan_noticed": False, "account_requires_login": False}

    def _save_state(self) -> None:
        self.state["updated_at"] = self.now()
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.state_path)
        except Exception:
            pass

    def log(self, msg: str) -> None:
        line = f"[wd] {time.strftime('%H:%M:%S')} {msg}"
        if self._log_fn is not None:
            self._log_fn(line)
            return
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with (self.state_dir / "watchdog.log").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def health(self, info: dict, status: dict) -> dict:
        now = self.now()
        alive, reason = self.checker.verify(info)
        loop_ts = float(status.get("event_loop_ts") or 0.0)
        fresh = bool(alive and loop_ts and (now - loop_ts) <= self.stall_seconds)
        return {
            "process_alive": bool(alive),
            "process_reason": reason,
            "event_loop_alive": fresh,
            "ws_connected": bool(alive and status.get("state") == "connected"),
            "account_online": status.get("account_online")
            if isinstance(status.get("account_online"), bool) else None,
            "dev_available": status.get("dev_state") is not None if status else None,
            "conversation_available": status.get("state") == "connected"
            if status else None,
        }

    def _outage_recipient(self) -> str:
        return self.recipient

    # ---- 账号监管（2026-10-10）：NapCat 存在性 + 被踢自动重登 ----
    def _episode_id(self) -> str:
        eid = str(self.state.get("account_episode_id") or "")
        if not eid:
            base = float(self.state.get("account_offline_since")
                         or self.state.get("napcat_missing_since")
                         or self.now())
            eid = f"acct{int(base)}"
            self.state["account_episode_id"] = eid
        return eid

    def _awaiting_scan(self, now: float, window_s: float = 150.0) -> bool:
        """近 window_s 内生成过二维码 → 实例正在等扫码。

        2026-10-11：扫码成功→桥状态翻转为在线之间有几十秒盲区，重登
        冷却一到就重启会把用户刚扫的会话毁掉（实例事故）。等扫码期间
        一律不重启，靠提醒等人工。测试可用 qr_guard_path 注入隔离。
        """
        try:
            p = getattr(self, "qr_guard_path", None)
            if p is None:
                from backend.yhlz_paths import NAPCAT_QR

                p = NAPCAT_QR
            p = pathlib.Path(p)
            if not p.is_file():
                return False
            stamp = p.stat().st_mtime
            episode = float(self.state.get("account_offline_since") or 0)
            return (now - stamp) <= window_s or bool(episode and stamp >= episode)
        except Exception:
            return False

    def _supervise(self, now: float, status: dict, health: dict) -> None:
        # 1) NapCat 存在性：端口不可达太久；没在跑就拉起，在跑则等登录/扫码。
        reachable = self.checker.onebot_reachable()
        if reachable:
            self.state["napcat_missing_since"] = 0.0
            if health.get("account_online") is True:
                self.state["napcat_launch_count"] = 0
        else:
            if not self.state.get("napcat_missing_since"):
                self.state["napcat_missing_since"] = now
            missing = now - float(self.state["napcat_missing_since"])
            running = (self.checker.napcat_running()
                       or self.checker.napcat_owned_alive(self.state_dir))
            if running:
                if (missing >= self.scan_notice_after
                        and not self.state.get("account_scan_noticed")):
                    self._create_notice("account_needs_scan",
                                        outage_id=self._episode_id())
                    self.state["account_scan_noticed"] = True
                    self.log(f"NapCat 在运行但端口不可达 {missing:.0f}s："
                             "疑似等待扫码，已发提示")
            else:
                last = float(self.state.get("napcat_last_launch_at") or 0)
                if (self.auto_start_napcat
                        and int(self.state.get("napcat_launch_count", 0)) < self.napcat_max_attempts
                        and missing >= self.napcat_miss_grace
                        and (not last
                             or now >= last + self.napcat_launch_cooldown)):
                    self.state["napcat_last_launch_at"] = now
                    self.state["napcat_launch_count"] = int(
                        self.state.get("napcat_launch_count", 0)) + 1
                    self.log(f"NapCat 未运行且端口不可达 {missing:.0f}s："
                             f"拉起尝试 #{self.state['napcat_launch_count']}")
                    try:
                        out = self.checker.launch_napcat(self.napcat_launch_wait)
                        self.log("NapCat 拉起结果: port_open="
                                 f"{bool(out.get('port_open'))}"
                                 + (f" err={out.get('error')}"
                                    if out.get("error") else ""))
                    except Exception as exc:  # noqa: BLE001
                        self.log(f"NapCat 拉起异常 {type(exc).__name__}")
        # 2) 账号离线（WS 连接正常时判定为被踢/掉登录）→ 重启 NapCat 自动重登。
        acct = health.get("account_online")
        ws_ok = bool(health.get("process_alive") and health.get("ws_connected"))
        if ws_ok and acct is False and self.auto_relogin:
            if not self.state.get("account_offline_since"):
                self.state["account_offline_since"] = now
            offline = now - float(self.state["account_offline_since"])
            if offline >= self.account_grace:
                blocked_until = float(
                    self.state.get("account_blocked_until") or 0)
                if now >= blocked_until and not self.state.get("account_requires_login"):
                    attempts = int(self.state.get("account_attempts", 0))
                    last = float(self.state.get("account_last_restart_at") or 0)
                    if attempts >= self.account_max_attempts:
                        self.state["account_blocked_until"] = (
                            now + self.account_blocked_retry)
                        self.state["account_requires_login"] = True
                        if not self.state.get("account_scan_noticed"):
                            self._create_notice("account_needs_scan",
                                                outage_id=self._episode_id())
                            self.state["account_scan_noticed"] = True
                        self.log(f"账号离线 {offline:.0f}s：自动重登 "
                                 f"{attempts} 次未恢复，"
                                 "已停止自动重登，等待手动登录或重新启动QQ桥")
                    elif self._awaiting_scan(now):
                        # 手里已有"待扫码"实例（二维码新鲜）：重启只会毁掉
                        # 用户正在扫的进度并制造新码；继续等，超时提醒。
                        if (offline >= self.scan_notice_after
                                and not self.state.get("account_scan_noticed")):
                            self._create_notice("account_needs_scan",
                                                outage_id=self._episode_id())
                            self.state["account_scan_noticed"] = True
                            self.log(f"账号离线 {offline:.0f}s 等待扫码：已发提醒")
                    elif (not last
                          or now >= last + self.account_restart_cooldown):
                        self.state["account_attempts"] = attempts + 1
                        self.state["account_last_restart_at"] = now
                        if not self.state.get("account_lost_created"):
                            self._create_notice("account_lost",
                                                outage_id=self._episode_id())
                            self.state["account_lost_created"] = True
                        self.log(f"账号离线 {offline:.0f}s：重启 NapCat "
                                 f"自动重登 尝试#{attempts + 1}")
                        try:
                            out = self.checker.restart_napcat(
                                self.account_recover_wait)
                            self.log("重登尝试结果: port_open="
                                     f"{bool(out.get('port_open'))}")
                        except Exception as exc:  # noqa: BLE001
                            self.log(f"重登尝试异常 {type(exc).__name__}")
        elif acct is True and ws_ok:
            if (self.state.get("account_lost_created")
                    or self.state.get("account_scan_noticed")):
                self._create_notice("account_recovered",
                                    outage_id=self._episode_id())
                self.log("账号已恢复在线")
            self.state["account_offline_since"] = 0.0
            self.state["account_attempts"] = 0
            self.state["account_blocked_until"] = 0.0
            self.state["account_requires_login"] = False
            self.state["account_lost_created"] = False
            self.state["account_scan_noticed"] = False
            self.state["account_episode_id"] = ""

    def _create_notice(self, kind: str, *,
                       outage_id: str | None = None) -> dict:
        record = self.store.create(
            outage_id=str(outage_id or self.state["outage_id"]),
            kind=kind, recipient=self._outage_recipient(), now=self.now())
        if record.get("status") in ("pending",):
            send = self.checker.try_send_notice(record["text"],
                                                record["recipient"])
            mapping = {"confirmed": "sent", "unknown": "unknown"}
            self.store.mark(record["notice_id"], mapping.get(send, "pending"),
                            error="" if send == "confirmed" else send,
                            now=self.now())
            self.log(f"通知 {kind}: try={send}")
        return record

    def _begin_outage(self) -> None:
        if not self.state.get("outage_id"):
            self.state["outage_id"] = f"out{int(self.now())}"
            self.state["attempt"] = 0
            self.state["lost_created"] = False
            self.state["next_attempt_at"] = self.now()
            self.state["outage_seen_bridge"] = bool(
                self.state.get("seen_bridge"))
            self.log(f"outage 开始 id={self.state['outage_id']}")

    def _start_attempt(self) -> None:
        self.state["attempt"] = int(self.state.get("attempt", 0)) + 1
        attempt = self.state["attempt"]
        self.state["attempt_deadline"] = self.now() + self.attempt_timeout
        self.state["next_attempt_at"] = self.state["attempt_deadline"]
        self.state["phase"] = f"recovering(attempt{attempt})"
        try:
            self.checker.spawn_bridge()
            self.log(f"attempt{attempt}: 已拉起同一 Lite profile")
        except Exception as exc:  # noqa: BLE001
            self.log(f"attempt{attempt}: 拉起失败 {type(exc).__name__}")
        self._save_state()

    def _attempt_failed(self) -> None:
        self.state["consecutive_failures"] = \
            int(self.state.get("consecutive_failures", 0)) + 1
        failures = self.state["consecutive_failures"]
        attempt = int(self.state.get("attempt", 1))
        self.state["attempt_deadline"] = 0.0
        if attempt >= 2 and not self.state.get("lost_created"):
            self._create_notice("lost")
            self.state["lost_created"] = True
        if failures >= self.blocked_after:
            self.state["phase"] = "blocked"
            self.state["blocked_until"] = self.now() + self.blocked_retry
            self.log(f"熔断：连续 {failures} 次失败，{self.blocked_retry:g}s 后重试")
        else:
            if attempt <= 1:
                wait = self.attempt2_delay
            else:
                idx = min(max(attempt - 2, 0), len(self.backoff) - 1)
                wait = self.backoff[idx] * self._jitter()
            self.state["phase"] = "backoff"
            self.state["next_attempt_at"] = self.now() + wait
            self.log(f"attempt{attempt} 失败，{wait:.1f}s 后再试")
        self._save_state()

    def tick(self) -> dict:
        now = self.now()
        desired = read_desired(self.state_dir)
        if desired == "stopped":
            self.state["phase"] = "stopped"
            # 计划停机不报警：清除 outage 痕迹，恢复后按首次启动处理。
            self.state["outage_id"] = ""
            self.state["lost_created"] = False
            self.state["outage_seen_bridge"] = False
            self.state["seen_bridge"] = False
            self.state["attempt"] = 0
            self.state["consecutive_failures"] = 0
            self._save_state()
            return self.snapshot()

        info = self.checker.bridge_pid_info(self.state_dir)
        status = self.checker.bridge_status(self.state_dir)
        health = self.health(info, status)
        self._supervise(now, status, health)

        if health["process_alive"] and health["event_loop_alive"]:
            if not self.state.get("healthy_since"):
                self.state["healthy_since"] = now
            self.state["phase"] = "healthy"
            self.state["seen_bridge"] = True
            stable = (now - self.state["healthy_since"]) >= STABLE_SECONDS
            if stable:
                had_outage = bool(self.state.get("outage_id"))
                # 首次启动成功不发"已接续"；只有故障前桥曾在线才发。
                if had_outage and self.state.get("outage_seen_bridge"):
                    self._create_notice("recovered")
                self.state["outage_id"] = ""
                self.state["attempt"] = 0
                self.state["lost_created"] = False
                self.state["consecutive_failures"] = 0
                self.state["blocked_until"] = 0.0
            self.state["stale_since"] = 0.0
            self._save_state()
            return self.snapshot()

        if health["process_alive"] and not health["event_loop_alive"]:
            if not self.state.get("stale_since"):
                self.state["stale_since"] = now
            stuck = now - self.state["stale_since"]
            deadline = max(self.start_grace, self.stall_seconds)
            if stuck >= deadline:
                ok, reason = self.checker.terminate(info)
                self.log(f"疑似卡死 {stuck:.0f}s，终止归属进程 ok={ok} ({reason})")
                self.state["stale_since"] = 0.0
            if self.state.get("attempt_deadline") and \
                    now >= float(self.state["attempt_deadline"]):
                self._attempt_failed()
            self._save_state()
            return self.snapshot()

        if self.state.get("phase") == "blocked" and \
                now < float(self.state.get("blocked_until") or 0):
            return self.snapshot()

        self._begin_outage()
        if self.state.get("phase", "").startswith("recovering") and \
                self.state.get("attempt_deadline") and \
                now >= float(self.state["attempt_deadline"]):
            self._attempt_failed()
            if self.state.get("phase") != "backoff":
                return self.snapshot()
        if now >= float(self.state.get("next_attempt_at") or 0):
            self._start_attempt()
        self._save_state()
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            "phase": self.state.get("phase"),
            "outage_id": self.state.get("outage_id"),
            "attempt": self.state.get("attempt"),
            "consecutive_failures": self.state.get("consecutive_failures"),
            "blocked_until": self.state.get("blocked_until"),
            "notices": self.store.summary(),
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QQ Bridge Lite watchdog (P2)")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--config", default=str(_ROOT / "config" / "qq_bridge_lite.json"))
    ap.add_argument("--state-dir", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--fake-checker", default=None,
                    help="JSON script for offline checker injection")
    args = ap.parse_args(argv)
    try:
        cfg = load_profile(pathlib.Path(args.config))
        from argparse import Namespace

        resolved = resolve(Namespace(
            profile=args.profile, config=args.config, master=None,
            conversation=None, uin=None, onebot_config=None,
            state_dir=args.state_dir, voice=None), cfg)
        resolved["config"] = cfg
        resolved["config_path"] = args.config
    except ProfileError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    state_dir = pathlib.Path(resolved["state_dir"])
    if args.status:
        state = _read_json(state_dir / "watchdog_state.json")
        print(json.dumps({"ok": True, "state_dir": str(state_dir),
                          "watchdog": state,
                          "bridge_pid": read_info(state_dir / "bridge.pid"),
                          "notices": NoticeStore(
                              state_dir / "notices.jsonl",
                              bot_uin=str(resolved.get("uin") or "")).summary()},
                         ensure_ascii=False))
        return 0
    if args.fake_checker:
        script = json.loads(pathlib.Path(args.fake_checker).read_text("utf-8"))
        checker = FakeChecker(script)
    else:
        checker = RealChecker(resolved)
    wd = Watchdog(resolved, checker=checker)
    if args.interval is not None:
        wd.interval = args.interval
    if args.once:
        snap = wd.tick()
        print(json.dumps({"ok": True, "snapshot": snap,
                          "calls": getattr(checker, "calls", {})},
                         ensure_ascii=False))
        return 0
    info = make_info(resolved["profile"],
                     entry=str(pathlib.Path(__file__).resolve()), role="watchdog")
    try:
        acquire_pid_lock(state_dir / "watchdog.lock", info)
    except LockError as exc:
        print(f"[wd] 启动失败：{exc}", flush=True)
        return 3
    wd.log(f"watchdog start pid={os.getpid()} interval={wd.interval:g}s")
    try:
        while True:
            wd.tick()
            time.sleep(wd.interval)
    except KeyboardInterrupt:
        pass
    finally:
        release_pid_lock(state_dir / "watchdog.lock", info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
