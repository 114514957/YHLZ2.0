"""T3 持久投递存储测试（ledger 0611）。纯 SQLite，隔离，无网络/模型。"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

import backend.qq_delivery_store as ds  # noqa: E402


class DeliveryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t3_del_"))
        self.con = ds.connect(self.tmp / "delivery.db")

    def tearDown(self):
        self.con.close()

    def _enq(self, **kw):
        base = dict(source_event_id="e1", channel="qq_p1", target_type="private",
                    target_id="2258374446", kind="reply")
        base.update(kw)
        return ds.enqueue(self.con, **base)

    def test_enqueue_and_idempotent(self):
        a = self._enq()
        self.assertFalse(a["idempotent"])
        b = self._enq()
        self.assertTrue(b["idempotent"])
        self.assertEqual(a["delivery_id"], b["delivery_id"])
        self.assertEqual(ds.status_summary(self.con), {"queued": 1})

    def test_claim_then_confirm(self):
        a = self._enq()
        claimed = ds.claim_due(self.con, "w1", now=100.0)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["delivery_id"], a["delivery_id"])
        ep = claimed[0]["lease_epoch"]
        self.assertEqual(ds.status_summary(self.con), {"sending": 1})
        self.assertTrue(ds.mark_confirmed(self.con, a["delivery_id"], lease_epoch=ep,
                                          remote_message_id="m1", ack_ref="ok"))
        self.assertEqual(ds.status_summary(self.con), {"confirmed": 1})

    def test_stale_epoch_cannot_confirm(self):
        a = self._enq()
        claimed = ds.claim_due(self.con, "w1", now=100.0)
        ep = claimed[0]["lease_epoch"]
        self.assertFalse(ds.mark_confirmed(self.con, a["delivery_id"], lease_epoch=ep - 1))

    def test_before_send_failure_is_retryable(self):
        a = self._enq()
        ep = ds.claim_due(self.con, "w1", now=100.0)[0]["lease_epoch"]
        st = ds.mark_failed(self.con, a["delivery_id"], lease_epoch=ep, before_send=True,
                            error_code="connect_failed", retry_at=130.0)
        self.assertEqual(st, "retryable")
        # 未到 retry_at 不领
        self.assertEqual(ds.claim_due(self.con, "w2", now=110.0), [])
        # 到期可领
        self.assertEqual(len(ds.claim_due(self.con, "w2", now=140.0)), 1)

    def test_after_send_failure_is_unknown_not_retry(self):
        a = self._enq()
        ep = ds.claim_due(self.con, "w1", now=100.0)[0]["lease_epoch"]
        st = ds.mark_failed(self.con, a["delivery_id"], lease_epoch=ep, before_send=False,
                            error_code="timeout_after_send")
        self.assertEqual(st, "unknown")
        # unknown 不再被领取
        self.assertEqual(ds.claim_due(self.con, "w2", now=999.0), [])

    def test_reclaim_expired_lease_to_unknown(self):
        a = self._enq()
        ds.claim_due(self.con, "w1", now=100.0, lease_s=10.0)
        self.assertEqual(ds.reclaim_expired(self.con, now=200.0), 1)
        row = self.con.execute("SELECT state,last_error_code FROM deliveries WHERE delivery_id=?",
                               (a["delivery_id"],)).fetchone()
        self.assertEqual(row[0], "unknown")
        self.assertIn("lease_expired", row[1])
        self.assertEqual(ds.claim_due(self.con, "w3", now=999.0), [])

    def test_expire_due_ttl(self):
        self._enq(expires_at=150.0)
        self.assertEqual(ds.expire_due(self.con, now=160.0), 1)
        self.assertEqual(ds.status_summary(self.con), {"expired": 1})

    def test_concurrent_claim_single(self):
        self._enq()
        self.assertEqual(len(ds.claim_due(self.con, "w1", now=1.0)), 1)
        self.assertEqual(ds.claim_due(self.con, "w2", now=1.0), [])


if __name__ == "__main__":
    unittest.main()
