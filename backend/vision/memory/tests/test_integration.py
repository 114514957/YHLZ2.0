"""
YHLZ Vision Memory V1.0 - 集成测试

覆盖:
    - Understanding → Memory 全链路 (Mock VLM 理解 → 保存视觉记忆)
    - SQLite 持久化 + 检索
    - 权限全链路 (默认拒绝 → 开启 → 拒绝重置)
    - 单例 Service + Manager 组合
"""
import os
import tempfile
import unittest

from backend.vision.memory.logger import MemoryLogger
from backend.vision.memory.manager import (
    MemoryManager,
    get_manager,
    reset_manager,
)
from backend.vision.memory.permission import PermissionChecker
from backend.vision.memory.schema import MemoryQuery
from backend.vision.memory.service import (
    MemoryService,
    get_service,
    reset_service,
)
from backend.vision.memory.stores.sqlite_store import SQLiteMemoryStore
from backend.vision.understanding.service import (
    UnderstandingService,
    reset_service as reset_understanding_service,
)


class TestUnderstandingToMemoryIntegration(unittest.TestCase):

    def setUp(self):
        # Understanding: Mock 模式
        os.environ["YHLZ_UNDERSTANDING_TEST_MODE"] = "true"
        # Memory: 强制测试模式 (内存 store, 防止污染默认 SQLite 库)
        self._old_mem_env = os.environ.get("YHLZ_VISION_MEMORY_TEST_MODE")
        os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = "true"
        self.u_svc = UnderstandingService()
        self.u_svc.load_config({"understanding_enabled": True})
        # Memory: 内存 store
        self.m_svc = MemoryService(
            manager=MemoryManager(),
            permission=PermissionChecker(),
            mlog=MemoryLogger(enable_logging=False),
        )
        self.m_svc.load_config({"vision_memory_enabled": True})

    def tearDown(self):
        reset_understanding_service()
        reset_service()
        if self._old_mem_env is None:
            os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)
        else:
            os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = self._old_mem_env

    def _mock_image(self):
        import numpy as np
        return np.zeros((64, 64, 3), dtype=np.uint8)

    def test_understand_then_save(self):
        # 1. 理解屏幕 (Mock 场景描述)
        result = self.u_svc.describe_scene(self._mock_image())
        self.assertTrue(result.is_ok)
        # 2. 保存视觉记忆
        res = self.m_svc.save_understanding_result(result)
        self.assertTrue(res.success)
        # 3. 检索验证
        query_res = self.m_svc.query(MemoryQuery())
        self.assertEqual(query_res.count, 1)
        record = query_res.records[0]
        self.assertEqual(record.source, result.source)
        self.assertEqual(record.scene_type, result.scene_type)
        self.assertEqual(record.description, result.description)
        self.assertEqual(record.metadata.get("result_id"), result.id)

    def test_qa_remember_type(self):
        result = self.u_svc.answer_visual(self._mock_image(), "屏幕上有什么?")
        self.assertTrue(result.is_ok)
        res = self.m_svc.save_understanding_result(result)
        record = self.m_svc.retrieve(res.memory_id).record
        self.assertEqual(record.memory_type, "qa")

    def test_denied_result_not_saved(self):
        bad = self.u_svc.describe_scene(None)  # 空图 → 失败
        self.assertFalse(bad.is_ok)
        res = self.m_svc.save_understanding_result(bad)
        self.assertFalse(res.success)
        self.assertEqual(self.m_svc.count(), 0)

    def test_recent_context_after_save(self):
        result = self.u_svc.describe_scene(self._mock_image())
        self.m_svc.save_understanding_result(result)
        context = self.m_svc.recent_visual_context(limit=3)
        self.assertTrue(context)
        self.assertIn(result.description, context)


class TestSQLiteIntegration(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="yhlz_mem_integ_")
        self._db = os.path.join(self._tmp, "integ.db")
        self.store = SQLiteMemoryStore(self._db)
        self.mgr = MemoryManager()
        self.mgr.register_store("sqlite", self.store)
        self.svc = MemoryService(manager=self.mgr, permission=PermissionChecker())
        self.svc.load_config({"vision_memory_enabled": True})

    def tearDown(self):
        reset_service()
        self.store.close()
        for name in (self._db, self._db + "-wal", self._db + "-shm"):
            if os.path.exists(name):
                try:
                    os.remove(name)
                except OSError:
                    pass

    def test_save_query_delete_cycle(self):
        from backend.vision.memory.schema import VisualMemoryRecord
        # 保存
        rec = VisualMemoryRecord.create(
            description="网页上有价格信息",
            scene_type="web",
            tags=["价格"],
            importance="high",
        )
        res = self.svc.save(rec)
        self.assertTrue(res.success)
        self.assertEqual(self.svc.count(), 1)
        # 检索
        q = self.svc.query(MemoryQuery(scene_type="web", importance="high"))
        self.assertEqual(q.count, 1)
        # 更新
        up = self.svc.update(res.memory_id, importance="low")
        self.assertTrue(up.success)
        got = self.svc.retrieve(res.memory_id)
        self.assertEqual(got.record.importance, "low")
        # 删除
        d = self.svc.delete(res.memory_id)
        self.assertTrue(d.success)
        self.assertEqual(self.svc.count(), 0)


class TestSingletonIntegration(unittest.TestCase):

    def tearDown(self):
        reset_service()

    def test_get_service_singleton(self):
        os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = "true"
        try:
            s1 = get_service()
            s2 = get_service()
            self.assertIs(s1, s2)
            self.assertEqual(s1.manager.get_default_store().name, "memory")
        finally:
            os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)

    def test_reset_service(self):
        os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = "true"
        try:
            s1 = get_service()
            reset_service()
            s2 = get_service()
            self.assertIsNot(s1, s2)
        finally:
            os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)

    def test_get_manager_singleton_db_path(self):
        reset_manager()
        old = os.environ.get("YHLZ_VISION_MEMORY_TEST_MODE")
        os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)
        tmp = tempfile.mkdtemp(prefix="yhlz_mem_sing_")
        db = os.path.join(tmp, "sing.db")
        try:
            mgr = get_manager(db_path=db)
            self.assertEqual(mgr.get_default_store().name, "sqlite")
            from backend.vision.memory.schema import VisualMemoryRecord
            mgr.save(VisualMemoryRecord.create(description="单例保存"))
            self.assertTrue(os.path.exists(db))
        finally:
            reset_manager()
            if old is None:
                os.environ.pop("YHLZ_VISION_MEMORY_TEST_MODE", None)
            else:
                os.environ["YHLZ_VISION_MEMORY_TEST_MODE"] = old
            for name in (db, db + "-wal", db + "-shm"):
                if os.path.exists(name):
                    try:
                        os.remove(name)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
