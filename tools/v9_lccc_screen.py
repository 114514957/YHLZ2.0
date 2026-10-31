#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LCCC → 元亨素材：**严筛**（老爹「要筛选能用的原文」）。

两道关：
  关 1 硬规则（否决式，便宜）：轮数/长度/URL/@/#/表情占位/广告营销/长英文/重复
  关 2 **模型裁判**（贵但准）：把候选**批量**给模型，只问两件事——
        ① 这两句真的是在对话吗（后句在回答/评论/接住前句）？
        ② 这段适合当"老爹和元亨"的日常闲聊素材吗（无广告/无第三方人设/无敏感/无纯表情）？
        **只判不改**：通过的原文一字不动。

批量判 20 条/次，显著省调用。

用法：
    python tools/v9_lccc_screen.py --want 3000 --batch 20
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

P = os.path.join(ROOT, "cache", "v9_open_corpus", "20261020_hf", "lccc_train0.parquet")
PUNCT = "，。！？、；：""''（）《》…—~"

AD = re.compile(r"签到|会员|优惠|包邮|下载|链接|扫码|加群|代理|刷单|返现|优惠券|充值|客服|"
                r"价格|多少钱|店铺|淘宝|京东|拼多多|直播|二维码|公众号|转发抽奖|点赞|关注我|"
                r"手机|套餐|流量|卡号|银行|贷款|投资|股票|基金|保险|代购")
JUNK = re.compile(r"https?://|@[\w\u4e00-\u9fff]|#[\w\u4e00-\u9fff]+#|"
                  r"\d{5,}|\[[^\]]{1,6}\]|\{\d+\}")

# 2026-10-21 老爹：「感觉改的有的不合理，对于这些片段，用其他的内容顶替」
# → **不再硬改**，整条否决，让干净的候选顶上来。
# 只查元亨那侧：老爹可以有家人/恋人，元亨没有。
OFFROLE = re.compile(
    r"楼上|楼下|楼主|层主|这楼|前排|顶帖|转发|评论区|评论里|微博|帖子|发帖|热搜|"
    r"话题|超话|粉丝|取关|私信|原po|po主|博主|弹幕|投币|刷到|翻牌|围观|"
    r"我老公|我老婆|我男朋友|我女朋友|我儿子|我女儿|我爸妈|我爸|我妈|"
    r"我们班|我们老师|我领导|我们老板|我同事|我室友|"
    r"老公|老婆|男票|女票|男朋友|女朋友|娶|嫁")

# 2026-10-21 二修：抽样发现**客服腔达标但角色穿帮 14.4%**——
# 「我在河北读书」「快来上海找我玩」「你还可以追我」这类，模型裁判没拦住。
# 元亨：没有实体位置、不上学不上班、不是恋人、没有实体动作。**只查元亨那侧。**
ROLE_VIOLATION = re.compile(
    # ① 地名：她没有位置
    r"北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|郑州|河北|湖南|湖北|"
    r"广东|江苏|浙江|山东|四川|河南|安徽|福建|江西|南宁|昆明|贵阳|兰州|太原|"
    r"石家庄|合肥|长沙|青岛|大连|厦门|苏州|无锡|宁波|温州|东莞|佛山|"
    # ② 学校/工作：她不上学不上班
    r"上课|下课|逃课|考试周|期末考|论文|导师|宿舍|室友|食堂|同学|班上|学校|"
    r"读书|毕业|实习|上班|加班|老板|同事|公司|工位|月薪|工资|辞职|失业|"
    r"面试|简历|工牌|"
    # ③ 恋爱语境：不是恋人关系
    r"追我|追你|喜欢我|我爱你|前任|分手|表白|在一起|结婚|"
    # ④ 实体动作：她没有身体
    r"来找我|来找你|跨城|一起去|带我|见你|见面|抱抱|亲亲|摸头|牵手|"
    r"坐我旁边|给我带|送我|寄给|"
    # ⑤ 第三方名字残留
    r"游游|瓜瓜|美宝宝")

