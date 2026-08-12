"""
YHLZ Vision Memory V1.0 - Service 单元测试

覆盖:
    - 配置加载 / 权限管理
    - save / save_understanding_result (权限拒绝 / 只保存成功结果)
    - retrieve / update / delete / query / clear / count
    - recent_visual_context
    - 日志与状态
"""
import unittest

from backend.vision.memory.logger import MemoryLogger
from backend.vision.memory.manager import MemoryManager
from backend.vision.memory.permission import PermissionChecker
from backend.vision.memory.schema import (
    MemoryQuery,
    MemoryStatus,
    VisualMemoryRecord,
)
from backend.vision.memory.service import MemoryService, reset_service
from backend.vision.memory.stores.memory_store import InMemoryMemoryStore
from backend.vision.understanding.schema import (
    UnderstandingResult,
    UnderstandingSource,
)


class MemoryServiceTestCase(unittest.TestCase):

    def setUp(self):
        self.store = InMemoryMemoryStore(max_entries=100)
        self.mgr = MemoryManager()
        self.mgr.register_store("test", self.store)
        self.permission = PermissionChecker()
        self.mlog = MemoryLogger(max_entries=200, enable_logging=False)
        self.svc = MemoryService(
            manager=self.mgr,
            permission=self.permission,
            mlog=self.mlog,
        )

    def tearDown(self):
        self.store.close()
        reset_service()

    def _enable(self):
        self.permission.load(vision_memory_enabled=True)

    def _make(self, description="测试记忆", **kw):
        return VisualMemoryRecord.create(description=description, **kw)

    def _ok_result(self, source=UnderstandingSource.DESCRIBE.value, scene_type="desktop"):
        return UnderstandingResult.create_ok(
            source=source,
            scene_type=scene_type,
            description="桌面上有代码编辑器",
            summary="开发环境",
            confidence=0.9,
        )

    # ── 配置 ──────────────────────────────────────────────────────
    def test_load_config(self):
        svc = MemoryService()
        svc.load_config({"vision_memory_enabled": True})
        self.assertTrue(svc.get_permission()["vision_memory_enabled"])
        self.assertTrue(svc._initialized)

    def test_load_config_denied_default(self):
        svc = MemoryService()
        svc.load_config({})
        self.assertFalse(svc.get_permission()["vision_memory_enabled"])

    def test_load_config_custom(self):
        svc = MemoryService()
        svc.load_config({
            "vision_memory_enabled": True,
            "default_importance": "high",
            "max_query_limit": 10,
        })
        d = svc.get_permission()
        self.assertTrue(d["vision_memory_enabled"])
        self.assertEqual(d["default_importance"], "high")
        self.assertEqual(d["max_query_limit"], 10)

    def test_update_permission(self):
        perm = self.svc.update_permission(vision_memory_enabled=True, max_query_limit=5)
        self.assertTrue(perm.vision_memory_enabled)
        self.assertEqual(perm.max_query_limit, 5)

    def test_reset_permission(self):
        self.svc.update_permission(vision_memory_enabled=True)
        self.svc.reset_permission()
        self.assertFalse(self.svc.get_permission()["vision_memory_enabled"])

    def test_set_logger(self):
        new_log = MemoryLogger(enable_logging=False)
        self.svc.set_logger(new_log)
        self.assertIs(self.svc.mlog, new_log)

    # ── 保存 ──────────────────────────────────────────────────────
    def test_save_denied_by_default(self):
        res = self.svc.save(self._make())
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)
        self.assertIn("vision_memory_enabled", res.error)
        self.assertEqual(self.store.count(), 0)

    def test_save_ok(self):
        self._enable()
        res = self.svc.save(self._make("保存成功"))
        self.assertTrue(res.success)
        self.assertEqual(res.status, MemoryStatus.OK.value)
        self.assertTrue(res.memory_id)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.retrieve(res.memory_id).description, "保存成功")

    def test_save_rejects_raw_image(self):
        self._enable()
        rec = self._make("带图")
        rec.metadata["image"] = "raw_base64"
        res = self.svc.save(rec)
        self.assertFalse(res.success)
        self.assertEqual(self.store.count(), 0)

    def test_save_understanding_result_ok(self):
        self._enable()
        result = self._ok_result()
        res = self.svc.save_understanding_result(result)
        self.assertTrue(res.success)
        self.assertEqual(res.status, MemoryStatus.OK.value)
        record = self.store.retrieve(res.memory_id)
        self.assertEqual(record.scene_type, "desktop")
        self.assertEqual(record.source, UnderstandingSource.DESCRIBE.value)
        self.assertEqual(record.metadata.get("result_id"), result.id)

    def test_save_understanding_result_denied(self):
        res = self.svc.save_understanding_result(self._ok_result())
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)
        self.assertEqual(self.store.count(), 0)

    def test_save_understanding_result_none(self):
        self._enable()
        res = self.svc.save_understanding_result(None)
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.EMPTY_INPUT.value)

    def test_save_understanding_result_failed(self):
        self._enable()
        bad = UnderstandingResult.create_error(
            source="describe",
            status="error",
            error="理解失败",
        )
        res = self.svc.save_understanding_result(bad)
        self.assertFalse(res.success)
        self.assertEqual(self.store.count(), 0)

    def test_save_understanding_result_custom(self):
        self._enable()
        res = self.svc.save_understanding_result(
            self._ok_result(),
            tags=["代码"],
            importance="high",
            memory_type="text",
        )
        record = self.store.retrieve(res.memory_id)
        self.assertEqual(record.tags, ["代码"])
        self.assertEqual(record.importance, "high")
        self.assertEqual(record.memory_type, "text")

    def test_save_uses_default_importance(self):
        self._enable()
        self.svc.update_permission(default_importance="high")
        res = self.svc.save_understanding_result(self._ok_result())
        self.assertEqual(self.store.retrieve(res.memory_id).importance, "high")

    # ── 检索 ──────────────────────────────────────────────────────
    def test_retrieve_ok(self):
        self._enable()
        mid = self.svc.save(self._make("检索")).memory_id
        res = self.svc.retrieve(mid)
        self.assertTrue(res.success)
        self.assertEqual(res.record.description, "检索")

    def test_retrieve_denied(self):
        self.svc.save(self._make("a"))
        res = self.svc.retrieve("x")
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)

    def test_retrieve_missing(self):
        self._enable()
        res = self.svc.retrieve("not_exist")
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.NOT_FOUND.value)

    def test_query_ok(self):
        self._enable()
        self.svc.save(self._make("代码编辑器", scene_type="desktop"))
        self.svc.save(self._make("音乐播放器", scene_type="desktop"))
        res = self.svc.query(MemoryQuery(keyword="代码"))
        self.assertTrue(res.success)
        self.assertEqual(res.count, 1)
        self.assertEqual(res.records[0].description, "代码编辑器")

    def test_query_denied(self):
        res = self.svc.query(MemoryQuery())
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)

    def test_query_limit_cap(self):
        self._enable()
        self.svc.update_permission(max_query_limit=3)
        for i in range(10):
            self.svc.save(self._make(f"记录{i}"))
        res = self.svc.query(MemoryQuery(limit=100))
        self.assertEqual(res.count, 3)

    def test_query_tag_and_importance(self):
        self._enable()
        self.svc.save(self._make("a", tags=["工作"], importance="high"))
        self.svc.save(self._make("b", tags=["娱乐"]))
        res = self.svc.query(MemoryQuery(tag="工作", importance="high"))
        self.assertEqual(res.count, 1)
        self.assertEqual(res.records[0].description, "a")

    # ── 更新 / 删除 / 清空 ────────────────────────────────────────
    def test_update_ok(self):
        self._enable()
        mid = self.svc.save(self._make("原始")).memory_id
        res = self.svc.update(mid, description="更新后")
        self.assertTrue(res.success)
        self.assertEqual(self.store.retrieve(mid).description, "更新后")

    def test_update_missing(self):
        self._enable()
        res = self.svc.update("not_exist", description="x")
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.NOT_FOUND.value)

    def test_update_denied(self):
        res = self.svc.update("x", description="y")
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)

    def test_delete_ok(self):
        self._enable()
        mid = self.svc.save(self._make("待删")).memory_id
        res = self.svc.delete(mid)
        self.assertTrue(res.success)
        self.assertIsNone(self.store.retrieve(mid))

    def test_delete_missing(self):
        self._enable()
        res = self.svc.delete("not_exist")
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.NOT_FOUND.value)

    def test_delete_denied(self):
        res = self.svc.delete("x")
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)

    def test_clear_ok(self):
        self._enable()
        self.svc.save(self._make("a"))
        self.svc.save(self._make("b"))
        res = self.svc.clear()
        self.assertTrue(res.success)
        self.assertEqual(res.count, 2)
        self.assertEqual(self.store.count(), 0)

    def test_clear_denied(self):
        res = self.svc.clear()
        self.assertFalse(res.success)
        self.assertEqual(res.status, MemoryStatus.PERMISSION_DENIED.value)

    def test_count(self):
        self.assertEqual(self.svc.count(), 0)
        self._enable()
        self.svc.save(self._make("a"))
        self.assertEqual(self.svc.count(), 1)

    # ── 视觉上下文 ────────────────────────────────────────────────
    def test_recent_visual_context(self):
        self._enable()
        self.svc.save_understanding_result(self._ok_result())
        context = self.svc.recent_visual_context(limit=5)
        self.assertIn("桌面", context)
        self.assertIn("desktop", context)

    def test_recent_visual_context_empty(self):
        self._enable()
        self.assertEqual(self.svc.recent_visual_context(limit=5), "")

    def test_recent_visual_context_denied(self):
        self.assertEqual(self.svc.recent_visual_context(limit=5), "")

    def test_recent_visual_context_zero_limit(self):
        self._enable()
        self.svc.save_understanding_result(self._ok_result())
        self.assertEqual(self.svc.recent_visual_context(limit=0), "")

    # ── 日志 / 状态 ───────────────────────────────────────────────
    def test_logs_recorded(self):
        self._enable()
        self.svc.save(self._make("a"))
        logs = self.svc.get_logs()
        self.assertGreaterEqual(len(logs), 1)
        stats = self.svc.get_log_stats()
        self.assertGreaterEqual(stats["total"], 1)

    def test_clear_logs(self):
        self._enable()
        self.svc.save(self._make("a"))
        n = self.svc.clear_logs()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(self.svc.get_log_stats()["total"], 0)

    def test_status(self):
        self._enable()
        status = self.svc.status()
        self.assertEqual(status["version"], "1.0.0")
        self.assertTrue(status["permission"]["vision_memory_enabled"])
        self.assertEqual(status["manager"]["stores_count"], 1)

    def test_list_stores(self):
        stores = self.svc.list_stores()
        self.assertEqual(len(stores), 1)
        self.assertEqual(stores[0]["name"], "test")


if __name__ == "__main__":
    unittest.main()
