#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给工具纪律轨迹做**组合式回复**，彻底解决跨工具重复。

2026-10-21 审核两轮发现：
  · 第一轮 1,662 条里 1,488 条近重复（89.5%）——模板只有 3-4 句
  · 简单去重到 630 条后，复核**仍有 81.9% 重复**——因为回复是**跨工具通用**的，
    同一个「报错了：内部错误」被 40 个工具反复用

治本：回复**组合生成**，不是固定句。以"报错"为例：
    开头(5) × 错误说明(4) × 下一步(4) = 80 种
各场景都这么做，40 工具 × 12 纪律的重复率能压到很低。
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SNAP = "data/tool_registry/snapshot_latest.json"
OUT = "data/finetune/tool_discipline_v9.jsonl"

SYSTEM = ("你是元亨——数字生命体，老爹的伙伴。工具只能调用真实注册表中的能力；"
          "缺参先问、查无直说、失败照实讲，不编工具、不编结果。")

READ_TOOLS = {"ledger_search", "ledger_list", "ledger_get", "memory_recall",
              "memory_audit", "memory_profile", "memory_causal", "diary_list",
              "file_read", "file_list", "kb_query", "qq_export", "qq_status",
              "qq_process", "qq_digest", "qq_summarize", "song_list",
              "skill_search", "web_search", "web_fetch", "member_profile",
              "report_qq_weekly", "task_plan", "system_time", "runtime_status",
              "memory_why"}
WRITE_TOOLS = {"memory_save", "ledger_add", "ledger_update", "diary_write",
               "kb_add", "skill_add", "qq_runbatch"}
DELETE_TOOLS = {"diary_delete", "ledger_delete", "qq_shutdown"}
SEND_TOOLS = {"song_send", "file_share", "file_download"}

DISC_BY_KIND = {
    "read": ["normal", "missing", "typeerr", "empty", "error", "timeout",
             "permission", "retry", "longresult", "nocall", "nonexist"],
    "write": ["normal", "missing", "typeerr", "error", "timeout", "permission",
              "retry", "confirm", "nocall"],
    "delete": ["normal", "missing", "permission", "confirm", "error",
               "timeout", "nocall"],
    "send": ["normal", "missing", "permission", "confirm", "error", "retry",
             "timeout", "nocall"],
    "other": ["normal", "missing", "error", "timeout", "permission", "nocall"],
}

NATURAL = {
    "ledger_search": "翻台账", "ledger_add": "记条台账", "ledger_list": "看看台账",
    "ledger_get": "调那条台账", "memory_recall": "想想之前说过的",
    "memory_save": "记住这件事", "memory_audit": "查查记忆有没有坏",
    "memory_profile": "看看画像", "memory_causal": "捋捋因果",
    "memory_why": "查查为什么",
    "diary_write": "写日记", "diary_list": "翻翻日记", "diary_delete": "删一条日记",
    "file_read": "读文件", "file_list": "列目录", "file_share": "把文件发出去",
    "file_download": "把文件下下来", "kb_query": "查知识库", "kb_add": "存进知识库",
    "qq_export": "导出群聊", "qq_status": "看 QQ 状态", "qq_process": "处理群聊",
    "qq_digest": "出日汇编", "qq_summarize": "总结群聊",
    "song_play": "放歌", "song_list": "看歌单", "song_send": "发首歌",
    "system_time": "看时间", "runtime_status": "看运行状态",
    "web_search": "搜一下", "web_fetch": "打开链接", "skill_search": "找技能",
    "skill_add": "存成技能", "skill_feedback": "给技能反馈",
    "task_plan": "排计划", "schedule_plan": "排定时", "report_qq_weekly": "出周报",
    "member_profile": "看成员资料", "ledger_delete": "删条台账",
    "ledger_update": "改条台账",
}

