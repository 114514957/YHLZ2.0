"""
元亨桌面虚拟形象 — Live2D 原生渲染版
基于 live2d-py 0.7 + QOpenGLWidget 直接渲染，替代 QWebEngineView 方案
参考: NachoBot renderer.py (pygame+OpenGL+live2d.v3 透明桌宠窗)

特性:
  - 无边框透明窗口 (FramelessWindowHint + WA_TranslucentBackground)
  - 口型同步: 三正弦叠加 (RMS×8 + 参数保护)
  - 表情系统: 基线三快照 + 差分淡出
  - 视线状态机: GAZE 跟随 + 参数补间 ease-out quad
  - WS 连接 backend 接收口型/表情事件
  - 全屏拖动 / 右键菜单 / 双击切表情 / 滚轮缩放 / 系统托盘
"""

import sys
import os
import json
import time
import logging
import threading
import random
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QPoint, QTimer, QSize
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMenu, QSystemTrayIcon,
    QVBoxLayout, QOpenGLWidget
)
from PyQt5.QtGui import (
    QPainter, QColor, QPixmap, QIcon, QSurfaceFormat
)

from live2d_renderer import Live2DRenderer

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('YHLZ.Avatar')

BASE_DIR = Path(__file__).parent
# 模型目录: 纯英文路径 (Cubism Core C++ 不支持中文路径)
MODEL_DIRS = [
    BASE_DIR / 'assets' / 'live2d' / 'hiyori_vts',
    BASE_DIR / 'assets' / 'live2d' / 'akari_vts',
    BASE_DIR / 'assets' / 'live2d' / 'hijiki_vts',
    BASE_DIR / 'assets' / 'live2d' / 'tororo_vts',
    BASE_DIR / 'assets' / 'live2d' / 'wanko_vts',
]
CONFIG_DIR = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'yuanheng-avatar'
CONFIG_FILE = CONFIG_DIR / 'avatar-config.json'


# ══════════════════════════════════════════════════════════
# 蓝图D6: 桌宠→backend WebSocket 客户端
# ══════════════════════════════════════════════════════════

