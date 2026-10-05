"""T4 持久复盘任务存储测试（ledger 0628）。纯 SQLite，隔离，无模型/网络。"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, ".")

import backend.review_queue_store as rq  # noqa: E402


class ReviewQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="t4_rq_"))
        self.con = rq.connect(self.tmp / "review.db")

    def tearDown(self):
        self.con.close()

    def _enq(self, **kw):
        base = dict(channel="qq_p1", principal_id="owner", session_id="s1",
                    start_seq=1, end_seq=10)
        base.update(kw)
        return rq.enqueue_window(self.con, **base)

    def test_idempotent_window(self):
        a = self._enq()
        b = self._enq()
        self.assertFalse(a["idempotent"])
        self.assertTrue(b["idempotent"])
        self.assertEqual(a["job_id"], b["job_id"])

    def test_commit_advances_watermark(self):
        a = self._enq()
        claimed = rq.claim_due(self.con, "w1", now=100.0)
        ep = claimed[0]["lease_epoch"]
        self.assertTrue(rq.advance(self.con, a["job_id"], lease_epoch=ep, state="extracting"))
        self.assertTrue(rq.advance(self.con, a["job_id"], lease_epoch=ep, state="adjudicating"))
        self.assertTrue(rq.advance(self.con, a["job_id"], lease_epoch=ep, state="committing"))
        self.assertEqual(rq.watermark(self.con, channel="qq_p1", principal_id="owner",
                                      session_id="s1"), 0)
        self.assertTrue(rq.commit_review(self.con, a["job_id"], lease_epoch=ep, committed_seq=10))
        self.assertEqual(rq.watermark(self.con, channel="qq_p1", principal_id="owner",
                                      session_id="s1"), 10)
        self.assertEqual(rq.status_summary(self.con), {"done": 1})

    def test_failure_does_not_advance_watermark(self):
        a = self._enq()
        ep = rq.claim_due(self.con, "w1", now=100.0)[0]["lease_epoch"]
        st = rq.schedule_retry(self.con, a["job_id"], lease_epoch=ep,
                               error_code="json_truncated", retry_at=130.0)
        self.assertEqual(st, "retry_wait")
        self.assertEqual(rq.watermark(self.con, channel="qq_p1", principal_id="owner",
                                      session_id="s1"), 0)
        # 未到 retry_at 不领
        self.assertEqual(rq.claim_due(self.con, "w2", now=110.0), [])
        self.assertEqual(len(rq.claim_due(self.con, "w2", now=140.0)), 1)

    def test_validated_empty_is_success(self):
        a = self._enq()
        ep = rq.claim_due(self.con, "w1", now=100.0)[0]["lease_epoch"]
        self.assertTrue(rq.mark_validated_empty(self.con, a["job_id"], lease_epoch=ep,
                                                committed_seq=10))
        self.assertEqual(rq.status_summary(self.con), {"validated_empty": 1})
        self.assertEqual(rq.watermark(self.con, channel="qq_p1", principal_id="owner",
                                      session_id="s1"), 10)

    def test_expired_lease_recovered_not_resent(self):
        a = self._enq()
        rq.claim_due(self.con, "w1", now=100.0, lease_s=10.0)
        self.assertEqual(rq.recover_expired(self.con, now=200.0), 1)
        row = self.con.execute("SELECT state,last_error_code FROM review_jobs WHERE job_id=?",
                               (a["job_id"],)).fetchone()
        self.assertEqual(row[0], "retry_wait")
        self.assertEqual(row[1], "lease_expired")

    def test_stale_epoch_cannot_commit(self):
        a = self._enq()
        ep = rq.claim_due(self.con, "w1", now=100.0)[0]["lease_epoch"]
        self.assertFalse(rq.commit_review(self.con, a["job_id"], lease_epoch=ep - 1,
                                          committed_seq=10))

    def test_watermark_monotonic(self):
        a = self._enq(start_seq=1, end_seq=10)
        ep = rq.claim_due(self.con, "w", now=1.0)[0]["lease_epoch"]
        rq.commit_review(self.con, a["job_id"], lease_epoch=ep, committed_seq=10)
        b = self._enq(start_seq=11, end_seq=20)
        ep2 = rq.claim_due(self.con, "w", now=2.0)[0]["lease_epoch"]
        rq.commit_review(self.con, b["job_id"], lease_epoch=ep2, committed_seq=20)
        # 旧窗口重放不能把水位回退
        c = self._enq(start_seq=1, end_seq=10)   # 幂等 → 同一 job（已 done）
        self.assertTrue(c["idempotent"])
        self.assertEqual(rq.watermark(self.con, channel="qq_p1", principal_id="owner",
                                      session_id="s1"), 20)


if __name__ == "__main__":
    unittest.main()
