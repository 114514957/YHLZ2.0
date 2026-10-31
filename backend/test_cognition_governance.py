"""L3 认知治理收口（0546）：稳定 ID / 持久拒绝账 / 失效输入过滤 / 失败不出队。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend import target_persona_loop as P  # noqa: E402


class ClaimIdTests(unittest.TestCase):
    def test_stable_and_kind_sensitive(self):
        a = {"claim": "元亨喜欢深夜思考", "kind": "new", "tier": "core"}
        b = dict(a)
        self.assertEqual(P.claim_id(a), P.claim_id(b))
        c = {"claim": "元亨喜欢深夜思考", "kind": "refine", "tier": "core"}
        self.assertNotEqual(P.claim_id(a), P.claim_id(c))

    def test_valid_claim_filter(self):
        self.assertFalse(P._valid_claim({"claim": ""}))
        self.assertFalse(P._valid_claim({"claim": "ab"}))
        self.assertFalse(P._valid_claim({"claim": "。。。！"}))
        self.assertTrue(P._valid_claim({"claim": "元亨喜欢深夜思考"}))


class PendingGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pending = Path(self.tmp.name) / "pending.json"
        self.rejected = Path(self.tmp.name) / "rejected.json"
        self._p = patch.object(P, "PENDING_FILE", self.pending)
        self._r = patch.object(P, "REJECTED_FILE", self.rejected)
        self._p.start()
        self._r.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(self._r.stop)
        self.loop = P.PersonaConsolidationLoop(llm_turn=None, memory=None)

    def _decisions(self, *claims):
        return [{"claim": c, "kind": "new", "tier": "core", "item_ids": []}
                for c in claims]

    def test_save_pending_assigns_stable_id_and_skips_invalid(self):
        n = self.loop.save_pending(
            self._decisions("元亨喜欢深夜思考", "x", "。。。"), [])
        self.assertEqual(n, 1)
        import json

        rows = json.loads(self.pending.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertTrue(str(rows[0]["id"]).startswith("cog_"))

    def test_duplicate_not_added_twice(self):
        self.loop.save_pending(self._decisions("元亨喜欢深夜思考"), [])
        n = self.loop.save_pending(self._decisions("元亨喜欢深夜思考"), [])
        self.assertEqual(n, 0)

    def test_rejected_claim_not_re_added(self):
        entry = {"claim": "元亨喜欢深夜思考", "kind": "new", "tier": "core",
                 "item_ids": []}
        P.record_rejection(entry, reason="owner_rejected", path=self.rejected)
        self.assertIn(P.claim_id(entry), P.load_rejected(self.rejected))
        n = self.loop.save_pending(self._decisions("元亨喜欢深夜思考"), [])
        self.assertEqual(n, 0)

    def test_rejection_ledger_deduped(self):
        entry = {"claim": "元亨喜欢深夜思考", "kind": "new", "tier": "core"}
        P.record_rejection(entry, path=self.rejected)
        P.record_rejection(entry, path=self.rejected)
        self.assertEqual(len(P.load_rejected(self.rejected)), 1)


if __name__ == "__main__":
    unittest.main()