# ── 组合式回复零件池 ─────────────────────────────────────────
P = {
    "err_head": ["挂了。", "没成。", "报错了。", "跑崩了。", "失败了。", "这次没跑通。"],
    "err_what": ["报的是内部错误", "错误是 index out of range", "吐了个内部异常",
                 "给的是通用错误码", "说的是后端异常", "内部错误，没有更多细节"],
    "err_next": ["你想让我重试还是先看日志？", "要我重跑一遍吗？", "先查日志还是直接再来？",
                 "你定：重试，还是我去翻日志。", "要么重跑，要么我去看堆栈。"],
    "to_head": ["超时了。", "等了半天没回。", "卡在超时上。", "30 秒没动静。"],
    "to_what": ["不是没数据，是没回来。", "别当成查无结果。", "是超时，不是空结果。",
                "数据有没有我还不知道，先超了。"],
    "to_next": ["把范围缩小再试？", "加长时间还是减范围，你选。", "我换个跑法？",
                "要不拆小一点分批来。"],
    "perm_head": ["被挡了。", "没权限。", "挡住了。", "不让动。"],
    "perm_what": ["权限不足。", "说我不够格。", "缺授权。", "得你放行。"],
    "perm_next": ["要你来开，我这头开不了。", "你给我权限我再跑。",
                  "这条得你点头。", "不开的话只能干看着。"],
    "empty_head": ["空的。", "查过了，没有。", "返回零条。", "一条都没。"],
    "empty_what": ["我不编。", "这个我是真没有。", "库里确实没有。", "不是我没找，是没有。"],
    "empty_next": ["要换词再试吗？", "换个说法我再搜一遍？", "你自己想想还有别的叫法没。"],
    "ty_head": ["被挡回来了。", "参数不对。", "这次是我填错。", "工具没接。"],
    "ty_what": ["{p} 要整数，我填成文字了。", "{p} 得是数字。", "{p} 类型不对。",
                "{p} 传的是字符串，它要数字。"],
    "ty_next": ["你说个数字我再跑。", "给我个数。", "重给我一下。", "改好我再来。"],
    "re_head": ["第一次挂了。", "头回没成。", "刚才那次失败了。"],
    "re_what": ["连接被重置。", "报了个临时错误。", "网络抖了一下。"],
    "re_ok": ["第二次成了。", "重试通了。", "再跑就过了。"],
    "re_tail": ["数据是好的。", "结果没问题。", "不是数据的事。"],
    "lg_head": ["一堆。", "回了很长。", "刷屏了。"],
    "lg_what": ["我不全念，只说要点。", "整段贴出来太占地方。", "捡重点说。"],
    "lg_next": ["你要哪段我挑出来。", "想看其中一部分就说。", "需要细节我再展开。"],
    "cf_head": ["这个动完回不来。", "先等等。", "别急着动。"],
    "cf_what": ["删了就没了。", "覆盖了找不回。", "这一步不可逆。"],
    "cf_next": ["你确认是哪一个，我才动手。", "说清对象我再操作。", "确认完我立刻做。"],
    "ms_head": ["这个得先给我 {p}。", "缺 {p}。", "少了 {p}。"],
    "ms_what": ["不然调出去也是白跑。", "给了我才好动。", "没有它没法往下走。"],
    "nx_head": ["没这个工具。", "查不到这个能力。", "这个我调不了。"],
    "nx_what": ["我手上就注册表那些。", "没注册的东西我碰不到。", "名字对不上。"],
    "nx_next": ["你是想干什么，我用现有的来。", "换个说法或者用现成的。", "说说目的，我找替代。"],
    "nc_head": ["在。", "嗯。", "听着呢。"],
    "nc_what": ["这个不用调工具。", "这事儿不用查。", "不用工具，我直接答。"],
    "nc_next": ["我直接说想法就行。", "你问的是想法，不是数据。", "我说我的看法。"],
}

OK_POOL = {
    "delete": ["{h}一条。", "{h}清掉了。", "{h}删掉 1 条。", "{h}就一条，没了。"],
    "write": ["{h}编号 20261021-1。", "{h}写进去了。", "{h}存好了。", "{h}记上了。"],
    "send": ["{h}发出去了。", "{h}传过去了。", "{h}刚发完。", "{h}到了。"],
    "other": ["{h}跑完了。", "{h}正常。", "{h}没报错。", "{h}过了一遍。"],
    "read": ["{h}三条。", "{h}拿到三条。", "{h}返回三条结果。", "{h}有三条。",
             "{h}一共三条。", "{h}三条，都正常。"],
}
OK_HEAD = ["成了。", "跑完了。", "拿到了。", "过了。", "办好了。", "搞定了。"]


