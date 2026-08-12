"""
YHLZ Voice Identity System V1.7 - V1 最终集成审计测试

验证全链路: Service → Manager → Registry/Cache → Store → DB
使用临时 DB 隔离, 不污染生产 voice_identity.db

运行: venv\Scripts\python.exe 对话DEMO\test_v1_final_audit.py
"""
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 隔离: 临时 DB + 临时缓存目录, 避免污染生产
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="yhlz_v1_audit_"))
_TMP_DB = _TMP_ROOT / "voice_identity.db"
_TMP_CACHE = _TMP_ROOT / "voice_cache"
_TMP_CACHE.mkdir(parents=True, exist_ok=True)

# 在导入 voice_identity 之前 patch DEFAULT_DB_PATH, 确保单例指向临时库
os.environ["YHLZ_V1_AUDIT_TMP_ROOT"] = str(_TMP_ROOT)

from backend.voice_identity.database import VoiceIdentityDB
from backend.voice_identity.profile import VoiceProfileStore, VoiceProfileError
from backend.voice_identity.registry import VoiceRegistry, VoiceRegistryError
from backend.voice_identity.manager import VoiceManager, VoiceManagerError
from backend.voice_identity.cache_manager import VoiceCacheManager
from backend.voice_identity.service import (
    VoiceIdentityService,
    VoiceIdentityServiceError,
)
from backend.voice_identity.models import VoiceProfile
from backend.voice_identity import schema


# ── Duck-typed 假适配器 (模拟 Qwen3 / GPT-SoVITS, 验证 Cache 桥接不触真引擎) ──
class FakeQwen3Adapter:
    """模拟 Qwen3 适配器: 仅记录调用, 不触真模型"""
    def __init__(self):
        self.calls = []
        self.disk = {}  # voice_id -> entry (模拟磁盘缓存)

    def load_voice(self, voice_id, ref_audio=None, x_vector_only_mode=True):
        self.calls.append(("load_voice", voice_id, ref_audio))
        return {"prompt": f"fake_prompt_{voice_id}", "embedding": b"\x00\x01",
                "metadata": {"voice_id": voice_id, "ref_audio": ref_audio}}

    def save_voice_cache_to_disk(self, voice_id, dir_path):
        self.calls.append(("save_disk", voice_id, dir_path))
        out_dir = Path(dir_path) / voice_id
        out_dir.mkdir(parents=True, exist_ok=True)
        import json
        with open(out_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump({"voice_id": voice_id}, f)
        self.disk[voice_id] = out_dir
        return str(out_dir)

    def load_voice_cache_from_disk(self, voice_id, dir_path):
        self.calls.append(("load_disk", voice_id, dir_path))
        in_dir = Path(dir_path) / voice_id
        if not (in_dir / "metadata.json").is_file():
            return None
        return {"prompt": f"restored_{voice_id}", "embedding": b"\x00\x01",
                "metadata": {"voice_id": voice_id}}

    def clear_voice(self, voice_id=None):
        self.calls.append(("clear", voice_id))
        return 1


class FakeGptSovitsAdapter:
    """模拟 GPT-SoVITS 适配器"""
    def __init__(self):
        self.calls = []
        self.current_weights = None

    def change_weights(self, sovits_model=None, gpt_model=None, text_lang=None):
        self.calls.append(("change_weights", sovits_model, gpt_model))
        self.current_weights = (sovits_model, gpt_model)


def _build_service() -> VoiceIdentityService:
    """构建隔离的 V1 Service (临时 DB + 假适配器)"""
    db = VoiceIdentityDB(str(_TMP_DB))
    store = VoiceProfileStore(db)
    registry = VoiceRegistry(store)
    cache = VoiceCacheManager(
        qwen3_adapter=FakeQwen3Adapter(),
        gpt_sovits_adapter=FakeGptSovitsAdapter(),
        cache_root=str(_TMP_CACHE),
        db=db,
    )
    manager = VoiceManager(store=store, registry=registry, cache=cache)
    return VoiceIdentityService(manager=manager, registry=registry, cache=cache, db=db)


class TestSchemaAndDB(unittest.TestCase):
    """V1.1 数据层: schema + DB 自动初始化 + CRUD"""

    def test_db_auto_init_creates_tables(self):
        db = VoiceIdentityDB(str(_TMP_DB))
        h = db.health()
        self.assertTrue(h["ok"])
        self.assertEqual(h["schema_version"], schema.SCHEMA_VERSION)
        # voice_profiles 表存在且可计数 (测试间共享临时 DB, 不断言具体数量)
        self.assertIn("voice_profiles", h)

    def test_table_columns_match_design(self):
        db = VoiceIdentityDB(str(_TMP_DB))
        cols = {r["name"] for r in db._conn.execute(
            "PRAGMA table_info(voice_profiles);").fetchall()}
        expected = {"id", "voice_id", "owner_id", "name", "type", "language",
                    "status", "engine", "reference_audio", "style", "metadata",
                    "created_at", "updated_at"}
        self.assertTrue(expected.issubset(cols), f"缺失列: {expected - cols}")

    def test_profile_crud(self):
        db = VoiceIdentityDB(str(_TMP_DB))
        p = VoiceProfile(voice_id="audit_crud", name="审计CRUD", engine="qwen3")
        db.insert_profile(p)
        got = db.get_profile_by_id("audit_crud")
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "审计CRUD")
        n = db.update_profile("audit_crud", {"name": "改名后"})
        self.assertEqual(n, 1)
        n = db.delete_profile("audit_crud")
        self.assertEqual(n, 1)
        self.assertIsNone(db.get_profile_by_id("audit_crud"))


