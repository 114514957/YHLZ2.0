"""TCM v1 tests (ledger 0438): A1 stance, episodes, causal gate, why, as-of."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from backend.target_kw_index import KeywordIndex
from backend.target_memory import L2Item, TargetMemoryService, infer_stance


def _it(iid, summary, *, source="", kind="episodic", stance="",
        created=None, valid_at=0.0, protected=0):
    return L2Item(id=iid, tier="L2", type="fact", importance=5, summary=summary,
                  content_hash=iid, keywords=summary[:24],
                  created_at=created or time.time(), source=source, kind=kind,
                  stance=stance, valid_at=valid_at, protected=protected)


class TCMTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = TargetMemoryService(
            db_path=self.tmp / "m.db",
            kw_index=KeywordIndex(self.tmp / "kw.db"))

    # ---------- A1 stance ----------
    def test_infer_stance(self):
        self.assertEqual(infer_stance("老爹"), "fact")
        self.assertEqual(infer_stance("群聊"), "speculation")
        self.assertEqual(infer_stance("agent"), "opinion")
        self.assertEqual(infer_stance("", explicit="fact"), "fact")
        self.assertEqual(infer_stance(""), "speculation")

    def test_store_persists_stance(self):
        self.svc.store_item(_it("m1", "老爹喜欢靛蓝", source="老爹"))
        self.svc.store_item(_it("m2", "群里有人说显卡降价", source="群聊"))
        self.svc.store_item(_it("m3", "我认为该早睡", source="agent"))
        self.assertEqual(self.svc._item_brief("m1")["stance"], "fact")
        self.assertEqual(self.svc._item_brief("m2")["stance"], "speculation")
        self.assertEqual(self.svc._item_brief("m3")["stance"], "opinion")

    # ---------- episodes ----------
    def test_episode_add_list_dedupe(self):
        eid = self.svc.add_episode(channel="console", kind="voice",
                                   source="老爹", raw_ref="v1.wav",
                                   summary="买瓶醋", ts=1000.0)
        eid2 = self.svc.add_episode(channel="console", kind="voice",
                                    source="老爹", raw_ref="v1.wav",
                                    summary="买瓶醋", ts=1000.0)
        self.assertEqual(eid, eid2)
        rows = self.svc.list_episodes(channel="console")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_ref"], "v1.wav")

    # ---------- causal gate ----------
    def _seed(self):
        self.svc.store_item(_it("c1", "因为服务器过热所以服务重启了", source="老爹"))
        self.svc.store_item(_it("c2", "服务重启了", source="老爹"))

    def test_auto_gate_activates_verified_high_confidence(self):
        self._seed()
        res = self.svc.add_causal_edge(
            "c1", "c2", "cause", 0.9, quote="因为服务器过热所以服务重启了",
            created_by="auto:rule")
        self.assertEqual(res["status"], "active", res)

    def test_auto_gate_pending_low_confidence(self):
        self._seed()
        res = self.svc.add_causal_edge(
            "c1", "c2", "cause", 0.5, quote="因为服务器过热所以服务重启了")
        self.assertEqual(res["status"], "pending")
        self.assertIn("low-confidence", res["reasons"])

    def test_auto_gate_pending_risky_relation(self):
        self._seed()
        res = self.svc.add_causal_edge(
            "c1", "c2", "contradict", 0.99, quote="因为服务器过热所以服务重启了")
        self.assertEqual(res["status"], "pending")
        self.assertIn("relation-needs-review", res["reasons"])

    def test_auto_gate_pending_unverified_quote(self):
        self._seed()
        res = self.svc.add_causal_edge(
            "c1", "c2", "follow", 0.9, quote="这句话根本不存在")
        self.assertEqual(res["status"], "pending")
        self.assertIn("quote-unverified", res["reasons"])

    def test_auto_gate_pending_external_source(self):
        self.svc.store_item(_it("g1", "群里说因为显卡降价所以装机量涨了",
                                source="群聊"))
        self.svc.store_item(_it("g2", "装机量涨了", source="群聊"))
        res = self.svc.add_causal_edge(
            "g1", "g2", "cause", 0.95, quote="因为显卡降价所以装机量涨了")
        self.assertEqual(res["status"], "pending")
        self.assertIn("external-source", res["reasons"])

    def test_auto_gate_pending_profile_endpoint(self):
        # protected=1 keeps the profile item out of the automatic M2
        # supersede scan while we exercise the causal gate
        self.svc.store_item(_it("p1", "老爹因为过敏所以不吃海鲜",
                                source="老爹", kind="profile", protected=1))
        self.svc.store_item(_it("c2", "不吃海鲜", source="老爹"))
        res = self.svc.add_causal_edge(
            "p1", "c2", "cause", 0.95, quote="因为过敏所以不吃海鲜")
        self.assertEqual(res["status"], "pending")
        self.assertIn("profile-endpoint", res["reasons"])

    def test_auto_gate_pending_pair_conflict(self):
        self._seed()
        ok = self.svc.add_causal_edge(
            "c1", "c2", "cause", 0.9, quote="因为服务器过热所以服务重启了")
        self.assertEqual(ok["status"], "active")
        res = self.svc.add_causal_edge(
            "c1", "c2", "enable", 0.9, quote="因为服务器过热所以服务重启了")
        self.assertEqual(res["status"], "pending")
        self.assertIn("pair-conflict", res["reasons"])

    def test_auto_gate_daily_cap(self):
        self._seed()
        now = time.time()
        con = sqlite3.connect(str(self.svc.db_path))
        for i in range(5):
            con.execute(
                "INSERT INTO causal_edges(id,src_id,dst_id,relation,confidence,"
                "quote,status,created_by,created_at,activated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"cap{i}", "x", f"y{i}", "cause", 0.9, "", "active",
                 "auto:test", now, now))
        con.commit()
        con.close()
        res = self.svc.add_causal_edge(
            "c1", "c2", "cause", 0.9, quote="因为服务器过热所以服务重启了")
        self.assertEqual(res["status"], "pending")
        self.assertIn("daily-cap", res["reasons"])

    def test_owner_explicit_bypasses_guards(self):
        self.svc.store_item(_it("o1", "甲", source="群聊"))
        self.svc.store_item(_it("o2", "乙", source="群聊"))
        res = self.svc.add_causal_edge("o1", "o2", "cause", 0.2, quote="",
                                       created_by="owner")
        self.assertEqual(res["status"], "active")

    def test_rejects_bad_input(self):
        self._seed()
        self.assertEqual(
            self.svc.add_causal_edge("c1", "c2", "because", 0.9)["status"],
            "rejected")
        self.assertEqual(
            self.svc.add_causal_edge("c1", "nope", "cause", 0.9)["status"],
            "rejected")

    # ---------- why / undo ----------
    def test_why_and_undo(self):
        self._seed()
        res = self.svc.add_causal_edge(
            "c1", "c2", "cause", 0.9, quote="因为服务器过热所以服务重启了")
        rows = self.svc.why("c2")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["relation"], "cause")
        self.assertEqual(rows[0]["direction"], "backward")
        self.assertTrue(self.svc.causal_undo(res["edge_id"]))
        self.assertEqual(self.svc.why("c2"), [])
        self.assertFalse(self.svc.causal_undo(res["edge_id"]))

    # ---------- as-of time travel ----------
    def test_recall_as_of(self):
        now = time.time()
        item = _it("t1", "老爹在A公司", source="老爹", valid_at=1000.0)
        item.invalid_at = now - 10
        self.svc.store_item(item)
        self.assertEqual(self.svc.recall("A公司"), [])
        past = self.svc.recall("A公司", as_of=2000.0)
        self.assertEqual([h["id"] for h in past], ["t1"])

    # ---------- rule-based auto link ----------
    def test_extract_causal(self):
        from backend.target_memory import extract_causal

        pairs = extract_causal("因为机房温度报警所以服务器宕机了")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["cause"], "机房温度报警")
        self.assertEqual(pairs[0]["effect"], "服务器宕机了")
        self.assertEqual(pairs[0]["relation"], "cause")
        self.assertEqual(extract_causal("今天天气不错"), [])

    def test_auto_rule_link_creates_active_edge(self):
        self.svc.store_item(_it("b1", "机房温度报警持续了十分钟", source="老爹"))
        self.svc.store_item(_it("a1", "因为机房温度报警所以服务器宕机了",
                                source="老爹"))
        edges = self.svc.causal_list()
        self.assertTrue(edges)
        active = [e for e in edges if e["status"] == "active"]
        self.assertEqual(len(active), 1, edges)
        self.assertEqual(active[0]["src_id"], "b1")
        self.assertEqual(active[0]["dst_id"], "a1")
        self.assertEqual(active[0]["relation"], "cause")

    def test_auto_rule_link_external_stays_pending(self):
        self.svc.store_item(_it("gb", "群里在聊机房温度报警", source="群聊"))
        self.svc.store_item(_it("ga", "因为机房温度报警所以服务器宕机了",
                                source="群聊"))
        edges = self.svc.causal_list()
        self.assertTrue(edges)
        self.assertTrue(all(e["status"] == "pending" for e in edges), edges)

    def test_auto_rule_link_no_marker_no_edge(self):
        self.svc.store_item(_it("n1", "今天天气不错", source="老爹"))
        self.svc.store_item(_it("n2", "服务器重启了", source="老爹"))
        self.assertEqual(self.svc.causal_list(), [])

    # ---------- ledger 0441: shadow scoring + spreading ----------
    def test_shadow_scoring_logs_ordering(self):
        self.svc.store_item(_it("w1", "量子计算讨论一", source="老爹"))
        self.svc.store_item(_it("w2", "量子计算讨论二", source="老爹"))
        hits = self.svc.recall("量子计算")
        self.assertGreaterEqual(len(hits), 2)
        p = self.tmp / "memory_shadow.jsonl"
        self.assertTrue(p.exists())
        rec = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(len(rec["base"]), len(rec["shadow"]))
        self.assertIn("changed", rec)

    def test_spread_hits_from_entity_graph(self):
        from backend import entity_graph as eg

        old = eg.DB_PATH
        eg.DB_PATH = self.tmp / "eg.db"
        try:
            eg.upsert([{"subject": "量子计算", "relation": "相关",
                        "object": "薛定谔猫"}])
            self.svc.store_item(_it("sp1", "薛定谔猫实验记录", source="老爹"))
            hits = self.svc.recall("量子计算")
            self.assertTrue(any(h.get("via") == "spread" for h in hits), hits)
        finally:
            eg.DB_PATH = old

    # ---------- health ----------
    def test_health_counts(self):
        self._seed()
        self.svc.add_episode(channel="console", kind="voice", summary="x")
        self.svc.add_causal_edge(
            "c1", "c2", "cause", 0.9, quote="因为服务器过热所以服务重启了")
        h = self.svc.health()
        self.assertEqual(h["episodes"], 1)
        self.assertEqual(h["causal_active"], 1)
        self.assertEqual(h["causal_pending"], 0)


if __name__ == "__main__":
    unittest.main()