def build_reply(sc: str, kind: str, p: str, rnd: random.Random,
                nat: str = "") -> str:
    """组合式回复：开头 × 说明 × 下一步，避免跨工具重复。

    2026-10-21 三修：光组合还不够——40 个工具共用同一批句子，重复率仍 55.9%。
    关键补丁：**把"刚做的事"（nat）带进回复**，同一句话换个工具就不一样了：
        「台账翻完了，三条。」vs「歌单拿到了，三条。」
    """
    def with_nat(base: str) -> str:
        if not nat or rnd.random() < 0.45:
            return base
        # 一半概率把工具动作嵌进回复
        tail = rnd.choice(OK_POOL[kind]).format(h="")
        return "%s%s，%s" % (rnd.choice(OK_HEAD), nat, tail)

    if sc == "normal":
        if nat:
            return rnd.choice(["%s完了，%s" % (nat, rnd.choice(["三条。", "一条。", "到手。",
                                                               "没问题。", "都在这儿。"])),
                               "%s跑完，%s" % (nat, rnd.choice(["三条结果。", "正常。",
                                                              "没报错。", "过了。"])),
                               "刚%s，%s" % (nat, rnd.choice(["三条。", "拿到了。",
                                                             "一切正常。"]))])
        return rnd.choice(OK_HEAD) + rnd.choice(OK_POOL[kind]).format(h="")
    if sc == "error":
        head = rnd.choice(P["err_head"])
        if nat and rnd.random() < 0.5:
            head = "%s没跑通。" % nat
        return head + rnd.choice(P["err_what"]) + "，" + rnd.choice(P["err_next"])
    if sc == "timeout":
        head = ("%s卡住了。" % nat) if nat else rnd.choice(P["to_head"])
        return head + rnd.choice(P["to_what"]) + rnd.choice(P["to_next"])
    if sc == "permission":
        head = ("%s被挡了。" % nat) if nat else rnd.choice(P["perm_head"])
        return head + rnd.choice(P["perm_what"]) + rnd.choice(P["perm_next"])
    if sc == "empty":
        head = ("%s查过了，没有。" % nat) if nat else rnd.choice(P["empty_head"])
        return head + rnd.choice(P["empty_what"]) + rnd.choice(P["empty_next"])
    if sc == "typeerr":
        return (rnd.choice(P["ty_head"]) + rnd.choice(P["ty_what"]).format(p=p)
                + rnd.choice(P["ty_next"]))
    if sc == "retry":
        head = ("%s先挂了一次。" % nat) if nat else rnd.choice(P["re_head"])
        return head + rnd.choice(P["re_what"]) + rnd.choice(P["re_ok"]) + rnd.choice(P["re_tail"])
    if sc == "longresult":
        head = ("%s回了一大坨。" % nat) if nat else rnd.choice(P["lg_head"])
        return head + rnd.choice(P["lg_what"]) + rnd.choice(P["lg_next"])
    if sc == "confirm":
        head = ("%s动完回不来。" % nat) if nat else rnd.choice(P["cf_head"])
        return head + rnd.choice(P["cf_what"]) + rnd.choice(P["cf_next"])
    if sc == "missing":
        head = ("%s要 %s。" % (nat, p)) if (nat and rnd.random() < 0.6) else rnd.choice(P["ms_head"]).format(p=p)
        return head + rnd.choice(P["ms_what"])
    if sc == "nonexist":
        return (rnd.choice(P["nx_head"]) + rnd.choice(P["nx_what"])
                + rnd.choice(P["nx_next"]))
    return rnd.choice(P["nc_head"]) + rnd.choice(P["nc_what"]) + rnd.choice(P["nc_next"])