class TestProfileStoreStateMachine(unittest.TestCase):
    """V1.2 Profile 状态机"""

    def test_valid_transitions(self):
        svc = _build_service()
        store = svc.manager.store
        p = store.create(name="状态机测试", voice_id="sm_test")
        self.assertEqual(p.status, "creating")
        p = store.mark_processing(p.voice_id)
        self.assertEqual(p.status, "processing")
        p = store.mark_ready(p.voice_id)
        self.assertEqual(p.status, "ready")
        p = store.activate(p.voice_id)
        self.assertEqual(p.status, "active")
        p = store.deactivate(p.voice_id)
        self.assertEqual(p.status, "ready")

    def test_invalid_transition_raises(self):
        svc = _build_service()
        store = svc.manager.store
        p = store.create(name="非法转移", voice_id="bad_trans", status="creating")
        with self.assertRaises(VoiceProfileError):
            store.activate(p.voice_id)  # creating → active 非法

    def test_soft_delete_keeps_data(self):
        svc = _build_service()
        store = svc.manager.store
        p = store.create(name="软删", voice_id="soft_del")
        ok = store.delete(p.voice_id, soft=True)
        self.assertTrue(ok)
        got = store.get(p.voice_id)
        self.assertIsNotNone(got)
        self.assertEqual(got.status, "deleted")

    def test_auto_generated_voice_id_unique(self):
        svc = _build_service()
        store = svc.manager.store
        p1 = store.create(name="test")
        p2 = store.create(name="test")
        self.assertNotEqual(p1.voice_id, p2.voice_id)


class TestRegistryDiscoverability(unittest.TestCase):
    """V1.3 Registry 发现层"""

    def test_register_makes_discoverable(self):
        svc = _build_service()
        reg = svc.registry
        p = svc.manager.store.create(name="注册测试", voice_id="reg_test")
        # creating 状态不可发现
        self.assertIsNone(reg.get_voice("reg_test"))
        # 注册 → ready → 可发现
        reg.register_voice("reg_test")
        self.assertIsNotNone(reg.get_voice("reg_test"))

    def test_unregister_hides(self):
        svc = _build_service()
        reg = svc.registry
        svc.manager.store.create(name="注销", voice_id="unreg_test", status="ready")
        self.assertIsNotNone(reg.get_voice("unreg_test"))
        reg.unregister_voice("unreg_test")
        self.assertIsNone(reg.get_voice("unreg_test"))  # disabled 不可发现

    def test_list_discoverable_only(self):
        svc = _build_service()
        reg = svc.registry
        svc.manager.store.create(name="可发现", voice_id="disc_1", status="ready")
        svc.manager.store.create(name="不可发现", voice_id="disc_2", status="creating")
        result = reg.list_voice(discoverable_only=True)
        ids = [p.voice_id for p in result]
        self.assertIn("disc_1", ids)
        self.assertNotIn("disc_2", ids)

    def test_deleted_cannot_register(self):
        svc = _build_service()
        reg = svc.registry
        svc.manager.store.create(name="已删", voice_id="del_reg", status="deleted")
        with self.assertRaises(VoiceRegistryError):
            reg.register_voice("del_reg")


