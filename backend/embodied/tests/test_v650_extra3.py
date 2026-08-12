"""
YHLZ Embodied AI V6.5 - 认知反思生成式补充测试 (V6.5 Extra3)

覆盖 (专项补足至 ≥400, 生成式批量用例):
    - 模式分析变体矩阵
    - 矛盾检测组合
    - 评估矩阵
    - 守护字段矩阵
    - 验证组合
"""
import time
import unittest

from backend.embodied.companion.growth import (
    GrowthApplier,
    GrowthEvaluator,
    GrowthProposal,
)
from backend.embodied.companion.identity import (
    ChangeValidator,
    IdentityGuard,
)
from backend.embodied.companion.reflection import (
    CognitiveContradictionDetector,
    PatternAnalyzer,
)

_TRIGGERS = [
    "生成工程Prompt", "环境扫描", "拾取物体", "整理房间",
    "语音唤醒", "日程提醒", "代码审查", "日志分析",
    "策略调整", "目标规划", "关系互动", "创造方案",
]

_VARIANTS = ["成功", "超时", "位置不匹配", "权限拒绝", "重试成功"]

# ── 生成式模式分析测试 ──────────────────────────────────────────
def _make_pattern_test(idx, trigger):
    def test(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_rec(trigger=trigger, result="成功", rid=f"{trigger}{i}")
            for i in range(4)
        ]
        patterns = a.analyze(records)
        self.assertGreaterEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["trigger"], trigger)
    test.__name__ = f"test_pattern_{trigger}_{idx}"
    test.__doc__ = f"模式分析: {trigger}"
    return test


def _make_failure_test(idx, trigger):
    def test(self):
        a = PatternAnalyzer(min_samples=3, min_streak=2)
        records = [
            make_rec(trigger=trigger, type="failure",
                     result="错误", rid=f"{trigger}{i}")
            for i in range(3)
        ]
        types = [p["type"] for p in a.analyze(records)]
        self.assertIn("problem_pattern", types)
    test.__name__ = f"test_failure_{trigger}_{idx}"
    test.__doc__ = f"失败模式: {trigger}"
    return test


def make_rec(trigger="t", type="improvement", result="成功",
             rid="r", ts_offset=0):
    return {
        "id": rid, "type": type, "trigger": trigger,
        "lesson": "l", "result": result,
        "timestamp": time.time() - ts_offset * 86400,
    }


class TestGeneratedPatterns(unittest.TestCase):
    """生成式模式测试"""
    pass


for i, t in enumerate(_TRIGGERS):
    setattr(TestGeneratedPatterns, _make_pattern_test(i, t).__name__,
            _make_pattern_test(i, t))
    setattr(TestGeneratedPatterns, _make_failure_test(i, t).__name__,
            _make_failure_test(i, t))


# ── 生成式矛盾检测测试 ──────────────────────────────────────────
class TestGeneratedContradictions(unittest.TestCase):
    """生成式矛盾测试"""
    pass


def _make_conflict_test(idx, text, expected_type):
    def test(self):
        d = CognitiveContradictionDetector()
        r = d.detect({"trigger": text, "lesson": "l",
                      "result": "成功"})
        self.assertTrue(r["conflict"], text)
        if expected_type:
            self.assertEqual(r["type"], expected_type, text)
    test.__name__ = f"test_conflict_{idx}"
    test.__doc__ = f"矛盾: {text}"
    return test


_conflict_cases = [
    ("涉及使命调整", "identity_conflict"),
    ("修改核心价值观", "identity_conflict"),
    ("基础人格变化", "identity_conflict"),
    ("不可靠处理", "value_conflict"),
    ("违背诚信", "value_conflict"),
    ("不尊重用户", "value_conflict"),
    ("不负责行为", "value_conflict"),
    ("不安全操作", "value_conflict"),
]

for i, (text, etype) in enumerate(_conflict_cases):
    setattr(TestGeneratedContradictions,
            _make_conflict_test(i, text, etype).__name__,
            _make_conflict_test(i, text, etype))


