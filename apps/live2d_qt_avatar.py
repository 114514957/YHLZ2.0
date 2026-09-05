"""
YHLZ 2.0 Live2D 桌面虚拟角色（纯 PyQt5 + QOpenGLWidget + Live2D）
- 无边框透明窗口：QOpenGLWidget + win32gui LWA_COLORKEY 黑色透传
- 原生 Live2D 渲染：live2d.v3 + QOpenGLWidget OpenGL 上下文
- 右键 QWidget 气泡菜单（独立弹出）
- QWebSocket 连接后端实时同步
- 鼠标滚轮缩放，键盘 +/- 缩放，0 重置缩放，R 重置位置，F 显示帧率，Esc 退出
"""

import sys
import os
import json
import time
import math
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Live2D.Qt")

# ==================== 依赖检查 ====================

try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
        QOpenGLWidget, QTextEdit, QLineEdit, QLabel
    )
    from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject, QUrl, QThread
    from PyQt5.QtGui import QFont, QSurfaceFormat, QTextCursor
    from PyQt5.QtWebSockets import QWebSocket
except ImportError as e:
    logger.error(f"PyQt5 未安装或缺少模块: {e}")
    logger.error("请执行: pip install PyQt5 PyQtWebSockets")
    sys.exit(1)

try:
    import win32gui
    import win32con
    import win32api
except ImportError:
    logger.error("pywin32 未安装，请执行: pip install pywin32")
    sys.exit(1)

try:
    from OpenGL import GL as gl
except ImportError:
    logger.error("PyOpenGL 未安装，请执行: pip install PyOpenGL")
    sys.exit(1)

try:
    import pyaudio
except ImportError:
    logger.warning("pyaudio 未安装，语音聊天将仅支持文本模式")
    pyaudio = None

# ==================== 配置 ====================

MODEL_DIRS = [
    Path(__file__).parent / "assets" / "live2d" / "hiyori_vts",
    Path(__file__).parent / "assets" / "live2d" / "akari_vts",
    Path(__file__).parent / "assets" / "live2d" / "hijiki_vts",
    Path(__file__).parent / "assets" / "live2d" / "tororo_vts",
    Path(__file__).parent / "assets" / "live2d" / "wanko_vts",
    Path(__file__).parent / "assets" / "live2d" / "haru",
    Path(__file__).parent / "assets" / "live2d" / "mao",
]

WINDOW_W = 400
WINDOW_H = 560
FPS = 60
SCALE_MIN = 0.3
SCALE_MAX = 3.0
SCALE_STEP = 0.1
WS_URL = "ws://localhost:8000/ws/avatar"
WEBUI_URL = "http://127.0.0.1:5000"


def find_model_dir():
    for d in MODEL_DIRS:
        if d.exists():
            json_files = list(d.glob("*.model3.json"))
            if json_files:
                logger.info(f"找到模型: {d / json_files[0].name}")
                return d, json_files[0].name
    return None, None


# ==================== WebSocket 客户端 ====================

class QtWSClient(QObject):
    mouth_updated = pyqtSignal(float)
    speech_started = pyqtSignal()
    speech_ended = pyqtSignal()
    emotion_changed = pyqtSignal(str, float)
    connected = pyqtSignal()
    disconnected = pyqtSignal()

    def __init__(self, url=WS_URL, parent=None):
        super().__init__(parent)
        self.url = url
        self.socket = None
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._do_connect)
        self._reconnect_delay = 1
        self._max_delay = 30

    def start(self):
        self._do_connect()

    def stop(self):
        self._reconnect_timer.stop()
        if self.socket:
            self.socket.close()

    def _do_connect(self):
        if self.socket:
            self.socket.deleteLater()
        self.socket = QWebSocket()
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.textMessageReceived.connect(self._on_message)
        try:
            self.socket.errorOccurred.connect(self._on_error)
        except AttributeError:
            self.socket.error.connect(self._on_error)
        self.socket.open(QUrl(self.url))

    def _on_connected(self):
        logger.info("Live2D 同步服务已连接")
        self._reconnect_delay = 1
        self.connected.emit()

    def _on_disconnected(self):
        logger.info("WebSocket 断开，将重连...")
        self.disconnected.emit()
        self._schedule_reconnect()

    def _on_error(self, error=None):
        logger.error(f"WebSocket 错误: {error}")
        self._schedule_reconnect()

    def _schedule_reconnect(self):
        delay_ms = self._reconnect_delay * 1000
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_delay)
        self._reconnect_timer.start(delay_ms)

    def _on_message(self, message):
        try:
            msg = json.loads(message)
            msg_type = msg.get("type", "")
            data = msg.get("data", {})
            if msg_type == "mouth_sync":
                self.mouth_updated.emit(data.get("value", 0.0))
            elif msg_type == "speech_start":
                self.speech_started.emit()
            elif msg_type == "speech_end":
                self.speech_ended.emit()
            elif msg_type == "emotion_change":
                self.emotion_changed.emit(data.get("emotion", "neutral"), data.get("intensity", 1.0))
        except Exception as e:
            logger.debug(f"消息处理: {e}")


