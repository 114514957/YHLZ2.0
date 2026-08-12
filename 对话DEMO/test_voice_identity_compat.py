"""
M0.4 Voice Identity 兼容性单测: personality.json 单源扩展 (替代 character.yaml)

覆盖:
1. 默认配置: DEFAULT_PERSONALITY_CONFIG / DEFAULT_VOICE_IDENTITY 含 voice_identity
2. 旧 json 兼容: 无 voice_identity / 空 voice_identity / 字段缺失 → 自动回填默认值
3. 新 json 读取: voice_identity 完整时正常返回
4. 字段级 merge: update_voice_identity / update_personality(voice_identity=...) 不丢字段
5. 持久化: 更新后写盘 + 重读一致
6. 重置: reset_personality 后 voice_identity 也是默认值
7. 系统提示词不受影响: _get_system_prompt 与 voice_identity 解耦
8. 损坏 json 回退: 加载失败 → DEFAULT_PERSONALITY_CONFIG (含 voice_identity)

运行: venv\Scripts\python.exe 对话DEMO\test_voice_identity_compat.py
（不依赖 GPU / 不依赖 LLM, 仅测 personality.json 读写与 voice_identity 字段）
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.context_manager as cm_module
from backend.context_manager import (
    ContextManager,
    DEFAULT_PERSONALITY_CONFIG,
    DEFAULT_VOICE_IDENTITY,
)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class _TmpConfig:
    """临时 personality.json 隔离 fixture: patch 模块级 PERSONALITY_CONFIG_FILE"""

    def __init__(self, payload: dict = None):
        self.tmpdir = tempfile.mkdtemp(prefix="yhlz_m04_")
        self.path = Path(self.tmpdir) / "personality.json"
        if payload is not None:
            _write_json(self.path, payload)

    def cleanup(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestDefaultConfig(unittest.TestCase):
    """默认配置常量含 voice_identity"""

    def test_default_voice_identity_constants(self):
        self.assertIn("voice_id", DEFAULT_VOICE_IDENTITY)
        self.assertIn("engine", DEFAULT_VOICE_IDENTITY)
        self.assertEqual(DEFAULT_VOICE_IDENTITY["voice_id"], "default")
        self.assertEqual(DEFAULT_VOICE_IDENTITY["engine"], "qwen3")

    def test_default_personality_config_has_voice_identity(self):
        self.assertIn("voice_identity", DEFAULT_PERSONALITY_CONFIG)
        vi = DEFAULT_PERSONALITY_CONFIG["voice_identity"]
        self.assertEqual(vi["voice_id"], "default")
        self.assertEqual(vi["engine"], "qwen3")

    def test_default_voice_identity_is_copied_not_shared(self):
        """DEFAULT_PERSONALITY_CONFIG 中的 voice_identity 应是 copy, 防止全局可变状态污染"""
        a = DEFAULT_PERSONALITY_CONFIG["voice_identity"]
        b = DEFAULT_VOICE_IDENTITY
        # 不同对象 (copy), 但内容相等
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


class TestLegacyJsonCompat(unittest.TestCase):
    """旧 json (无 voice_identity) 必须正常运行 — M0.4 核心要求"""

    def test_load_legacy_json_without_voice_identity(self):
        """旧 json 完全没有 voice_identity 字段 → 内存回填默认值, 不写盘"""
        legacy = {
            "name": "元亨",
            "role": "铁哥们",
            "traits": ["义气"],
            "tone": "兄弟腔",
            "description": "测试旧角色",
        }
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                cfg = cm.get_personality_config()
                # 旧字段保留
                self.assertEqual(cfg["name"], "元亨")
                self.assertEqual(cfg["role"], "铁哥们")
                # voice_identity 自动回填
                self.assertIn("voice_identity", cfg)
                self.assertEqual(cfg["voice_identity"]["voice_id"], "default")
                self.assertEqual(cfg["voice_identity"]["engine"], "qwen3")
                # 不写盘 (兼容性回填仅在内存)
                with open(tmp.path, "r", encoding="utf-8") as f:
                    on_disk = json.load(f)
                self.assertNotIn("voice_identity", on_disk)
        finally:
            tmp.cleanup()

    def test_load_legacy_json_with_empty_voice_identity(self):
        """旧 json voice_identity={} → 字段级补全"""
        legacy = {
            "name": "元亨",
            "voice_identity": {},
        }
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                vi = cm.get_voice_identity()
                self.assertEqual(vi["voice_id"], "default")
                self.assertEqual(vi["engine"], "qwen3")
        finally:
            tmp.cleanup()

    def test_load_legacy_json_with_partial_voice_identity(self):
        """旧 json voice_identity 只含 voice_id → engine 字段级补全"""
        legacy = {
            "name": "元亨",
            "voice_identity": {"voice_id": "yuanheng_v1"},
        }
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                vi = cm.get_voice_identity()
                self.assertEqual(vi["voice_id"], "yuanheng_v1")  # 保留用户值
                self.assertEqual(vi["engine"], "qwen3")           # 补全默认
        finally:
            tmp.cleanup()

    def test_load_legacy_json_with_null_voice_identity(self):
        """旧 json voice_identity=null → 回填默认 (非 dict 视为缺失)"""
        legacy = {
            "name": "元亨",
            "voice_identity": None,
        }
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                vi = cm.get_voice_identity()
                self.assertEqual(vi, {"voice_id": "default", "engine": "qwen3"})
        finally:
            tmp.cleanup()


class TestNewJsonLoad(unittest.TestCase):
    """新 json (含完整 voice_identity) 正常读取"""

    def test_load_new_json_full_voice_identity(self):
        new_cfg = {
            "name": "元亨",
            "role": "铁哥们",
            "voice_identity": {
                "voice_id": "yuanheng_clone_v2",
                "engine": "gpt-sovits",
            },
        }
        tmp = _TmpConfig(new_cfg)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                vi = cm.get_voice_identity()
                self.assertEqual(vi["voice_id"], "yuanheng_clone_v2")
                self.assertEqual(vi["engine"], "gpt-sovits")
                # get_personality_config 也带 voice_identity
                cfg = cm.get_personality_config()
                self.assertEqual(cfg["voice_identity"], vi)
        finally:
            tmp.cleanup()


class TestUpdateVoiceIdentity(unittest.TestCase):
    """字段级 merge + 持久化"""

    def test_update_voice_identity_full_persists(self):
        """update_voice_identity 同时更新 voice_id+engine, 写盘 + 重读一致"""
        legacy = {"name": "元亨", "voice_identity": {"voice_id": "default", "engine": "qwen3"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                new_vi = cm.update_voice_identity(voice_id="clone_v1", engine="gpt-sovits")
                self.assertEqual(new_vi["voice_id"], "clone_v1")
                self.assertEqual(new_vi["engine"], "gpt-sovits")
                # 写盘验证
                with open(tmp.path, "r", encoding="utf-8") as f:
                    on_disk = json.load(f)
                self.assertEqual(on_disk["voice_identity"]["voice_id"], "clone_v1")
                self.assertEqual(on_disk["voice_identity"]["engine"], "gpt-sovits")
                # 重读一致
                cm2 = ContextManager()
                self.assertEqual(cm2.get_voice_identity(), new_vi)
        finally:
            tmp.cleanup()

    def test_update_voice_identity_partial_keeps_other_field(self):
        """只更新 voice_id, engine 不变"""
        legacy = {"name": "元亨", "voice_identity": {"voice_id": "default", "engine": "qwen3"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                new_vi = cm.update_voice_identity(voice_id="clone_v1")
                self.assertEqual(new_vi["voice_id"], "clone_v1")
                self.assertEqual(new_vi["engine"], "qwen3")  # 保留
        finally:
            tmp.cleanup()

    def test_update_voice_identity_no_args_no_change(self):
        """无参数调用 = 不修改, 返回当前值"""
        legacy = {"name": "元亨", "voice_identity": {"voice_id": "v1", "engine": "e1"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                vi = cm.update_voice_identity()
                self.assertEqual(vi, {"voice_id": "v1", "engine": "e1"})
        finally:
            tmp.cleanup()

    def test_update_voice_identity_empty_string_falls_back_to_default(self):
        """传 voice_id="" 视为缺失 → 回填默认值 (防用户误清空)"""
        legacy = {"name": "元亨", "voice_identity": {"voice_id": "v1", "engine": "e1"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                # voice_id="" 走 falsy 回填, engine 保留
                new_vi = cm.update_voice_identity(voice_id="", engine="edge")
                self.assertEqual(new_vi["voice_id"], "default")
                self.assertEqual(new_vi["engine"], "edge")
        finally:
            tmp.cleanup()

    def test_update_personality_with_voice_identity_dict_merges(self):
        """update_personality(voice_identity={...}) 走字段级 merge, 不整对象覆盖"""
        legacy = {"name": "元亨", "voice_identity": {"voice_id": "v1", "engine": "qwen3"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                # 只传 voice_id, 不传 engine → engine 应保留 qwen3
                cm.update_personality(voice_identity={"voice_id": "v2"})
                vi = cm.get_voice_identity()
                self.assertEqual(vi["voice_id"], "v2")
                self.assertEqual(vi["engine"], "qwen3")  # 字段级 merge 保留
        finally:
            tmp.cleanup()

    def test_update_personality_with_voice_identity_missing_fields_refills(self):
        """update_personality(voice_identity={'voice_id':'', 'engine':''}) → 回填默认"""
        legacy = {"name": "元亨", "voice_identity": {"voice_id": "v1", "engine": "qwen3"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                cm.update_personality(voice_identity={"voice_id": "", "engine": ""})
                vi = cm.get_voice_identity()
                self.assertEqual(vi["voice_id"], "default")
                self.assertEqual(vi["engine"], "qwen3")
        finally:
            tmp.cleanup()

    def test_update_personality_other_fields_unaffected(self):
        """更新 voice_identity 不影响 name/role 等其他字段"""
        legacy = {"name": "元亨", "role": "铁哥们", "voice_identity": {"voice_id": "v1", "engine": "qwen3"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                cm.update_voice_identity(voice_id="v2")
                cfg = cm.get_personality_config()
                self.assertEqual(cfg["name"], "元亨")
                self.assertEqual(cfg["role"], "铁哥们")
                self.assertEqual(cfg["voice_identity"]["voice_id"], "v2")
        finally:
            tmp.cleanup()


class TestResetPersonality(unittest.TestCase):
    """reset_personality 后 voice_identity 也是默认值"""

    def test_reset_personality_resets_voice_identity(self):
        modified = {
            "name": "改过的",
            "role": "改过的",
            "voice_identity": {"voice_id": "modified", "engine": "modified"},
        }
        tmp = _TmpConfig(modified)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                cm.reset_personality()
                # 重新加载
                cm2 = ContextManager()
                cfg = cm2.get_personality_config()
                self.assertEqual(cfg["name"], DEFAULT_PERSONALITY_CONFIG["name"])
                self.assertEqual(cfg["voice_identity"], {"voice_id": "default", "engine": "qwen3"})
        finally:
            tmp.cleanup()


class TestSystemPromptUnaffected(unittest.TestCase):
    """voice_identity 字段不影响 _get_system_prompt 输出"""

    def test_system_prompt_does_not_contain_voice_identity(self):
        legacy = {"name": "元亨", "role": "铁哥们", "traits": ["义气"], "tone": "兄弟腔",
                  "description": "测试", "voice_identity": {"voice_id": "v1", "engine": "e1"}}
        tmp = _TmpConfig(legacy)
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                prompt = cm._get_system_prompt()
                self.assertIn("元亨", prompt)
                self.assertIn("铁哥们", prompt)
                self.assertNotIn("voice_identity", prompt)
                self.assertNotIn("v1", prompt)
                self.assertNotIn("e1", prompt)
        finally:
            tmp.cleanup()


class TestCorruptedJsonFallback(unittest.TestCase):
    """损坏 json → 返回 DEFAULT_PERSONALITY_CONFIG (含 voice_identity)"""

    def test_load_corrupted_json_returns_default_with_voice_identity(self):
        tmp = _TmpConfig()
        # 写入损坏的 json
        with open(tmp.path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                cfg = cm.get_personality_config()
                # 回退到默认配置 (含 voice_identity)
                self.assertEqual(cfg["name"], DEFAULT_PERSONALITY_CONFIG["name"])
                self.assertIn("voice_identity", cfg)
                self.assertEqual(cfg["voice_identity"], DEFAULT_VOICE_IDENTITY)
        finally:
            tmp.cleanup()


class TestMissingFileFallback(unittest.TestCase):
    """personality.json 不存在 → 返回 DEFAULT_PERSONALITY_CONFIG"""

    def test_load_when_file_missing(self):
        tmp = _TmpConfig()  # 不写文件
        try:
            with patch.object(cm_module, "PERSONALITY_CONFIG_FILE", tmp.path):
                cm = ContextManager()
                cfg = cm.get_personality_config()
                self.assertEqual(cfg["name"], DEFAULT_PERSONALITY_CONFIG["name"])
                self.assertEqual(cfg["voice_identity"], DEFAULT_VOICE_IDENTITY)
                vi = cm.get_voice_identity()
                self.assertEqual(vi, DEFAULT_VOICE_IDENTITY)
        finally:
            tmp.cleanup()


class TestRealPersonalityJson(unittest.TestCase):
    """集成验证: 真实 backend/data/personality.json 含 voice_identity 字段"""

    def test_real_personality_json_has_voice_identity(self):
        real_path = Path(__file__).resolve().parents[1] / "backend" / "data" / "personality.json"
        if not real_path.exists():
            self.skipTest("real personality.json not found")
        with open(real_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("voice_identity", data, "M0.4: 真实 personality.json 必须含 voice_identity 字段")
        vi = data["voice_identity"]
        self.assertIn("voice_id", vi)
        self.assertIn("engine", vi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