def _make_clean_test(idx, text):
    def test(self):
        d = CognitiveContradictionDetector()
        r = d.detect({"trigger": text, "lesson": "l",
                      "result": "成功"})
        self.assertFalse(r["conflict"], text)
    test.__name__ = f"test_clean_{idx}"
    test.__doc__ = f"无冲突: {text}"
    return test


_clean_cases = [
    "正常任务执行", "用户打招呼", "环境温度正常",
    "文件已保存", "网络连接成功", "音量调整",
    "灯光开启", "音乐播放", "天气查询", "时间显示",
    "电量充足", "系统运行稳定",
]

for i, text in enumerate(_clean_cases):
    setattr(TestGeneratedContradictions,
            _make_clean_test(i, text).__name__,
            _make_clean_test(i, text))


# ── 生成式评估测试 ──────────────────────────────────────────────
class TestGeneratedEvaluations(unittest.TestCase):
    """生成式评估测试"""
    pass


def _make_eval_ok_test(idx, desc, risk):
    def test(self):
        ev = GrowthEvaluator()
        r = ev.evaluate({
            "id": f"p{idx}", "type": "skill_improvement",
            "description": desc, "expected_gain": "改进收益",
            "risk": risk, "confidence": 0.8,
        })
        self.assertTrue(r["approved"], desc)
    test.__name__ = f"test_eval_ok_{idx}"
    test.__doc__ = f"评估通过: {desc}"
    return test


_eval_ok_cases = [
    ("改进执行流程", "low"), ("优化记忆整理", "low"),
    ("调整互动频率", "low"), ("改进推理步骤", "low"),
    ("优化策略参数", "medium"), ("调整响应节奏", "low"),
    ("改进失败处理", "low"), ("优化经验查询", "medium"),
    ("调整情绪表达", "low"), ("改进创造流程", "low"),
]

for i, (desc, risk) in enumerate(_eval_ok_cases):
    setattr(TestGeneratedEvaluations,
            _make_eval_ok_test(i, desc, risk).__name__,
            _make_eval_ok_test(i, desc, risk))


def _make_eval_block_test(idx, desc):
    def test(self):
        ev = GrowthEvaluator()
        r = ev.evaluate({
            "id": f"p{idx}", "type": "skill_improvement",
            "description": desc, "expected_gain": "g",
            "risk": "low", "confidence": 0.8,
        })
        self.assertFalse(r["approved"], desc)
    test.__name__ = f"test_eval_block_{idx}"
    test.__doc__ = f"评估拒绝: {desc}"
    return test


_eval_block_cases = [
    "修改使命", "修改价值观", "修改人格", "修改安全规则",
    "修改权限", "关闭权限保护", "绕过安全检查",
    "自我修改核心", "调整使命方向", "改变核心价值观",
]

for i, desc in enumerate(_eval_block_cases):
    setattr(TestGeneratedEvaluations,
            _make_eval_block_test(i, desc).__name__,
            _make_eval_block_test(i, desc))


# ── 生成式守护测试 ──────────────────────────────────────────────
class TestGeneratedGuard(unittest.TestCase):
    """生成式守护测试"""
    pass


def _make_guard_block_test(idx, field):
    def test(self):
        g = IdentityGuard()
        ok, reason = g.check({field: "新值"})
        self.assertFalse(ok, field)
        self.assertIn("保护字段", reason)
    test.__name__ = f"test_guard_block_{idx}"
    test.__doc__ = f"守护拦截: {field}"
    return test


_guard_block_fields = [
    "mission", "core_value", "base_personality",
    "safety_rules", "permission",
]

for i, field in enumerate(_guard_block_fields):
    setattr(TestGeneratedGuard,
            _make_guard_block_test(i, field).__name__,
            _make_guard_block_test(i, field))


def _make_guard_ok_test(idx, field):
    def test(self):
        g = IdentityGuard()
        ok, reason = g.check({field: "值"})
        self.assertTrue(ok, field)
    test.__name__ = f"test_guard_ok_{idx}"
    test.__doc__ = f"守护放行: {field}"
    return test


_guard_ok_fields = [
    "dimensions", "communication_style", "note",
    "param_a", "param_b", "threshold_x", "window_size",
    "retry_limit", "timeout", "max_records",
]

