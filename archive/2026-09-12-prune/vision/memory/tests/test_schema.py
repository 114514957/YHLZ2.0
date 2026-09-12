"""
YHLZ Vision Memory V1.0 - Schema 单元测试

覆盖:
    - 枚举 (MemoryType / MemoryImportance / MemoryStatus)
    - VisualMemoryRecord 序列化 / 工厂方法 / from_understanding_result
    - MemoryQuery 序列化
"""
import unittest

from backend.vision.memory.schema import (
    MemoryImportance,
    MemoryQuery,
    MemoryStatus,
    MemoryType,
    VisualMemoryRecord,
)
from backend.vision.understanding.schema import (
    UnderstandingResult,
    UnderstandingSource,
)


class TestEnums(unittest.TestCase):

    def test_memory_type_values(self):
        self.assertEqual(MemoryType.SCENE.value, "scene")
        self.assertEqual(MemoryType.TEXT.value, "text")
        self.assertEqual(MemoryType.OBJECT.value, "object")
        self.assertEqual(MemoryType.QA.value, "qa")
        self.assertEqual(MemoryType.COMBINED.value, "combined")

    def test_importance_values(self):
        self.assertEqual(MemoryImportance.LOW.value, "low")
        self.assertEqual(MemoryImportance.MEDIUM.value, "medium")
        self.assertEqual(MemoryImportance.HIGH.value, "high")

    def test_status_values(self):
        self.assertEqual(MemoryStatus.OK.value, "ok")
        self.assertEqual(MemoryStatus.PERMISSION_DENIED.value, "denied")
        self.assertEqual(MemoryStatus.NOT_FOUND.value, "not_found")
        self.assertEqual(MemoryStatus.EMPTY_INPUT.value, "empty_input")


class TestVisualMemoryRecord(unittest.TestCase):

    def test_defaults(self):
        r = VisualMemoryRecord.create(description="测试描述")
        self.assertTrue(r.id)
        self.assertEqual(r.memory_type, MemoryType.SCENE.value)
        self.assertEqual(r.source, "vlm")
        self.assertEqual(r.scene_type, "unknown")
        self.assertEqual(r.description, "测试描述")
        self.assertEqual(r.subjects, [])
        self.assertEqual(r.tags, [])
        self.assertEqual(r.importance, MemoryImportance.MEDIUM.value)
        self.assertEqual(r.confidence, 0.0)
        self.assertEqual(r.metadata, {})
        self.assertGreater(r.created_at, 0)
        self.assertGreater(r.updated_at, 0)

    def test_to_dict_roundtrip(self):
        r = VisualMemoryRecord.create(
            description="桌面有代码编辑器",
            memory_type=MemoryType.SCENE.value,
            source="describe",
            scene_type="desktop",
            subjects=[{"name": "editor", "category": "ui", "confidence": 0.9}],
            tags=["代码", "编辑器"],
            importance=MemoryImportance.HIGH.value,
            confidence=0.85,
            metadata={"result_id": "abc"},
        )
        d = r.to_dict()
        r2 = VisualMemoryRecord.from_dict(d)
        self.assertEqual(r2.id, r.id)
        self.assertEqual(r2.memory_type, r.memory_type)
        self.assertEqual(r2.source, r.source)
        self.assertEqual(r2.scene_type, r.scene_type)
        self.assertEqual(r2.description, r.description)
        self.assertEqual(r2.subjects, r.subjects)
        self.assertEqual(r2.tags, r.tags)
        self.assertEqual(r2.importance, r.importance)
        self.assertEqual(r2.confidence, r.confidence)
        self.assertEqual(r2.metadata, r.metadata)
        self.assertEqual(r2.created_at, r.created_at)

    def test_from_dict_defaults(self):
        r = VisualMemoryRecord.from_dict({})
        self.assertTrue(r.id)
        self.assertEqual(r.importance, "medium")

    def test_from_understanding_result(self):
        result = UnderstandingResult.create_ok(
            source=UnderstandingSource.DESCRIBE.value,
            scene_type="desktop",
            description="桌面上有 VS Code 和浏览器窗口",
            summary="开发环境",
            confidence=0.9,
            metadata={"provider": "mock"},
        )
        r = VisualMemoryRecord.from_understanding_result(result)
        self.assertEqual(r.source, UnderstandingSource.DESCRIBE.value)
        self.assertEqual(r.scene_type, "desktop")
        self.assertEqual(r.description, "桌面上有 VS Code 和浏览器窗口")
        self.assertEqual(r.memory_type, MemoryType.SCENE.value)
        self.assertEqual(r.metadata.get("result_id"), result.id)
        self.assertEqual(r.metadata.get("summary"), "开发环境")
        self.assertEqual(r.importance, MemoryImportance.MEDIUM.value)

    def test_from_understanding_result_qa_type(self):
        result = UnderstandingResult.create_ok(
            source=UnderstandingSource.QA.value,
            scene_type="document",
            description="文档内容",
            summary="回答内容",
        )
        r = VisualMemoryRecord.from_understanding_result(result)
        self.assertEqual(r.memory_type, MemoryType.QA.value)

    def test_from_understanding_result_custom(self):
        result = UnderstandingResult.create_ok(
            source=UnderstandingSource.DESCRIBE.value,
            scene_type="web",
            description="网页",
        )
        r = VisualMemoryRecord.from_understanding_result(
            result,
            tags=["自定义标签"],
            importance=MemoryImportance.HIGH.value,
            memory_type=MemoryType.TEXT.value,
        )
        self.assertEqual(r.tags, ["自定义标签"])
        self.assertEqual(r.importance, MemoryImportance.HIGH.value)
        self.assertEqual(r.memory_type, MemoryType.TEXT.value)


class TestMemoryQuery(unittest.TestCase):

    def test_defaults(self):
        q = MemoryQuery()
        self.assertIsNone(q.time_from)
        self.assertIsNone(q.time_to)
        self.assertIsNone(q.scene_type)
        self.assertIsNone(q.tag)
        self.assertIsNone(q.keyword)
        self.assertIsNone(q.importance)
        self.assertEqual(q.limit, 20)
        self.assertEqual(q.offset, 0)

    def test_to_dict_roundtrip(self):
        q = MemoryQuery(
            time_from=100.0,
            time_to=200.0,
            scene_type="desktop",
            tag="代码",
            keyword="编辑器",
            importance="high",
            limit=10,
            offset=5,
        )
        q2 = MemoryQuery.from_dict(q.to_dict())
        self.assertEqual(q2.time_from, 100.0)
        self.assertEqual(q2.time_to, 200.0)
        self.assertEqual(q2.scene_type, "desktop")
        self.assertEqual(q2.tag, "代码")
        self.assertEqual(q2.keyword, "编辑器")
        self.assertEqual(q2.importance, "high")
        self.assertEqual(q2.limit, 10)
        self.assertEqual(q2.offset, 5)

    def test_from_dict_float_convert(self):
        q = MemoryQuery.from_dict({"time_from": 100, "time_to": 200, "limit": "10"})
        self.assertEqual(q.time_from, 100.0)
        self.assertEqual(q.time_to, 200.0)
        self.assertEqual(q.limit, 10)


if __name__ == "__main__":
    unittest.main()
