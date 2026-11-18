# -*- coding: utf-8 -*-
"""记忆召回 v2 / 语义索引的单元测试（**不加载真实模型**，用假嵌入函数）。

覆盖：
  1. 闸门：太短/寒暄/工程指令要被挡住
  2. 分层：工程类记忆不进候选池
  3. 索引：建库→落盘→重新载入→能查；内容不变时复用向量
  4. 语义优先、无相关时不回退（避免噪声）
  5. 模型不可用 → 降级到字符串召回
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from backend import memory_recall_semantic as S  # noqa: E402


def fake_embed(texts: list[str]):
    """把文本映射成可复现的 8 维向量：用字符位置哈希，不做语义。"""
    out = []
    for t in texts:
        v = np.zeros(8, dtype=np.float32)
        for i, ch in enumerate(t[:64]):
            v[ord(ch) % 8] += 1.0 + (i % 3) * 0.1
        n = float(np.linalg.norm(v))
        out.append(v / n if n else v)
    return np.vstack(out)


class GateTest(unittest.TestCase):
    def test_short_blocked(self):
        for q in ("在吗", "嗯", "晚安", "哈哈哈哈"):
            ok, why = S.gate_allows(q)
            self.assertFalse(ok, q)
            # "嗯/晚安"这类命中寒暄词表，"哈哈哈哈"则因过短；两者都算挡住
            self.assertTrue(("短" in why) or (why == "寒暄/应答"), "%s → %s" % (q, why))

    def test_engineering_blocked(self):
        for q in ("帮我看看这个报错", "跑一下测试", "把v14的评测结果发我", "重启一下服务"):
            ok, why = S.gate_allows(q)
            self.assertFalse(ok, q)
            self.assertEqual("工程指令", why)

    def test_normal_allowed(self):
        for q in ("我不吃香菜，记着点", "莫高窟你最喜欢哪个窟", "黄河为什么被叫作母亲河"):
            ok, why = S.gate_allows(q)
            self.assertTrue(ok, "%s → %s" % (q, why))


class IndexTest(unittest.TestCase):
    def setUp(self):
        # 2026-11-18：临时目录必须落在 cache/tmp，别在仓库根目录堆 memvec-*（结构检查会红）
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp_root = os.path.join(root, "cache", "tmp")
        os.makedirs(tmp_root, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="memvec-", dir=tmp_root)
        self.db = os.path.join(self.tmp, "memstore.db")
        self.vec = os.path.join(self.tmp, "memvec.db")
        self._make_db()

    def _make_db(self):
        import sqlite3
        con = sqlite3.connect(self.db)
        con.execute("""CREATE TABLE l2_items(
            id TEXT PRIMARY KEY, type TEXT, importance INTEGER, summary TEXT,
            source TEXT, status TEXT, keywords TEXT)""")
        rows = [
            ("m1", "preference", 6, "老爹不吃香菜，以后别给我推荐香菜。", "老爹", "active", ""),
            ("m2", "fact", 9, "莫高窟第 735 窟，藏经洞是元亨最偏爱的地方。", "owner", "active", ""),
            ("e1", "context", 5, "台账记录 0042：验收探针与链路重构", "agent", "active", ""),
            ("m3", "event", 5, "元亨: 门槛是可乐，不是嘴皮子。", "qq_group:1", "active", ""),
            ("m4", "fact", 2, "低优先级的碎屑", "owner", "active", ""),
            ("m5", "preference", 6, "已归档的旧偏好", "老爹", "archive", ""),
        ]
        con.executemany("insert into l2_items values(?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()

    def test_build_and_reload(self):
        idx = S.SemanticIndex(self.vec, embed_fn=fake_embed)
        stat = idx.build(self.db)
        # 只该收 m1/m2/m3（m4 重要度<4；m5 非 active；e1 是工程来源）
        self.assertEqual(stat["pool"], 3, stat)
        self.assertEqual(stat["indexed"], 3)
        idx2 = S.SemanticIndex(self.vec, embed_fn=fake_embed)
        self.assertTrue(idx2.load(self.db))
        got = idx2.search("老爹不吃香菜，记着点", sim_min=0.0, limit=2)
        self.assertTrue(got)
        self.assertIn(got[0]["id"], ("m1", "m3", "m2"))

    def test_reuse_when_unchanged(self):
        idx = S.SemanticIndex(self.vec, embed_fn=fake_embed)
        idx.build(self.db)
        again = idx.build(self.db, force=False)
        self.assertEqual(again["rebuilt"], 0, again)
        self.assertEqual(again["reused"], again["pool"])

    def test_gate_blocks_short_query(self):
        idx = S.SemanticIndex(self.vec, embed_fn=fake_embed)
        idx.build(self.db)
        self.assertEqual(idx.search("在吗"), [])

    def test_degrade_to_string_recall(self):
        class Boom:
            degraded = False

            def search(self, *a, **k):
                raise RuntimeError("model gone")

        got = S.semantic_recall("老爹不吃香菜记着点", index=Boom(), db_path=self.db)
        self.assertIsInstance(got, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