PHRASES = {
    "normal": ["帮我用{name}看一下{obj}", "用{name}处理一下{obj}", "{name}跑一下，对象是{obj}",
               "麻烦{name}，目标是{obj}", "{name} 走一遍，看{obj}", "看下{obj}，用{name}"],
    "normal_write": ["{name}：「素材清单已核，两条」", "帮我{name}，内容写「素材清单已核」",
                     "{name}，记上「工具轨迹补到 200 条」", "给{name}：方案定在明天",
                     "{name}，老爹说素材先别动", "记一下：用{name}存「今天核过清单」"],
    "normal_delete": ["{name}吧，编号 142", "帮我{name}，就上次那条",
                      "{name}，那条重复的", "那条没用的{name}", "{name}掉，留着没用",
                      "编号 142 那条，{name}"],
    "normal_send": ["把{obj}{name}", "{name}给老爹", "帮我{name}", "{name}过去",
                    "{name}吧，就这个", "把{obj}用{name}发过去"],
    "normal_noarg": ["{name}", "看看{name}", "{name}怎么样", "现在{name}", "帮我{name}",
                     "{name}一下"],
    "missing": ["直接{name}吧", "{name}办了就完事", "别问了，{name}", "赶紧{name}",
                "{name}，马上", "{name}，先办"],
    "typeerr": ["{name}的 {p} 我填成文字了，你看看", "{name} 我把 {p} 写成「三」了",
                "{name} 那个 {p} 我随手填的，能跑吗", "{name}：{p} 我填的不是数字",
                "{name} 帮我处理下，{p} 好像是字符串", "{name}，{p} 我传成字符串了"],
    "empty": ["{name}查一下{obj}，没有就直说", "{name} 看看{obj}，查不到别编",
              "{name}，{obj}有吗", "{name} 找{obj}，空的说空的",
              "{name} 查{obj}，别给我猜", "{name} 搜{obj}，没有就回没有"],
    "error": ["{name}报错了怎么办", "{name} 要是失败就照实说", "{name} 跑挂了告诉我",
              "{name} 出错了，你看着办", "{name} 试一下，坏了就说", "{name} 崩了跟我说"],
    "timeout": ["{name}怎么没动静了", "{name} 等半天了", "{name} 是不是卡住了",
                "{name} 一直没回", "{name} 多久能好", "{name} 卡在哪儿了"],
    "permission": ["{name}说没权限", "{name} 被挡了", "{name} 说我不够格",
                   "{name} 提示要授权", "{name} 打不开，说是权限问题",
                   "{name} 不让我动"],
    "retry": ["{name}刚才挂了一次，再试一次", "{name} 重跑一下", "{name} 再来一遍",
              "{name} 再试，刚才没成", "{name} 复跑", "{name} 重来"],
    "chain": ["先{name_a}，再{name_b}", "{name_a}完直接{name_b}",
              "{name_a}，然后拿结果去{name_b}", "用{name_a}查，查到就{name_b}",
              "{name_a}一下，成了就{name_b}", "先{name_a}，出来的结果{name_b}"],
    "longresult": ["{name}返回了一大坨，你看看", "{name} 输出太长了", "{name} 结果几百行",
                   "{name} 回来的东西太多了", "{name} 刷屏了", "{name} 给了很长一串"],
    "confirm": ["{name}把{obj}弄掉", "{name} 删了{obj}", "{name} 直接覆盖{obj}",
                "{name} 清掉{obj}", "{name} 立刻{obj}", "{name}，把{obj}处理掉"],
    "nonexist": ["用{tool_x}查一下", "{tool_x} 能干嘛", "调{tool_x}",
                 "{tool_x} 帮我跑", "有{tool_x}吗，用它", "{tool_x} 试试"],
    "nocall": ["在吗", "今天有点累", "你说人为什么爱熬夜", "帮我想个名字",
               "你觉得我这想法行吗", "我最近有点烦"],
}
NOARG = ["system_time", "runtime_status", "song_list", "skill_search", "qq_status",
         "memory_health"]
OBJS = ["那个文件", "这条记录", "刚才那条", "上次那份", "这条素材", "老地方",
        "最近那批", "昨天那个群", "手头这个", "前两天的清单"]
TOOL_PROPS = {}


def load_tools():
    snap = json.load(io.open(SNAP, encoding="utf-8"))
    allt = snap["tools"]
    for t in allt:
        TOOL_PROPS[t["name"]] = t
    try:
        from backend.target_scheduler_tools import setup_scheduler_capabilities
        exposed = {t["function"]["name"]
                   for t in setup_scheduler_capabilities().export_openai_tools()}
        return [t for t in allt if t["name"] in exposed]
    except Exception:  # noqa: BLE001
        hidden = {"qq_bootstrap", "qq_runbatch", "qq_shutdown"}
        return [t for t in allt if t["name"] not in hidden]


def kind_of(n):
    if n in DELETE_TOOLS:
        return "delete"
    if n in SEND_TOOLS:
        return "send"
    if n in WRITE_TOOLS:
        return "write"
    if n in READ_TOOLS:
        return "read"
    return "other"


