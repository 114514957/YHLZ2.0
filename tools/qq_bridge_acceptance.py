"""QQ Bridge Lite acceptance summary (P5).

Scans artifacts/qq_lite/<run>/ evidence and prints a Gate 0-5 table; writes
acceptance.json next to the newest evidence root. Pending real-machine items
(Gate 5 real QQ, NapCat login recovery, 24h observation) are reported as
pending, never as passed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
ART = _ROOT / "artifacts" / "qq_lite"


def _latest(prefix: str) -> pathlib.Path | None:
    dirs = sorted(p for p in ART.glob(prefix + "*") if p.is_dir())
    return dirs[-1] if dirs else None


def _read(path: pathlib.Path | None, name: str) -> dict:
    if path is None:
        return {}
    try:
        return json.loads((path / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect() -> dict:
    p0 = _latest("p0_")
    p1 = _latest("p1_")
    p2 = _latest("p2_")
    p3 = _latest("p3_")
    p4 = _latest("p4_")
    p5_fault = (_ROOT / "artifacts" / "qq_lite" / "fault_30min")
    p5_soak = (_ROOT / "artifacts" / "qq_lite" / "soak_2h")

    gates = {
        "gate0_static_isolation": {
            "pass": bool(_read(p0, "manifest.json").get("gate0", {})
                         .get("pass")),
            "evidence": str(p0 / "manifest.json") if p0 else "",
        },
        "gate1_resident": {
            "pass": bool(_read(p1, "fake_echo.json").get("pass"))
            and bool(_read(p2, "restart_matrix.json").get("pass")),
            "evidence": [str(p1 / "fake_echo.json") if p1 else "",
                         str(p2 / "restart_matrix.json") if p2 else ""],
        },
        "gate2_owner_dev": {
            "pass": bool(_read(p3, "p3_matrix.json").get("pass")),
            "evidence": str(p3 / "p3_matrix.json") if p3 else "",
        },
        "gate3_conversation": {
            "pass": bool(_read(p4, "p4_matrix.json").get("pass")),
            "evidence": str(p4 / "p4_matrix.json") if p4 else "",
        },
        "gate4_delivery_reconnect": {
            "pass": bool(_read(p2, "restart_matrix.json").get("pass"))
            and bool(_read(p4, "p4_matrix.json").get("pass")),
            "evidence": "P2 矩阵 + P4 chat/sticker 投递语义",
        },
        "gate5_longrun": {
            "pass": bool(_read(p5_fault, "fault_30min.json").get("pass")),
            "fault_30min": _read(p5_fault, "fault_30min.json"),
            "soak_2h_pending": not (p5_soak / "soak_2h.json").exists(),
            "evidence": str(p5_fault / "fault_30min.json"),
        },
    }
    pending_real = [
        "NapCat owned 登录恢复 needs_login 真机验证",
        "真实 QQ 收发验证（认主、非主人聊天、群 50 条上下文）",
        "30 分钟真实故障注入与 2 小时实机常驻",
        "24 小时观察与资源时序报告",
    ]
    overall = all(g["pass"] for k, g in gates.items()
                  if k != "gate5_longrun") and gates["gate5_longrun"]["pass"]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gates": gates,
        "offline_overall_pass": overall,
        "pending_real_machine": pending_real,
        "note": "全部通过项均为离线 fake 传输/假 agent 证据；真机项未做不得宣称完成。",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ART / "acceptance.json"))
    args = ap.parse_args()
    report = collect()
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[acceptance] out={args.out} offline_pass={report['offline_overall_pass']}")
    for name, gate in report["gates"].items():
        print(f"[acceptance] {name} = {gate['pass']}")
    for item in report["pending_real_machine"]:
        print(f"[acceptance] pending: {item}")
    return 0 if report["offline_overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