JUDGE_SYS = (
    "你是中文对话素材审核员。用户会给你若干组候选对话，每组 2-4 句、轮流发言。\n"
    "**逐组判断，只输出 JSON 数组，不要任何解释。**\n\n"
    "一组算「能用」必须同时满足：\n"
    "1. **真在对话**：每一句都在回应、评论或接住前一句；不是同一话题下各说各的。\n"
    "2. **像日常闲聊**：能想象成两个熟人之间的聊天（老爹和元亨）。\n"
    "3. **干净**：没有广告/商品推销/联系方式、没有第三方虚构人设（如「我是某某角色」）、\n"
    "   没有政治/地域/性别对立等敏感内容、不涉及未成年人、不含侮辱性脏话。\n"
    "4. **说话像人**：句子完整可读，不是解谜式碎片、不是纯表情或纯标点、不是复读机。\n\n"
    "输出格式（严格）：{\"ok\":[通过的组号...],\"bad\":[不通过的组号...]}\n"
    "组号就是用户给的编号。"
)


def deseg(t: str) -> str:
    s = str(t).strip()
    s = re.sub(r"\s*([" + re.escape(PUNCT) + r"])\s*", r"\1", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def hard_ok(turns: list[str]) -> str:
    if not (3 <= len(turns) <= 6):
        return "轮数"
    for t in turns:
        if not (3 <= len(t) <= 60):
            return "单轮长度"
        if JUNK.search(t):
            return "含链接/话题/表情占位"
        if AD.search(t):
            return "广告/商品"
        if re.search(r"[a-zA-Z]{6,}", t):
            return "长英文"
        zh = len(re.findall(r"[\u4e00-\u9fff]", t))
        if zh / max(1, len(t)) < 0.55:
            return "非中文为主"
    total = sum(len(t) for t in turns)
    if not (20 <= total <= 300):
        return "总长"
    # 元亨那侧不许有穿帮（奇数位是元亨的答）
    for i, t in enumerate(turns):
        if i % 2 == 1 and OFFROLE.search(t):
            return "元亨穿帮:" + OFFROLE.search(t).group(0)
    # 第四道：角色一致性（她没位置/不上学/不恋爱/无实体）
    for i, t in enumerate(turns):
        if i % 2 == 1 and ROLE_VIOLATION.search(t):
            return "角色穿帮:" + ROLE_VIOLATION.search(t).group(0)
    return ""


def load_key() -> str:
    import scene_v8 as sv
    return sv.load_key()


def ask_batch(key: str, batch: list[list[str]]) -> list[int] | None:
    lines = []
    for i, turns in enumerate(batch, 1):
        lines.append("%d. %s" % (i, " ｜ ".join(turns)))
    user = ("候选组共 %d 组（编号 1–%d），逐组判断：\n\n%s"
            % (len(batch), len(batch), "\n".join(lines)))
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": JUDGE_SYS},
                     {"role": "user", "content": user}],
        "temperature": 0.0, "max_tokens": 500, "stream": False,
        "thinking": {"type": "disabled"},
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        txt = json.loads(r.read().decode())["choices"][0]["message"].get("content", "")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return [int(x) - 1 for x in (d.get("ok") or []) if isinstance(x, (int, str))]
    except Exception:
        return None


