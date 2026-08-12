"""
YHLZ Embodied AI V4.2 - 状态不变式检测器单元测试

覆盖:
    - 无动作时对象状态自发变化 → 违规
    - 主体位置自发变化 (无移动动作) → 违规
    - 对象凭空出现 → 违规
    - 位置变化伴随移动动作 → 豁免
    - check_prediction (预测级检测)
    - 规则管理 (add_rule / rules / reset / stats)
"""
import unittest

from backend.embodied.reasoning import (
    DEFAULT_INVARIANT_RULES,
    InvariantChecker,
)
from backend.embodied.schema import EnvironmentObject, EnvironmentState


def make_state(objects=None, location=None) -> EnvironmentState:
    return EnvironmentState.create(
        objects=objects or [], location=location or {"x": 0.0, "y": 0.0},
    )


def make_obj(name="door", state="open", oid=None):
    obj = EnvironmentObject.create(
        name=name, state=state, position={"x": 1.0, "y": 1.0},
    )
    if oid:
        obj.object_id = oid
    return obj


class TestInvariantObserve(unittest.TestCase):

    def setUp(self):
        self.checker = InvariantChecker()

    def test_no_violation_when_unchanged(self):
        door = make_obj()
        prev = make_state(objects=[door])
        curr = make_state(objects=[door])  # 复用同一对象 (相同 object_id)
        violations = self.checker.check(prev, curr)
        self.assertEqual(violations, [])

    def test_spontaneous_state_change_violation(self):
        """door=open 不会自动变成 door=closed"""
        door1 = make_obj(state="open")
        door2 = make_obj(state="closed", oid=door1.object_id)
        # 保持相同 object_id, 仅状态变化
        door2.object_id = door1.object_id
        prev = make_state(objects=[door1])
        curr = make_state(objects=[door2])
        violations = self.checker.check(prev, curr)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["rule"], "no_spontaneous_state_change")
        self.assertEqual(violations[0]["object"], "door")
        self.assertEqual(violations[0]["state"], {"from": "open", "to": "closed"})

    def test_spontaneous_position_change_violation(self):
        prev = make_state(location={"x": 0.0, "y": 0.0})
        curr = make_state(location={"x": 2.0, "y": 0.0})
        violations = self.checker.check(prev, curr)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["rule"], "no_spontaneous_position_change")

    def test_position_change_with_move_action_ok(self):
        prev = make_state(location={"x": 0.0, "y": 0.0})
        curr = make_state(location={"x": 2.0, "y": 0.0})
        violations = self.checker.check(prev, curr, action_types=["move"])
        self.assertEqual(violations, [])

    def test_object_appearance_violation(self):
        prev = make_state(objects=[make_obj()])
        curr = make_state(objects=[make_obj(), make_obj(name="box", oid="new")])
        violations = self.checker.check(prev, curr)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["rule"], "no_spontaneous_object_appearance")

    def test_none_states_no_violations(self):
        self.assertEqual(self.checker.check(None, None), [])
        self.assertEqual(self.checker.check(None, make_state()), [])

    def test_all_rules_violation_at_once(self):
        d1 = make_obj(state="open")
        d2 = make_obj(state="closed", oid=d1.object_id)
        prev = make_state(objects=[d1], location={"x": 0.0, "y": 0.0})
        curr = make_state(objects=[d2], location={"x": 1.0, "y": 1.0})
        violations = self.checker.check(prev, curr)
        rules = {v["rule"] for v in violations}
        self.assertIn("no_spontaneous_state_change", rules)
        self.assertIn("no_spontaneous_position_change", rules)

    def test_state_change_allowed_with_action(self):
        """pick 动作解释 held 状态变化 → 不违规"""
        cup1 = make_obj(name="cup", state="on_ground")
        cup2 = make_obj(name="cup", state="held", oid=cup1.object_id)
        prev = make_state(objects=[cup1])
        curr = make_state(objects=[cup2])
        violations = self.checker.check(
            prev, curr, action_types=["pick"],
            allowed_state_changes=["cup"],
        )
        self.assertEqual(violations, [])

    def test_state_change_other_object_still_violates(self):
        cup1 = make_obj(name="cup", state="on_ground")
        cup2 = make_obj(name="cup", state="held", oid=cup1.object_id)
        lamp1 = make_obj(name="lamp", state="on")
        lamp2 = make_obj(name="lamp", state="off", oid=lamp1.object_id)
        prev = make_state(objects=[cup1, lamp1])
        curr = make_state(objects=[cup2, lamp2])
        violations = self.checker.check(
            prev, curr, action_types=["pick"],
            allowed_state_changes=["cup"],
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["object"], "lamp")


class TestInvariantPrediction(unittest.TestCase):

    def setUp(self):
        self.checker = InvariantChecker()

    def test_stability_prediction_ok(self):
        violations = self.checker.check_prediction(
            {"event": "stability", "expected": "no_change"},
        )
        self.assertEqual(violations, [])

    def test_position_change_from_move_ok(self):
        violations = self.checker.check_prediction(
            {"event": "move", "expected": "position_change"},
        )
        self.assertEqual(violations, [])

    def test_position_change_without_move_violation(self):
        violations = self.checker.check_prediction(
            {"event": "teleport", "expected": "position_change"},
        )
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["rule"], "no_spontaneous_position_change")

    def test_empty_change_ok(self):
        self.assertEqual(self.checker.check_prediction({}), [])

    def test_reset_event_ok(self):
        self.assertEqual(
            self.checker.check_prediction({"event": "reset", "expected": "reset"}),
            [],
        )


class TestInvariantRules(unittest.TestCase):

    def setUp(self):
        self.checker = InvariantChecker()

    def test_default_rules(self):
        self.assertGreaterEqual(len(DEFAULT_INVARIANT_RULES), 3)

    def test_add_rule(self):
        self.checker.add_rule("custom_rule", "自定义规则")
        rules = self.checker.rules
        self.assertTrue(any(r["name"] == "custom_rule" for r in rules))

    def test_stats(self):
        st = self.checker.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertGreaterEqual(st["rules_count"], 3)

    def test_reset(self):
        self.checker.add_rule("temp", "临时")
        self.checker.reset()
        self.assertFalse(any(r["name"] == "temp" for r in self.checker.rules))

    def test_custom_rules_constructor(self):
        checker = InvariantChecker(rules=[{"name": "only", "description": "只有一条"}])
        self.assertEqual(len(checker.rules), 1)


if __name__ == "__main__":
    unittest.main()