# ==================== Live2D OpenGL 渲染控件 ====================

class Live2DGLWidget(QOpenGLWidget):
    """使用 QOpenGLWidget 提供 OpenGL 上下文，渲染 Live2D 模型"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._loaded = False

        self._win_w = WINDOW_W
        self._win_h = WINDOW_H
        self._scale = 1.0
        self._canvas_w = 1.0
        self._canvas_h = 1.0

        # 口型
        self._mouth_value = 0.0
        self._mouth_target = 0.0
        self._mouth_phase = 0.0
        self._is_speaking = False

        # 视线
        self._gaze_x = 0.5
        self._gaze_y = 0.5
        self._gaze_target_x = 0.5
        self._gaze_target_y = 0.5

        # 表情
        self._current_emotion = "neutral"
        self._emotion_intensity = 1.0

        # 防止重复初始化
        self._gl_initialized = False

    def initializeGL(self):
        """OpenGL 初始化（QOpenGLWidget 回调）"""
        if self._gl_initialized:
            return
        self._gl_initialized = True

        logger.info("QOpenGLWidget OpenGL 上下文就绪，初始化 Live2D...")

        import live2d.v3 as l2d
        l2d.init()
        l2d.glInit()
        logger.info("Live2D OpenGL 初始化完成")

        model_dir, model_json = find_model_dir()
        if not model_dir:
            logger.error("未找到 Live2D 模型！")
            return

        self._model = l2d.LAppModel()
        self._model.SetAutoBreathEnable(True)
        self._model.SetAutoBlinkEnable(True)

        model_json_path = str(model_dir / model_json)
        try:
            logger.info(f"加载模型: {model_json_path}")
            self._model.LoadModelJson(model_json_path)
            self._model.Resize(self._win_w, self._win_h)

            self._canvas_w, self._canvas_h = self._model.GetCanvasSize()
            self._fit_scale()
            self._loaded = True
            logger.info(f"Live2D 模型加载成功 (canvas: {self._canvas_w:.1f}x{self._canvas_h:.1f}, scale: {self._scale:.2f}x)")
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            import traceback
            traceback.print_exc()

    def resizeGL(self, w, h):
        self._win_w = w
        self._win_h = h
        if self._model and self._loaded:
            self._model.Resize(w, h)

    def paintGL(self):
        """渲染一帧（QOpenGLWidget 回调）"""
        import live2d.v3 as l2d

        # 黑色透传：RGB(0,0,0) 将被 LWA_COLORKEY 变为透明
        l2d.clearBuffer(0.0, 0.0, 0.0, 0.0)

        if self._model and self._loaded:
            self._model.Update()
            self._model.Draw()

    def update_animation(self, dt):
        """更新口型和视线动画"""
        if not self._loaded or not self._model:
            return

        # 口型动画
        if self._is_speaking or self._mouth_target > 0.01:
            self._mouth_phase += dt * 12.0
            m1 = 0.4 * math.sin(2.5 * self._mouth_phase)
            m2 = 0.3 * math.sin(1.8 * self._mouth_phase + 0.5)
            m3 = 0.3 * math.sin(3.3 * self._mouth_phase + 1.2)
            t = self._mouth_target
            raw = (m1 + m2 + m3) * t
            self._mouth_value += (raw - self._mouth_value) * 0.3
        else:
            self._mouth_value += (0.0 - self._mouth_value) * 0.15

        self._mouth_value = max(0.0, min(1.0, self._mouth_value))

        # 视线平滑
        self._gaze_x += (self._gaze_target_x - self._gaze_x) * 0.08
        self._gaze_y += (self._gaze_target_y - self._gaze_y) * 0.08

        self.makeCurrent()
        self._model.SetParameterValue("ParamMouthOpenY", self._mouth_value, 0.8)
        self._model.SetParameterValue("ParamAngleX", self._gaze_x * 60 - 30, 0.5)
        self._model.SetParameterValue("ParamAngleY", self._gaze_y * 60 - 30, 0.5)
        self._model.SetParameterValue("ParamEyeBallX", self._gaze_x * 2 - 1, 0.5)
        self._model.SetParameterValue("ParamEyeBallY", self._gaze_y * 2 - 1, 0.5)
        self.doneCurrent()

    def _fit_scale(self):
        if self._canvas_h <= 0:
            return
        model_aspect = self._canvas_w / self._canvas_h
        if model_aspect > (self._win_w / self._win_h):
            self._scale = self._win_w / self._canvas_w
        else:
            self._scale = self._win_h / self._canvas_h
        if self._model:
            self.makeCurrent()
            self._model.SetScale(self._scale)
            self.doneCurrent()

    def set_scale(self, s):
        self._scale = max(SCALE_MIN, min(SCALE_MAX, s))
        if self._model:
            self.makeCurrent()
            self._model.SetScale(self._scale)
            self.doneCurrent()
        logger.info(f"缩放: {self._scale:.2f}x")

    def zoom(self, delta):
        self.set_scale(self._scale + delta * SCALE_STEP)

    def reset_scale(self):
        self._fit_scale()

    def set_mouth(self, value):
        self._mouth_target = max(0.0, min(1.0, value))

    def set_speaking(self, speaking):
        self._is_speaking = speaking
        if not speaking:
            self._mouth_target = 0.0

    def set_emotion(self, emotion, intensity=1.0):
        self._current_emotion = emotion
        self._emotion_intensity = intensity

    def set_gaze_target(self, x, y):
        self._gaze_target_x = max(0.0, min(1.0, x))
        self._gaze_target_y = max(0.0, min(1.0, y))

    def is_loaded(self):
        return self._loaded

    def cleanup(self):
        import live2d.v3 as l2d
        if self._model and self._loaded:
            self.makeCurrent()
            try:
                self._model.DestroyRenderer()
            except Exception:
                pass
            l2d.glRelease()
            l2d.dispose()
            self.doneCurrent()
            self._model = None
            self._loaded = False
        logger.info("Live2D 渲染器已清理")


# ==================== 气泡菜单 ====================

class BubbleMenu(QWidget):
    action_triggered = pyqtSignal(str)

    BUBBLE_W = 120
    BUBBLE_H = 32
    BUBBLE_GAP = 6
    RADIUS = 10

    ITEMS = [
        ("启用聊天", "enable_chat"),
        ("放大", "zoom_in"),
        ("缩小", "zoom_out"),
        ("重置缩放", "reset_scale"),
        ("重置位置", "reset_pos"),
        ("显示帧率", "toggle_fps"),
        ("退出桌宠", "quit"),
    ]

    def __init__(self, parent=None):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._buttons = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.BUBBLE_GAP)

        for text, action in self.ITEMS:
            btn = QPushButton(text, self)
            btn.setFixedSize(self.BUBBLE_W, self.BUBBLE_H)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(QFont("Microsoft YaHei", 10))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(18, 20, 28, 220);
                    color: #cccdd2;
                    border: 1px solid rgba(55, 60, 75, 180);
                    border-radius: {self.RADIUS}px;
                    padding: 4px 12px;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background: rgba(60, 100, 220, 220);
                    color: #ffffff;
                    border: 1px solid rgba(100, 140, 255, 200);
                }}
                QPushButton:pressed {{
                    background: rgba(40, 70, 180, 240);
                }}
            """)
            btn.clicked.connect(lambda checked, a=action: self._on_click(a))
            layout.addWidget(btn)
            self._buttons.append(btn)

        self.setFixedSize(
            self.BUBBLE_W + 2,
            len(self.ITEMS) * (self.BUBBLE_H + self.BUBBLE_GAP) + 2
        )

    def _on_click(self, action):
        self.action_triggered.emit(action)
        self.hide()

    def show_at(self, global_pos: QPoint):
        self.adjustSize()
        x = global_pos.x() - self.width() // 2
        y = global_pos.y() - self.height() - 8
        self.move(max(0, x), max(0, y))
        self.show()


