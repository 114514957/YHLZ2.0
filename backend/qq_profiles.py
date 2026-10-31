"""QQ group member profiles for Lite (2026-10-06).

Derived, local-only profiles for every group member who has spoken: message
counts, active hours, interest categories (curated lexicon), frequent words
and a couple of recent quotes. No LLM required; every hobby line carries
evidence counts so it can be audited. Data source is the profile-scoped
group history DB.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import time

INTERESTS: dict[str, tuple[str, ...]] = {
    "游戏": ("游戏", "开黑", "王者", "荣耀", "吃鸡", "原神", "星穹", "崩坏",
             "lol", "英雄联盟", "下棋", "麻将", "斗地主", "塞尔达", "steam",
             "副本", "打本", "抽卡", "上分", "排位", "手游", "网游", "单机",
             "csgo", "cs2", "永劫无间", "黑神话", "金铲铲"),
    "AI与编程": ("ai", "模型", "训练", "代码", "程序", "bug", "部署", "显卡",
                 "显存", "python", "java", "开源", "github", "微调", "大模型",
                 "智能体", "agent", "prompt", "提示词", "算法", "接口", "脚本",
                 "前端", "后端", "数据库", "服务器", "linux",
                 "token", "api", "推理", "算力", "语料", "数据集", "标注",
                 "对齐", "蒸馏", "量化", "embedding", "rag", "llm"),
    "音乐": ("歌", "音乐", "唱歌", "翻唱", "吉他", "钢琴", "耳机", "音箱",
             "演唱会", "专辑", "乐队", "旋律", "歌词",
             "术力口", "vocaloid", "初音", "miku", "电音", "民谣"),
    "动漫二次元": ("动漫", "番剧", "新番", "追番", "漫画", "二次元", "手办",
                   "cos", "声优", "谷子", "痛包"),
    "影视": ("电影", "美剧", "日剧", "韩剧", "纪录片", "追剧", "票房",
             "剧情", "综艺"),
    "运动健身": ("健身", "跑步", "骑车", "骑行", "游泳", "篮球", "足球",
                 "羽毛球", "乒乓球", "爬山", "撸铁", "马拉松", "徒步", "瑜伽"),
    "美食": ("好吃", "美食", "火锅", "奶茶", "咖啡", "做饭", "下厨", "烧烤",
             "蛋糕", "零食", "外卖", "夜宵", "干饭", "餐厅"),
    "旅行摄影": ("旅游", "旅行", "摄影", "拍照", "相机", "风景", "露营",
                 "自驾", "机票", "酒店", "打卡"),
    "学习考试": ("学习", "考试", "考研", "高考", "论文", "英语", "单词",
                 "读书", "看书", "大学", "课程", "笔记",
                 "作业", "刷题", "上课", "晚自习"),
    "工作职场": ("上班", "加班", "老板", "会议", "摸鱼", "工资", "面试",
                 "毕业", "找工作", "项目", "同事", "客户", "出差"),
    "宠物": ("猫", "狗", "猫猫", "狗狗", "仓鼠", "宠物", "铲屎", "橘猫"),
    "数码": ("手机", "电脑", "装机", "键盘", "鼠标", "显示器", "nas",
             "路由", "机械键盘"),
    "作息健康": ("熬夜", "失眠", "睡觉", "睡", "减肥", "早睡", "补觉"),
    "情感日常": ("心情", "开心", "难过", "emo", "焦虑", "烦", "郁闷", "幸福"),
}
_STOPWORDS = ("的", "了", "是", "我", "你", "他", "她", "它", "们", "这", "那",
              "在", "和", "就", "都", "也", "不", "吗", "吧", "啊", "呢", "还",
              "有", "没", "一个", "什么", "怎么", "可以", "现在", "真的",
              # 多字泛词（2026-10-09：提高"口头禅"信噪比）
              "自己", "知道", "觉得", "感觉", "就是", "没有", "时候", "如果",
              "因为", "所以", "但是", "这么", "那么", "东西", "事情", "问题",
              "我们", "你们", "他们", "大家", "今天", "明天", "昨天", "不是",
              "这个", "那个", "一下", "一样", "一起", "有点", "应该",
              # 2026-10-12：AI对话群抽样新增（身份词/泛词不进"口头禅"）
              "群友", "个人", "已经")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  qq          TEXT PRIMARY KEY,
  nickname    TEXT NOT NULL DEFAULT '',
  first_seen  REAL NOT NULL DEFAULT 0,
  last_seen   REAL NOT NULL DEFAULT 0,
  msg_count   INTEGER NOT NULL DEFAULT 0,
  groups_json TEXT NOT NULL DEFAULT '[]',
  hours_json  TEXT NOT NULL DEFAULT '{}',
  hobbies_json TEXT NOT NULL DEFAULT '[]',
  words_json  TEXT NOT NULL DEFAULT '[]',
  style       TEXT NOT NULL DEFAULT '',
  quotes_json TEXT NOT NULL DEFAULT '[]',
  updated_at  REAL NOT NULL DEFAULT 0
);
"""

