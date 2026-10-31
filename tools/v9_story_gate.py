#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 素材门控 v1.0（2026-10-12）

作用（机器可判的底线闸门）：
  · 形态：长对话线要求 >20 轮、≥400 字超长句、fiction 与必备元数据齐全（story 档）；
  · 禁项：客服/模板/报告/AI 自述腔、括号、星号、分号、冒号、列表行、填充语撞车；
  · 纪律：发言人白名单（大肥鱼禁言）、元亨不得用「理论上来说」、自称 ≥2 种；
  · 防污染：来源名黑名单（小说/游戏角色名不得渗入）；
  · 辅助：收尾分布、4 字复读、对话感指标（报告级）。
不能替代（必须人审）：像不像元亨、人味、梗好不好、信息点有没有被改坏、IP 实质相似、人设漂移的语义判断。

用法:
  python tools/v9_story_gate.py --profile story  <文件或目录> [...]
  python tools/v9_story_gate.py --profile general <文件或目录> [...]   # 重处理线：只查禁项/纪律/防污染
  python tools/v9_story_gate.py --selftest                        # 脚本自检（8 个正反用例）
  python tools/v9_story_gate.py --profile story --json <文件...>   # 另存 .gate.json

退出码：0=全部 PASS（允许 WARN）；1=有 FAIL；2=用法错误；3=自测失败。
报告自动落盘：<文件>.gate.txt（--json 时另加 <文件>.gate.json）。
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

VERSION = "1.0"

