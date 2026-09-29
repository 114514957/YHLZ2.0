"""Acceptance checklist verification (Step 4 prep).

Runs automated checks for the 7-point manual acceptance checklist.
Items requiring human input are marked [人工]; automated items are [自动].

Usage:
    python tools/acceptance_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check_1_owner_chat() -> dict:
    """[人工] 主人私聊：普通聊天，确认只有一次正常回复。"""
    return {"id": 1, "name": "主人私聊", "type": "人工",
            "description": "发一条普通消息，确认只收到一次回复",
            "automated": False}


def check_2_speaker_identity() -> dict:
    """[人工] 测试群两位成员分别发不同偏好，确认说话者没混淆。"""
    return {"id": 2, "name": "说话者区分", "type": "人工",
            "description": "两位群成员发不同偏好，确认模型分清了谁说的",
            "automated": False}


def check_3_privacy_boundary() -> dict:
    """[人工] 群里问主人私人事项，确认没有载入私有人格/私有历史。"""
    return {"id": 3, "name": "隐私边界", "type": "人工",
            "description": "群里问主人私人事项，确认未载入私有数据",
            "automated": False}


def check_4_dedup() -> dict:
    """[自动] 离线重放重复 message_id，确认不重复请求。"""
    try:
        result = subprocess_run([sys.executable, "tools/qq_replay_test.py"])
        passed = result.get("returncode", 1) == 0
        return {"id": 4, "name": "消息去重", "type": "自动",
                "description": "离线重放重复 message_id，确认不重复请求",
                "automated": True, "passed": passed,
                "detail": result.get("stdout", "")[-200:]}
    except Exception as e:
        return {"id": 4, "name": "消息去重", "type": "自动",
                "description": "离线重放重复 message_id",
                "automated": True, "passed": False,
                "detail": str(e)[:200]}


def check_5_error_handling() -> dict:
    """[人工] 断开测试后端一次，确认错误提示简短、无密钥、不自动重做。"""
    return {"id": 5, "name": "错误处理", "type": "人工",
            "description": "断开后端确认错误提示简短、无密钥、不自动重做",
            "automated": False}


def check_6_restart_recovery() -> dict:
    """[人工] 聊超过窗口和存档上限，重启测试实例，再问早前内容。"""
    return {"id": 6, "name": "重启恢复", "type": "人工",
            "description": "聊超窗口上限→重启→问早前内容，确认记忆可恢复",
            "automated": False}


def check_7_persona_preserved() -> dict:
    """[人工] 默认人格语气仍保留，审批入口仍要求明确批准。"""
    return {"id": 7, "name": "人格保留", "type": "人工",
            "description": "确认默认人格语气保留，审批入口要求明确批准",
            "automated": False}


def subprocess_run(cmd: list[str]) -> dict:
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except Exception as e:
        return {"returncode": 1, "stdout": "", "stderr": str(e)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    checks = [
        check_1_owner_chat(),
        check_2_speaker_identity(),
        check_3_privacy_boundary(),
        check_4_dedup(),
        check_5_error_handling(),
        check_6_restart_recovery(),
        check_7_persona_preserved(),
    ]
    report = {
        "date": "2026-09-29",
        "total": len(checks),
        "automated": sum(1 for c in checks if c.get("automated")),
        "manual": sum(1 for c in checks if not c.get("automated")),
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))

    # save report
    out = ROOT / "cache" / "voice_metrics" / "acceptance_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nReport: {out}")

    # summary
    auto_passed = sum(1 for c in checks if c.get("automated") and c.get("passed"))
    auto_total = sum(1 for c in checks if c.get("automated"))
    print(f"\n自动验收: {auto_passed}/{auto_total} 通过")
    print(f"人工验收: {report['manual']} 项待执行")
    return 0 if auto_passed == auto_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
