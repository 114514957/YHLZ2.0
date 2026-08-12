"""
YHLZ Voice Identity System V1.5 - Voice Cache Manager 永久缓存管理

职责:
    - 管理 embedding 缓存 / engine cache / prompt cache
    - 桥接 Voice Identity 层与 M0 TTS Adapter 层 (唯一桥接点)
    - 实现 V1.4 Manager 期望的 Cache 协议: prepare/load/unload/remove/exists
    - 实现 V1.5 Prompt API: save/load/remove/exists

兼容性 (M0):
    - Qwen3 多 voice cache: 经适配器 load_voice / save_voice_cache_to_disk /
      load_voice_cache_from_disk / clear_voice 操作 (embedding.pt + prompt.pt + metadata.json)
    - GPT-SoVITS 缓存: 权重路径登记 (voice_models.model_path), load 时 change_weights

设计原则:
    - 不 import backend.tts (duck-typed 适配器注入, 保持 voice_identity 解耦)
    - 永久缓存目录: backend/data/voice_cache/<voice_id>/
    - 生命周期: 删除→清缓存, 禁用→保留缓存 (对齐 V1.4 Manager)
    - voice_models 表追踪 cache_path / model_path / hash / loaded
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from backend.voice_identity.database import VoiceIdentityDB, get_db
from backend.voice_identity.models import VoiceModel

logger = logging.getLogger(__name__)

# 永久缓存根目录: backend/data/voice_cache/
_CACHE_ROOT = Path(__file__).resolve().parent.parent / "data" / "voice_cache"
_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
DEFAULT_CACHE_ROOT: str = str(_CACHE_ROOT)


def _file_hash(path: str) -> Optional[str]:
    """计算文件 md5 (不存在返回 None)"""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


class VoiceCacheManager:
    """声音缓存管理器 (桥接 TTS Adapter)

    适配器协议 (duck-typed, 经构造函数注入):
        Qwen3 适配器:
            load_voice(voice_id, ref_audio, x_vector_only_mode) → entry|None
            get_voice(voice_id) → entry|None
            clear_voice(voice_id) → int
            save_voice_cache_to_disk(voice_id, dir_path) → path|None
            load_voice_cache_from_disk(voice_id, dir_path) → entry|None
        GPT-SoVITS 适配器:
            change_weights(sovits_model, gpt_model, text_lang) → None
    """

    def __init__(
        self,
        qwen3_adapter: Optional[Any] = None,
        gpt_sovits_adapter: Optional[Any] = None,
        cache_root: Optional[str] = None,
        db: Optional[VoiceIdentityDB] = None,
    ):
        self._qwen3 = qwen3_adapter
        self._gpt = gpt_sovits_adapter
        self._cache_root = Path(cache_root or DEFAULT_CACHE_ROOT)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._db = db or get_db()

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    def _voice_dir(self, voice_id: str) -> Path:
        return self._cache_root / voice_id

    def _resolve_engine(self, voice_id: str) -> str:
        """从 profile 解析引擎类型; 无 profile 默认 qwen3"""
        profile = self._db.get_profile_by_id(voice_id)
        return profile.engine if profile else "qwen3"

    # ------------------------------------------------------------------
    # 核心协议 (V1.4 Manager 调用)
    # ------------------------------------------------------------------

    def prepare(self, voice_id: str, reference_audio: Optional[str]) -> bool:
        """PROCESSING 阶段: 提取并持久化缓存

        - Qwen3: load_voice 提取 embedding → save 到磁盘 → 登记 voice_models
        - GPT-SoVITS: 登记 weight 路径到 voice_models (无提取)
        返回是否成功。
        """
        engine = self._resolve_engine(voice_id)
        if engine == "qwen3":
            return self._prepare_qwen3(voice_id, reference_audio)
        if engine == "gpt_sovits":
            return self._prepare_gpt_sovits(voice_id, reference_audio)
        # edge 等无缓存引擎: 仅记录
        logger.info(f"引擎 {engine} 无需缓存准备: {voice_id}")
        return True

    def load(self, voice_id: str) -> bool:
        """ACTIVE 阶段: 从磁盘恢复缓存到内存

        - Qwen3: load_voice_cache_from_disk → 标记 loaded=1
        - GPT-SoVITS: change_weights (若适配器可用)
        """
        engine = self._resolve_engine(voice_id)
        if engine == "qwen3":
            return self._load_qwen3(voice_id)
        if engine == "gpt_sovits":
            return self._load_gpt_sovits(voice_id)
        return True

    def unload(self, voice_id: str) -> bool:
        """DISABLE 阶段: 清除内存缓存 (保留磁盘)"""
        engine = self._resolve_engine(voice_id)
        if engine == "qwen3" and self._qwen3 is not None:
            try:
                self._qwen3.clear_voice(voice_id)
            except Exception as e:
                logger.warning(f"Qwen3 unload 失败 {voice_id}: {e}")
        # 标记 voice_models loaded=0
        for m in self._db.get_models_by_voice(voice_id):
            if m.loaded:
                self._db.update_model_loaded(m.id, False)
        logger.info(f"缓存已卸载 (内存): {voice_id}")
        return True

    def remove(self, voice_id: str) -> bool:
        """DELETE 阶段: 清理磁盘 + 内存 + voice_models 记录"""
        # 内存
        if self._qwen3 is not None:
            try:
                self._qwen3.clear_voice(voice_id)
            except Exception as e:
                logger.debug(f"Qwen3 clear 失败 {voice_id}: {e}")
        # 磁盘
        vdir = self._voice_dir(voice_id)
        if vdir.is_dir():
            shutil.rmtree(vdir, ignore_errors=True)
            logger.info(f"磁盘缓存已清理: {vdir}")
        # DB 记录
        self._db.delete_models_by_voice(voice_id)
        logger.info(f"缓存已彻底清理: {voice_id}")
        return True

    def exists(self, voice_id: str) -> bool:
        """缓存是否存在 (磁盘目录含 metadata.json 或 voice_models 有记录)"""
        vdir = self._voice_dir(voice_id)
        if (vdir / "metadata.json").is_file():
            return True
        return len(self._db.get_models_by_voice(voice_id)) > 0

    # ------------------------------------------------------------------
    # V1.5 Prompt API
    # ------------------------------------------------------------------

    def save(self, voice_id: str) -> bool:
        """持久化内存缓存到磁盘 (Qwen3)"""
        engine = self._resolve_engine(voice_id)
        if engine != "qwen3" or self._qwen3 is None:
            logger.debug(f"save 跳过 (引擎={engine} 或无适配器): {voice_id}")
            return False
        try:
            saved = self._qwen3.save_voice_cache_to_disk(voice_id, str(self._cache_root))
            if saved:
                self._upsert_model_record(voice_id, engine, cache_path=saved)
                logger.info(f"缓存已保存: {voice_id} → {saved}")
                return True
        except Exception as e:
            logger.error(f"save 失败 {voice_id}: {e}")
        return False

    # load / remove / exists 见上 (V1.4 协议复用)

    # ------------------------------------------------------------------
    # Qwen3 实现
    # ------------------------------------------------------------------

    def _prepare_qwen3(self, voice_id: str, reference_audio: Optional[str]) -> bool:
        if self._qwen3 is None:
            logger.warning(f"无 Qwen3 适配器, 跳过 prepare: {voice_id}")
            return False
        try:
            entry = self._qwen3.load_voice(voice_id, reference_audio, x_vector_only_mode=True)
            if entry is None:
                logger.warning(f"Qwen3 提取 embedding 失败: {voice_id}")
                return False
            # 持久化到磁盘
            saved = self._qwen3.save_voice_cache_to_disk(voice_id, str(self._cache_root))
            ref_hash = _file_hash(reference_audio) if reference_audio else None
            self._upsert_model_record(
                voice_id, "qwen3",
                model_path=reference_audio,
                cache_path=saved,
                hash=ref_hash,
            )
            logger.info(f"Qwen3 缓存准备完成: {voice_id}")
            return True
        except Exception as e:
            logger.error(f"Qwen3 prepare 异常 {voice_id}: {e}")
            return False

    def _load_qwen3(self, voice_id: str) -> bool:
        if self._qwen3 is None:
            return False
        vdir = self._voice_dir(voice_id)
        if not (vdir / "metadata.json").is_file():
            logger.warning(f"磁盘缓存不存在: {voice_id}")
            return False
        try:
            entry = self._qwen3.load_voice_cache_from_disk(voice_id, str(self._cache_root))
            if entry is None:
                return False
            # 标记 loaded=1
            for m in self._db.get_models_by_voice(voice_id):
                if m.engine == "qwen3":
                    self._db.update_model_loaded(m.id, True)
            logger.info(f"Qwen3 缓存已加载到内存: {voice_id}")
            return True
        except Exception as e:
            logger.error(f"Qwen3 load 异常 {voice_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # GPT-SoVITS 实现 (权重路径登记)
    # ------------------------------------------------------------------

    def _prepare_gpt_sovits(self, voice_id: str, reference_audio: Optional[str]) -> bool:
        """GPT-SoVITS: 从 profile.metadata 读权重路径, 登记 voice_models"""
        profile = self._db.get_profile_by_id(voice_id)
        meta = (profile.metadata if profile else {}) or {}
        sovits = meta.get("sovits_model") or reference_audio
        gpt = meta.get("gpt_model")
        if not sovits and not gpt:
            logger.warning(f"GPT-SoVITS 未配置权重路径: {voice_id}")
            return False
        self._upsert_model_record(
            voice_id, "gpt_sovits",
            model_path=sovits,
            cache_path=gpt,
        )
        logger.info(f"GPT-SoVITS 权重已登记: {voice_id} (sovits={sovits}, gpt={gpt})")
        return True

    def _load_gpt_sovits(self, voice_id: str) -> bool:
        """GPT-SoVITS: 热切换权重 (若适配器可用)"""
        if self._gpt is None:
            logger.debug(f"无 GPT-SoVITS 适配器, 跳过 load: {voice_id}")
            return True  # 仅登记, 不切换
        profile = self._db.get_profile_by_id(voice_id)
        meta = (profile.metadata if profile else {}) or {}
        sovits = meta.get("sovits_model")
        gpt = meta.get("gpt_model")
        models = self._db.get_models_by_voice(voice_id)
        for m in models:
            if m.engine == "gpt_sovits":
                sovits = sovits or m.model_path
                gpt = gpt or m.cache_path
        if not sovits or not gpt:
            logger.warning(f"GPT-SoVITS 权重路径缺失: {voice_id}")
            return False
        try:
            self._gpt.change_weights(sovits_model=sovits, gpt_model=gpt)
            for m in models:
                if m.engine == "gpt_sovits":
                    self._db.update_model_loaded(m.id, True)
            logger.info(f"GPT-SoVITS 权重已切换: {voice_id}")
            return True
        except Exception as e:
            logger.error(f"GPT-SoVITS load 异常 {voice_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # voice_models 记录管理
    # ------------------------------------------------------------------

    def _upsert_model_record(
        self,
        voice_id: str,
        engine: str,
        model_path: Optional[str] = None,
        cache_path: Optional[str] = None,
        hash: Optional[str] = None,
    ) -> None:
        """插入或更新 voice_models 记录 (同引擎同 voice_id 覆盖)"""
        existing = [m for m in self._db.get_models_by_voice(voice_id) if m.engine == engine]
        if existing:
            # 更新首条
            m = existing[0]
            with self._db._lock:
                assert self._db._conn is not None
                self._db._conn.execute(
                    "UPDATE voice_models SET model_path=?, cache_path=?, hash=? WHERE id=?;",
                    (model_path, cache_path, hash, m.id),
                )
        else:
            self._db.insert_model(VoiceModel(
                voice_id=voice_id, engine=engine,
                model_path=model_path, cache_path=cache_path, hash=hash, loaded=False,
            ))

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """缓存统计"""
        disk_voices = [
            d.name for d in self._cache_root.iterdir()
            if d.is_dir() and (d / "metadata.json").is_file()
        ]
        return {
            "cache_root": str(self._cache_root),
            "disk_voices": disk_voices,
            "disk_count": len(disk_voices),
            "has_qwen3_adapter": self._qwen3 is not None,
            "has_gpt_sovits_adapter": self._gpt is not None,
        }