_COLUMN_ADD = [
    # 身份（2026-10-09）：老爹（主人）/ 群友；预留后续群内职务等。
    ("role", "TEXT NOT NULL DEFAULT ''"),
    # 跟谁熟（2026-10-09）：接话相邻 + 昵称点名 → top3 [{"qq","name","score"}]。
    ("inter_json", "TEXT NOT NULL DEFAULT '[]'"),
]


def _hour_label(hours: dict) -> str:
    if not hours:
        return ""
    buckets = {
        "凌晨(0-6)": sum(hours.get(str(h), 0) for h in range(0, 6)),
        "上午(6-12)": sum(hours.get(str(h), 0) for h in range(6, 12)),
        "下午(12-18)": sum(hours.get(str(h), 0) for h in range(12, 18)),
        "晚上(18-24)": sum(hours.get(str(h), 0) for h in range(18, 24)),
    }
    top = sorted(buckets.items(), key=lambda kv: -kv[1])
    return "、".join(f"{k}×{v}" for k, v in top if v > 0)[:60]


def _hobbies(texts: list[str]) -> list[dict]:
    """爱好证据（2026-10-12 v2）：按"提及该类的消息条数"计，避免同类多词重复计。"""
    hits: dict[str, int] = {}
    blobs = [t.lower() for t in texts]
    for name, words in INTERESTS.items():
        count = 0
        for blob in blobs:
            if any(w.lower() in blob for w in words):
                count += 1
        if count:
            hits[name] = count
    return [{"name": k, "count": v}
            for k, v in sorted(hits.items(), key=lambda kv: -kv[1])]


_JIEBA = None


def _jieba_cut(text: str):
    """jieba 整词切分（懒加载；不可用返回 None → 退回 n-gram）。"""
    global _JIEBA
    if _JIEBA is None:
        try:
            import jieba

            jieba.setLogLevel(60)
            _JIEBA = jieba
        except Exception:  # noqa: BLE001
            _JIEBA = False
    if not _JIEBA:
        return None
    return list(_JIEBA.cut(text))