# ==================== 聊天 SSE 工作线程 ====================

class ChatWorker(QThread):
    """后台线程：发送消息到 /api/chat/stream 并解析 SSE 流"""
    chunk_received = pyqtSignal(str)
    finished_stream = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, message, tts_enabled=False, parent=None):
        super().__init__(parent)
        self._message = message
        self._tts_enabled = tts_enabled

    def run(self):
        import requests as req
        try:
            resp = req.post(
                f"{WEBUI_URL}/api/chat/stream",
                json={
                    "message": self._message,
                    "tts_enabled": self._tts_enabled,
                    "use_tools": True
                },
                stream=True, timeout=120
            )
            if not resp.ok:
                self.error_occurred.emit(f"HTTP {resp.status_code}")
                return

            full = ""
            buffer = ""
            for chunk in resp.iter_content(chunk_size=512, decode_unicode=True):
                if not chunk:
                    continue
                buffer += chunk
                while "\n\n" in buffer:
                    line, buffer = buffer.split("\n\n", 1)
                    line = line.strip()
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            content = data.get("content", "")
                            if content:
                                full += content
                                self.chunk_received.emit(content)
                            if data.get("is_done"):
                                final = data.get("full_content", full)
                                self.finished_stream.emit(final)
                                return
                        except json.JSONDecodeError:
                            pass
            if full:
                self.finished_stream.emit(full)
            else:
                self.error_occurred.emit("后端未返回内容")
        except Exception as e:
            self.error_occurred.emit(str(e))


