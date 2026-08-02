"""
Live2D 原生渲染模块 — 基于 live2d-py 0.7 + QOpenGLWidget
参考: NachoBot renderer.py (pygame+OpenGL+live2d.v3 透明桌宠窗)
特性:
  - 口型同步: 三正弦叠加 (0.4sin(2.5φ)+0.3sin(1.8φ)+0.3sin(3.3φ))
  - 表情系统: 基线三快照 + 差分淡出
  - 视线状态机: 参数补间 ease-out quad + GAZE跟随
  - 参数保护: LIPSYNC_OVERRIDE_THRESHOLD 防止动作覆盖口型
"""

import sys
import os
import math
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from collections import deque

import live2d.v3 as l2d

logger = logging.getLogger('YHLZ.Live2DRenderer')

# ── 常量 ──────────────────────────────────────────────
LIPSYNC_PARAMS = [
    'ParamMouthOpenY', 'ParamMouthForm',
    'ParamA', 'ParamI', 'ParamU', 'ParamE', 'ParamO'
]
LIPSYNC_OVERRIDE_THRESHOLD = 0.001  # 说话时强制覆盖嘴部参数
FPS = 60
FRAME_MS = 1000 / FPS

# 表情映射 (emotion_id → expression_id)
EMOTION_EXPR_MAP = {
    'happy':     'f01',
    'sad':       'f02',
    'angry':     'f03',
    'surprised': 'f04',
    'neutral':   'f01',  # 中性默认开心
}

# 视线状态 → 屏幕坐标映射
GAZE_STATE_MAP = {
    'idle':       (0.0, 0.0),     # 正中
    'viewing':    (-0.5, -0.2),   # 看聊天区
    'thinking':   (0.3, 0.5),     # 看气泡
    'replying':   (0.0, 0.0),     # 直视
    'finished':   (0.0, 0.0),     # 回正
}


# ══════════════════════════════════════════════════════════
# 口型同步器: 三正弦叠加
# ══════════════════════════════════════════════════════════

class MouthSync:
    """三正弦口型同步: 0.4*sin(2.5φ) + 0.3*sin(1.8φ) + 0.3*sin(3.3φ)"""

    def __init__(self):
        self._phase = 0.0
        self._is_speaking = False
        self._mouth_value = 0.0
        self._mouth_target = 0.0

    @property
    def value(self) -> float:
        return self._mouth_value

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def set_speaking(self, speaking: bool):
        self._is_speaking = speaking
        if not speaking:
            self._mouth_target = 0.0

    def set_mouth_open(self, rms_value: float):
        """设置音频RMS值 (0.0-1.0), 驱动口型"""
        self._mouth_target = min(rms_value * 8.0, 1.0)  # 放大8倍
        if rms_value > LIPSYNC_OVERRIDE_THRESHOLD:
            self._is_speaking = True

    def update(self, dt: float) -> float:
        """更新口型, 返回当前 mouth_open 值"""
        if self._is_speaking:
            self._phase += 0.12
            # 三正弦叠加
            synth = (
                0.4 * math.sin(2.5 * self._phase) +
                0.3 * math.sin(1.8 * self._phase) +
                0.3 * math.sin(3.3 * self._phase)
            )
            # 归一化到 [0, 1]
            self._mouth_value = (synth + 1.0) / 2.0
            # 混合 RMS 驱动值
            self._mouth_value = 0.7 * self._mouth_value + 0.3 * self._mouth_target
        else:
            # 平滑归零
            self._mouth_value += (0.0 - self._mouth_value) * min(dt * 8.0, 1.0)
            if self._mouth_value < 0.001:
                self._mouth_value = 0.0

        return self._mouth_value


# ══════════════════════════════════════════════════════════
# 参数补间: ease-out quad
# ══════════════════════════════════════════════════════════

class ParamTween:
    """单个参数补间"""

    def __init__(self, param_id: str, start_val: float, end_val: float, duration: float):
        self.param_id = param_id
        self.start_val = start_val
        self.end_val = end_val
        self.duration = duration
        self.elapsed = 0.0
        self.finished = False

    def update(self, dt: float) -> float:
        self.elapsed += dt
        t = min(self.elapsed / self.duration, 1.0)
        if t >= 1.0:
            self.finished = True
            return self.end_val
        # ease-out quad: 1 - (1-t)^2
        eased = 1.0 - (1.0 - t) * (1.0 - t)
        return self.start_val + (self.end_val - self.start_val) * eased


# ══════════════════════════════════════════════════════════
# 表情管理器: 基线三快照 + 差分淡出
# ══════════════════════════════════════════════════════════

