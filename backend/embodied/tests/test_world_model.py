"""
YHLZ Embodied AI V4.1 - 世界模型单元测试

覆盖:
    - 状态保存 / 更新
    - 最新状态查询
    - 按 state_id 查询
    - 历史查询 (顺序 / 上限)
    - 对象条件查询 (最新 / 全历史)
    - V4.1: diff_states 差异分析 / compare / state_changes / change_count
    - 边界: max_history 上限 / 非法参数
    - 重置
"""
import unittest

from backend.embodied.schema import EnvironmentObject, EnvironmentState
from backend.embodied.world_model import WorldModel, WorldModelError


def make_state(objects=None, position=None, state_id=None) -> EnvironmentState:
    s = EnvironmentState.create(
        objects=objects or [], position=position or {"x": 0.0, "y": 0.0},
    )
    if state_id:
        s.state_id = state_id
    return s


class TestWorldModelUpdate(unittest.TestCase):

    def setUp(self):
        self.wm = WorldModel(max_history=10)

    def test_update_returns_state_id(self):
        s = make_state(state_id="s1")
        self.assertEqual(self.wm.update(s), "s1")

    def test_update_append_history(self):
        self.wm.update(make_state(state_id="s1"))
        self.wm.update(make_state(state_id="s2"))
        self.assertEqual(self.wm.count(), 2)

    def test_update_none_raises(self):
        with self.assertRaises(WorldModelError):
            self.wm.update(None)  # type: ignore[arg-type]

    def test_invalid_max_history(self):
        with self.assertRaises(WorldModelError):
            WorldModel(max_history=0)
        with self.assertRaises(WorldModelError):
            WorldModel(max_history=-5)

    def test_max_history_cap(self):
        wm = WorldModel(max_history=3)
        for i in range(6):
            wm.update(make_state(state_id=f"s{i}"))
        self.assertEqual(wm.count(), 3)
        self.assertEqual(wm.get_latest().state_id, "s5")


class TestWorldModelQuery(unittest.TestCase):

    def setUp(self):
        self.wm = WorldModel(max_history=10)
        self.objs = [
            EnvironmentObject.create(name="lamp", category="light", position={"x": 1.0, "y": 1.0}, state="on"),
            EnvironmentObject.create(name="box", category="container", position={"x": 2.0, "y": 3.0}, state="closed"),
        ]
        self.wm.update(make_state(objects=self.objs, state_id="s1"))
        self.wm.update(make_state(objects=[self.objs[0]], position={"x": 1.0, "y": 1.0}, state_id="s2"))

    def test_get_latest(self):
        s = self.wm.get_latest()
        self.assertEqual(s.state_id, "s2")

    def test_get_latest_empty(self):
        wm = WorldModel()
        self.assertIsNone(wm.get_latest())

    def test_get_state_by_id(self):
        s = self.wm.get_state("s1")
        self.assertEqual(len(s.objects), 2)

    def test_get_state_missing(self):
        self.assertIsNone(self.wm.get_state("missing"))

    def test_history_order(self):
        ids = [s.state_id for s in self.wm.history()]
        self.assertEqual(ids, ["s1", "s2"])

    def test_history_limit(self):
        ids = [s.state_id for s in self.wm.history(limit=1)]
        self.assertEqual(ids, ["s2"])

    def test_history_dicts(self):
        d = self.wm.history_dicts(limit=1)
        self.assertEqual(d[0]["state_id"], "s2")

    def test_find_objects_latest(self):
        found = self.wm.find_objects(name="lamp")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "lamp")

    def test_find_objects_category(self):
        found = self.wm.find_objects(category="container", use_latest=False)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "box")

    def test_find_objects_all_history(self):
        found = self.wm.find_objects(name="lamp", use_latest=False)
        self.assertEqual(len(found), 2)

    def test_find_objects_no_match(self):
        found = self.wm.find_objects(name="nonexistent")
        self.assertEqual(found, [])

    def test_object_count_latest(self):
        self.assertEqual(self.wm.object_count(), 1)

    def test_object_count_empty(self):
        wm = WorldModel()
        self.assertEqual(wm.object_count(), 0)