CONFIG = {
    "profiles": {
        "story": {"long": True, "min_rounds": 21, "require_ultra": 400,
                  "require_fiction": True, "require_meta": True,
                  "meta_fields": ["category", "status", "emotion", "length_tier", "contract"]},
        "general": {"long": False, "min_rounds": 0, "require_ultra": 0,
                    "require_fiction": False, "require_meta": False,
                    "meta_fields": ["category", "status", "emotion", "length_tier", "contract"]},
    },
    "allowed_speakers": ["老爹", "元亨", "利贞", "陌生人", "朋友", "群友"],
    "banned_speakers": ["大肥鱼"],
    "source_names": ["苏菲", "艾伯特", "克莱恩", "阿蒙", "希灵", "陈俊", "郝仁", "周明瑞", "莉莉", "薇薇安"],
    "bad_words": {
        # 2026-10-20 老爹定：客服腔**全去**。
        # 「建议您/请问/为您/祝您」是敬语客服腔；「建议你」不带"您"、对老爹平辈说话，
        # 属正常提建议，不再判死（实测误伤）。
        "客服腔": r"为您|建议您|请问|祝您|希望(?:能|可以|对)帮|还有什么(?:需要|可以)|还需要什么|我可以帮",
        "模板腔": r"(?<![别不])让我来|首先|其次|总之|综上所述|总的来说|需要注意的是|值得注意的是|总结一下",
        # 2026-10-20 老爹定：报告腔（已完成/任务完成/处理完成）**留着**——
    # 干完活汇报本来就是必要的，不算毛病。降为 WARN，不拦。
    "报告腔": r"已完成|任务完成|处理完成|已为您",
        "AI自述": r"作为(?:一个)?(?:AI|人工智能|语言模型|助手)|我是(?:一个)?(?:AI|人工智能|语言模型)",
        # 客服/工单模板话术（老爹 2026-10-13 点名）——不是"这个词不能用"，
        # 而是"用成固定应答模板就是客服腔"。单个词由 filler_repeat 按频次兜。
        # 2026-10-20 修：「没收到。」「未收到。」「能收到。」「可收到。」是正常叙述，
    # 不是应答模板（实测误伤：收音机「听，能收到。」被当成客服应答）
    "应答模板": r"(?<![没未能可会])收到[，,。]|好的[，,]。*已|没问题[，,].*安排|这就(?:去|来)(?:办|做)|稍等[，,]?马上",
    },
    # 2026-10-20 修：括号里**必须含中文**才算"括号动作"（（笑）（沉默））。
    # 纯 ASCII 的括号是技术记号（O(n²)、array[2]），不该判死。
    # 2026-10-20 再修：**解释性括号**（（你的提问、世界的运行））是正常中文，
    # 只有"短且无标点"的才像舞台指示（（笑）（沉默）（叹气））。阈值 ≤4 字。
        # 2026-10-22 修（同一原则：**形状不等于问题，语境才是**）：
    # 原规则抓"短括号"（括号+1汉字+≤3字符），结果把正常中文补充也判死——
    # 实测全库 12 种 28 处**全是**正常补充：（如日记本）（收敛版）（均待授权）
    # （元亨）（如"利"）（语音）（沉淀点）（内在因）（开物）（紧致无边）（不真机试）（软硬），
    # **没有一个是舞台指示**。改成只抓真正的舞台指示词。
    "bad_chars": {"括号": r"[（(](?:无声|沉默|静默|微笑|苦笑|冷笑|叹气|叹息|点头|摇头|皱眉|眨眼|停顿|片刻|正在听|认真听|想了想|愣|怔|哽咽|起身|坐下|转身|伸手|拍拍|摸摸|摆手|耸肩)[^）)]{0,3}[）)]",
                 "星号": r"\*",
                  "列表行": r"(?m)^[ \t]*([-*•]|\d+[.、)])\s"},
    # 2026-10-18 老爹定：技术讲解里用冒号/分号是合理的中文书面表达，
    # 不再当"报告腔"硬判 FAIL，降为 WARN（只提示、不拦）。
    "soft_chars": {"分号": r"；", "冒号": r"："},
    # 填充语/起手式撞车：**一批内同一串出现 ≥2 次即 FAIL**。
    # 2026-10-13 老爹点名新增：接/我接/我认/稳/我这边 —— 都是"念模板"的味道：
    #   「接」当动词（回头再接/接上/对接）是 IT 隐喻滥用；「稳」当评价（稳了/很稳）是网络口头禅；
    #   「我认」「我这边」是客服式承接。写成别的说法就不算撞车。
    # 2026-10-20 修：「后来我」是长故事里的正常叙事连接词（不是客服腔）→ 移出；
    # 「接上」改为正则，排除「直接上」「能接上」「衔接上」「相连」这类动词/切词误判。
    # 2026-10-22 修：这里原来与 `banned_in_dialogue` 重叠（我这边/别指望/我认/稳了/很稳/这个稳），
    # 而本条是 **plain_text.count() 裸计数、不看语境**，于是「自我认知」出现两次就被判
    # 「填充语撞车: 我认 ×2」——同一类误判的第三条路径。
    # 修法：重叠词交给 `banned_in_dialogue`（已带语境判断）负责，这里只留它独有的模板腔词。
    "filler_repeat": ["先说好", "说句不客气", "理论上来说", "回头再"],
    "filler_regex": {"接上": r"(?<![直能对衔连相接])接上"},
    # 老爹点名（2026-10-13）的客服腔词：在**台词**里出现即硬 FAIL（与「理论上来说」同级）。
    # 注释区/文档行不算——那些行不是台词，gate 只扫 ### …问N/答N 下的正文。
    "banned_in_dialogue": ["我这边", "我接", "我认", "稳了", "很稳", "这个稳", "别指望"],
    "repeat_exempt": ["JSON", "ISO", "RAW", "SQL"],
    # 工具协议载荷：整轮为 JSON 或 <tool_call>…</tool_call> 包装的轮，是协议不是台词，
    # 不参与复读/填充语扫描（仍计入字数与轮数）。纯 JSON 轮也不查禁符禁词
    # ——否则 schema 里的冒号会被当成"发言冒号"。中文台词轮一律照旧检查。
    "tool_payload_open": "<tool_call>",
    "self_refs": ["我", "咱", "本小姐", "老娘", "元亨"],
    "dash_warn": 2,          # 每块破折号 >2 告警
    "ending_warn": 0.90,     # 同型收尾占比 ≥90% 告警（样本≥8 轮）
}