class AvatarWSClient:
    """桌宠 WebSocket 客户端 — 连接 backend /ws/avatar 接收口型/表情事件"""

    BACKEND_URL = "ws://127.0.0.1:8000/ws/avatar"
    HEARTBEAT_INTERVAL = 10
    HEARTBEAT_TIMEOUT = 3
    RECONNECT_BASE = 1
    RECONNECT_MAX = 30

    def __init__(self):
        self._ws = None
        self._running = False
        self._thread = None
        self._mouth_open = 0.0
        self._emotion = "neutral"
        self._is_speaking = False
        self._connected = False
        self._heartbeat_missed = 0
        self._reconnect_attempt = 0
        self._on_event_callbacks = []

    @property
    def mouth_open(self) -> float: return self._mouth_open
    @property
    def emotion(self) -> str: return self._emotion
    @property
    def is_speaking(self) -> bool: return self._is_speaking
    @property
    def connected(self) -> bool: return self._connected

    def on_event(self, callback):
        self._on_event_callbacks.append(callback)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("WebSocket 客户端已启动")

    def stop(self):
        self._running = False
        self._connected = False
        logger.info("WebSocket 客户端已停止")

    def _run_loop(self):
        while self._running:
            try:
                self._connect_and_listen()
            except Exception as e:
                logger.warning(f"WebSocket 连接异常: {e}")
            if not self._running:
                break
            delay = min(self.RECONNECT_BASE * (2 ** self._reconnect_attempt), self.RECONNECT_MAX)
            self._reconnect_attempt += 1
            logger.info(f"WebSocket 重连等待 {delay}s (第 {self._reconnect_attempt} 次)")
            time.sleep(delay)

    def _connect_and_listen(self):
        try:
            import websocket
        except ImportError:
            logger.warning("websocket-client 未安装")
            self._running = False
            return

        try:
            self._ws = websocket.create_connection(self.BACKEND_URL, timeout=10)
            self._connected = True
            self._reconnect_attempt = 0
            self._heartbeat_missed = 0
            logger.info(f"已连接到 backend: {self.BACKEND_URL}")

            last_heartbeat = time.time()

            while self._running and self._connected:
                elapsed = time.time() - last_heartbeat
                if elapsed > self.HEARTBEAT_INTERVAL:
                    self._heartbeat_missed += 1
                    if self._heartbeat_missed >= self.HEARTBEAT_TIMEOUT:
                        logger.warning("WebSocket 心跳超时")
                        self._connected = False
                        break

                self._ws.settimeout(1.0)
                try:
                    data = self._ws.recv()
                    if data:
                        msg = json.loads(data)
                        msg_type = msg.get("type", "")

                        if msg_type == "pong":
                            self._heartbeat_missed = 0
                            last_heartbeat = time.time()
                        elif msg_type == "ping":
                            self._ws.send(json.dumps({"type": "pong", "ts": time.time()}))
                            last_heartbeat = time.time()
                        elif msg_type == "connected":
                            last_heartbeat = time.time()
                        elif msg_type == "mouth_sync":
                            self._mouth_open = msg.get("data", {}).get("value", 0.0)
                            self._is_speaking = self._mouth_open > 0.02
                            self._notify("mouth_sync", msg.get("data", {}))
                        elif msg_type == "emotion_change":
                            self._emotion = msg.get("data", {}).get("emotion", "neutral")
                            self._notify("emotion_change", msg.get("data", {}))
                        elif msg_type == "speech_start":
                            self._is_speaking = True
                            self._notify("speech_start", msg.get("data", {}))
                        elif msg_type == "speech_end":
                            self._is_speaking = False
                            self._notify("speech_end", msg.get("data", {}))
                except Exception:
                    pass  # 超时正常

                if time.time() - last_heartbeat >= self.HEARTBEAT_INTERVAL:
                    try:
                        self._ws.send(json.dumps({"type": "ping", "ts": time.time()}))
                    except Exception:
                        self._connected = False
                        break

        except Exception as e:
            logger.warning(f"WebSocket 连接失败: {e}")
            self._connected = False
        finally:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None

    def _notify(self, event_type, data):
        for cb in self._on_event_callbacks:
            try:
                cb(event_type, data)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════
# Live2D OpenGL 渲染控件
# ══════════════════════════════════════════════════════════

class Live2DWidget(QOpenGLWidget):
    """QOpenGLWidget 封装 Live2D 原生渲染"""

    def __init__(self, renderer: Live2DRenderer, parent=None):
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)  # 4x 抗锯齿
        super().__init__(parent)
        self.setFormat(fmt)
        self._renderer = renderer
        self._init_done = False
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

    def initializeGL(self):
        self._renderer.init_gl()
        self._init_done = True
        logger.info("OpenGL 初始化完成")
        
        # 直接在 GL 上下文中加载模型
        try:
            model_dir = None
            for d in MODEL_DIRS:
                if d.exists():
                    model_dir = str(d)
                    break
            if model_dir:
                logger.info(f"开始加载模型: {model_dir}")
                if self._renderer.load_model(model_dir):
                    self._renderer.resize(self.width(), self.height())
                    self.parent()._model_loaded = True
                    self.parent()._renderer = self._renderer
                    logger.info("Live2D 模型加载完成")
                else:
                    logger.error("Live2D 模型加载失败")
            else:
                logger.error("未找到 Live2D 模型目录")
        except Exception as e:
            logger.error(f"模型加载异常: {e}")
            import traceback
            traceback.print_exc()

    def paintGL(self):
        import live2d.v3 as l2d
        l2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if self._renderer.loaded:
            self._renderer.render_frame()

    def resizeGL(self, w: int, h: int):
        self._renderer.resize(w, h)


# ══════════════════════════════════════════════════════════
# 桌宠主窗口
# ══════════════════════════════════════════════════════════

