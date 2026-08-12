"""
YHLZ 2.0 Qwen3-TTS 本地引擎
基于 Qwen3-TTS-12Hz-0.6B-Base 模型，本地推理，零网络延迟

M0.1 变更: 单实例 prompt 缓存 → 多 voice_id 缓存 (Dict[str, Cache])
- voice_id 可选参数, 旧调用 tts.synthesize(text) 行为不变
- 缓存结构: {voice_id: {prompt, embedding, metadata}}
- 只提供底层能力, 不绑定任何 Voice Identity 模块
"""
import logging
import os
import time
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, AsyncGenerator, Dict, Any

from backend.tts.base import BaseTTSEngine

logger = logging.getLogger(__name__)

# 模型路径
MODEL_PATH = os.environ.get(
    "QWEN3_TTS_MODEL_PATH",
    r"D:\HF_Models\Qwen\Qwen3-TTS-12Hz-0___6B-Base"
)

# 默认参考音频
DEFAULT_REF_AUDIO = os.environ.get(
    "QWEN3_TTS_REF_AUDIO",
    r"d:\YHLZ2.0\index-tts\examples\voice_01.wav"
)

# 默认 voice_id (未显式指定时使用)
DEFAULT_VOICE_ID = "default"


class _RestoredPrompt:
    """从磁盘恢复时的轻量 prompt 包装 (当完整 prompt 对象不可还原时使用)

    暴露 x_vector 属性, 供 Qwen3TTSEngine._resolve_prompt / generate_voice_clone 使用。
    真实场景下若 generate_voice_clone 需要完整 prompt 对象, 应优先还原 prompt.pt。
    """
    def __init__(self, x_vector, voice_id: str = "restored"):
        self.x_vector = x_vector
        self.voice_id = voice_id


