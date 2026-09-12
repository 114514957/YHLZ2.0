"""
YHLZ Embodied AI V6.4 - 记忆网关增强与 NMS 单元测试

覆盖:
    - 六维最终评分 (含 Reflection Score)
    - Memory Gate 集成反思/反事实 (steps)
    - NMS 多目标模板检测
"""
import unittest

from backend.embodied.companion.perception import (
    ApprovalRule,
    MemoryGate,
    TemplateDetectorAdapter,
)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def make_candidate(**over):
    c = {
        "candidate_id": "mc_1",
        "source": "camera",
        "kind": "ocr",
        "summary": "用户屏幕显示重要任务清单",
        "confidence": 0.9,
        "occurrence_count": 1,
    }
    c.update(over)
    return c


class TestSixDimApproval(unittest.TestCase):
    """六维最终评分"""

    def setUp(self):
        self.rule = ApprovalRule()

    def test_five_dim_without_reflection(self):
        """无反思评分 → 5 维 (向后兼容)"""
        r = self.rule.evaluate(make_candidate())
        self.assertEqual(len(r["dimensions"]), 5)
        self.assertIsNone(r["reflection_score"])

    def test_six_dim_with_reflection(self):
        r = self.rule.evaluate(make_candidate(),
                               reflection_score=0.8)
        self.assertEqual(len(r["dimensions"]), 6)
        self.assertEqual(r["reflection_score"], 0.8)

    def test_reflection_dimension_present(self):
        r = self.rule.evaluate(make_candidate(),
                               reflection_score=0.8)
        names = {d["name"] for d in r["dimensions"]}
        self.assertIn("reflection", names)

    def test_high_reflection_boosts(self):
        r_low = self.rule.evaluate(make_candidate(
            source="mock", summary="普通内容", confidence=0.5,
        ))
        r_high = self.rule.evaluate(make_candidate(
            source="mock", summary="普通内容", confidence=0.5,
        ), reflection_score=1.0)
        self.assertGreater(r_high["final_score"],
                           r_low["final_score"])

    def test_low_reflection_lowers(self):
        r_none = self.rule.evaluate(make_candidate())
        r_low = self.rule.evaluate(make_candidate(),
                                   reflection_score=0.1)
        self.assertLess(r_low["final_score"],
                        r_none["final_score"])

    def test_final_score_field(self):
        r = self.rule.evaluate(make_candidate(),
                               reflection_score=0.7)
        self.assertIn("final_score", r)
        self.assertEqual(r["final_score"], r["confidence"])

    def test_reflection_clamped(self):
        r = self.rule.evaluate(make_candidate(),
                               reflection_score=5.0)
        self.assertLessEqual(r["reflection_score"], 1.0)

    def test_reflection_none_type(self):
        r = self.rule.evaluate(make_candidate(),
                               reflection_score=None)
        self.assertIsNone(r["reflection_score"])

    def test_reflection_negative_clamped(self):
        r = self.rule.evaluate(make_candidate(),
                               reflection_score=-1.0)
        self.assertGreaterEqual(r["reflection_score"], 0.0)

    def test_reflection_raises_score_above_threshold(self):
        """低 5 维 + 高反思 → 六维可过阈值"""
        r = self.rule.evaluate(make_candidate(
            source="mock", summary="x", confidence=0.5,
        ), reflection_score=1.0)
        self.assertGreaterEqual(r["final_score"], 0.5)