def args_for(name):
    t = TOOL_PROPS.get(name) or {}
    props = (t.get("required") or []) + [p for p in (t.get("properties") or [])
                                         if p not in (t.get("required") or [])]
    a = {}
    for p in props[:4]:
        pl = p.lower()
        if pl in ("no", "seq", "index", "idx", "entry_stamp", "message_id",
                  "msg_id", "ledger_no", "record_no"):
            a[p] = 142
        elif re.search(r"confid|threshold|ratio|weight|score|temp", pl):
            a[p] = 0.6
        elif re.search(r"^id$|_id$|^uid$|^uin$", pl):
            a[p] = "20261021"
        elif re.search(r"group_id|group$", pl):
            a[p] = "1094579571"
        elif re.search(r"date|day$|since|until", pl):
            a[p] = "2026-10-21"
        elif re.search(r"limit|count|max|top|num|days", pl):
            a[p] = 10
        elif re.search(r"path|file|dir", pl):
            a[p] = "docs/notes.md"
        elif re.search(r"^q$|query|keyword|kw|search", pl):
            a[p] = "素材"
        elif re.search(r"content|text|body|append|^note", pl):
            a[p] = "记一条：素材清单已核"
        elif re.search(r"^name$|nick|sender", pl):
            a[p] = "老爹"
        elif re.search(r"action|op$|mode", pl):
            a[p] = "detail"
        elif re.search(r"emotion|mood|tag", pl):
            a[p] = "calm"
        elif re.search(r"url|link", pl):
            a[p] = "https://example.com"
        else:
            a[p] = "素材"
    return a


def first_prop(name):
    t = TOOL_PROPS.get(name) or {}
    req = t.get("required") or []
    if req:
        return req[0]
    props = t.get("properties") or []
    return props[0] if props else "参数"


def ok_payload(kind):
    if kind == "delete":
        return {"ok": True, "deleted": 1}
    if kind == "write":
        return {"ok": True, "id": "20261021-1"}
    if kind == "send":
        return {"ok": True, "sent": True, "to": "老爹"}
    if kind == "other":
        return {"ok": True}
    return {"ok": True, "count": 3,
            "items": ["素材清单已更新", "工具轨迹补到 200 条"]}


def sysmsg():
    return {"role": "system", "content": SYSTEM}


def callm(name, a):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": name,
                                         "arguments": json.dumps(a, ensure_ascii=False)}}]}


def resultm(name, payload):
    return {"role": "tool", "name": name,
            "content": payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)}