# ==================== 语音录制线程 ====================

class VoiceRecorder(QThread):
    """后台线程：录制麦克风音频并发送到 ASR"""
    transcription_done = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._frames = []
        self._pa = None
        self._stream = None

    def run(self):
        if pyaudio is None:
            self.error_occurred.emit("pyaudio 未安装")
            return

        CHUNK = 1024
        RATE = 16000
        SILENCE_THRESHOLD = 500
        SILENCE_LIMIT = 30
        MAX_RECORD = 10 * RATE // CHUNK  # 最多录10秒

        try:
            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )
        except Exception as e:
            self.error_occurred.emit(f"麦克风初始化失败: {e}")
            return

        self._running = True
        self._frames = []
        silence_count = 0
        has_speech = False
        self.status_changed.emit("正在录音...请说话")

        try:
            for _ in range(MAX_RECORD):
                if not self._running:
                    break
                data = self._stream.read(CHUNK, exception_on_overflow=False)
                self._frames.append(data)

                # 简单能量检测
                import struct
                samples = struct.unpack(f"<{CHUNK}h", data)
                energy = sum(abs(s) for s in samples) // CHUNK
                if energy > SILENCE_THRESHOLD:
                    has_speech = True
                    silence_count = 0
                elif has_speech:
                    silence_count += 1
                    if silence_count > SILENCE_LIMIT:
                        break

            if not self._running:
                return

            if not has_speech:
                self.status_changed.emit("未检测到语音")
                return

            self.status_changed.emit("识别中...")

            # 转为 float32 数组
            import numpy as np
            raw = b"".join(self._frames)
            samples = struct.unpack(f"<{len(raw)//2}h", raw)
            audio_float = np.array(samples, dtype=np.float32) / 32768.0

            # 发送到 ASR
            import requests as req
            resp = req.post(
                f"{WEBUI_URL}/api/asr/transcribe",
                json={"audio_data": audio_float.tolist(), "sample_rate": RATE},
                timeout=30
            )
            data = resp.json()
            text = data.get("text", "").strip()
            if text:
                self.transcription_done.emit(text)
            else:
                self.status_changed.emit("未识别到内容")

        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
            if self._pa:
                self._pa.terminate()

    def stop(self):
        self._running = False


# ==================== 聊天窗口 ====================