class ExpressionManager:
    """表情管理: 保存基线快照, 切换时差分淡出"""

    def __init__(self):
        self._current_emotion = 'neutral'
        self._target_emotion = 'neutral'
        self._fade_progress = 1.0  # 0→1
        self._fade_duration = 0.3  # 秒
        # 基线快照: {emotion: {param_id: value}}
        self._baselines: Dict[str, Dict[str, float]] = {}
        self._param_ids: List[str] = []

    def set_param_ids(self, param_ids: List[str]):
        self._param_ids = param_ids

    def snapshot_baseline(self, model, emotion: str):
        """保存当前参数为某情绪的基线"""
        baseline = {}
        for pid in self._param_ids:
            try:
                baseline[pid] = model.GetParameterValue(pid)
            except Exception:
                baseline[pid] = 0.0
        self._baselines[emotion] = baseline

    def set_emotion(self, emotion: str):
        """切换目标情绪"""
        if emotion == self._current_emotion:
            return
        self._target_emotion = emotion
        self._fade_progress = 0.0

    def update(self, dt: float, model) -> bool:
        """更新差分淡出, 返回是否正在淡出中"""
        if self._fade_progress >= 1.0:
            return False

        self._fade_progress += dt / self._fade_duration
        if self._fade_progress >= 1.0:
            self._fade_progress = 1.0
            self._current_emotion = self._target_emotion

        # 获取当前和目标基线
        cur_baseline = self._baselines.get(self._current_emotion, {})
        tgt_baseline = self._baselines.get(self._target_emotion, {})

        # 差分混合
        t = self._fade_progress
        for pid in self._param_ids:
            if pid in LIPSYNC_PARAMS:
                continue  # 口型参数不参与表情淡出
            cur = cur_baseline.get(pid, 0.0)
            tgt = tgt_baseline.get(pid, 0.0)
            if cur != tgt:
                val = cur + (tgt - cur) * t
                try:
                    model.SetParameterValue(pid, val, 1.0)
                except Exception:
                    pass

        return True

    @property
    def current_emotion(self) -> str:
        return self._target_emotion


# ══════════════════════════════════════════════════════════
# 视线管理器: 参数补间 + GAZE
# ══════════════════════════════════════════════════════════

class GazeManager:
    """视线管理: 自动/手动凝视, 参数补间"""

    GAZE_SPEED = 0.01  # lerp 速度

    def __init__(self):
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._target_x = 0.0
        self._target_y = 0.0
        self._active_tweens: List[ParamTween] = []
        self._cooldown = 0.0  # 交互冷却
        self._auto_gaze = True

    def set_gaze_state(self, state: str):
        """设置视线状态"""
        if state in GAZE_STATE_MAP:
            self._target_x, self._target_y = GAZE_STATE_MAP[state]

    def set_gaze_target(self, x: float, y: float):
        """设置凝视目标 (屏幕坐标归一化到 -1~1)"""
        self._target_x = x
        self._target_y = y
        self._auto_gaze = False

    def update(self, dt: float, model):
        """更新视线"""
        # 交互冷却
        if self._cooldown > 0:
            self._cooldown -= dt
        else:
            self._auto_gaze = True

        # Lerp 平滑
        self._gaze_x += (self._target_x - self._gaze_x) * self.GAZE_SPEED
        self._gaze_y += (self._target_y - self._gaze_y) * self.GAZE_SPEED

        # 应用 Drag
        if abs(self._gaze_x) > 0.001 or abs(self._gaze_y) > 0.001:
            try:
                model.Drag(self._gaze_x, self._gaze_y)
            except Exception:
                pass

        # 更新参数补间
        for tween in self._active_tweens[:]:
            tween.update(dt)
            if tween.finished:
                self._active_tweens.remove(tween)

    def add_tween(self, param_id: str, start_val: float, end_val: float, duration: float = 0.5):
        """添加参数补间"""
        self._active_tweens.append(ParamTween(param_id, start_val, end_val, duration))
        self._cooldown = 1.0  # 交互后冷却1秒


# ══════════════════════════════════════════════════════════
# Live2D 渲染器核心
# ══════════════════════════════════════════════════════════