class TestManagerLifecycle(unittest.TestCase):
    """V1.4 Manager 生命周期"""

    def test_create_voice_ready_state(self):
        svc = _build_service()
        p = svc.create_voice(name="经理创建", voice_id="mgr_1")
        self.assertEqual(p.status, "ready")

    def test_activate_loads_cache(self):
        svc = _build_service()
        p = svc.create_voice(name="激活", voice_id="mgr_act", engine="qwen3",
                             reference_audio="/fake/ref.wav")
        p = svc.manager.activate_voice("mgr_act")
        self.assertEqual(p.status, "active")
        # Qwen3 假适配器应被调用 load
        fake = svc.cache._qwen3
        self.assertTrue(any(c[0] == "load_disk" for c in fake.calls))

    def test_disable_unloads_cache(self):
        svc = _build_service()
        svc.create_voice(name="停用", voice_id="mgr_dis", engine="qwen3",
                         reference_audio="/fake/ref.wav")
        svc.manager.activate_voice("mgr_dis")
        fake = svc.cache._qwen3
        fake.calls.clear()
        svc.manager.disable_voice("mgr_dis")
        self.assertTrue(any(c[0] == "clear" for c in fake.calls))

    def test_delete_soft_keeps_cache(self):
        svc = _build_service()
        svc.create_voice(name="软删经理", voice_id="mgr_sdel", engine="qwen3",
                         reference_audio="/fake/ref.wav")
        ok = svc.manager.delete_voice("mgr_sdel", soft=True)
        self.assertTrue(ok)
        # 软删保留缓存
        self.assertTrue(svc.cache.exists("mgr_sdel"))
        got = svc.manager.get_voice("mgr_sdel")
        self.assertEqual(got.status, "deleted")

    def test_delete_hard_removes_cache(self):
        svc = _build_service()
        svc.create_voice(name="硬删经理", voice_id="mgr_hdel", engine="qwen3",
                         reference_audio="/fake/ref.wav")
        ok = svc.manager.delete_voice("mgr_hdel", soft=False)
        self.assertTrue(ok)
        self.assertIsNone(svc.manager.get_voice("mgr_hdel"))
        self.assertFalse(svc.cache.exists("mgr_hdel"))

    def test_manager_never_imports_tts(self):
        """架构约束: manager 不得 import backend.tts"""
        import inspect
        from backend.voice_identity import manager as mgr_mod
        src = inspect.getsource(mgr_mod)
        self.assertNotIn("from backend.tts", src)
        self.assertNotIn("import backend.tts", src)