class AvatarWindow(QWidget):
    """无边框桌面虚拟形象 — live2d-py 原生渲染 + 透明窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('元亨桌宠')
        self.resize(400, 500)

        # 无边框 + 工具窗口 + 置顶
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowStaysOnTopHint
        )

        # 透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAutoFillBackground(False)

        # 拖拽状态
        self.is_dragging = False
        self.drag_start = None
        self.window_start = None

        # Live2D 渲染器
        self._renderer = Live2DRenderer()
        self._model_loaded = False

        # WebSocket 客户端
        self._ws_client = AvatarWSClient()
        self._ws_client.on_event(self._on_ws_event)

        # 构建 UI
        self._init_ui()
        self._init_menu()
        self._init_tray()
        self._restore_position()

        # 渲染循环 (60fps)
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._update_frame)
        self._render_timer.start(16)  # ~60fps

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._gl_widget = Live2DWidget(self._renderer, self)
        layout.addWidget(self._gl_widget)

    def _init_menu(self):
        self.context_menu = QMenu(self)
        self.context_menu.setStyleSheet("""
            QMenu {
                background: rgba(30,30,40,240);
                color: white;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px;
                padding: 8px;
            }
            QMenu::item { padding: 8px 16px; border-radius: 4px; color: white; }
            QMenu::item:selected { background: rgba(0,212,255,0.2); }
        """)

        act_status = self.context_menu.addAction('状態: 运行中')
        act_status.setEnabled(False)
        self.context_menu.addSeparator()

        for emo, label in [('happy', '开心'), ('sad', '伤心'),
                           ('angry', '生气'), ('surprised', '惊讶')]:
            act = self.context_menu.addAction(f'{label}')
            act.triggered.connect(lambda checked, e=emo: self._set_emotion(e))

        self.context_menu.addSeparator()
        act_reset = self.context_menu.addAction('重置位置')
        act_reset.triggered.connect(self._reset_position)
        act_webui = self.context_menu.addAction('打开WebUI')
        act_webui.triggered.connect(lambda: os.system('start http://127.0.0.1:5000'))
        self.context_menu.addSeparator()
        act_quit = self.context_menu.addAction('退出')
        act_quit.triggered.connect(QApplication.instance().quit)

    def _init_tray(self):
        try:
            icon_pixmap = QPixmap(32, 32)
            icon_pixmap.fill(Qt.transparent)
            p = QPainter(icon_pixmap)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(0, 212, 255, 200))
            p.setPen(Qt.NoPen)
            p.drawEllipse(2, 2, 28, 28)
            p.setPen(QColor(255, 255, 255))
            font = p.font()
            font.setPixelSize(14)
            font.setBold(True)
            p.setFont(font)
            p.drawText(0, 0, 32, 32, Qt.AlignCenter, '元')
            p.end()

            self.tray = QSystemTrayIcon(QIcon(icon_pixmap), self)
            self.tray.setToolTip('元亨 YHLZ 2.0 - Live2D')

            tray_menu = QMenu()
            tray_menu.addAction('显示').triggered.connect(self.show)
            tray_menu.addAction('隐藏').triggered.connect(self.hide)
            tray_menu.addSeparator()
            tray_menu.addAction('退出').triggered.connect(QApplication.instance().quit)

            self.tray.setContextMenu(tray_menu)
            self.tray.show()
        except Exception as e:
            logger.warning(f"托盘创建失败: {e}")

    def _load_model(self):
        """加载 Live2D 模型 (需要 GL 上下文)"""
        self._gl_widget.makeCurrent()
        
        model_dir = None
        for d in MODEL_DIRS:
            if d.exists():
                model_dir = str(d)
                break

        if not model_dir:
            logger.error("未找到 Live2D 模型目录")
            self._gl_widget.doneCurrent()
            return

        if self._renderer.load_model(model_dir):
            self._model_loaded = True
            self._renderer.resize(self.width(), self.height())
            logger.info("Live2D 模型加载完成")
        else:
            logger.error("Live2D 模型加载失败")
        
        self._gl_widget.doneCurrent()

    def _update_frame(self):
        """每帧更新"""
        self._gl_widget.update()

    def _set_emotion(self, emotion: str):
        """设置表情"""
        self._renderer.set_emotion(emotion)
        logger.info(f"表情: {emotion}")

    def _reset_position(self):
        """重置位置到屏幕中央"""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.move(
                (geo.width() - self.width()) // 2,
                (geo.height() - self.height()) // 2
            )

    def _restore_position(self):
        try:
            if CONFIG_FILE.exists():
                config = json.loads(CONFIG_FILE.read_text())
                pos = config.get('position', {})
                if 'x' in pos and 'y' in pos:
                    self.move(pos['x'], pos['y'])
        except Exception:
            pass

    def _save_position(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            config = {
                'position': {'x': self.x(), 'y': self.y()},
                'size': {'w': self.width(), 'h': self.height()}
            }
            CONFIG_FILE.write_text(json.dumps(config, indent=2))
        except Exception:
            pass

    def show_animation(self):
        self.show()

    # ── WS 事件处理 ────────────────────────────────────

    def _on_ws_event(self, event_type, data):
        try:
            if event_type == "mouth_sync":
                value = data.get("value", 0.0)
                self._renderer.set_mouth_open(value)
            elif event_type == "emotion_change":
                emotion = data.get("emotion", "neutral")
                self._renderer.set_emotion(emotion)
            elif event_type == "speech_start":
                self._renderer.set_speaking(True)
            elif event_type == "speech_end":
                self._renderer.set_speaking(False)
        except Exception as e:
            logger.debug(f"WS事件处理异常: {e}")

    # ── 鼠标事件 ───────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            self.drag_start = event.globalPos()
            self.window_start = self.pos()
            self.raise_()
            self.activateWindow()
            event.accept()
        elif event.button() == Qt.RightButton:
            self.context_menu.exec_(event.globalPos())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging and event.buttons() == Qt.LeftButton:
            delta = event.globalPos() - self.drag_start
            self.move(self.window_start + delta)
            event.accept()
        else:
            # 更新视线跟随鼠标
            w, h = self.width(), self.height()
            cx = (event.pos().x() / w - 0.5) * 2.0  # 归一化到 -1~1
            cy = (event.pos().y() / h - 0.5) * 2.0
            self._renderer.set_gaze_target(cx, cy)

    def mouseReleaseEvent(self, event):
        if self.is_dragging:
            self.is_dragging = False
            self._save_position()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            emotions = ['happy', 'surprised', 'sad', 'angry']
            self._set_emotion(random.choice(emotions))
            self._renderer.start_random_motion()
            event.accept()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 1.08 if delta > 0 else 0.92
        old_w, old_h = self.width(), self.height()
        new_w = max(250, min(600, int(old_w * factor)))
        new_h = int(old_h * factor)
        new_h = max(300, min(700, new_h))
        pos = self.pos()
        bottom = pos.y() + old_h
        new_x = pos.x() + (old_w - new_w) // 2
        new_y = bottom - new_h
        self.resize(new_w, new_h)
        self.move(new_x, new_y)
        self._save_position()
        event.accept()

    # ── 窗口事件 ───────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))

    def closeEvent(self, event):
        self._render_timer.stop()
        self._save_position()
        self._renderer.cleanup()
        if hasattr(self, 'tray') and self.tray:
            self.tray.hide()
        event.accept()


# ══════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════

def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, False)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = AvatarWindow()
    window.show_animation()

    # 启动 WebSocket 客户端
    window._ws_client.start()

    print("=" * 50)
    print("  YHLZ 2.0 Live2D 桌宠已启动 (原生渲染)")
    print("  live2d-py 0.7 + QOpenGLWidget")
    print("  左键拖动 | 右键菜单 | 双击切表情+动作 | 滚轮缩放")
    print("  视线跟随鼠标 | WS口型同步: /ws/avatar")
    print("=" * 50)

    def on_quit():
        window._ws_client.stop()
        try:
            window._save_position()
        except Exception:
            pass

    app.aboutToQuit.connect(on_quit)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()