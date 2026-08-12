"""
YHLZ Embodied AI V10.0 - 热机健康指标引擎测试 (Warm Runtime Health)

覆盖 (规则驱动 + 生成式):
    - 四维报告结构 (Cognitive/Memory/Growth/Safety + overall)
    - 各维度计算正确性 (mock 引擎)
    - 容错 (引擎缺失/异常不抛)
    - 停用错误帧
    - Service API 集成
"""
import unittest

from backend.embodied.companion.warm_health import (
    WarmRuntimeHealth,
)
from backend.embodied.service import EmbodiedService


# ── Mock 引擎 (健康指标只读聚合, 输入可替换) ──────────────────
class MockMetaCognition:
    """Mock 元认知引擎 (固定统计)"""

    def __init__(self, record=10, error=1, reflect=10,
                 update=5, conf=0.8):
        self._d = {
            "enabled": True,
            "monitor": {
                "record_count": record,
                "avg_confidence": conf,
            },
            "detector": {"error_count": error},
            "reflection": {
                "reflection_count": reflect,
                "update_count": update,
            },
            "verification": {
                "verified_count": 7, "uncertain_count": 1,
            },
        }

    def stats(self):
        return dict(self._d)


class MockContinuity:
    """Mock 连续层 (记忆总览 + 成长指标)"""

    def __init__(self, index_total=100, active=60,
                 recycled=10, confirmed=8, reflect=4,
                 by_type=None):
        self._index_total = index_total
        self._active = active
        self._recycled = recycled
        self._confirmed = confirmed
        self._reflect = reflect
        self._by_type = by_type or {"experience_confirmed": 8}

    def memory_overview(self):
        return {
            "index": {
                "total": self._index_total,
                "by_stage": {
                    "active": self._active,
                    "cold": 20, "archive": 15, "recycle": 5,
                },
            },
            "recycled_total": self._recycled,
        }

    def growth_metrics(self):
        return {
            "enabled": True,
            "confirmed_count": self._confirmed,
            "reflection_count": self._reflect,
            "by_type": self._by_type,
        }


class MockMemoryGate:
    """Mock 感知记忆门禁"""

    def __init__(self, candidates=50, approved=40, rejected=5):
        self._d = {
            "enabled": True,
            "candidate_count": candidates,
            "approved_count": approved,
            "rejected_count": rejected,
        }

    def stats(self):
        return dict(self._d)


class MockIdentityGuard:
    """Mock 身份守护"""

    def __init__(self, intercept=2, approval=3):
        self._d = {
            "enabled": True,
            "intercept_count": intercept,
            "approval_count": approval,
        }

    def stats(self):
        return dict(self._d)


class MockConstitution:
    """Mock 宪法引擎"""

    def __init__(self, delusion=1, decisions=None):
        self._d = {
            "enabled": True,
            "validator": {"delusion_block_count": delusion},
            "rule_engine": {
                "decisions": decisions or {
                    "allow": 90, "block": 3, "review": 2,
                },
            },
        }

    def stats(self):
        return dict(self._d)


def make_health(**kwargs):
    """构造健康引擎 (默认全部 mock)"""
    defaults = dict(
        meta_cognition=MockMetaCognition(),
        continuity=MockContinuity(),
        memory_gate=MockMemoryGate(),
        identity_guard=MockIdentityGuard(),
        constitution=MockConstitution(),
    )
    defaults.update(kwargs)
    return WarmRuntimeHealth(**defaults)


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


class TestHealthReport(unittest.TestCase):
    """报告结构"""

    def test_report_structure(self):
        h = make_health()
        r = h.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["version"], "9.5.0")
        self.assertIn("generated_at", r)
        self.assertIn("overall", r)
        for dim in ("cognitive", "memory", "growth", "safety"):
            self.assertIn(dim, r)
            self.assertIn("score", r[dim])
            self.assertIn("level", r[dim])
            self.assertIn("reasons", r[dim])

    def test_overall_levels(self):
        h = make_health()
        r = h.report()
        self.assertIn(r["overall"]["level"],
                      ("good", "warning", "risk"))
        self.assertIn("reason", r["overall"])

    def test_cognitive_metrics(self):
        h = make_health(
            meta_cognition=MockMetaCognition(
                record=10, error=1, reflect=10,
                update=5, conf=0.8,
            ),
        )
        c = h.report()["cognitive"]
        self.assertEqual(c["stability"], 0.8)
        self.assertEqual(c["error_rate"], 0.1)
        self.assertEqual(c["correction_rate"], 0.5)
        self.assertEqual(c["level"], "good")

    def test_memory_metrics(self):
        h = make_health(
            continuity=MockContinuity(
                index_total=100, active=60, recycled=10,
            ),
            memory_gate=MockMemoryGate(
                candidates=50, approved=40, rejected=5,
            ),
        )
        m = h.report()["memory"]
        self.assertEqual(m["duplicate_rate"], 0.1)
        self.assertEqual(m["pollution_rate"], 0.1)
        self.assertEqual(m["retrieval_quality"], 0.6)
        self.assertEqual(m["level"], "good")

    def test_growth_metrics(self):
        h = make_health(
            continuity=MockContinuity(
                confirmed=8, reflect=4,
            ),
        )
        g = h.report()["growth"]
        self.assertEqual(g["effective_optimizations"], 12)
        self.assertEqual(g["level"], "good")

    def test_safety_metrics(self):
        h = make_health(
            identity_guard=MockIdentityGuard(intercept=2),
            constitution=MockConstitution(delusion=1),
        )
        s = h.report()["safety"]
        self.assertEqual(s["interception_count"], 3)
        self.assertEqual(s["level"], "good")