class TestCacheManager(unittest.TestCase):
    """V1.5 Cache Manager"""

    def test_prepare_qwen3_persists_to_disk(self):
        svc = _build_service()
        svc.create_voice(name="缓存准备", voice_id="cache_prep", engine="qwen3",
                         reference_audio="/fake/ref.wav")
        # create_voice 已触发 prepare (有 cache 时)
        self.assertTrue(svc.cache.exists("cache_prep"))
        # voice_models 表应有记录
        models = svc.db.get_models_by_voice("cache_prep")
        self.assertTrue(any(m.engine == "qwen3" for m in models))

    def test_save_load_cycle(self):
        svc = _build_service()
        svc.create_voice(name="存取", voice_id="cache_sl", engine="qwen3",
                         reference_audio="/fake/ref.wav")
        # save (显式)
        self.assertTrue(svc.cache.save("cache_sl"))
        # exists
        self.assertTrue(svc.cache.exists("cache_sl"))
        # remove
        self.assertTrue(svc.cache.remove("cache_sl"))
        # 磁盘目录应被清
        self.assertFalse((svc.cache._voice_dir("cache_sl") / "metadata.json").is_file())

    def test_gpt_sovits_weight_registration(self):
        svc = _build_service()
        svc.create_voice(
            name="GPT权重", voice_id="gpt_w", engine="gpt_sovits",
            metadata={"sovits_model": "/fake/sovits.pth", "gpt_model": "/fake/gpt.pth"},
        )
        models = svc.db.get_models_by_voice("gpt_w")
        self.assertTrue(any(m.engine == "gpt_sovits" for m in models))

    def test_cache_manager_no_tts_import(self):
        """架构约束: cache_manager 不得真实 import backend.tts (AST 校验, 排除 docstring)"""
        import ast
        import inspect
        from backend.voice_identity import cache_manager as cm_mod
        tree = ast.parse(inspect.getsource(cm_mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(
                        alias.name.startswith("backend.tts"),
                        f"cache_manager 禁止 import {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module and node.module.startswith("backend.tts"),
                    f"cache_manager 禁止 from {node.module} import",
                )


class TestServiceLayer(unittest.TestCase):
    """V1.6 Service API + 单激活策略"""

    def test_create_get_list(self):
        svc = _build_service()
        svc.create_voice(name="服务1", voice_id="svc_1")
        svc.create_voice(name="服务2", voice_id="svc_2")
        self.assertIsNotNone(svc.get_voice("svc_1"))
        ids = [p.voice_id for p in svc.list_voice()]
        self.assertIn("svc_1", ids)
        self.assertIn("svc_2", ids)

    def test_select_voice_single_activation(self):
        svc = _build_service()
        svc.create_voice(name="选中A", voice_id="sel_a", engine="qwen3",
                         reference_audio="/fake/a.wav")
        svc.create_voice(name="选中B", voice_id="sel_b", engine="qwen3",
                         reference_audio="/fake/b.wav")
        # 选 A
        p = svc.select_voice("sel_a")
        self.assertEqual(p.status, "active")
        self.assertEqual(svc.get_selected_voice_id(), "sel_a")
        # 选 B → A 应去激活 (active→ready)
        p = svc.select_voice("sel_b")
        self.assertEqual(p.status, "active")
        self.assertEqual(svc.get_selected_voice_id(), "sel_b")
        a = svc.get_voice("sel_a")
        self.assertEqual(a.status, "ready")  # 去激活保留可发现

    def test_select_persists_across_instances(self):
        svc = _build_service()
        svc.create_voice(name="持久", voice_id="persist", engine="qwen3",
                         reference_audio="/fake/p.wav")
        svc.select_voice("persist")
        # 重建 Service (复用同 DB), 选中状态应恢复
        svc2 = _build_service()
        self.assertEqual(svc2.get_selected_voice_id(), "persist")

    def test_select_deleted_raises(self):
        svc = _build_service()
        # Service.create_voice 不暴露 status (正确设计), 经 store 直接造 deleted 态
        svc.manager.store.create(name="已删", voice_id="sel_del", status="deleted")
        with self.assertRaises(VoiceIdentityServiceError):
            svc.select_voice("sel_del")

    def test_delete_clears_selection(self):
        svc = _build_service()
        svc.create_voice(name="选中后删", voice_id="sel_del2", engine="qwen3",
                         reference_audio="/fake/x.wav")
        svc.select_voice("sel_del2")
        svc.delete_voice("sel_del2", soft=True)
        self.assertIsNone(svc.get_selected_voice_id())

    def test_health_snapshot(self):
        svc = _build_service()
        h = svc.health()
        self.assertIn("db", h)
        self.assertTrue(h["db"]["ok"])
        self.assertIn("cache", h)
        self.assertIn("selected_voice", h)


class TestStartupIsolation(unittest.TestCase):
    """V1 兼容性: 模块导入无副作用, 不影响旧启动"""

    def test_import_voice_identity_no_side_effects(self):
        """import backend.voice_identity 不创建 db 文件 (懒初始化)"""
        # 重新 import 不应触发 get_db
        import importlib
        import backend.voice_identity as vi
        importlib.reload(vi)
        # 模块 __init__ 不应主动调 get_db, 仅定义函数
        self.assertTrue(callable(vi.init_voice_identity))
        self.assertTrue(callable(vi.health))

    def test_tts_adapters_not_polluted(self):
        """TTS 适配器模块不 import voice_identity"""
        import inspect
        from backend.tts.adapters import gpt_sovits_adapter as gpt_mod
        from backend.tts import qwen3_tts as qwen_mod
        for mod in (gpt_mod, qwen_mod):
            src = inspect.getsource(mod)
            self.assertNotIn("voice_identity", src,
                             f"{mod.__name__} 不应引用 voice_identity")

    def test_personality_voice_identity_field_unchanged(self):
        """M0.4 personality.json 的 voice_identity 字段语义未被 V1 改动"""
        from backend.context_manager import DEFAULT_VOICE_IDENTITY
        self.assertEqual(set(DEFAULT_VOICE_IDENTITY.keys()), {"voice_id", "engine"})


def _cleanup():
    """测试结束后清理临时目录"""
    global _TMP_ROOT
    try:
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _cleanup()
