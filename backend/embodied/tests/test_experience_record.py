"""
YHLZ Embodied AI V5.7 - 经历记录单元测试 (Experience Record)

覆盖 (experience_record.py):
    - ExperienceRecord: 数据模型字段 / to_dict / from_dict / create
    - 5 种经验类型白名单
    - 参数校验: 非法类型 / confidence/value 范围 / trigger 空
"""
import time
import unittest

from backend.embodied.companion.experience import (
    EXPERIENCE_TYPES,
    ExperienceError,
    ExperienceRecord,
    VALUE_HIGH,
    VALUE_LOW,
    VALUE_MEDIUM,
)


class TestExperienceRecord(unittest.TestCase):
    """经历记录模型"""

    def test_create_valid(self):
        """合法创建"""
        rec = ExperienceRecord.create(
            type="engineering", trigger="完成V5.6开发",
            lesson="关系系统需要独立于人格", confidence=0.9,
        )
        self.assertEqual(rec.type, "engineering")
        self.assertEqual(rec.trigger, "完成V5.6开发")
        self.assertEqual(rec.lesson, "关系系统需要独立于人格")
        self.assertEqual(rec.confidence, 0.9)

    def test_id_auto(self):
        """自动 ID"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.assertTrue(rec.id)

    def test_timestamp_auto(self):
        """自动时间戳"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.assertGreater(rec.timestamp, 0)

    def test_to_dict_fields(self):
        """to_dict 字段完整"""
        rec = ExperienceRecord.create(type="interaction", trigger="t",
                                      lesson="l")
        d = rec.to_dict()
        for key in ("id", "type", "source", "trigger", "action",
                    "result", "evaluation", "lesson", "confidence",
                    "value", "timestamp"):
            self.assertIn(key, d)

    def test_from_dict_roundtrip(self):
        """from_dict 往返一致"""
        rec = ExperienceRecord.create(
            type="decision", trigger="t", lesson="l",
            action="a", result="r", confidence=0.8, value=0.7,
        )
        d = rec.to_dict()
        rec2 = ExperienceRecord.from_dict(d)
        self.assertEqual(rec2.id, rec.id)
        self.assertEqual(rec2.type, rec.type)
        self.assertEqual(rec2.lesson, rec.lesson)
        self.assertEqual(rec2.confidence, 0.8)

    def test_default_value(self):
        """默认价值 medium"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.assertEqual(rec.value, VALUE_MEDIUM)

    def test_default_confidence(self):
        """默认置信度 0"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.assertEqual(rec.confidence, 0.0)

    def test_default_source(self):
        """默认来源空"""
        rec = ExperienceRecord.create(type="failure", trigger="t",
                                      lesson="l")
        self.assertEqual(rec.source, "")


class TestTypes(unittest.TestCase):
    """经验类型"""

    def test_types_whitelist(self):
        """5 种类型"""
        self.assertEqual(set(EXPERIENCE_TYPES),
                         {"interaction", "engineering", "decision",
                          "failure", "improvement"})

    def test_all_types_valid(self):
        """全部类型可创建"""
        for t in EXPERIENCE_TYPES:
            rec = ExperienceRecord.create(type=t, trigger="t",
                                          lesson="l")
            self.assertEqual(rec.type, t)

    def test_invalid_type_raises(self):
        """非法类型 → ExperienceError"""
        with self.assertRaises(ExperienceError):
            ExperienceRecord.create(type="hack", trigger="t",
                                    lesson="l")

    def test_value_constants(self):
        """价值常量"""
        self.assertEqual(VALUE_LOW, 0.3)
        self.assertEqual(VALUE_MEDIUM, 0.6)
        self.assertEqual(VALUE_HIGH, 0.8)


class TestValidation(unittest.TestCase):
    """参数校验"""

    def test_trigger_required(self):
        """trigger 空 → ExperienceError"""
        with self.assertRaises(ExperienceError):
            ExperienceRecord.create(type="failure", trigger="",
                                    lesson="l")

    def test_confidence_range(self):
        """confidence 越界 → ExperienceError"""
        with self.assertRaises(ExperienceError):
            ExperienceRecord.create(type="failure", trigger="t",
                                    lesson="l", confidence=1.5)

    def test_confidence_negative(self):
        """confidence 负 → ExperienceError"""
        with self.assertRaises(ExperienceError):
            ExperienceRecord.create(type="failure", trigger="t",
                                    lesson="l", confidence=-0.1)

    def test_value_range(self):
        """value 越界 → ExperienceError"""
        with self.assertRaises(ExperienceError):
            ExperienceRecord.create(type="failure", trigger="t",
                                    lesson="l", value=1.5)

    def test_high_value_record(self):
        """高价值记录"""
        rec = ExperienceRecord.create(type="improvement", trigger="t",
                                      lesson="l", value=VALUE_HIGH)
        self.assertEqual(rec.value, 0.8)


if __name__ == "__main__":
    unittest.main()