class TestHealthTolerance(unittest.TestCase):
    """容错: 引擎缺失/异常不抛"""

    def test_all_missing(self):
        h = make_health(
            meta_cognition=None, continuity=None,
            memory_gate=None, identity_guard=None,
            constitution=None,
        )
        r = h.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("overall", r)

    def test_engine_exception(self):
        class Boom:
            def stats(self):
                raise RuntimeError("boom")

        class BoomContinuity:
            def memory_overview(self):
                raise RuntimeError("boom")

            def growth_metrics(self):
                raise RuntimeError("boom")

        h = make_health(
            meta_cognition=Boom(), continuity=BoomContinuity(),
        )
        r = h.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertIn("overall", r)

    def test_disabled_error_frame(self):
        h = make_health(enabled=False)
        r = h.report()
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])
        self.assertIn("reason", r)

    def test_clear_returns_zero(self):
        h = make_health()
        self.assertEqual(h.clear(), 0)

    def test_bad_numeric_input(self):
        class Weird:
            def stats(self):
                return {
                    "enabled": True,
                    "monitor": {"record_count": "x",
                                "avg_confidence": None},
                    "detector": {"error_count": None},
                    "reflection": {"reflection_count": 0,
                                   "update_count": "y"},
                    "verification": {},
                }

        h = make_health(meta_cognition=Weird())
        r = h.report()
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual(r["cognitive"]["error_rate"], 0.0)


# ── 生成式: 等级判定矩阵 ───────────────────────────────────────
_LEVEL_CASES = [
    # (记录, 错误, 反思, 更新, 置信, 期望等级)
    ("stability_good_error_low", 10, 1, 10, 5, 0.8, "good"),
    ("stability_warning", 10, 1, 10, 5, 0.45, "warning"),
    ("stability_risk", 10, 1, 10, 5, 0.2, "risk"),
    ("error_high_risk", 10, 5, 10, 5, 0.8, "risk"),
    ("error_mid_warning", 10, 2, 10, 5, 0.8, "warning"),
    ("correction_risk", 10, 1, 10, 0, 0.8, "risk"),
    ("correction_warning", 10, 1, 10, 1, 0.8, "warning"),
    ("empty_engine", 0, 0, 0, 0, 0.0, "risk"),
]


class TestGeneratedLevels(unittest.TestCase):
    """生成式: 认知等级矩阵"""
    pass


for _i, (_name, _rec, _err, _ref, _upd, _conf, _lvl) in \
        enumerate(_LEVEL_CASES):
    def _make(name=_name, rec=_rec, err=_err, ref=_ref,
              upd=_upd, conf=_conf, lvl=_lvl):
        def test_case(self):
            h = make_health(
                meta_cognition=MockMetaCognition(
                    record=rec, error=err, reflect=ref,
                    update=upd, conf=conf,
                ),
            )
            c = h.report()["cognitive"]
            self.assertEqual(c["level"], lvl)
        test_case.__name__ = f"test_level_{name}_{_i}"
        return test_case
    setattr(TestGeneratedLevels, f"test_level_{_name}_{_i}",
            _make())


# ── Service API 集成 ───────────────────────────────────────────
class TestServiceHealth(unittest.TestCase):
    """Service API: companion_health"""

    def test_service_health_ok(self):
        svc = setup_service()
        r = svc.companion_health()
        self.assertIn("overall", r)
        self.assertIn("cognitive", r)
        self.assertIn("memory", r)
        self.assertIn("growth", r)
        self.assertIn("safety", r)

    def test_service_health_repeatable(self):
        svc = setup_service()
        r1 = svc.companion_health()
        r2 = svc.companion_health()
        self.assertEqual(r1["overall"]["level"],
                         r2["overall"]["level"])

    def test_service_health_version(self):
        svc = setup_service()
        r = svc.companion_health()
        self.assertEqual(r["version"], "9.5.0")


if __name__ == "__main__":
    unittest.main()