class Live2DRenderer:
    """Live2D 模型渲染器 — 封装 live2d-py, 提供 OpenGL 渲染循环"""

    def __init__(self):
        self._model: Optional[l2d.LAppModel] = None
        self._model_path: Optional[str] = None
        self._loaded = False
        self._width = 400
        self._height = 500
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0

        # 子系统
        self.mouth = MouthSync()
        self.expression = ExpressionManager()
        self.gaze = GazeManager()

        # 帧计时
        self._last_frame = time.perf_counter()

    @property
    def model(self) -> Optional[l2d.LAppModel]:
        return self._model

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def init_gl(self):
        """初始化 OpenGL (在 QOpenGLWidget.initializeGL 中调用)"""
        l2d.init()
        l2d.glInit()  # 初始化 OpenGL 着色器
        logger.info("Live2D OpenGL 初始化完成")

    def load_model(self, model_dir: str) -> bool:
        """加载 Live2D 模型 (model_dir 为包含 .model3.json 的目录)"""
        self._model_path = model_dir

        # 查找 .model3.json 文件
        model_dir = Path(model_dir)
        json_files = list(model_dir.glob('*.model3.json'))
        if not json_files:
            logger.error(f"未找到 .model3.json 文件: {model_dir}")
            return False

        json_path = str(json_files[0])
        json_name = json_files[0].name  # 仅文件名

        try:
            # 加载模型 (需先 chdir 到模型目录, SDK 缓存 CWD)
            old_cwd = os.getcwd()
            os.chdir(str(model_dir))

            logger.info(f"  CWD → {os.getcwd()}")
            # 使用底层 Model 类直接加载
            self._model = l2d.LAppModel()
            logger.info(f"  LAppModel 创建完成")
            self._model.LoadModelJson(json_name)
            logger.info(f"  LoadModelJson 完成")
            self._model.Resize(self._width, self._height)
            logger.info(f"  Resize 完成")

            os.chdir(old_cwd)

            # 启用自动眨眼和呼吸
            self._model.SetAutoBlinkEnable(True)
            self._model.SetAutoBreathEnable(True)

            # 初始化表情管理器
            param_ids = self._model.GetParamIds()
            self.expression.set_param_ids(param_ids)

            self._loaded = True
            logger.info(f"Live2D 模型加载成功: {model_dir.name}")

            # 保存默认表情基线
            self._save_default_baselines()

            return True

        except Exception as e:
            logger.error(f"Live2D 模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _save_default_baselines(self):
        """保存默认表情基线快照"""
        for emotion in ['neutral', 'happy', 'sad', 'angry', 'surprised']:
            self.expression.snapshot_baseline(self._model, emotion)

    def resize(self, w: int, h: int):
        """调整画布大小"""
        self._width = w
        self._height = h
        if self._model:
            self._model.Resize(w, h)

    def set_scale(self, sx: float, sy: float):
        self._scale = (sx + sy) / 2.0
        if self._model:
            self._model.SetScale(sx, sy)

    def set_offset(self, x: float, y: float):
        self._offset_x = x
        self._offset_y = y
        if self._model:
            self._model.SetOffset(x, y)

    def render_frame(self):
        """渲染一帧 (在 QOpenGLWidget.paintGL 中调用)"""
        if not self._loaded or self._model is None:
            return

        now = time.perf_counter()
        dt = now - self._last_frame
        self._last_frame = now

        # 1. 更新口型
        mouth_val = self.mouth.update(dt)
        if self._model:
            for pid in LIPSYNC_PARAMS:
                try:
                    self._model.SetParameterValue(pid, mouth_val, 1.0)
                except Exception:
                    pass

        # 2. 更新表情差分淡出
        self.expression.update(dt, self._model)

        # 3. 更新视线
        self.gaze.update(dt, self._model)

        # 4. 更新模型物理和动作
        self._model.Update()

        # 5. 绘制
        self._model.Draw()

    def set_emotion(self, emotion: str):
        """设置表情"""
        self.expression.set_emotion(emotion)
        # 同时尝试通过 SetExpression 直接设置
        if self._model:
            expr_id = EMOTION_EXPR_MAP.get(emotion)
            if expr_id:
                try:
                    self._model.SetExpression(expr_id)
                except Exception:
                    pass

    def set_mouth_open(self, value: float):
        """设置口型张开度 (0.0-1.0)"""
        self.mouth.set_mouth_open(value)

    def set_speaking(self, speaking: bool):
        """设置说话状态"""
        self.mouth.set_speaking(speaking)

    def start_motion(self, group: str, no: int, priority: int = 3):
        """播放动作"""
        if self._model:
            try:
                self._model.StartMotion(group, no, priority)
            except Exception as e:
                logger.debug(f"动作播放失败: {e}")

    def start_random_motion(self):
        """随机播放动作"""
        if self._model:
            try:
                self._model.StartRandomMotion(priority=3)
            except Exception:
                pass

    def set_gaze_target(self, x: float, y: float):
        """设置凝视目标"""
        self.gaze.set_gaze_target(x, y)

    def set_gaze_state(self, state: str):
        """设置视线状态"""
        self.gaze.set_gaze_state(state)

    def hit_test(self, x: float, y: float) -> bool:
        """点击测试 (相对坐标)"""
        if self._model:
            try:
                return self._model.HitTest(x, y)
            except Exception:
                return False
        return False

    def get_expression_ids(self) -> List[str]:
        if self._model:
            return self._model.GetExpressionIds()
        return []

    def get_motion_groups(self) -> List[str]:
        if self._model:
            return self._model.GetMotionGroups()
        return []

    def cleanup(self):
        """清理资源"""
        if self._model:
            try:
                self._model = None
            except Exception:
                pass
        try:
            l2d.glRelease()
        except Exception:
            pass
        try:
            l2d.dispose()
        except Exception:
            pass
        self._loaded = False
        logger.info("Live2D 渲染器已清理")