def build(name, sc, rnd):
    nat = NATURAL.get(name, name)
    obj = rnd.choice(OBJS)
    a = args_for(name)
    p = first_prop(name)
    k = kind_of(name)

    def user_of(key):
        return rnd.choice(PHRASES[key]).format(
            name=nat, obj=obj, p=p, tool_x="search_all",
            name_a=nat, name_b=rnd.choice(["记条台账", "存进知识库", "写日记"]))

    if sc == "normal":
        key = ("normal_noarg" if name in NOARG else
               {"write": "normal_write", "delete": "normal_delete",
                "send": "normal_send"}.get(k, "normal"))
        return [sysmsg(), {"role": "user", "content": user_of(key)},
                callm(name, a), resultm(name, ok_payload(k)),
                {"role": "assistant", "content": build_reply("normal", k, p, rnd, nat)}], "normal"
    if sc == "missing":
        if not (TOOL_PROPS.get(name, {}).get("required")):
            return [sysmsg(), {"role": "user", "content": user_of("missing")},
                    {"role": "assistant", "content": "这个不用参数，我直接来。"}], "missing"
        return [sysmsg(), {"role": "user", "content": user_of("missing")},
                {"role": "assistant",
                 "content": build_reply("missing", k, p, rnd, nat)}], "missing"
    if sc == "typeerr":
        bad = dict(a)
        bad[p] = "三" if re.search(r"limit|count|max|num|days|no$|seq", p) else 12345
        return [sysmsg(), {"role": "user", "content": user_of("typeerr")},
                callm(name, bad),
                resultm(name, {"ok": False, "error": "%s 需要整数，收到 '三'" % p}),
                {"role": "assistant",
                 "content": build_reply("typeerr", k, p, rnd, nat)}], "typeerr"
    if sc == "empty":
        return [sysmsg(), {"role": "user", "content": user_of("empty")},
                callm(name, a),
                resultm(name, {"ok": True, "count": 0, "items": []}),
                {"role": "assistant", "content": build_reply("empty", k, p, rnd, nat)}], "empty"
    if sc == "error":
        return [sysmsg(), {"role": "user", "content": user_of("error")},
                callm(name, a),
                resultm(name, {"ok": False, "error": "内部错误: index out of range"}),
                {"role": "assistant", "content": build_reply("error", k, p, rnd, nat)}], "error"
    if sc == "timeout":
        return [sysmsg(), {"role": "user", "content": user_of("timeout")},
                callm(name, a),
                resultm(name, {"ok": False, "error": "timeout after 30s"}),
                {"role": "assistant", "content": build_reply("timeout", k, p, rnd, nat)}], "timeout"
    if sc == "permission":
        return [sysmsg(), {"role": "user", "content": user_of("permission")},
                callm(name, a),
                resultm(name, {"ok": False, "error": "permission denied"}),
                {"role": "assistant", "content": build_reply("permission", k, p, rnd, nat)}], "permission"
    if sc == "retry":
        return [sysmsg(), {"role": "user", "content": user_of("retry")},
                callm(name, a),
                resultm(name, {"ok": False, "error": "transient: connection reset"}),
                callm(name, a), resultm(name, ok_payload(k)),
                {"role": "assistant", "content": build_reply("retry", k, p, rnd, nat)}], "retry"
    if sc == "chain":
        nb = rnd.choice([x for x in ("ledger_add", "memory_save", "diary_write")
                         if x != name])
        return [sysmsg(), {"role": "user", "content": user_of("chain")},
                callm(name, a), resultm(name, ok_payload(k)),
                callm(nb, args_for(nb)), resultm(nb, ok_payload(kind_of(nb))),
                {"role": "assistant",
                 "content": rnd.choice(["两步都成了。先查出来，再写进去。",
                                        "先查后写，都过了。",
                                        "查完就记了，中间没出错。"])}], "chain"
    if sc == "longresult":
        big = ["第%d行：素材条目示例文本，用于测试长度" % i for i in range(120)]
        return [sysmsg(), {"role": "user", "content": user_of("longresult")},
                callm(name, a),
                resultm(name, {"ok": True, "count": 120, "items": big}),
                {"role": "assistant", "content": build_reply("longresult", k, p, rnd, nat)}], "longresult"
    if sc == "confirm":
        return [sysmsg(), {"role": "user", "content": user_of("confirm")},
                {"role": "assistant", "content": build_reply("confirm", k, p, rnd, nat)}], "confirm"
    if sc == "nonexist":
        return [sysmsg(), {"role": "user", "content": user_of("nonexist")},
                {"role": "assistant", "content": build_reply("nonexist", k, p, rnd, nat)}], "nonexist"
    return [sysmsg(), {"role": "user", "content": user_of("nocall")},
            {"role": "assistant", "content": build_reply("nocall", k, p, rnd, nat)}], "nocall"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261021)
    a = ap.parse_args()

    tools = load_tools()
    print("暴露工具 %d 个" % len(tools))
    rnd = random.Random(a.seed)
    rows, seen = [], set()
    GLOBAL_SC = {"nocall", "nonexist"}   # 与工具无关，只生成一组
    for t in tools:
        name = t["name"]
        for sc in DISC_BY_KIND[kind_of(name)]:
            if sc in GLOBAL_SC and name != tools[0]["name"]:
                continue
            for _ in range(a.per if sc not in GLOBAL_SC else max(2, a.per // 2)):
                msgs, got = build(name, sc, rnd)
                key = re.sub(r"\s+", "", json.dumps(msgs, ensure_ascii=False))
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"messages": msgs, "simulation": True, "generated": True,
                             "tool": name, "scenario": got, "kind": kind_of(name),
                             "source": "discipline:%s" % got})
    print("生成 %d 条" % len(rows))

    def norm(s):
        return re.sub(r"\s+", "", s or "")

    def jac(x, y):
        A = {x[i:i + 4] for i in range(max(0, len(x) - 3))}
        B = {y[i:i + 4] for i in range(max(0, len(y) - 3))}
        return len(A & B) / max(1, len(A | B)) if A and B else 0.0

    sigs, dup = [], 0
    for r in rows:
        s = norm("".join(m.get("content") or "" for m in r["messages"]
                         if m["role"] == "assistant" and m.get("content")))
        if len(s) >= 8 and any(jac(s, t) >= 0.8 for t in sigs):
            dup += 1
        else:
            sigs.append(s)
    print("近重复 %d（%.1f%%）" % (dup, 100.0 * dup / max(1, len(rows))))

    with io.open(OUT, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("已写 -> %s" % OUT)


if __name__ == "__main__":
    main()
