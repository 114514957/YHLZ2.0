"""
YHLZ 前端生成式测试 (Frontend Generated)

覆盖 (生成式):
    - 状态流转矩阵
    - 事件-情绪联动矩阵
    - 启动步骤矩阵
"""
import unittest

from frontend.avatar import EmotionStateManager
from frontend.runtime import (
    RUNTIME_EVENTS,
    RuntimeEvent,
    RuntimeEventBus,
    RuntimeState,
)


# ── 生成式: 事件-情绪联动矩阵 ─────────────────────────────────
_EVENT_EMOTION = [
    # (事件, 期望情绪)
    ("SYSTEM_READY", "happy"),
    ("MEMORY_SYNC", "surprised"),
    ("MODEL_SWITCH", "neutral"),
    ("TASK_START", "neutral"),
    ("TASK_END", "happy"),
    ("ERROR", "sad"),
]


class TestGeneratedEventEmotion(unittest.TestCase):
    """生成式: 事件→情绪"""
    pass


for _i, (_evt, _emotion) in enumerate(_EVENT_EMOTION):
    def _make(evt=_evt, emotion=_emotion):
        def test_case(self):
            esm = EmotionStateManager()
            r = esm.on_runtime_event(evt)
            self.assertTrue(r["ok"])
            self.assertEqual(r["emotion"], emotion)
        test_case.__name__ = f"test_evt_{evt}_{_i}"
        return test_case
    setattr(TestGeneratedEventEmotion,
            f"test_evt_{_evt}_{_i}", _make())


# ── 生成式: 状态-情绪联动矩阵 ─────────────────────────────────
_STATE_EMOTION = [
    ("idle", "neutral"),
    ("initializing", "neutral"),
    ("online", "happy"),
    ("thinking", "neutral"),
    ("learning", "surprised"),
    ("waiting", "neutral"),
    ("error", "sad"),
]


class TestGeneratedStateEmotion(unittest.TestCase):
    """生成式: 状态→情绪"""
    pass


for _i, (_state, _emotion) in enumerate(_STATE_EMOTION):
    def _make(state=_state, emotion=_emotion):
        def test_case(self):
            esm = EmotionStateManager()
            r = esm.on_companion_state(state)
            self.assertTrue(r["ok"])
            self.assertEqual(r["emotion"], emotion)
        test_case.__name__ = f"test_state_{state}_{_i}"
        return test_case
    setattr(TestGeneratedStateEmotion,
            f"test_state_{_state}_{_i}", _make())


# ── 生成式: 事件总线全类型矩阵 ────────────────────────────────
_ALL_EVENTS = [(e, ) for e in RUNTIME_EVENTS]


class TestGeneratedAllEvents(unittest.TestCase):
    """生成式: 全部事件可发布"""
    pass


for _i, (_evt,) in enumerate(_ALL_EVENTS):
    def _make(evt=_evt):
        def test_case(self):
            bus = RuntimeEventBus()
            got = []
            bus.subscribe(evt, lambda e: got.append(e.event_type))
            bus.publish(RuntimeEvent(evt, "测试"))
            self.assertEqual(got, [evt])
            self.assertEqual(bus.stats()["total"], 1)
        test_case.__name__ = f"test_all_evt_{evt}_{_i}"
        return test_case
    setattr(TestGeneratedAllEvents,
            f"test_all_evt_{_evt}_{_i}", _make())


# ── 生成式: 状态机全状态矩阵 ──────────────────────────────────
_ALL_STATES = [
    ("idle",), ("initializing",), ("online",),
    ("thinking",), ("learning",), ("waiting",), ("error",),
]


class TestGeneratedAllStates(unittest.TestCase):
    """生成式: 全部状态可设置"""
    pass


for _i, (_state,) in enumerate(_ALL_STATES):
    def _make(state=_state):
        def test_case(self):
            rs = RuntimeState()
            r = rs.set_state(state)
            self.assertTrue(r["ok"])
            self.assertEqual(rs.snapshot()["state"], state)
        test_case.__name__ = f"test_all_state_{state}_{_i}"
        return test_case
    setattr(TestGeneratedAllStates,
            f"test_all_state_{_state}_{_i}", _make())


# ── 生成式: 启动跳过组合矩阵 ──────────────────────────────────
_SKIP_COMBOS = [
    # (名称, 跳过列表, 期望 ready 执行)
    ("skip_network", ["backend", "runtime", "identity",
                      "memory", "model", "avatar"], True),
    ("skip_avatar", ["avatar"], False),  # backend 会失败
    ("skip_none", [], False),
]


class TestGeneratedSkip(unittest.TestCase):
    """生成式: 跳过组合"""
    pass


for _i, (_name, _skip, _exp) in enumerate(_SKIP_COMBOS):
    def _make(name=_name, skip=_skip, exp=_exp):
        def test_case(self):
            from frontend.startup import StartupCore
            # 用不可达端口隔离 (不依赖外部后端状态)
            core = StartupCore(backend_url="http://127.0.0.1:9")
            results = core.run(skip=skip)
            ready_run = any(
                r["step"] == "ready" for r in results
            )
            self.assertEqual(ready_run, exp)
        test_case.__name__ = f"test_skip_{name}_{_i}"
        return test_case
    setattr(TestGeneratedSkip,
            f"test_skip_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