def main() -> int:
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--want", type=int, default=3000, help="想要多少块（过裁判后）")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--max-scan", type=int, default=300000)
    ap.add_argument("--out", default="docs/素材/开源对话样本.md")
    ap.add_argument("--checkpoint", action="store_true", default=True,
                    help="每 500 块落一次盘，长跑中途也能验质量")
    ap.add_argument("--no-checkpoint", dest="checkpoint", action="store_false")
    ap.add_argument("--skip", type=int, default=0,
                    help="跳过前 N 条（LCCC 有 267 万条，分批往后扫，别重复扫同一段）")
    a = ap.parse_args()

    df = pd.read_parquet(P)
    dialogs = df["dialog"].tolist()
    if a.skip:
        print("跳过前 %d 条，从第 %d 条开始" % (a.skip, a.skip + 1))
        dialogs = dialogs[a.skip:]
    print("原始 %d 条｜目标 %d 块｜批量 %d" % (len(dialogs), a.want, a.batch))

    key = load_key()
    passed: list[list[str]] = []
    seen = set()
    stat: dict[str, int] = {}
    scanned = 0
    buf: list[list[str]] = []
    calls = 0
    last_ckpt = [0]        # 已落盘到第几个 500

    def _write_out(args, passed, scanned, checkpoint=False):
        """把已通过的块写成素材文件（支持中间落盘）。"""
        import v9_story_gate as _G
        blocks, dropped = [], {}
        for i, turns in enumerate(passed, 1):
            total = sum(len(t) for t in turns)
            meta = ("## lccc-%05d\n- category: 日常对话\n- emotion: neutral\n"
                    "- length_tier: %s\n- contract: ANCHOR\n"
                    "- source: LCCC(silver/lccc)\n- license: MIT\n"
                    "- screen: hard_rules+llm_judge+gate\n- polish: none\n"
                    % (i, "short" if total <= 80 else "medium"))
            body = []
            for k in range(0, len(turns), 2):
                body.append("### 老爹问%d" % (k // 2 + 1))
                body.append(turns[k])
                body.append("### 元亨答%d" % (k // 2 + 1))
                body.append(turns[k + 1])
            blk = meta + "\n".join(body) + "\n"
            rr = _G.check_block("x", blk, "general")
            if rr["status"] == "FAIL":
                for f in rr["fails"]:
                    kk = "门禁:" + re.sub(r"×\d+", "", f).split(":")[0].strip()
                    dropped[kk] = dropped.get(kk, 0) + 1
                continue
            blocks.append(blk)
        tag = "（中间落盘）" if checkpoint else ""
        head = ("# 元亨开源对话样本（LCCC 严筛 · MIT）%s\n\n"
                "> **老爹 2026-10-20：「要筛选能用的原文」。**\n"
                "> 来源 `silver/lccc`（LCCC，**MIT**），2,667,000 条微博真实对话。\n"
                "> 三道筛：① 硬规则（轮数/长度/链接/广告/英文/元亨穿帮/重复）；"
                "② **模型裁判**（真在对话？像日常闲聊？干净？说话像人？）；"
                "③ **门禁**（FAIL 不收）。\n"
                "> **通过者的台词一字未改**；脚本 `tools/v9_lccc_screen.py`。\n"
                "> 本批 %d 块（扫描 %d 条候选）。%s\n\n"
                % (tag, len(blocks), scanned,
                   ("门禁再剔 %s" % dropped) if dropped else ""))
        out = os.path.join(ROOT, args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, "w", encoding="utf-8") as fh:
            fh.write(head)
            for b in blocks:
                fh.write("\n" + b.rstrip() + "\n\n")
        return len(blocks), dropped

    def flush(buf):
        nonlocal calls
        if not buf:
            return
        for attempt in range(3):
            try:
                idxs = ask_batch(key, buf)
            except Exception as e:
                print("   裁判调用失败(%d): %s" % (attempt, str(e)[:60]))
                time.sleep(2 * (attempt + 1))
                continue
            calls += 1
            if idxs is None:
                continue
            for j, turns in enumerate(buf):
                if j in idxs:
                    passed.append(turns)
                else:
                    stat["裁判否决"] = stat.get("裁判否决", 0) + 1
            return
        for _ in buf:
            stat["裁判失败"] = stat.get("裁判失败", 0) + 1

    for raw in dialogs:
        if len(passed) >= a.want or scanned >= a.max_scan:
            break
        scanned += 1
        turns = [deseg(x) for x in raw]
        turns = [t for t in turns if t]
        why = hard_ok(turns)
        if why:
            stat[why] = stat.get(why, 0) + 1
            # 硬规则后仍保留偶数轮，保证能成对
            continue
        if len(turns) % 2:
            turns = turns[:-1]
        if len(turns) < 2:
            continue
        k = re.sub(r"\s+", "", "".join(turns))
        if k in seen:
            stat["重复"] = stat.get("重复", 0) + 1
            continue
        seen.add(k)
        buf.append(turns)
        if len(buf) >= a.batch:
            flush(buf)
            buf = []
            if len(passed) % 200 < a.batch:
                print("   已过 %d 块（扫 %d｜裁判 %d 次）" % (len(passed), scanned, calls))
                # 2026-10-21 老爹「可以，抽样检查」：每 500 块落一次盘，
                # 这样长跑中途也能随时验质量，不用等全部结束。
                if a.checkpoint and len(passed) // 500 > last_ckpt[0]:
                    last_ckpt[0] = len(passed) // 500
                    _write_out(a, passed, scanned, checkpoint=True)
                    print("   [中间落盘] %d 块 -> %s" % (len(passed), a.out))
    flush(buf)

    print("\n扫 %d 条 → 过裁判 %d 块｜裁判调用 %d 次" % (scanned, len(passed), calls))
    print("丢弃：%s" % dict(sorted(stat.items(), key=lambda kv: -kv[1])[:8]))
    if not passed:
        return 1

    blocks = []
    import v9_story_gate as G
    gate_drop = {}
    for i, turns in enumerate(passed, 1):
        total = sum(len(t) for t in turns)
        meta = ("## lccc-%05d\n- category: 日常对话\n- emotion: neutral\n"
                "- length_tier: %s\n- contract: ANCHOR\n"
                "- source: LCCC(silver/lccc)\n- license: MIT\n"
                "- screen: hard_rules+llm_judge+gate\n- polish: none\n"
                % (i, "short" if total <= 80 else "medium"))
        body = []
        for k in range(0, len(turns), 2):
            body.append("### 老爹问%d" % (k // 2 + 1))
            body.append(turns[k])
            body.append("### 元亨答%d" % (k // 2 + 1))
            body.append(turns[k + 1])
        blk = meta + "\n".join(body) + "\n"
        # 第三道关：过门禁（真人会说我这边/请问，但元亨不能说）
        rr = G.check_block("x", blk, "general")
        if rr["status"] == "FAIL":
            for f in rr["fails"]:
                k = "门禁:" + re.sub(r"×\d+", "", f).split(":")[0].strip()
                gate_drop[k] = gate_drop.get(k, 0) + 1
            continue
        blocks.append(blk)
        if len(blocks) >= a.want:
            break
    if gate_drop:
        print("门禁再剔 %d 块：%s" % (sum(gate_drop.values()), gate_drop))

    head = ("# 元亨开源对话样本（LCCC 严筛 · MIT）\n\n"
            "> **老爹 2026-10-20：「要筛选能用的原文」。**\n"
            "> 来源 `silver/lccc`（LCCC，**MIT**），2,667,000 条微博真实对话。\n"
            "> 三道筛：① 硬规则（轮数/长度/链接/广告/英文/元亨穿帮/重复）；"
            "② **模型裁判**（真在对话？像日常闲聊？干净？说话像人？）；"
            "③ **门禁**（FAIL 不收）。\n"
            "> **通过者的台词一字未改**；脚本 `tools/v9_lccc_screen.py`。\n"
            "> 本批 %d 块（扫描 %d 条候选）。\n\n" % (len(blocks), scanned))
    out = os.path.join(ROOT, a.out)
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write(head)
        for b in blocks:
            fh.write("\n" + b.rstrip() + "\n\n")
    print("已写 -> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