for i, field in enumerate(_guard_ok_fields):
    setattr(TestGeneratedGuard,
            _make_guard_ok_test(i, field).__name__,
            _make_guard_ok_test(i, field))


# ── 生成式验证测试 ──────────────────────────────────────────────
class TestGeneratedValidators(unittest.TestCase):
    """生成式验证测试"""
    pass


def _make_validator_ok_test(idx, fields):
    def test(self):
        v = ChangeValidator()
        before = {f: 1 for f in fields}
        after = {f: 2 for f in fields}
        r = v.validate(before, after, "调整参数")
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["changed_fields"]), len(fields))
    test.__name__ = f"test_validator_ok_{idx}"
    test.__doc__ = f"验证通过: {fields}"
    return test


_validator_ok_cases = [
    ["a"], ["a", "b"], ["a", "b", "c"], ["x", "y", "z", "w"],
    ["param1", "param2"], ["n1", "n2", "n3", "n4", "n5"],
    ["q"], ["m", "n"], ["u", "v", "w"], ["s", "t"],
]

for i, fields in enumerate(_validator_ok_cases):
    setattr(TestGeneratedValidators,
            _make_validator_ok_test(i, fields).__name__,
            _make_validator_ok_test(i, fields))


def _make_validator_block_test(idx, field):
    def test(self):
        v = ChangeValidator()
        r = v.validate({field: "旧"}, {field: "新"}, "变更")
        self.assertFalse(r["ok"], field)
    test.__name__ = f"test_validator_block_{idx}"
    test.__doc__ = f"验证拒绝: {field}"
    return test


_validator_block_fields = [
    "mission", "core_value", "base_personality",
    "safety_rules", "permission",
]

for i, field in enumerate(_validator_block_fields):
    setattr(TestGeneratedValidators,
            _make_validator_block_test(i, field).__name__,
            _make_validator_block_test(i, field))


# ── 生成式建议测试 ──────────────────────────────────────────────
class TestGeneratedProposals(unittest.TestCase):
    """生成式建议测试"""
    pass


def _make_proposal_test(idx, trigger, ptype):
    def test(self):
        g = GrowthProposal()
        ps = g.generate({
            "patterns": [{"type": ptype, "trigger": trigger,
                          "confidence": 0.8, "meaning": "m"}],
        })
        self.assertGreaterEqual(len(ps), 1)
        self.assertTrue(ps[0]["id"].startswith("gp_"))
    test.__name__ = f"test_proposal_{idx}"
    test.__doc__ = f"建议: {trigger}"
    return test


_proposal_cases = [
    ("失败触发A", "problem_pattern"),
    ("失败触发B", "problem_pattern"),
    ("失败触发C", "problem_pattern"),
    ("成功触发A", "success_strategy"),
    ("成功触发B", "success_strategy"),
    ("成功触发C", "success_strategy"),
    ("成功触发D", "success_strategy"),
]

for i, (trigger, ptype) in enumerate(_proposal_cases):
    setattr(TestGeneratedProposals,
            _make_proposal_test(i, trigger, ptype).__name__,
            _make_proposal_test(i, trigger, ptype))


# ── 生成式应用测试 ──────────────────────────────────────────────
class TestGeneratedAppliers(unittest.TestCase):
    """生成式应用测试"""
    pass


def _make_apply_test(idx, param):
    def test(self):
        a = GrowthApplier()
        r = a.apply(
            {"id": f"p{idx}", "type": "skill_improvement",
             "description": "改进", "expected_gain": "g",
             "risk": "low", "confidence": 0.8},
            {"approved": True, "reason": "x"},
            before_state={param: 1},
            change_fn=lambda b, p: {param: 2},
        )
        self.assertEqual(r["status"], "applied")
        self.assertEqual(r["after"][param], 2)
    test.__name__ = f"test_apply_{idx}"
    test.__doc__ = f"应用: {param}"
    return test


_apply_params = [
    "param_1", "param_2", "param_3", "param_4", "param_5",
    "threshold", "step", "limit", "ratio", "window",
]

for i, param in enumerate(_apply_params):
    setattr(TestGeneratedAppliers,
            _make_apply_test(i, param).__name__,
            _make_apply_test(i, param))


if __name__ == "__main__":
    unittest.main()