class TestGateWithReflection(unittest.TestCase):
    """网关集成反思/反事实"""

    def setUp(self):
        self.gate = MemoryGate()
        self.stored = []

        def store_fn(c):
            self.stored.append(c)
            return {"id": "exp_1"}

        self.store_fn = store_fn

    def test_steps_include_reflection(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        steps = [s["step"] for s in r["steps"]]
        self.assertIn("reflection_evaluation", steps)
        self.assertIn("counterfactual_check", steps)
        self.assertIn("approval", steps)

    def test_high_value_approved(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        self.assertEqual(r["status"], "approved")

    def test_counterfactual_fail_rejected(self):
        """高风险单一来源 → 反思/反事实拒绝 (不形成经验)"""
        r = self.gate.process(make_candidate(
            summary="支付成功",
        ), store_fn=self.store_fn)
        self.assertEqual(r["status"], "rejected")
        self.assertNotIn("approved", r["status"])

    def test_low_value_rejected(self):
        r = self.gate.process(make_candidate(
            source="mock", summary="x", confidence=0.2,
        ), store_fn=self.store_fn)
        self.assertEqual(r["status"], "rejected")

    def test_reflection_steps_reason(self):
        r = self.gate.process(make_candidate(),
                              store_fn=self.store_fn)
        step = next(s for s in r["steps"]
                    if s["step"] == "reflection_evaluation")
        self.assertIn("反思评分", step["reason"])

    def test_known_experiences_passed(self):
        """reflect_fn 返回经历列表供评估 (重复信号 → 拒绝)"""
        gate = MemoryGate()
        captured = []

        def reflect_fn(candidate):
            captured.append(candidate)
            return [{"trigger": "用户屏幕显示重要", "lesson": "l"}]

        r = gate.process(make_candidate(),
                         store_fn=lambda c: {},
                         reflect_fn=reflect_fn)
        self.assertEqual(len(captured), 1)
        # 与已有经历重复 → 反思建议拒绝 (防重复记忆)
        self.assertEqual(r["status"], "rejected")

    def test_known_experiences_no_overlap_approved(self):
        """已有经历与候选不重叠 → 无矛盾 → 批准"""
        gate = MemoryGate()
        r = gate.process(make_candidate(),
                         store_fn=lambda c: {},
                         reflect_fn=lambda c: [
                             {"trigger": "环境扫描", "lesson": "l"},
                         ])
        self.assertEqual(r["status"], "approved")

    def test_gate_stats_unchanged_shape(self):
        self.gate.process(make_candidate(),
                          store_fn=self.store_fn)
        st = self.gate.stats()
        self.assertIn("candidate_count", st)
        self.assertIn("approved_count", st)


class TestNMS(unittest.TestCase):
    """NMS 多目标检测"""

    def _scene_two_squares(self):
        scene = np.zeros((300, 300), dtype=np.uint8)
        cv2.rectangle(scene, (20, 20), (69, 69), 255, -1)
        cv2.rectangle(scene, (150, 150), (199, 199), 255, -1)
        tpl = scene[20:70, 20:70].copy()
        return scene, tpl

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_two_targets(self):
        """两方块 → 两个目标"""
        scene, tpl = self._scene_two_squares()
        det = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.7,
            nms_enabled=True,
        )
        r = det.detect(scene)
        self.assertEqual(len(r.objects), 2)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_locations(self):
        scene, tpl = self._scene_two_squares()
        det = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.7,
            nms_enabled=True,
        )
        r = det.detect(scene)
        locs = sorted(o["bbox"][:2] for o in r.objects)
        self.assertEqual(locs, [[20, 20], [150, 150]])

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_confidences(self):
        scene, tpl = self._scene_two_squares()
        det = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.7,
            nms_enabled=True,
        )
        r = det.detect(scene)
        for o in r.objects:
            self.assertGreaterEqual(o["confidence"], 0.7)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_dup_suppressed(self):
        """重叠候选被 NMS 抑制 (单目标场景)"""
        scene = np.zeros((200, 200), dtype=np.uint8)
        cv2.rectangle(scene, (50, 50), (99, 99), 255, -1)
        tpl = scene[50:100, 50:100].copy()
        det = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.7,
            nms_enabled=True,
        )
        r = det.detect(scene)
        # 单方块 → 1 个目标 (NMS 去重)
        self.assertEqual(len(r.objects), 1)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_disabled_single(self):
        """关闭 NMS → 单目标场景仍 1 个 (min 全局)"""
        scene = np.zeros((200, 200), dtype=np.uint8)
        cv2.rectangle(scene, (50, 50), (99, 99), 255, -1)
        tpl = scene[50:100, 50:100].copy()
        det = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.7,
            nms_enabled=False,
        )
        r = det.detect(scene)
        self.assertEqual(len(r.objects), 1)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_info(self):
        det = TemplateDetectorAdapter(nms_enabled=True,
                                      nms_iou_threshold=0.6)
        info = det.get_info()
        self.assertTrue(info["nms_enabled"])
        self.assertEqual(info["nms_iou_threshold"], 0.6)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_iou_overlap(self):
        a = TemplateDetectorAdapter()
        iou = a._iou((0, 0), (10, 10), 50, 50)
        self.assertGreater(iou, 0.0)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_iou_no_overlap(self):
        a = TemplateDetectorAdapter()
        iou = a._iou((0, 0), (100, 100), 50, 50)
        self.assertEqual(iou, 0.0)

    @unittest.skipUnless(HAS_CV2, "OpenCV 不可用")
    def test_nms_no_match(self):
        scene = np.zeros((200, 200), dtype=np.uint8)
        tpl = np.zeros((51, 51), dtype=np.uint8)
        cv2.rectangle(tpl, (0, 0), (50, 50), 255, -1)
        det = TemplateDetectorAdapter(
            templates={"sq": tpl}, match_threshold=0.9,
            nms_enabled=True,
        )
        r = det.detect(scene)
        self.assertEqual(r.objects, [])


if __name__ == "__main__":
    unittest.main()