class TestWorldModelDiffV41(unittest.TestCase):
    """V4.1: 状态差异分析 / 变化历史"""

    def setUp(self):
        self.wm = WorldModel(max_history=10)

    def test_diff_added_removed_modified(self):
        o1 = EnvironmentObject.create(name="lamp", position={"x": 1.0, "y": 1.0}, state="on")
        o2 = EnvironmentObject.create(name="box", position={"x": 2.0, "y": 3.0}, state="closed")
        prev = make_state(objects=[o1, o2], position={"x": 0.0, "y": 0.0})
        o1c = EnvironmentObject(
            object_id=o1.object_id, name="lamp", position={"x": 1.0, "y": 1.0}, state="held",
        )
        o3 = EnvironmentObject.create(name="book", position={"x": 0.0, "y": 2.0})
        curr = make_state(objects=[o1c, o3], position={"x": 1.0, "y": 1.0})
        diff = WorldModel.diff_states(prev, curr)
        self.assertEqual(len(diff["added"]), 1)
        self.assertEqual(diff["added"][0]["name"], "book")
        self.assertEqual(len(diff["removed"]), 1)
        self.assertEqual(diff["removed"][0]["name"], "box")
        self.assertEqual(len(diff["modified"]), 1)
        self.assertEqual(diff["modified"][0]["state"]["to"], "held")
        self.assertEqual(diff["location"]["to"], {"x": 1.0, "y": 1.0})

    def test_diff_conditions(self):
        prev = EnvironmentState.create(
            position={"x": 0.0, "y": 0.0}, conditions={"temperature": 24.0},
        )
        curr = EnvironmentState.create(
            position={"x": 0.0, "y": 0.0}, conditions={"temperature": 26.0},
        )
        diff = WorldModel.diff_states(prev, curr)
        self.assertEqual(diff["conditions"]["to"], {"temperature": 26.0})

    def test_diff_relations_changed(self):
        prev = EnvironmentState.create(relations=[{"type": "near"}])
        curr = EnvironmentState.create(relations=[])
        diff = WorldModel.diff_states(prev, curr)
        self.assertTrue(diff["relations_changed"])

    def test_diff_no_change(self):
        prev = make_state(state_id="s1")
        curr = make_state(state_id="s2")
        diff = WorldModel.diff_states(prev, curr)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["modified"], [])
        self.assertIsNone(diff["location"])

    def test_diff_none_state(self):
        diff = WorldModel.diff_states(None, make_state())
        self.assertIn("error", diff)

    def test_update_records_change_history(self):
        self.wm.update(make_state(state_id="s1"))
        self.wm.update(make_state(state_id="s2"))
        self.assertEqual(self.wm.change_count(), 1)
        changes = self.wm.state_changes(limit=1)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["current_state"]["state_id"], "s2")

    def test_update_first_no_change_history(self):
        self.wm.update(make_state(state_id="s1"))
        self.assertEqual(self.wm.change_count(), 0)

    def test_compare_by_ids(self):
        self.wm.update(make_state(state_id="s1", position={"x": 0.0, "y": 0.0}))
        self.wm.update(make_state(state_id="s2", position={"x": 1.0, "y": 0.0}))
        diff = self.wm.compare("s1", "s2")
        self.assertEqual(diff["location"]["to"], {"x": 1.0, "y": 0.0})

    def test_compare_missing_id_raises(self):
        self.wm.update(make_state(state_id="s1"))
        with self.assertRaises(WorldModelError):
            self.wm.compare("s1", "missing")

    def test_state_changes_limit(self):
        for i in range(5):
            self.wm.update(make_state(state_id=f"s{i}"))
        self.assertEqual(len(self.wm.state_changes(limit=2)), 2)

    def test_reset_clears_changes(self):
        self.wm.update(make_state(state_id="s1"))
        self.wm.update(make_state(state_id="s2"))
        self.wm.reset()
        self.assertEqual(self.wm.change_count(), 0)


class TestWorldModelReset(unittest.TestCase):

    def test_reset_clears(self):
        wm = WorldModel()
        wm.update(make_state(state_id="s1"))
        n = wm.reset()
        self.assertEqual(n, 1)
        self.assertEqual(wm.count(), 0)
        self.assertIsNone(wm.get_latest())

    def test_max_history_property(self):
        wm = WorldModel(max_history=42)
        self.assertEqual(wm.max_history, 42)


if __name__ == "__main__":
    unittest.main()