class Qwen3TTSEngine(BaseTTSEngine):
    """Qwen3-TTS 本地引擎 (0.6B Base, 语音克隆, 多声音缓存)"""

    name = "qwen3-tts"

    def __init__(self):
        super().__init__()
        self._model = None
        # 多声音缓存: voice_id -> {prompt, embedding, metadata}
        self._voice_caches: Dict[str, Dict[str, Any]] = {}
        self._model_path = MODEL_PATH
        self._ref_audio_path = DEFAULT_REF_AUDIO
        self._sample_rate = 24000  # 模型原生采样率

    @property
    def _prompt_cache(self) -> Optional[Any]:
        """[兼容] 旧接口只读别名: 返回默认 voice 的 prompt (无则 None)"""
        cache = self._voice_caches.get(DEFAULT_VOICE_ID)
        return cache["prompt"] if cache else None

    def load(self) -> bool:
        """加载 Qwen3-TTS 模型"""
        if self.is_loaded:
            return True

        try:
            import torch
            from qwen_tts import Qwen3TTSModel

            if not os.path.isdir(self._model_path):
                logger.error(f"Qwen3-TTS 模型路径不存在: {self._model_path}")
                return False

            logger.info(f"正在加载 Qwen3-TTS 模型: {self._model_path}")
            t0 = time.time()

            self._model = Qwen3TTSModel.from_pretrained(
                self._model_path,
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )

            elapsed = time.time() - t0
            logger.info(f"Qwen3-TTS 模型加载完成, 耗时 {elapsed:.1f}s")

            # 预热: 创建默认语音克隆提示缓存
            self._warmup_prompt()

            self.is_loaded = True
            return True

        except ImportError as e:
            logger.error(f"Qwen3-TTS 依赖缺失: {e}")
            return False
        except Exception as e:
            logger.error(f"Qwen3-TTS 加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _warmup_prompt(self):
        """预热: 从默认参考音频提取说话人特征并缓存到 DEFAULT_VOICE_ID"""
        if not os.path.isfile(self._ref_audio_path):
            logger.warning(f"参考音频不存在: {self._ref_audio_path}, 跳过预热")
            return
        if DEFAULT_VOICE_ID in self._voice_caches:
            logger.info("默认 voice 缓存已存在, 跳过预热")
            return

        self.load_voice_cache(DEFAULT_VOICE_ID, ref_audio=self._ref_audio_path)

    # ------------------------------------------------------------------
    # 多声音缓存管理接口 (底层能力, 不绑定 Voice Identity)
    # ------------------------------------------------------------------

    def load_voice_cache(
        self,
        voice_id: str = DEFAULT_VOICE_ID,
        ref_audio: Optional[str] = None,
        x_vector_only_mode: bool = True,
    ) -> Optional[dict]:
        """提取指定 voice_id 的说话人特征并写入缓存

        返回 {prompt, embedding, metadata}; 失败返回 None。
        同一模型实例可持有多个 voice_id 缓存, 互不覆盖。
        """
        if not self.is_loaded or self._model is None:
            logger.warning("Qwen3-TTS 未加载, 无法提取 voice cache")
            return None

        ref_audio = ref_audio or self._ref_audio_path
        if not os.path.isfile(ref_audio):
            logger.error(f"参考音频不存在: {ref_audio}")
            return None

        try:
            logger.info(f"正在提取说话人特征 voice_id={voice_id}: {ref_audio}")
            t0 = time.time()

            prompt = self._model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                x_vector_only_mode=x_vector_only_mode,  # 仅用说话人向量，无需参考文本
            )

            # x_vector_only_mode=True 时 prompt 本身即 x-vector; 若模型暴露 x_vector 字段则优先
            x_vector = getattr(prompt, "x_vector", None)
            entry = {
                "prompt": prompt,
                "embedding": x_vector if x_vector is not None else prompt,
                "metadata": {
                    "voice_id": voice_id,
                    "ref_audio": ref_audio,
                    "x_vector_only_mode": x_vector_only_mode,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            }
            self._voice_caches[voice_id] = entry
            logger.info(
                f"说话人特征缓存完成 voice_id={voice_id}, 耗时 {time.time() - t0:.1f}s"
            )
            return entry

        except Exception as e:
            logger.error(f"voice cache 提取失败 voice_id={voice_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_voice_cache(self, voice_id: str = DEFAULT_VOICE_ID) -> Optional[dict]:
        """获取指定 voice_id 的说话人缓存 {prompt, embedding, metadata}"""
        return self._voice_caches.get(voice_id)

    def clear_voice_cache(self, voice_id: Optional[str] = None) -> int:
        """清空缓存; voice_id=None 时清空全部, 返回清理数量"""
        if voice_id is None:
            n = len(self._voice_caches)
            self._voice_caches.clear()
            logger.info(f"voice 缓存已全部清空 ({n} 个)")
            return n
        removed = self._voice_caches.pop(voice_id, None)
        if removed is not None:
            logger.info(f"voice 缓存已清空: {voice_id}")
            return 1
        return 0

    def get_voice_cache_stats(self) -> dict:
        """缓存统计: 数量 / voice 列表 / 是否含默认 voice"""
        return {
            "count": len(self._voice_caches),
            "voice_ids": list(self._voice_caches.keys()),
            "has_default": DEFAULT_VOICE_ID in self._voice_caches,
        }

    # ------------------------------------------------------------------
    # M0.6: 缓存持久化 (save/load to disk)
    # ------------------------------------------------------------------
    # 解决问题: 原缓存仅在内存, 程序重启即丢失, 需重新提取 (耗时数秒 + 占显存)
    # 持久化结构 (dir/<voice_id>/):
    #   metadata.json   - voice_id / ref_audio / 时间戳 / x_vector_only_mode
    #   embedding.pt    - x_vector (speaker embedding, torch.save, 可 numpy/tensor)
    #   prompt.pt       - 完整 prompt 对象 (best-effort, 失败则仅存 embedding)
    # 加载时: prompt.pt 可还原则用之; 否则用 embedding 构造轻量 prompt (暴露 x_vector)

    def save_voice_cache_to_disk(
        self,
        voice_id: str,
        dir_path: str,
    ) -> Optional[str]:
        """保存指定 voice_id 缓存到磁盘; 返回保存目录路径, 失败返回 None"""
        import json
        cache = self._voice_caches.get(voice_id)
        if cache is None:
            logger.warning(f"voice_id={voice_id} 无内存缓存, 无法保存")
            return None

        out_dir = Path(dir_path) / voice_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1) metadata.json
        meta = dict(cache.get("metadata", {}))
        meta["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        meta["voice_id"] = voice_id
        with open(out_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # 2) embedding.pt (x_vector, 持久化核心)
        embedding = cache.get("embedding")
        try:
            import torch
            torch.save(embedding, out_dir / "embedding.pt")
        except Exception as e:
            logger.warning(f"保存 embedding 失败 voice_id={voice_id}: {e}")
            # 回退: numpy 存 .npy
            try:
                import numpy as np
                if isinstance(embedding, np.ndarray):
                    np.save(out_dir / "embedding.npy", embedding)
            except Exception:
                pass

        # 3) prompt.pt (完整对象, best-effort)
        prompt = cache.get("prompt")
        prompt_saved = False
        try:
            import torch
            torch.save(prompt, out_dir / "prompt.pt")
            prompt_saved = True
        except Exception as e:
            logger.debug(f"完整 prompt 对象不可序列化 voice_id={voice_id}: {e} (仅存 embedding)")

        logger.info(
            f"voice 缓存已保存 voice_id={voice_id} → {out_dir} "
            f"(embedding={'pt' if (out_dir / 'embedding.pt').exists() else 'npy/fallback'}, "
            f"prompt={'full' if prompt_saved else 'none'})"
        )
        return str(out_dir)

    def load_voice_cache_from_disk(
        self,
        voice_id: str,
        dir_path: str,
    ) -> Optional[dict]:
        """从磁盘恢复指定 voice_id 缓存到内存; 返回缓存 entry, 失败返回 None"""
        import json
        in_dir = Path(dir_path) / voice_id
        if not in_dir.is_dir():
            logger.warning(f"磁盘缓存目录不存在: {in_dir}")
            return None

        # 1) metadata.json
        meta_path = in_dir / "metadata.json"
        if not meta_path.is_file():
            logger.warning(f"metadata.json 缺失: {in_dir}")
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # 2) embedding (优先 .pt, 回退 .npy)
        embedding = None
        emb_pt = in_dir / "embedding.pt"
        emb_npy = in_dir / "embedding.npy"
        try:
            import torch
            if emb_pt.is_file():
                embedding = torch.load(emb_pt, map_location="cpu", weights_only=False)
        except Exception as e:
            logger.warning(f"加载 embedding.pt 失败: {e}")
        if embedding is None:
            try:
                import numpy as np
                if emb_npy.is_file():
                    embedding = np.load(emb_npy, allow_pickle=True)
            except Exception as e:
                logger.warning(f"加载 embedding.npy 失败: {e}")

        if embedding is None:
            logger.error(f"无法恢复 embedding, 放弃 voice_id={voice_id}")
            return None

        # 3) prompt (优先完整 .pt, 否则用 embedding 构造轻量 prompt)
        prompt = None
        prompt_pt = in_dir / "prompt.pt"
        try:
            import torch
            if prompt_pt.is_file():
                prompt = torch.load(prompt_pt, map_location="cpu", weights_only=False)
        except Exception as e:
            logger.debug(f"加载 prompt.pt 失败 (改用轻量重建): {e}")

        if prompt is None:
            # 轻量重建: 暴露 x_vector 属性供下游 getattr(prompt, "x_vector") 使用
            prompt = _RestoredPrompt(x_vector=embedding, voice_id=voice_id)

        entry = {
            "prompt": prompt,
            "embedding": embedding,
            "metadata": metadata,
        }
        self._voice_caches[voice_id] = entry
        logger.info(
            f"voice 缓存已从磁盘恢复 voice_id={voice_id} ← {in_dir} "
            f"(prompt={'full' if not isinstance(prompt, _RestoredPrompt) else 'restored-light'})"
        )
        return entry

    def _resolve_prompt(self, voice_id: Optional[str]) -> Optional[Any]:
        """解析 voice_id 对应的 prompt; 缺失时回退默认 voice, 均无则 None"""
        requested = voice_id or DEFAULT_VOICE_ID
        cache = self._voice_caches.get(requested)
        if cache is not None:
            return cache["prompt"]
        if requested != DEFAULT_VOICE_ID:
            logger.warning(f"voice_id={requested} 无缓存, 回退默认 voice")
            cache = self._voice_caches.get(DEFAULT_VOICE_ID)
            if cache is not None:
                return cache["prompt"]
        logger.warning("voice 缓存为空, 请先调用 load_voice_cache()")
        return None

    def unload(self) -> None:
        """卸载模型，释放显存"""
        if self._model is not None:
            del self._model
            self._model = None
        self._voice_caches.clear()
        self.is_loaded = False

        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Qwen3-TTS 引擎已卸载，显存已释放")

    def release_gpu(self) -> None:
        self.unload()

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        rate: str = "+0%",
        voice_id: Optional[str] = None,
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        """文本转语音

        voice_id: 指定使用哪个声音的缓存 (M0.1 新增)
        - voice_id=None 时沿用 voice 参数 (默认 "default"), 旧接口完全兼容
        - voice_id 显式传入时优先于 voice
        - 指定 voice 无缓存时回退默认 voice
        """
        if not self.is_loaded or self._model is None:
            logger.warning("Qwen3-TTS 未加载")
            return self._get_mock_audio(text)

        if not text or not text.strip():
            return np.zeros(1000, dtype=np.float32), self._sample_rate

        resolved_voice_id = voice_id or voice or DEFAULT_VOICE_ID
        prompt = self._resolve_prompt(resolved_voice_id)
        if prompt is None:
            return self._get_mock_audio(text)

        try:
            logger.info(f"[Qwen3-TTS] 合成 voice_id={resolved_voice_id}: {text[:50]}...")
            t0 = time.time()

            wavs, sr = self._model.generate_voice_clone(
                text=text,
                language="chinese",
                voice_clone_prompt=prompt,
            )

            audio = wavs[0].astype(np.float32)
            elapsed = time.time() - t0
            logger.info(f"[Qwen3-TTS] 合成完成: {len(audio)} samples, {sr}Hz, 耗时 {elapsed:.1f}s")

            return audio, sr

        except Exception as e:
            logger.error(f"Qwen3-TTS 合成失败: {e}")
            import traceback
            traceback.print_exc()
            return self._get_mock_audio(text)

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "default",
        voice_id: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """流式合成（Qwen3-TTS 非流式，返回整段模拟流式）"""
        audio, sr = self.synthesize(text, voice=voice, voice_id=voice_id)
        yield audio, sr

    def _get_mock_audio(self, text: str) -> Tuple[np.ndarray, int]:
        """生成静默音频（兜底）"""
        duration = max(0.5, len(text) * 0.05)
        sample_rate = self._sample_rate
        n_samples = int(duration * sample_rate)
        audio = np.zeros(n_samples, dtype=np.float32)
        return audio, sample_rate


# 全局实例
qwen3_tts_engine = Qwen3TTSEngine()