def _words(texts: list[str], top: int = 8) -> list[str]:
    """常用词/口头禅（v2 · 2026-10-12）：优先 jieba 整词，消除子串碎片。

    旧版 2/3-gram 统计会产出「看起/起来/看起来」「呼噜/噜噜/呼噜噜」这类
    互相包含的碎片。现在：jieba 不可用时退回 n-gram；两条路都再过一遍
    「子串折叠」——近频次的长词吸收短子串，保证只留整词。
    """
    freq: dict[str, int] = {}
    for text in texts:
        tokens = _jieba_cut(text)
        if tokens is None:
            for size in (2, 3):
                for i in range(0, max(0, len(text) - size + 1)):
                    gram = text[i:i + size]
                    # 单字停用词命中 + 多字停用词整词命中（2026-10-09 修复：
                    # 原先只按单字过滤，"什么/一个/现在"等多字停用词会漏进口头禅）。
                    if gram in _STOPWORDS or any(
                            c in _STOPWORDS for c in gram):
                        continue
                    if not all("\u4e00" <= c <= "\u9fff" for c in gram):
                        continue
                    freq[gram] = freq.get(gram, 0) + 1
            continue
        for tok in tokens:
            tok = tok.strip()
            if len(tok) < 2 or tok in _STOPWORDS:
                continue
            if any(c in _STOPWORDS for c in tok):
                continue
            if not all("\u4e00" <= c <= "\u9fff" for c in tok):
                continue
            freq[tok] = freq.get(tok, 0) + 1
    ordered = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    kept: list[str] = []
    for word, count in ordered:
        if count < 2:
            continue
        covered = False
        for k in kept:
            if word != k and word in k and count <= freq[k] + max(
                    1, freq[k] // 5):
                covered = True
                break
        if covered:
            continue
        kept.append(word)
        if len(kept) >= top:
            break
    return kept


def _style(texts: list[str], media: dict | None = None,
           msg_count: int = 0) -> str:
    """说话风格（2026-10-09 扩展）：句长、笑点/提问习惯、表情/图片/语音习惯。"""
    if not texts:
        return ""
    avg = sum(len(t) for t in texts) / len(texts)
    laugh = sum(1 for t in texts if any(k in t for k in ("哈哈", "233", "草", "乐")))
    question = sum(1 for t in texts if t.endswith(("?", "？")))
    bits = [f"平均{avg:.0f}字/条"]
    if laugh / len(texts) >= 0.2:
        bits.append("爱笑/爱刷梗")
    if question / len(texts) >= 0.3:
        bits.append("爱提问")
    media = media or {}
    base = max(int(msg_count or 0), len(texts), 1)
    emoji = int(media.get("face", 0)) + int(media.get("mface", 0))
    if emoji >= 3 and emoji / base >= 0.08:
        bits.append("常发表情")
    if int(media.get("image", 0)) >= 2 and int(media.get("image", 0)) / base >= 0.05:
        bits.append("常发图")
    if int(media.get("record", 0)) >= 2:
        bits.append("发过语音")
    return "，".join(bits)


class MemberProfileStore:
    def __init__(self, db_path) -> None:
        self.db_path = pathlib.Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db_path), timeout=15)
        con.executescript(_SCHEMA)
        cols = {r[1] for r in con.execute(
            "PRAGMA table_info(members)").fetchall()}
        for name, decl in _COLUMN_ADD:
            if name not in cols:
                con.execute(f"ALTER TABLE members ADD COLUMN {name} {decl}")
        con.commit()
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=15)
        con.row_factory = sqlite3.Row
        return con

    def upsert(self, qq: str, **fields) -> None:
        keys = list(fields)
        con = self._con()
        try:
            exists = con.execute("SELECT qq FROM members WHERE qq=?",
                                 (str(qq),)).fetchone()
            if exists:
                sets = ", ".join(f"{k}=?" for k in keys)
                con.execute(f"UPDATE members SET {sets} WHERE qq=?",
                            (*fields.values(), str(qq)))
            else:
                cols = ", ".join(["qq", *keys])
                marks = ", ".join("?" for _ in range(len(keys) + 1))
                con.execute(f"INSERT INTO members({cols}) VALUES({marks})",
                            (str(qq), *fields.values()))
            con.commit()
        finally:
            con.close()

    def rebuild(self, history, *, min_messages: int = 1,
                now: float | None = None, masters=None,
                bot_uin: str = "") -> int:
        """Rebuild all profiles from the group history store.

        masters（2026-10-09）：主人的 QQ 集合 → 档案里标身份「老爹（主人）」；
        同时统计媒体习惯（表情/图片/语音）供说话风格使用。
        """
        now = time.time() if now is None else now
        master_set = {str(m) for m in (masters or ()) if str(m).strip()}
        rows = history.all_messages()
        agg: dict[str, dict] = {}
        for row in rows:
            if row.get("is_bot"):
                continue
            qq = str(row.get("sender_id") or "")
            if not qq.isdigit():
                continue
            item = agg.setdefault(qq, {
                "nickname": "", "first": float(row.get("at") or 0),
                "last": 0.0, "count": 0, "groups": set(), "hours": {},
                "texts": [], "quotes": [], "media": {}})
            item["count"] += 1
            at = float(row.get("at") or 0)
            item["last"] = max(item["last"], at)
            item["first"] = min(item["first"] or at, at)
            item["groups"].add(str(row.get("group_id") or ""))
            hour = time.localtime(at).tm_hour if at else 0
            item["hours"][str(hour)] = item["hours"].get(str(hour), 0) + 1
            name = str(row.get("sender_name") or "").strip()
            if name:
                item["nickname"] = name
            try:
                for m in json.loads(row.get("media") or "[]"):
                    kind = str((m or {}).get("type") or "")
                    if kind:
                        item["media"][kind] = item["media"].get(kind, 0) + 1
            except Exception:
                pass
            text = " ".join(str(row.get("text") or "").split())
            if text:
                item["texts"].append(text)
                if len(item["quotes"]) < 3 and not text.startswith("["):
                    item["quotes"].append(text[:60])
        # ---- 跟谁熟（2026-10-09）：接话相邻（≤300s 且换人）+ 昵称点名 ----
        rel: dict[str, dict[str, int]] = {}

        def _bump(a: str, b: str, w: int) -> None:
            rel.setdefault(a, {})
            rel[a][b] = rel[a].get(b, 0) + w

        nick_of = {qq: item["nickname"] for qq, item in agg.items()
                   if len(item["nickname"]) >= 2}
        pat = None
        nick_to_qq: dict[str, str] = {}
        if nick_of:
            ordered = sorted(nick_of.items(), key=lambda kv: -len(kv[1]))
            nick_to_qq = {name: qq for qq, name in ordered}
            pat = re.compile("|".join(re.escape(n) for n in nick_to_qq))
        by_group: dict[str, list] = {}
        for row in rows:
            by_group.setdefault(str(row.get("group_id") or ""), []).append(row)
        for msgs in by_group.values():
            msgs.sort(key=lambda r: int(r.get("seq") or 0))
            prev = None
            for row in msgs:
                sender = str(row.get("sender_id") or "")
                if row.get("is_bot") or not sender.isdigit():
                    continue
                at = float(row.get("at") or 0)
                text = str(row.get("text") or "")
                if text and pat is not None:
                    for m in pat.finditer(text):
                        other = nick_to_qq.get(m.group(0))
                        if other and other != sender:
                            _bump(sender, other, 3)
                if (prev and prev[0] != sender and prev[2] and text
                        and prev[1] and at and 0 <= at - prev[1] <= 300):
                    _bump(sender, prev[0], 1)
                    _bump(prev[0], sender, 1)
                prev = (sender, at, bool(text))
        updated = 0
        for qq, item in agg.items():
            if item["count"] < int(min_messages) or not item["texts"]:
                continue
            inter = [
                {"qq": other,
                 "name": (agg.get(other, {}).get("nickname")
                          or f"群友{str(other)[-4:]}"),
                 "score": score}
                for other, score in sorted(rel.get(qq, {}).items(),
                                           key=lambda kv: -kv[1])
                if score >= 2][:3]
            self.upsert(
                qq, nickname=item["nickname"][:40],
                role=("老爹（主人）" if qq in master_set else "群友"),
                first_seen=item["first"], last_seen=item["last"],
                msg_count=item["count"],
                groups_json=json.dumps(sorted(item["groups"]),
                                       ensure_ascii=False),
                hours_json=json.dumps(item["hours"], ensure_ascii=False),
                hobbies_json=json.dumps(_hobbies(item["texts"]),
                                        ensure_ascii=False),
                words_json=json.dumps(_words(item["texts"]),
                                      ensure_ascii=False),
                style=_style(item["texts"], item["media"], item["count"]),
                quotes_json=json.dumps(item["quotes"], ensure_ascii=False),
                inter_json=json.dumps(inter, ensure_ascii=False),
                updated_at=now)
            updated += 1
        return updated

    def get(self, qq: str) -> dict | None:
        con = self._con()
        try:
            row = con.execute("SELECT * FROM members WHERE qq=?",
                              (str(qq),)).fetchone()
        finally:
            con.close()
        if not row:
            return None
        data = dict(row)
        for key in ("groups_json", "hours_json", "hobbies_json",
                    "words_json", "quotes_json", "inter_json"):
            try:
                data[key[:-5]] = json.loads(data.get(key) or "[]")
            except Exception:
                data[key[:-5]] = []
        return data

    def list_members(self, limit: int = 20) -> list[dict]:
        con = self._con()
        try:
            rows = con.execute(
                "SELECT qq, nickname, role, msg_count, hobbies_json, last_seen "
                "FROM members ORDER BY msg_count DESC, last_seen DESC LIMIT ?",
                (int(limit),)).fetchall()
        finally:
            con.close()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["hobbies"] = json.loads(item.pop("hobbies_json") or "[]")
            except Exception:
                item["hobbies"] = []
            out.append(item)
        return out

    def count(self) -> int:
        con = self._con()
        try:
            return int(con.execute("SELECT COUNT(*) FROM members").fetchone()[0])
        finally:
            con.close()

    # ---- presentation ----------------------------------------------------
    @staticmethod
    def profile_text(profile: dict) -> str:
        qq = str(profile.get("qq") or "")
        name = profile.get("nickname") or f"群友{qq[-4:]}"
        groups = profile.get("groups") or []
        hobbies = profile.get("hobbies") or []
        words = profile.get("words") or []
        quotes = profile.get("quotes") or []
        lines = [f"【人物档案】{name}（{qq}）",
                 f"身份：{profile.get('role') or '群友'} ｜ 发言 {profile.get('msg_count', 0)} 条 / "
                 f"群 {len(groups)} 个 / 活跃时段 {_hour_label(profile.get('hours') or {}) or '未知'}"]
        if hobbies:
            lines.append("爱好：" + "、".join(
                f"{h['name']}({h['count']})" for h in hobbies[:5]))
        inter = profile.get("inter") or []
        if inter:
            lines.append("跟谁熟：" + "、".join(
                f"{i.get('name')}({i.get('score')})" for i in inter[:3]))
        if words:
            head = "、".join(words[:8])
            mouth = "、".join(words[:2])
            lines.append(f"常用词：{head}（口头禅：{mouth}）")
        if profile.get("style"):
            lines.append("风格：" + str(profile["style"]))
        if quotes:
            lines.append("印象句：" + " / ".join(f"“{q}”" for q in quotes[:2]))
        if profile.get("last_seen"):
            lines.append("最近发言：" + time.strftime(
                "%m-%d %H:%M", time.localtime(float(profile["last_seen"]))))
        return "\n".join(lines)

    def brief(self, qq: str, max_len: int = 180) -> str:
        """紧凑单行卡（2026-10-09：注入她当前轮上下文用）。无档案返回空串。

        优先级：名字/身份/发言量 > 常聊 > 跟谁熟 > 口头禅 > 风格；超长按序裁剪。
        """
        profile = self.get(str(qq))
        if not profile:
            return ""
        name = profile.get("nickname") or f"群友{str(qq)[-4:]}"
        parts = [f"{name}({qq})", str(profile.get("role") or "群友"),
                 f"发言{profile.get('msg_count', 0)}"]
        hobbies = profile.get("hobbies") or []
        if hobbies:
            parts.append("常聊: " + "、".join(h["name"] for h in hobbies[:2]))
        inter = profile.get("inter") or []
        if inter:
            parts.append("跟谁熟: " + "、".join(
                str(i.get("name")) for i in inter[:2]))
        words = profile.get("words") or []
        if words:
            parts.append("口头禅: " + "/".join(words[:2]))
        if profile.get("style"):
            parts.append(str(profile["style"]))
        while len("｜".join(parts)) > int(max_len) and len(parts) > 3:
            parts.pop()
        return "｜".join(parts)[:max_len]

    def search_name(self, fragment: str, limit: int = 5) -> list[dict]:
        """按昵称片段找人（精简条目：qq/昵称/身份/发言量）。"""
        frag = str(fragment or "").strip()
        if not frag:
            return []
        con = self._con()
        try:
            rows = con.execute(
                "SELECT qq, nickname, role, msg_count FROM members "
                "WHERE nickname LIKE ? ORDER BY msg_count DESC LIMIT ?",
                (f"%{frag}%", max(1, int(limit)))).fetchall()
        finally:
            con.close()
        return [dict(r) for r in rows]

    def list_text(self, limit: int = 20) -> str:
        rows = self.list_members(limit)
        if not rows:
            return "（还没有群友档案，群里有人说话后自动生成）"
        total = self.count()
        lines = [f"群友档案 共 {total} 人（显示前 {len(rows)}，按发言量）:"]
        for r in rows:
            hobbies = "、".join(h["name"] for h in (r.get("hobbies") or [])[:3])
            star = "★" if str(r.get("role") or "").startswith("老爹") else ""
            lines.append(f"{star}{r.get('nickname') or r['qq']}({r['qq']}) "
                         f"{r.get('role') or '群友'} · 发言{r['msg_count']}"
                         + (f" · {hobbies}" if hobbies else ""))
        return "\n".join(lines)
