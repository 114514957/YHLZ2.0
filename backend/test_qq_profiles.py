"""Offline tests for the QQ member profile builder (2026-10-06)."""
import pathlib
import tempfile
import unittest

from backend.qq_group_store import GroupHistoryStore
from backend.qq_profiles import MemberProfileStore


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.history = GroupHistoryStore(self.tmp / "h.db", bot_uin="900")
        rows = [
            ("A", "111", "1", "今晚开黑打王者吗", 1),
            ("A", "111", "2", "代码又出bug了，程序跑不动", 2),
            ("A", "111", "3", "哈哈哈这算法真有意思", 3),
            ("B", "111", "4", "原神抽卡歪了", 4),
            ("A", "222", "1", "火锅真好吃", 20),
            ("A", "222", "2", "奶茶续命", 21),
            ("A", "333", "1", "", 22),
        ]
        for group, sender, mid, text, _ in rows:
            self.history.add(group_id=group,
                             message_id=f"{group}-{sender}-{mid}",
                             sender_id=sender, sender_name=f"群友{sender}",
                             text=text, at=1790000000 + int(mid))
        self.history.add(group_id="A", message_id="bot-1", sender_id="900",
                         text="元亨说话", is_bot=True, at=1790000100)
        self.history.add(group_id="A", message_id="weird", sender_id="abc",
                         text="不是数字", at=1790000200)
        self.store = MemberProfileStore(self.tmp / "profiles.db")

    def test_rebuild_and_hobbies(self):
        updated = self.store.rebuild(self.history, now=1790001000)
        self.assertEqual(updated, 2)          # bot/非数字/空文本不算
        profile = self.store.get("111")
        self.assertEqual(profile["msg_count"], 4)
        self.assertEqual(len(profile["groups"]), 2)
        hobbies = {h["name"]: h["count"] for h in profile["hobbies"]}
        # 2026-10-12：按“消息条数”计（原按词命中，会重复计）。
        self.assertGreaterEqual(hobbies.get("游戏", 0), 2)
        self.assertGreaterEqual(hobbies.get("AI与编程", 0), 2)

    def test_profile_text_and_list(self):
        self.store.rebuild(self.history, now=1790001000)
        text = MemberProfileStore.profile_text(self.store.get("111"))
        self.assertIn("人物档案", text)
        self.assertIn("爱好", text)
        self.assertIn("游戏", text)
        listing = self.store.list_text()
        self.assertIn("111", listing)
        self.assertIn("222", listing)

    def test_min_messages_filter(self):
        self.assertEqual(self.store.rebuild(self.history, min_messages=3,
                                            now=1), 1)
        self.assertIsNotNone(self.store.get("111"))
        self.assertIsNone(self.store.get("222"))

    def test_rebuild_is_idempotent(self):
        first = self.store.rebuild(self.history, now=1)
        second = self.store.rebuild(self.history, now=2)
        self.assertEqual(first, second)
        self.assertEqual(self.store.count(), first)
        self.assertEqual(self.store.get("111")["msg_count"], 4)

    def test_role_media_style_and_brief(self):
        # 2026-10-09：身份（老爹/群友）+ 媒体习惯进风格 + 单行卡 brief。
        self.history.add(group_id="A", message_id="md-1", sender_id="111",
                         sender_name="群友111", text="嘿嘿嘿嘿",
                         media=[{"type": "face"}, {"type": "face"},
                                {"type": "face"}],
                         at=1790000300)
        updated = self.store.rebuild(self.history, masters={"111"},
                                     now=1790002000)
        self.assertEqual(updated, 2)
        master = self.store.get("111")
        self.assertEqual(master["role"], "老爹（主人）")
        self.assertEqual(self.store.get("222")["role"], "群友")
        self.assertIn("常发表情", master["style"])
        card = self.store.brief("111")
        self.assertIn("群友111(111)", card)
        self.assertIn("老爹（主人）", card)
        self.assertLessEqual(len(card), 180)
        self.assertEqual(self.store.brief("999"), "")
        text = MemberProfileStore.profile_text(master)
        self.assertIn("身份：老爹（主人）", text)
        self.assertIn("口头禅", text)
        listing = self.store.list_text()
        self.assertIn("★", listing)

    def test_relations_follow_and_mention(self):
        # 跟谁熟（2026-10-09）：接话相邻（双方都有文字）+ 昵称点名。
        self.history.add(group_id="A", message_id="rel-1", sender_id="222",
                         sender_name="群友222", text="在吗在吗",
                         at=1790000090)
        self.history.add(group_id="A", message_id="rel-2", sender_id="111",
                         sender_name="群友111", text="群友222 在的",
                         at=1790000095)
        self.history.add(group_id="A", message_id="rel-3", sender_id="111",
                         sender_name="群友111", text="你继续", at=1790000100)
        self.history.add(group_id="A", message_id="rel-4", sender_id="222",
                         sender_name="群友222", text="好哈哈哈",
                         at=1790000105)
        self.store.rebuild(self.history, now=1790003000)
        p111 = self.store.get("111")
        pairs = {i["qq"]: i["score"] for i in p111["inter"]}
        self.assertIn("222", pairs)
        self.assertGreaterEqual(pairs["222"], 2)
        p222 = self.store.get("222")
        self.assertTrue(any(i["qq"] == "111" for i in p222["inter"]))
        text = MemberProfileStore.profile_text(p111)
        self.assertIn("跟谁熟", text)
        self.assertIn("跟谁熟", self.store.brief("111"))
        hits = self.store.search_name("群友22")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["qq"], "222")

    def test_words_no_fragments(self):
        # 2026-10-12：jieba 整词——"看起来"不应拆出 看起/起来 碎片。
        for i in range(3):
            self.history.add(group_id="A", message_id=f"w-{i}",
                             sender_id="333", sender_name="群友333",
                             text="看起来今天要下雨", at=1790000400 + i)
        self.store.rebuild(self.history, now=1790005000)
        words = self.store.get("333")["words"]
        self.assertIn("看起来", words)
        self.assertNotIn("看起", words)
        self.assertNotIn("起来", words)

    def test_words_fallback_no_fragments(self):
        # 无 jieba 时的子串折叠兜底（把模块级缓存强制为 False 走 n-gram 路）。
        import backend.qq_profiles as qp

        for i in range(3):
            self.history.add(group_id="A", message_id=f"wf-{i}",
                             sender_id="333", sender_name="群友333",
                             text="看起来今天要下雨", at=1790000600 + i)
        old = qp._JIEBA
        qp._JIEBA = False
        try:
            self.store.rebuild(self.history, now=1790006000)
        finally:
            qp._JIEBA = old
        words = self.store.get("333")["words"]
        self.assertIn("看起来", words)
        self.assertNotIn("看起", words)
        self.assertNotIn("起来", words)

    def test_hobbies_count_per_message(self):
        # 2026-10-12：同类多词命中按“消息条数”计（睡+睡觉 不翻倍）。
        self.history.add(group_id="A", message_id="hb-1", sender_id="444",
                         sender_name="群友444", text="好累，睡觉睡觉，想睡",
                         at=1790000700)
        self.store.rebuild(self.history, now=1790007000)
        hobbies = {h["name"]: h["count"]
                   for h in self.store.get("444")["hobbies"]}
        self.assertEqual(hobbies.get("作息健康"), 1)

    def test_pet_lexicon_drops_meow(self):
        # 2026-10-12：喵/汪 不再算宠物信号（人设口癖）；"猫咪"仍计。
        self.history.add(group_id="A", message_id="pet-1", sender_id="555",
                         sender_name="群友555", text="喵呜喵呜喵",
                         at=1790000800)
        self.history.add(group_id="A", message_id="pet-2", sender_id="555",
                         sender_name="群友555", text="我家猫咪真可爱",
                         at=1790000810)
        self.store.rebuild(self.history, now=1790008000)
        hobbies = {h["name"]: h["count"]
                   for h in self.store.get("555")["hobbies"]}
        self.assertEqual(hobbies.get("宠物"), 1)


if __name__ == "__main__":
    unittest.main()
