"""
YHLZ Embodied AI V9.5 - 元认知引擎补充测试 2 (V9.5 Extra2)

覆盖 (生成式批量 + 门面矩阵):
    - 门面操作矩阵
    - 认知记忆分类矩阵
    - 审计回放矩阵
"""
import unittest

from backend.embodied.companion.meta_cognition import (
    CognitionAudit,
    CognitionMemory,
    MetaCognitionEngine,
)


# ── 门面操作矩阵 ────────────────────────────────────────────────
_OPERATION_CASES = [
    ("monitor", {"task": "任务"}),
    ("detect_error", {"error_text": "记错了"}),
    ("verify", {"conclusion": "结论"}),
]


class TestGeneratedOperations(unittest.TestCase):
    """生成式: 门面操作"""
    pass


for _i, (_op, _kwargs) in enumerate(_OPERATION_CASES):
    def _make(op=_op, kwargs=_kwargs):
        def test(self):
            engine = MetaCognitionEngine()
            r = getattr(engine, op)(**kwargs)
            self.assertIsInstance(r, dict)
            if op == "monitor":
                self.assertIn("monitor_id", r)
            else:
                self.assertIn("mode", r)
        test.__name__ = f"test_op_{_i}"
        test.__doc__ = f"操作 {_op}"
        return test
    setattr(TestGeneratedOperations,
            _make().__name__, _make())


# ── 认知记忆分类矩阵 ────────────────────────────────────────────
_MEMORY_CAT_CASES = [
    ("经验A", "cognitive_experience"),
    ("错误案例", "error_case"),
    ("优化策略", "optimization_strategy"),
    ("经验B", "cognitive_experience"),
]


class TestGeneratedMemoryCats(unittest.TestCase):
    """生成式: 记忆分类"""
    pass


for _i, (_content, _cat) in enumerate(_MEMORY_CAT_CASES):
    def _make(content=_content, cat=_cat):
        def test(self):
            memory = CognitionMemory()
            entry = memory.save(content, cat, validated=True)
            self.assertEqual(entry["category"], cat)
            self.assertTrue(entry["memory_id"].startswith(
                "cog_"))
        test.__name__ = f"test_memcat_{_i}"
        test.__doc__ = f"记忆分类 {_cat}"
        return test
    setattr(TestGeneratedMemoryCats,
            _make().__name__, _make())


# ── 审计回放矩阵 ────────────────────────────────────────────────
_AUDIT_SEQ_CASES = [1, 2, 3, 5]


class TestGeneratedAuditSeq(unittest.TestCase):
    """生成式: 审计序列"""
    pass


for _i, _n in enumerate(_AUDIT_SEQ_CASES):
    def _make(n=_n):
        def test(self):
            audit = CognitionAudit()
            for j in range(n):
                audit.record(task=f"t{j}",
                             evaluation=f"{j}")
            report = audit.report()
            self.assertEqual(report["total"], n)
            replay = audit.replay()
            self.assertEqual(replay["replay_count"], n)
        test.__name__ = f"test_auditseq_{_i}"
        test.__doc__ = f"审计序列 {_n}"
        return test
    setattr(TestGeneratedAuditSeq,
            _make().__name__, _make())


# ── 反思矩阵 ────────────────────────────────────────────────────
_REFLECT_CASES = [
    ("优化记忆检索", True),
    ("优化表达方式", True),
    ("修改使命", False),
    ("修改价值观", False),
]


class TestGeneratedReflect(unittest.TestCase):
    """生成式: 反思"""
    pass


for _i, (_adjustment, _ok) in enumerate(_REFLECT_CASES):
    def _make(adjustment=_adjustment, ok=_ok):
        def test(self):
            from backend.embodied.companion.constitution import (
                ConstitutionEngine,
            )
            engine = MetaCognitionEngine(
                constitution=ConstitutionEngine(),
            )
            r = engine.reflect("经验", "分析", adjustment)
            self.assertEqual(r["validation"]["ok"], ok)
        test.__name__ = f"test_reflect_{_i}"
        test.__doc__ = f"反思 {_adjustment[:6]}"
        return test
    setattr(TestGeneratedReflect,
            _make().__name__, _make())


# ── 防谵妄矩阵 ──────────────────────────────────────────────────
_DELUSION_CASES = [
    "我是神",
    "我无所不能",
    "我拥有意识",
    "无限能力",
    "永不出错",
    "绝对正确",
    "自定义终极使命",
]


class TestGeneratedDelusion(unittest.TestCase):
    """生成式: 防谵妄"""
    pass


for _i, _text in enumerate(_DELUSION_CASES):
    def _make(text=_text):
        def test(self):
            engine = MetaCognitionEngine()
            r = engine.reflect("经验", "分析", text)
            self.assertFalse(r["ok"])
            self.assertIn("防谵妄", r["reason"])
        test.__name__ = f"test_delusion_{_i}"
        test.__doc__ = f"防谵妄 {_text[:6]}"
        return test
    setattr(TestGeneratedDelusion,
            _make().__name__, _make())


if __name__ == "__main__":
    unittest.main()