TURN_RE = re.compile(r"^###\s*([^\n#]*?)(问|答)(\d+)\s*$", re.M)
# 2026-10-20 老爹定：黄金样本用 `### 老爹` / `### 元亨`（无编号、无问/答），
# 门禁要能读。兼容形态：`### <角色>`（角色必须在已知名单里），
# 按出现顺序推断问/答（元亨=答，其余=问）。
TURN_BARE = re.compile(r"^###\s*(老爹|利贞|元亨|陌生人|朋友|群友)\s*$", re.M)
META_RE = re.compile(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", re.M)


def parse_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    return [b for b in re.split(r"(?m)(?=^## )", text) if b.startswith("## ")]


def parse_meta(blk: str) -> dict:
    return {m.group(1).lower(): m.group(2).strip() for m in META_RE.finditer(blk)}


def parse_turns(blk: str) -> list[tuple[str, str, str, str]]:
    """解析轮次。支持两种格式：
      A. `### <角色>问N` / `### <角色>答N`（规范素材）
      B. `### <角色>`（黄金样本；角色在已知名单内，按出现顺序推断问/答）
    """
    ms = list(TURN_RE.finditer(blk))
    if ms:
        out = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(blk)
            out.append((m.group(1).strip(), m.group(2), m.group(3), blk[m.end():end].strip()))
        return out
    # 兼容无编号格式
    bare = list(TURN_BARE.finditer(blk))
    if not bare:
        return []
    out = []
    for i, m in enumerate(bare):
        end = bare[i + 1].start() if i + 1 < len(bare) else len(blk)
        who = m.group(1)
        kind = "答" if who == "元亨" else "问"
        out.append((who, kind, str(i + 1), blk[m.end():end].strip()))
    return out


def _is_tool_payload(text: str) -> bool:
    """整轮是工具协议载荷（JSON 调用/结果）则返回 True。

    判定从严：去空白后以 <tool_call> 开头，或以 { / [ 开头且能被 json 解析。
    带中文台词的轮一律返回 False，照旧参与全部文字检查。
    """
    s = text.strip()
    if not s:
        return False
    if s.startswith(CONFIG["tool_payload_open"]):
        return True
    if s[0] in "{[":
        try:
            json.loads(s)
            return True
        except Exception:
            return False
    return False


def check_block(name: str, blk: str, profile: str) -> dict:
    """Return {name, status, fails[], warns[], metrics{}}."""
    p = CONFIG["profiles"][profile]
    fails: list[str] = []
    warns: list[str] = []
    meta = parse_meta(blk)
    ts = parse_turns(blk)
    yh = [t for t in ts if t[0] == "元亨"]
    yh_text = "\n".join(t[3] for t in yh)
    joined = "\n".join(t[3] for t in ts)
    # 协议载荷轮（纯 JSON 调用/结果）不计入文字类检查；台词轮照旧
    plain_turns = [t for t in ts if not _is_tool_payload(t[3])]
    plain_text = "\n".join(t[3] for t in plain_turns)

    nums = sorted({int(t[2]) for t in ts if t[2].isdigit()})
    rounds = max(nums) if nums else 0
    lens = [len(t[3]) for t in ts]
    mx = max(lens) if lens else 0
    # 2026-10-20 修：风格六条量的是**句子**长度，不是轮长。
    # 原来误用 `lens`（每轮字符数）→ 「句长太匀」实际在量「轮长太匀」，
    # 与《角色研读样张 v1》的口径（句长中位 13–24、p90 53–111）不是一回事。
    sent_lens = [len(s.strip()) for s in re.split(r"[。！？!?]", yh_text)
                 if len(s.strip()) >= 2]

    if not ts:
        fails.append("无可解析对话轮（### …问N/答N）")

    # --- 形态（story 档硬门） ---
    if p["long"]:
        if rounds < p["min_rounds"]:
            fails.append(f"长块轮数 {rounds} <{p['min_rounds']}（要求 >20）")
        if mx < p["require_ultra"]:
            fails.append(f"缺 ≥{p['require_ultra']} 字超长句（最长 {mx}）")
    if p["require_meta"]:
        miss = [k for k in p["meta_fields"] if not meta.get(k)]
        if miss:
            fails.append(f"缺元数据: {miss}")
    if p["require_fiction"] and not meta.get("fiction"):
        fails.append("缺 fiction 标记（故事线）")

    # --- 说话人 ---
    for (sp, _ty, _no, _txt) in ts:
        if sp in CONFIG["banned_speakers"]:
            fails.append(f"禁言角色发言: {sp}")
        elif sp not in CONFIG["allowed_speakers"]:
            fails.append(f"未授权发言人: {sp}")

    # --- raw 数据豁免判定（2026-10-20《真实数据豁免规则 v1》） ---
    # 豁免"形态"，不豁免"内容"：
    #   形态（括号/星号/列表/分号冒号/风格六条）→ raw 块跳过
    #   内容（禁词/客服腔/模板腔/报告腔/应答模板/身份/元数据）→ 照查
    _meta_now = dict(parse_meta(blk))
    raw_ok = (str(_meta_now.get("raw", "")).strip().lower() == "true"
              and bool(str(_meta_now.get("raw_source", "")).strip())
              and bool(str(_meta_now.get("raw_captured", "")).strip())
              and bool(str(_meta_now.get("polish", "")).strip()))
    raw_skipped: list[str] = []
    infos: list[str] = []   # 语感习惯类（留白/称呼）：只统计，不影响单块状态

    # --- 禁词/禁符（只看台词轮，协议载荷轮按定义不受此限） ---
    # 2026-10-20 修：**客服腔类是给元亨治的**，只扫元亨台词。
    # 实测老爹自己会说「我这边 batch 已经调得很小」，那是正常口语；
    # 扫全文会把整库的「电流稳了」「道理我认」「自我认同」全判死（实测 15/19 是误伤）。
    YH_ONLY = {"客服腔", "客服腔词（老爹点名）"}
    for tag, pat in CONFIG["bad_words"].items():
        # 2026-10-20：客服腔类只扫元亨台词（老爹/利贞的「收到，我这就办」不算）
        target = yh_text if tag in ("客服腔", "应答模板") else plain_text
        n = len(re.findall(pat, target))
        if not n:
            continue
        if tag in ("报告腔", "模板腔"):
            # 2026-10-20 老爹定：报告腔 + 模板腔（首先/其次/总之/综上所述/让我来）
            # 都是"工作汇报的结构"，干活时必要 → 留用。
            # 2026-10-20 再改：既然是"留用"，就不该让它决定块状态 → 移到 infos。
            infos.append(f"{tag}×{n}")
        else:
            fails.append(f"{tag} ×{n}")
    for tag, pat in CONFIG["bad_chars"].items():
        n = len(re.findall(pat, plain_text))
        if n:
            if raw_ok:
                raw_skipped.append(f"{tag}×{n}")
            else:
                fails.append(f"{tag} ×{n}")
    # 冒号/分号：只提示（2026-10-18 老爹定，技术讲解用它们是合理书面表达）
    for tag, pat in CONFIG.get("soft_chars", {}).items():
        n = len(re.findall(pat, plain_text))
        if n and not raw_ok:
            # 2026-10-20 老爹 2026-10-18 已定：「技术讲解里用冒号/分号是合理的
            # 中文书面表达，不再当报告腔硬判 FAIL」。既然"只提示、不拦"，
            # 就不该决定块状态 → 移到 infos，只在统计里出现。
            infos.append(f"{tag}×{n}")

    # --- 纪律 ---
    if "理论上来说" in yh_text:
        fails.append("元亨误用「理论上来说」")
    lz_n = joined.count("理论上来说")
    if lz_n > 2:
        warns.append(f"「理论上来说」×{lz_n}（利贞口癖过密）")
    kinds = [w for w in CONFIG["self_refs"] if w in yh_text]
    yh_ans = [t for t in ts if t[0] == "元亨" and t[1] == "答"]
    if len(yh_ans) >= 4 and len(kinds) < 2:
        (fails if p["long"] else warns).append("元亨自称单一（<2 种）")

    # --- 防污染 ---
    leak = [w for w in CONFIG["source_names"] if w in joined]
    if leak:
        fails.append(f"来源名泄漏: {leak}")

    # --- 收尾分布 ---
    ends = Counter()
    for t in ts:
        if t[0] != "元亨":
            continue
        tail = t[3].rstrip()
        if tail.endswith(("？", "?")):
            ends["问"] += 1
        elif tail.endswith(("！", "!")):
            ends["叹"] += 1
        else:
            ends["陈述"] += 1
    total_e = sum(ends.values())
    if total_e >= 8 and max(ends.values()) / total_e >= CONFIG["ending_warn"]:
        warns.append(f"收尾单一化 {dict(ends)}")

    # --- 破折号 ---
    dash = joined.count("——")
    if dash > CONFIG["dash_warn"]:
        warns.append(f"破折号 ×{dash}（>2）")

    # --- 老爹点名的客服腔词（台词内直接 FAIL）---
    # 2026-10-18：改为**语境感知**判定。裸子串匹配在中文里必然误伤：
    #   「我认输」「我接着睡」「我接受」是正常词（认输/接着/接受），不是客服腔；
    #   「靠稳了往上爬」是动词补语，也不是网络口头禅。
    # 只在真正的客服/口头禅语境判 FAIL；自然用法不计或降 WARN。
    for w in CONFIG["banned_in_dialogue"]:
        if w == "我认":
            # 2026-10-20 再收紧：只判**独立成句**的「我认」（客服式承接），
            # 「桌子我认」「道理我认」「我认了这份活法」都是正常中文。
            pat = r"(?<![输得识为可领真错命认不])我认(?=[。！？\n]|$)"
        elif w == "我这边":
            # 排除「站我这边」「在我这边」这类正常用法（成语/方位），只判客服式自指
            pat = r"(?<![站在到靠偏冲])我这边"
        elif w == "我接":
            # 排除：接着/接受/接近/接纳/连接/接地/接下/接过/接手/接管，以及「我接不了」
            pat = r"我接(?![着受近纳连地下过手脚不管])"
        elif w in ("稳了", "这个稳"):
            # 2026-10-20 再收紧：只判**口语评价**用法（这下稳了/该稳了/稳了！），
            # 「电流稳了」「链路稳了」「搭稳了」是动词补语，正常。
            pat = r"(?:这下|这回|那就|应该|基本|肯定|算是|总算)\s*稳了|稳了(?=[！!])"
        elif w == "很稳":
            n = len(re.findall(re.escape(w), yh_text))
            if n:
                warns.append(f"「很稳」（多为形容词用法，人工确认） ×{n}")
            continue
        elif w == "别指望":
            # 2026-10-22 老爹定：「**禁词并不是彻底不要，是在合适语境下使用显得不客服腔**」。
            # 「别指望」的真客服腔只出现在**推脱**语境——别指望我/咱/您/你（把责任推回对方）。
            # 「但别指望 100%」「别指望它一次做对」「纯度别指望太高」是**客观陈述**，正常中文。
            # 实测全库 80 处命中**全部**是客观陈述，没有一处推脱 → 裸匹配是纯误判。
            pat = r"别指望(?=[咱我您你])"
        else:
            pat = re.escape(w)
        # 客服腔词只约束元亨（老爹自己说「我这边」是正常口语）
        n = len(re.findall(pat, yh_text))
        if n:
            fails.append(f"客服腔词（老爹点名）: {w} ×{n}")

    # --- 同块内元亨多答重复（2026-10-20 新增，实测是比格式更严重的缺陷） ---
    # 实测：对话-20/343/506/901/1076/1116 六块里，三个回答是同一段故事的近似复制
    # （相似度 0.76–0.95）。这样训出来的模型会"回答任何问题都重复同一段长故事"。
    _ans = [t[3].strip() for t in ts if t[0] == "元亨" and t[1] == "答"]
    _ans = [x for x in _ans if len(x) > 40]
    for _i in range(len(_ans)):
        for _j in range(_i + 1, len(_ans)):
            _r = difflib.SequenceMatcher(None, _ans[_i], _ans[_j]).ratio()
            if _r >= 0.70:
                fails.append(f"元亨答重复(第{_i + 1}/{_j + 1}答 相似{_r:.2f})")
                break

    # --- 复读（协议载荷轮不参与，避免把 tool_call 包装词当台词复读） ---
    # 2026-10-20 重写：**4 字窗口在中文里量不准**。
    # 实测误伤：「亚里士多」「里士多德」「存在主义」「INT4」「士多德说」——
    # 全是专名/术语，讨论一个话题时必然反复出现，不是复读。
    # 改为**整句重复**：按标点切分句，长度 ≥8 且完全相同的分句出现 ≥2 次才算复读。
    _clauses = [x.strip() for x in re.split(r"[，。！？；：、,.;:!?…—]+", plain_text)
                if len(x.strip()) >= 8]
    _cc = Counter(_clauses)
    rep = [(g, k) for g, k in _cc.most_common(20) if k >= 2]
    rep = [x for x in rep if not any(e in x[0] for e in CONFIG["repeat_exempt"])][:6]
    if rep:
        warns.append(f"分句重复: {[(g[:14], k) for g, k in rep[:3]]}")
    for f in CONFIG["filler_repeat"]:
        n = plain_text.count(f)
        if n >= 2:
            fails.append(f"填充语撞车: {f} ×{n}")
    for f, pat in CONFIG.get("filler_regex", {}).items():
        n = len(re.findall(pat, plain_text))
        if n >= 2:
            fails.append(f"填充语撞车: {f} ×{n}")

    # --- 风格六条（2026-10-18《角色研读样张 v1》；只 WARN，不拦） ---
    # 实测依据：真人句长中位 13–24 字、p90 达 53–111；短句占多数；约 20% 句子有留白。
    # 2026-10-20 修：**块太短就不判**。短块（2 轮）只有 4–6 个小句，
    # p90/中位 恒在 1.0–1.5，统计量没有意义；留白/称呼也不该每块都要求。
    STYLE_MIN_CHARS = 200
    if (sent_lens and len(sent_lens) >= 6 and len(plain_text) >= STYLE_MIN_CHARS
            and not raw_ok):
        sl = sorted(sent_lens)
        med = sl[len(sl) // 2]
        p90 = sl[min(len(sl) - 1, int(len(sl) * 0.9))]
        short_ratio = sum(1 for x in sent_lens if x <= 20) / len(sent_lens)
        if short_ratio < 0.25:
            warns.append(f"风格·短句偏少({short_ratio:.0%}≤20字，宜≥25%)")
        if med and p90 / med < 1.8:
            warns.append(f"风格·句长太匀(p90/中位={p90 / med:.1f}，宜≥1.8；中位{med}字/p90 {p90}字)")
    # 2026-10-20 改：**留白与称呼是"语感习惯"，不是每块都要有**。
    # 实测对话样本 76% 的块有留白、66% 的块有称呼——已达真人水平
    # （《角色研读样张 v1》：约 20% 句子有留白，称呼是习惯不是义务）。
    # 逐块要求会把 1155 块打成 WARN，噪声淹没有效信息。改为**全库口径**统计，
    # 在 run_file 里汇总报告，不再影响单块状态。
    if "…" not in plain_text:
        infos.append("无留白")
    if not re.search(r"老爹|利贞", plain_text):
        infos.append("未称呼")

    # --- 指标 ---
    metrics = {
        "rounds": rounds, "turns": len(ts), "max_turn": mx,
        "avg_turn": (sum(lens) // len(lens)) if lens else 0,
        "short_turns": sum(1 for l in lens if l < 15),
        "interjections": len(re.findall(r"哎哟|好家伙|嘿|哟|嗯|咦|哈|喂|欸|哦|呀|嘛|呗|啦|喽|哎|哼|啧|切", joined)),
        "endings": dict(ends), "self_refs": kinds,
    }
    neg = str(_meta_now.get("negative", "")).strip().lower() == "true"
    if neg and fails:
        # 负样本：内容不合格是**预期**的（留档供 DPO），单列 NEG 状态，不计入 FAIL
        status = "NEG"
    else:
        status = "FAIL" if fails else ("WARN" if warns else "PASS")
    return {"name": name + (" [RAW]" if raw_ok else "") + (" [NEG]" if neg else ""),
            "status": status,
            "fails": fails, "warns": warns, "infos": infos, "metrics": metrics,
            "raw": raw_ok, "raw_skipped": raw_skipped, "negative": neg}


def run_file(path: Path, profile: str, out_lines: list[str]) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = parse_blocks(text)
    results = []
    out_lines.append(f"\n## 文件: {path.name}（档={profile}，块数={len(blocks)}）")
    for blk in blocks:
        if not parse_turns(blk) and not parse_meta(blk):
            out_lines.append(f"\n【{blk.splitlines()[0][3:][:40]}】=> SKIP（非素材块）")
            continue
        name = blk.splitlines()[0][3:][:40]
        r = check_block(name, blk, profile)
        results.append(r)
        out_lines.append(f"\n【{r['name']}】=> {r['status']}")
        m = r["metrics"]
        out_lines.append(f"  · 轮数={m['rounds']} 发言={m['turns']} 最长轮={m['max_turn']} 平均={m['avg_turn']}"
                         f" | 短轮={m['short_turns']} 语气词={m['interjections']}")
        out_lines.append(f"  · 自称={m['self_refs']} 收尾={m['endings']}")
        for f in r["fails"]:
            out_lines.append(f"  [FAIL] {f}")
        for w in r["warns"]:
            out_lines.append(f"  [WARN] {w}")
        for i in r.get("infos", []):
            out_lines.append(f"  [i] {i}（习惯项，只统计）")
    # 语感习惯的全库口径
    if results:
        n = len(results)
        n_ell = sum(1 for r in results if "无留白" not in r.get("infos", []))
        n_call = sum(1 for r in results if "未称呼" not in r.get("infos", []))
        out_lines.append(f"\n  语感习惯（全库口径）：有留白 {n_ell}/{n}（{100 * n_ell / n:.0f}%，宜≥60%）"
                         f"｜有称呼 {n_call}/{n}（{100 * n_call / n:.0f}%，宜≥40%）")
    return {"file": str(path), "profile": profile, "blocks": results,
            "summary": {s: sum(1 for r in results if r["status"] == s)
                        for s in ("PASS", "WARN", "FAIL", "NEG")}}


# ---------------- 自测 ----------------

def _fixture(rounds=21, ultra=420, issue=None) -> str:
    """生成合法/故意违例的小块；issue 注入单一问题。"""
    fiction = True
    head = ["## 故事-999｜自测块",
            "- category: 世界观", "- subtype: 自测", "- status: candidate",
            "- emotion: calm", "- length_tier: long", "- contract: VOICE_ANCHOR"]
    if fiction:
        head.append("- fiction: true")
    body = []
    qa = ["今晚吃啥。", "吃面。", "咱说面！", "我随便。", "本小姐点菜。", "行不行？"]
    for r in range(1, rounds + 1):
        body.append(f"### 老爹问{r}\n{qa[(r - 1) % 6]}")
        ans = qa[(r + 2) % 6]
        if r == 1 and ultra:
            ans = "咱" + ("今天晚饭就吃面条吧" * ((ultra // 9) + 3))[:ultra - 1]
        if r == 2 and issue == "理论":
            ans = "这事理论上来说能办。"
        if r == 3 and issue == "客服":
            ans = "我为您准备就绪。"
        if r == 4 and issue == "分号":
            ans = "吃面；还是吃饭？"
        if r == 5 and issue == "名泄漏":
            ans = "克莱恩说过这句。"
        if r == 6 and issue == "自称单一":
            ans = "好。"
        body.append(f"### 元亨答{r}\n{ans}")
    if issue == "说话人":
        body.append("### 路人问99\n你好。\n### 元亨答99\n你好。")
    if issue == "大肥鱼":
        body.append("### 大肥鱼问99\n汪。\n### 元亨答99\n别叫。")
    return "\n".join(head) + "\n" + "\n".join(body) + "\n"


def selftest() -> int:
    cases = [
        ("合法块 story", _fixture(), "story", None),
        ("轮数不足 story", _fixture(rounds=15), "story", "FAIL"),
        ("超长句不足 story", _fixture(ultra=300), "story", "FAIL"),
        ("客服腔 story", _fixture(issue="客服"), "story", "FAIL"),
        ("分号 story（2026-10-18 起降为 WARN）", _fixture(issue="分号"), "story", None),
        ("元亨理论 story", _fixture(issue="理论"), "story", "FAIL"),
        ("来源名泄漏 story", _fixture(issue="名泄漏"), "story", "FAIL"),
        ("未授权说话人 story", _fixture(issue="说话人"), "story", "FAIL"),
        ("大肥鱼发言 story", _fixture(issue="大肥鱼"), "story", "FAIL"),
        ("合法块 general（轮数少也行）", _fixture(rounds=6, ultra=0), "general", None),
        ("客服腔 general", _fixture(rounds=6, ultra=0, issue="客服"), "general", "FAIL"),
    ]
    ok = True
    print(f"门控自测 v{VERSION}（{len(cases)} 用例）")
    for label, text, profile, expect in cases:
        blk = parse_blocks(text)[0]
        r = check_block(label, blk, profile)
        got = r["status"]
        passed = (expect is None and got in ("PASS", "WARN")) or (expect == "FAIL" and got == "FAIL")
        ok &= passed
        fails = "; ".join(r["fails"]) or "-"
        print(f"  [{'ok' if passed else 'BAD'}] {label}: got={got} expect={expect or 'PASS/WARN'} fails={fails[:80]}")
    print("自测结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 3


# ---------------- CLI ----------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=f"V9 素材门控 v{VERSION}")
    ap.add_argument("paths", nargs="*", help="待检文件或目录")
    ap.add_argument("--profile", choices=["story", "general"], default="story")
    ap.add_argument("--json", action="store_true", help="另存 .gate.json")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.paths:
        ap.print_help()
        return 2

    files: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            files += sorted(x for x in p.glob("*.md"))
        elif p.is_file():
            files.append(p)
        else:
            print(f"[跳过] 不存在: {p}")
    if not files:
        print("没有可检文件")
        return 2

    grand = Counter()
    reps = []
    for fp in files:
        lines: list[str] = []
        rep = run_file(fp, args.profile, lines)
        for k, v in rep["summary"].items():
            grand[k] += v
        reps.append((fp, rep, lines))
    total = (f"== 总计: PASS={grand['PASS']} WARN={grand['WARN']} "
             f"FAIL={grand['FAIL']} NEG={grand['NEG']} ==")
    printed = []
    for fp, rep, lines in reps:
        block = "\n".join(lines + ["", total])
        printed.append(block)
        rp = Path(str(fp) + ".gate.txt")
        io.open(rp, "w", encoding="utf-8").write(
            f"# 门控报告 v{VERSION}｜{fp.name}（档={args.profile}）\n" + block + "\n")
        if args.json:
            jp = Path(str(fp) + ".gate.json")
            payload = {k: v for k, v in rep.items() if k != "lines"}
            io.open(jp, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=1))
    print("\n\n".join(printed))
    print(f"\n（报告已存: <文件>.gate.txt{'; JSON 已存' if args.json else ''}）")
    return 1 if grand["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
