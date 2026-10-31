"""通过 NapCat 的 OneBot WebSocket 拉群历史（ledger 0875）。

背景：QCE（qq-chat-exporter）本机未安装、40653 未运行；NapCat 的 OneBot 只在
`ws://127.0.0.1:3001`（token `yhlz2026`，见 config/onebot11_3655185302.json）开 WS server。
本脚本用它自己的 OneBot 动作拉历史——不是另找抓取源。

动作：get_group_list → get_group_msg_history（按 message_seq 向前翻页）
产出：data/finetune/qq_napcat_history.jsonl（原始消息，字段对齐 qq_pull_raw.raw_records）
用法：python tools/v9_napcat_pull.py [--groups 855372167,...] [--max-pages 40] [--page 100]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "finetune" / "qq_napcat_history.jsonl"
WS = "ws://127.0.0.1:3001"
TOKEN = "yhlz2026"


async def call(ws, action: str, params: dict, echo: str, timeout: float = 30) -> dict:
    await ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("echo") == echo:
            return msg
        # 忽略事件推送


def to_record(m: dict, group: str) -> dict:
    sender = m.get("sender") or {}
    return {
        "group": str(group),
        "msg_id": str(m.get("message_id") or ""),
        "seq": str(m.get("message_seq") or ""),
        "ts": int(m.get("time") or 0),
        "time": "",
        "user": str(m.get("user_id") or ""),
        "nick": str(sender.get("card") or sender.get("nickname") or ""),
        "text": str(m.get("raw_message") or ""),
        "elements": m.get("message") or [],
        "resources": [],
        "mentions": [],
        "recalled": False,
        "system": False,
    }


async def main_async(groups: list[str], page: int, max_pages: int) -> int:
    import websockets

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with websockets.connect(WS, additional_headers=headers,
                                  open_timeout=15, max_size=64 * 1024 * 1024) as ws:
        echo = "gl0"
        resp = await call(ws, "get_group_list", {}, echo)
        data = resp.get("data") or []
        all_groups = {str(g.get("group_id")) for g in data if isinstance(g, dict)}
        print(f"[napcat] 群 {len(all_groups)} 个：{sorted(all_groups)}")
        targets = [g for g in (groups or sorted(all_groups)) if g in all_groups or not groups]
        if not targets:
            print("[napcat] 指定群不在账号列表里", file=sys.stderr)
            return 2

        seen: set[tuple[str, str]] = set()
        rows: list[dict] = []
        for g in targets:
            seq = None
            got = 0
            for p in range(max_pages):
                params = {"group_id": int(g), "count": page}
                if seq:
                    params["message_seq"] = int(seq)
                resp = await call(ws, "get_group_msg_history", params,
                                  f"h{g}_{p}", timeout=45)
                msgs = (resp.get("data") or {}).get("messages") or []
                if not msgs:
                    break
                oldest = None
                for m in msgs:
                    rec = to_record(m, g)
                    key = (g, rec["msg_id"] or f"{g}:{rec['seq']}")
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(rec)
                    got += 1
                    s = rec["seq"]
                    if s.isdigit():
                        oldest = min(int(s), int(oldest)) if oldest else int(s)
                if not oldest:
                    break
                seq = oldest
                await asyncio.sleep(0.6)
        print(f"[napcat] 拉到 {len(rows)} 条")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        meta = {"rows": len(rows), "groups": targets,
                "file": str(OUT.relative_to(ROOT))}
        (OUT.parent / "qq_napcat_manifest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(meta, ensure_ascii=False))
        return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", default="")
    ap.add_argument("--page", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=40)
    args = ap.parse_args()
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    try:
        return asyncio.run(main_async(groups, args.page, args.max_pages))
    except Exception as exc:  # noqa: BLE001
        print(f"[napcat] 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
