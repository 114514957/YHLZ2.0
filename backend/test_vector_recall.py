"""向量召回测试（2026-09-24，台账 0499）。

覆盖三处真问题：
1. `semantic_l2` 过去硬编码主库 → 自定义库（群记忆/测试）永远召不到；
2. L2 向量过去所有库共用一个 scope → 跨库 id 互相覆盖；
3. 召回命中不带日期（台账 0451 已证日期进上下文对时间问题有决定性作用）。
以及新增的"字面不足时补语义命中"主路径。

注意：embed 走本地 bge-small（CPU），首次调用会加载模型。
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.target_kw_index import KeywordIndex
from backend.target_memory import L2Item, TargetMemoryService
from backend import vector_memory as vm


def _svc(tmp: Path, name: str = "m") -> TargetMemoryService:
    return TargetMemoryService(db_path=tmp / f"{name}.db",
                               kw_index=KeywordIndex(tmp / f"{name}_kw.db"))


def _it(iid, summary, *, importance=5, created=None, valid_at=0.0,
        status="active"):
    import time

    return L2Item(id=iid, tier="L2", type="fact", importance=importance,
                  summary=summary, content_hash=iid, keywords=summary[:40],
                  created_at=created or time.time(), source="老爹",
                  valid_at=valid_at, status=status)


class ScopeIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_default_db_keeps_l2_scope(self):
        """默认库必须仍是 'l2'，否则既有向量缓存全失效（要重嵌入）。"""
        self.assertEqual(vm.l2_scope(vm.MEMORY_DB), "l2")
        self.assertEqual(vm.l2_scope(None), "l2")

    def test_other_db_gets_own_scope(self):
        s = vm.l2_scope(self.tmp / "m.db")
        self.assertTrue(s.startswith("l2@"), s)
        self.assertNotEqual(s, "l2")

    def test_same_id_in_two_dbs_does_not_collide(self):
        a, b = _svc(self.tmp, "a"), _svc(self.tmp, "b")
        a.store_item(_it("dup1", "甲库里说喜欢绿茶"))
        b.store_item(_it("dup1", "乙库里说讨厌绿茶"))
        hits_a = vm.semantic_l2("喜欢绿茶", top=3, min_score=0.0,
                                db_path=a.db_path)
        self.assertEqual([h["id"] for h in hits_a], ["dup1"])
        self.assertIn("甲库", hits_a[0]["summary"])


class CustomDbRecallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_semantic_l2_reads_the_given_db(self):
        """过去这里恒为空（join 的是主库）——群记忆的语义召回等于没有。"""
        svc = _svc(self.tmp, "grp")
        svc.store_item(_it("g1", "群友提到过要用 llama.cpp 跑量化",
                           importance=6))
        hits = vm.semantic_l2("llama.cpp 量化怎么跑", top=3, min_score=0.3,
                              db_path=svc.db_path)
        self.assertTrue(hits, "自定义库应能召到自己库里的向量")
        self.assertEqual(hits[0]["id"], "g1")

    def test_semantic_hits_carry_date(self):
        svc = _svc(self.tmp, "d")
        svc.store_item(_it("d1", "老爹去过兰州拉面馆", created=1700000000.0,
                           valid_at=1700000000.0))
        hits = vm.semantic_l2("兰州拉面", top=3, min_score=0.0,
                              db_path=svc.db_path)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["date"], "2023-11-15")


class ContextualRecallDateTest(unittest.TestCase):
    """回归：0496 归档时抓到的失败——语义命中排在首位却不带日期。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = _svc(self.tmp, "ctx")

    def test_contextual_recall_carries_date_for_all_paths(self):
        it = _it("c1", "老爹去过兰州拉面馆", created=1700000000.0,
                 valid_at=1700000000.0)
        it.type = "event"
        self.svc.store_item(it)
        rows = self.svc.contextual_recall("老爹是不是去过兰州拉面馆", limit=3)
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(r.get("date"), r)


class MainPathSemanticTest(unittest.TestCase):
    """0499：recall() 字面命中不足时，向量召回补位（via='semantic'）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = _svc(self.tmp, "main")

    def test_semantic_fallback_when_literal_is_thin(self):
        self.svc.store_item(_it("m1", "老爹说最近睡眠不好，想早点睡"))
        # 查询词与条目没有共同字面词（换说法），关键词/FTS/PPR 都命中不到
        out = self.svc.recall("作息不规律该怎么调整", limit=3)
        self.assertTrue(any(h.get("via") == "semantic" for h in out), out)

    def test_literal_hits_still_win_and_no_duplicate(self):
        self.svc.store_item(_it("m2", "老爹喜欢靛蓝色"))
        out = self.svc.recall("靛蓝色", limit=3)
        self.assertTrue(out)
        ids = [h["id"] for h in out]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertEqual(ids[0], "m2")

    def test_as_of_read_skips_semantic(self):
        """时间旅行读是确定性历史口径，不该混入语义补位。"""
        self.svc.store_item(_it("m3", "老爹在A公司上班", valid_at=1700000000.0))
        out = self.svc.recall("A公司", limit=3, as_of=1700000100.0)
        self.assertTrue(all(h.get("via") != "semantic" for h in out), out)

    def test_missing_vector_never_breaks_recall(self):
        """库里没向量（未 backfill）时 recall 必须照常返回字面命中。"""
        self.svc.store_item(_it("m4", "老爹喜欢喝乌龙茶"))
        con = sqlite3.connect(str(self.svc.db_path))
        try:
            con.execute("DELETE FROM l2_items WHERE id=?", ("m4",))
            con.commit()
        finally:
            con.close()
        self.svc.store_item(_it("m5", "老爹喜欢喝乌龙茶"))
        self.assertTrue(self.svc.recall("乌龙茶", limit=3))

    def test_soft_invalidated_item_never_leaks_via_semantic(self):
        """M1 契约回归：软失效（被取代）的旧事实不得经语义路径漏回召回。

        实测踩到过：向量命中只查了 status，没查 invalid_at → 默认读会看到旧事实。
        """
        import time as _t

        item = _it("old1", "老爹在A公司上班", valid_at=1000.0)
        item.invalid_at = _t.time() - 10
        self.svc.store_item(item)
        self.assertEqual(self.svc.recall("A公司"), [])
        self.assertEqual(self.svc.contextual_recall("老爹在哪家公司上班呀"), [])
        # 时间旅行读仍可回溯（as_of 路径不走向量补位）
        past = self.svc.recall("A公司", as_of=2000.0)
        self.assertEqual([h["id"] for h in past], ["old1"])
        # 显式要求时才带失效条目（离线诊断用）
        raw = vm.semantic_l2("A公司", top=3, min_score=0.0,
                             db_path=self.svc.db_path, include_invalid=True)
        self.assertTrue(any(h["id"] == "old1" for h in raw), raw)


if __name__ == "__main__":
    unittest.main()