class ChatWindow(QWidget):
    """独立的语音/文本聊天窗口"""

    def __init__(self, parent=None):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("元亨对话")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.resize(420, 520)
        self._chat_worker = None
        self._recorder = None
        self._tts_enabled = True

        self._setup_ui()
        self._move_near_avatar(parent)

    def _move_near_avatar(self, avatar):
        if avatar:
            ax = avatar.x()
            ay = avatar.y()
            aw = avatar.width()
            self.move(ax - self.width() - 10, ay)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.width() - self.width() - 20, 50)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 标题
        title = QLabel("语音对话")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title.setStyleSheet("color: #333;")
        layout.addWidget(title)

        # 对话显示区
        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setFont(QFont("Microsoft YaHei", 10))
        self._display.setStyleSheet("""
            QTextEdit {
                background: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        self._display.setHtml('<p style="color:#888;text-align:center;">— 欢迎使用元亨对话 —</p>')
        layout.addWidget(self._display)

        # 状态标签
        self._status_label = QLabel("")
        self._status_label.setFont(QFont("Microsoft YaHei", 9))
        self._status_label.setStyleSheet("color: #666;")
        layout.addWidget(self._status_label)

        # 输入行
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setFont(QFont("Microsoft YaHei", 10))
        self._input.setPlaceholderText("输入消息... (Enter 发送)")
        self._input.setStyleSheet("""
            QLineEdit {
                background: #fff;
                border: 1px solid #ccc;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QLineEdit:focus {
                border: 1px solid #4a90d9;
            }
        """)
        self._input.returnPressed.connect(self._send_text)
        input_row.addWidget(self._input)

        # 发送按钮
        send_btn = QPushButton("发送")
        send_btn.setFont(QFont("Microsoft YaHei", 10))
        send_btn.setFixedWidth(60)
        send_btn.setStyleSheet("""
            QPushButton {
                background: #4a90d9;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover { background: #357abd; }
            QPushButton:pressed { background: #2a5f9e; }
        """)
        send_btn.clicked.connect(self._send_text)
        input_row.addWidget(send_btn)

        # 语音按钮
        self._voice_btn = QPushButton("🎤 说话")
        self._voice_btn.setFont(QFont("Microsoft YaHei", 10))
        self._voice_btn.setFixedWidth(80)
        self._voice_btn.setCheckable(True)
        self._voice_btn.setStyleSheet("""
            QPushButton {
                background: #e74c3c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover { background: #c0392b; }
            QPushButton:checked { background: #27ae60; }
        """)
        self._voice_btn.clicked.connect(self._toggle_voice)
        input_row.addWidget(self._voice_btn)

        layout.addLayout(input_row)

    def _append_message(self, role, text):
        colors = {"user": "#4a90d9", "ai": "#27ae60", "sys": "#888"}
        labels = {"user": "我", "ai": "元亨", "sys": "系统"}
        color = colors.get(role, "#333")
        label = labels.get(role, role)
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(
            f'<p style="color:{color};margin:4px 0;"><b>{label}:</b> {text}</p>'
        )
        self._display.setTextCursor(cursor)
        self._display.ensureCursorVisible()

    def _set_status(self, text):
        self._status_label.setText(text)

    def _send_text(self, text=None):
        if text is None or isinstance(text, bool):
            text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._append_message("user", text)
        self._start_chat(text)

    def _start_chat(self, message):
        if self._chat_worker and self._chat_worker.isRunning():
            return
        self._set_status("元亨思考中...")
        self._append_message("ai", '<i style="color:#aaa;">思考中...</i>')

        self._chat_worker = ChatWorker(message, self._tts_enabled, self)
        self._chat_worker.chunk_received.connect(self._on_chunk)
        self._chat_worker.finished_stream.connect(self._on_finished)
        self._chat_worker.error_occurred.connect(self._on_error)
        self._chat_worker.start()

    def _on_chunk(self, content):
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        # 移除"思考中..."
        cursor.select(QTextCursor.WordUnderCursor)
        if cursor.selectedText() == "思考中...":
            cursor.removeSelectedText()
        cursor.insertText(content)
        self._display.ensureCursorVisible()

    def _on_finished(self, full_content):
        # 替换最后一条 AI 消息为完整内容
        self._set_status("")
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        self._append_message("ai", full_content)

    def _on_error(self, err):
        self._set_status("")
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        self._append_message("sys", f"连接失败: {err}")

    def _toggle_voice(self):
        if self._voice_btn.isChecked():
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        if pyaudio is None:
            self._voice_btn.setChecked(False)
            self._set_status("pyaudio 未安装")
            return
        self._voice_btn.setText("⏹ 停止")
        self._input.setEnabled(False)
        self._recorder = VoiceRecorder(self)
        self._recorder.transcription_done.connect(self._on_transcription)
        self._recorder.error_occurred.connect(self._on_recording_error)
        self._recorder.status_changed.connect(self._set_status)
        self._recorder.start()

    def _stop_recording(self):
        if self._recorder and self._recorder.isRunning():
            self._recorder.stop()
            self._recorder.wait(5000)
        self._voice_btn.setText("🎤 说话")
        self._input.setEnabled(True)

    def _on_transcription(self, text):
        self._voice_btn.setChecked(False)
        self._voice_btn.setText("🎤 说话")
        self._input.setEnabled(True)
        self._append_message("user", text)
        self._start_chat(text)

    def _on_recording_error(self, err):
        self._voice_btn.setChecked(False)
        self._voice_btn.setText("🎤 说话")
        self._input.setEnabled(True)
        self._set_status(f"录音错误: {err}")

    def closeEvent(self, event):
        if self._recorder and self._recorder.isRunning():
            self._recorder.stop()
            self._recorder.wait(3000)
        if self._chat_worker and self._chat_worker.isRunning():
            self._chat_worker.wait(3000)
        super().closeEvent(event)


# ==================== 主窗口 ====================

class DesktopAvatar(QWidget):
    """纯 PyQt5 无边框桌面桌宠窗口"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # 窗口尺寸
        screen = QApplication.primaryScreen().availableGeometry()
        self._win_w = int(screen.height() * 0.6 * (WINDOW_W / WINDOW_H))
        self._win_h = int(screen.height() * 0.6)
        self._win_w = max(200, self._win_w)
        self._win_h = max(280, self._win_h)

        self.setFixedSize(self._win_w, self._win_h)

        # 初始位置：右下角
        self._win_x = screen.width() - self._win_w - 20
        self._win_y = screen.height() - self._win_h - 80
        self.move(self._win_x, self._win_y)

        # Live2D 渲染控件（填满窗口）
        self._gl_widget = Live2DGLWidget(self)
        self._gl_widget.setGeometry(0, 0, self._win_w, self._win_h)
        self._gl_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 气泡菜单
        self._menu = BubbleMenu()
        self._menu.action_triggered.connect(self._on_menu_action)

        # 聊天窗口（延迟创建）
        self._chat_window = None

        # WebSocket 客户端
        self._ws = QtWSClient()
        self._ws.mouth_updated.connect(self._on_mouth)
        self._ws.speech_started.connect(self._on_speech_start)
        self._ws.speech_ended.connect(self._on_speech_end)
        self._ws.emotion_changed.connect(self._on_emotion)
        self._ws.start()

        # 拖拽状态
        self._dragging = False
        self._drag_offset = QPoint()

        # 右键状态
        self._rmb_pressed = False

        # FPS 显示
        self._show_fps = False
        self._frame_count = 0
        self._fps_timer = time.perf_counter()
        self._current_fps = 0

        # 渲染定时器
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._on_tick)
        self._render_timer.start(int(1000 / FPS))

        self._last_time = time.perf_counter()

        # 键盘快捷键定时器（低频率轮询，避免占用）
        self._key_timer = QTimer(self)
        self._key_timer.timeout.connect(self._poll_keyboard)
        self._key_timer.start(80)  # ~12Hz

        logger.info("PyQt5 桌宠启动完成")

    def showEvent(self, event):
        super().showEvent(event)
        # 设置窗口透明：黑色透传
        self._apply_transparency()

    def _apply_transparency(self):
        """通过 Win32 API 设置 LWA_COLORKEY 黑色透传"""
        hwnd = int(self.winId())
        if not hwnd:
            return

        # 扩展样式：分层窗口
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_LAYERED
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

        # 黑色透传
        win32gui.SetLayeredWindowAttributes(hwnd, 0, 0, win32con.LWA_COLORKEY)

        logger.info(f"透明窗口已设置 (HWND={hwnd})")

    # ==================== 鼠标事件（拖拽 + 缩放 + 右键） ====================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPos() - self.pos()
            self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.RightButton:
            self._rmb_pressed = True
            self._menu.show_at(event.globalPos())

    def mouseMoveEvent(self, event):
        if self._dragging:
            new_pos = event.globalPos() - self._drag_offset
            self.move(new_pos)
            self._win_x = new_pos.x()
            self._win_y = new_pos.y()

        # 视线跟踪
        if self._gl_widget.is_loaded():
            gx = event.pos().x() / max(self.width(), 1)
            gy = event.pos().y() / max(self.height(), 1)
            self._gl_widget.set_gaze_target(gx, gy)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
        elif event.button() == Qt.RightButton:
            self._rmb_pressed = False

    def leaveEvent(self, event):
        """鼠标离开窗口时，视线回到中心"""
        if self._gl_widget.is_loaded():
            self._gl_widget.set_gaze_target(0.5, 0.5)

    def wheelEvent(self, event):
        """滚轮缩放"""
        delta = event.angleDelta().y()
        if delta > 0:
            self._gl_widget.zoom(1)
        elif delta < 0:
            self._gl_widget.zoom(-1)

    # ==================== 键盘快捷键 ====================

    def _poll_keyboard(self):
        """轮询键盘快捷键"""
        # +/= 键放大
        if win32api.GetAsyncKeyState(0xBB) & 0x8000:
            self._gl_widget.zoom(1)
        # -/_ 键缩小
        if win32api.GetAsyncKeyState(0xBD) & 0x8000:
            self._gl_widget.zoom(-1)
        # 0 键重置缩放
        if win32api.GetAsyncKeyState(0x30) & 0x8000:
            self._gl_widget.reset_scale()
        # R 键重置位置
        if win32api.GetAsyncKeyState(0x52) & 0x8000:
            self._reset_position()
        # F 键切换 FPS 显示
        if win32api.GetAsyncKeyState(0x46) & 0x8000:
            self._show_fps = not self._show_fps
            logger.info(f"FPS 显示: {'开' if self._show_fps else '关'}")
            # 防止重复触发
            import time as _time
            _time.sleep(0.3)
        # Esc 退出
        if win32api.GetAsyncKeyState(0x1B) & 0x8000:
            logger.info("Esc 退出")
            self._shutdown()

    def _reset_position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self._win_x = screen.width() - self._win_w - 20
        self._win_y = screen.height() - self._win_h - 80
        self.move(self._win_x, self._win_y)
        logger.info("位置已重置")

    # ==================== 渲染循环 ====================

    def _on_tick(self):
        """每帧更新"""
        now = time.perf_counter()
        dt = min(now - self._last_time, 0.1)
        self._last_time = now

        if self._gl_widget.is_loaded():
            # 更新动画（口型、视线）
            self._gl_widget.update_animation(dt)
            # 触发重绘
            self._gl_widget.update()

        # FPS 统计
        if self._show_fps:
            self._frame_count += 1
            if now - self._fps_timer >= 1.0:
                self._current_fps = self._frame_count
                self._frame_count = 0
                self._fps_timer = now
                logger.info(f"FPS: {self._current_fps}")

    # ==================== WebSocket 回调 ====================

    def _on_mouth(self, value):
        self._gl_widget.set_mouth(value)

    def _on_speech_start(self):
        self._gl_widget.set_speaking(True)

    def _on_speech_end(self):
        self._gl_widget.set_speaking(False)

    def _on_emotion(self, emotion, intensity):
        self._gl_widget.set_emotion(emotion, intensity)

    # ==================== 菜单回调 ====================

    def _toggle_chat(self):
        if self._chat_window and self._chat_window.isVisible():
            self._chat_window.close()
            self._chat_window = None
        else:
            self._chat_window = ChatWindow(self)
            self._chat_window.show()

    def _on_menu_action(self, action):
        logger.info(f"菜单动作: {action}")
        if action == "enable_chat":
            self._toggle_chat()
        elif action == "zoom_in":
            self._gl_widget.zoom(1)
        elif action == "zoom_out":
            self._gl_widget.zoom(-1)
        elif action == "reset_scale":
            self._gl_widget.reset_scale()
        elif action == "reset_pos":
            self._reset_position()
        elif action == "toggle_fps":
            self._show_fps = not self._show_fps
            logger.info(f"FPS 显示: {'开' if self._show_fps else '关'}")
        elif action == "quit":
            self._shutdown()

    # ==================== 生命周期 ====================

    def _shutdown(self):
        self._render_timer.stop()
        self._key_timer.stop()
        self._ws.stop()
        if self._chat_window:
            self._chat_window.close()
            self._chat_window = None
        self._gl_widget.cleanup()
        self._menu.close()
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)


# ==================== 入口 ====================

def main():
    # 设置 OpenGL 表面格式（支持 Alpha 通道）
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setApplicationName("元亨桌宠")

    avatar = DesktopAvatar()
    avatar.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()