"""
YHLZ 2.0 Live2D桌面虚拟角色（WebView版）
使用QWebEngineView加载HTML查看器，解决图层叠加问题
支持模型加载、表情控制、口型同步、点击交互
"""

import sys
import os
import json
import time
import logging
import asyncio
import threading
import http.server
import socketserver

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

_live2d_server = None
_live2d_server_thread = None
_live2d_server_port = 8081


def _start_live2d_server():
    """启动Live2D查看器HTTP服务器"""
    global _live2d_server, _live2d_server_thread
    
    live2d_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'live2d')
    
    os.chdir(live2d_dir)
    
    Handler = http.server.SimpleHTTPRequestHandler
    Handler.extensions_map['.json'] = 'application/json'
    
    try:
        _live2d_server = socketserver.TCPServer(("", _live2d_server_port), Handler)
        logger.info(f"Live2D HTTP服务器启动: http://localhost:{_live2d_server_port}")
        _live2d_server.serve_forever()
    except Exception as e:
        logger.error(f"Live2D HTTP服务器启动失败: {e}")


def _stop_live2d_server():
    """停止Live2D查看器HTTP服务器"""
    global _live2d_server, _live2d_server_thread
    
    if _live2d_server:
        _live2d_server.shutdown()
        _live2d_server.server_close()
        _live2d_server = None
        logger.info("Live2D HTTP服务器已停止")
    
    if _live2d_server_thread and _live2d_server_thread.is_alive():
        _live2d_server_thread.join(timeout=2)
        _live2d_server_thread = None

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QSystemTrayIcon, 
    QMenu, QAction, QDialog, QFormLayout, QGroupBox, QLineEdit,
    QCheckBox, QPushButton, QHBoxLayout, QListWidget, QListWidgetItem,
    QMessageBox, QInputDialog
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QColor, QCursor, QImage, QLinearGradient, QFont,
    QIcon, QSurfaceFormat
)
from PyQt5.QtCore import Qt, QTimer, QRect, QThread, pyqtSignal, QPoint, QUrl, QObject, pyqtSlot, QJsonDocument
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineSettings
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebSockets import QWebSocket
import math
import random


class Live2DBridge(QObject):
    """Python-JavaScript通信桥接类"""
    
    mouth_open_changed = pyqtSignal(float)
    look_at_changed = pyqtSignal(float, float)
    motion_triggered = pyqtSignal(str)
    expression_changed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
    
    @pyqtSlot(str)
    def onModelLoaded(self, modelName):
        logger.info(f"模型加载完成: {modelName}")
    
    @pyqtSlot(str)
    def onMotionStart(self, motionGroup):
        logger.info(f"动画开始: {motionGroup}")
    
    @pyqtSlot(str)
    def onMotionFinish(self, motionGroup):
        logger.info(f"动画完成: {motionGroup}")
    
    @pyqtSlot(str)
    def onHitArea(self, hitAreas):
        logger.info(f"点击区域: {hitAreas}")
    
    @pyqtSlot(str)
    def onError(self, errorMsg):
        logger.error(f"JavaScript错误: {errorMsg}")


class AvatarWSClient(QObject):
    """WebSocket 客户端，连接后端 /ws/avatar 实现实时口型/表情/事件同步
    
    协议版本 PROTOCOL_VERSION="1.0"
    下行事件: mouth_sync / emotion_change / speech_start / speech_end / tts_chunk / ping / pong
    上行事件: ping / status
    """
    
    PROTOCOL_VERSION = "1.0"
    
    # 信号
    mouth_sync_signal = pyqtSignal(float)       # 口型开合度 0-1
    emotion_change_signal = pyqtSignal(str, float)  # 情感名, 强度
    speech_start_signal = pyqtSignal()
    speech_end_signal = pyqtSignal()
    tts_chunk_signal = pyqtSignal(int)           # 音频块长度
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws = QWebSocket()
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_disconnected)
        self._ws.textMessageReceived.connect(self._on_message)
        self._ws.error.connect(self._on_error)
        
        self._url = "ws://localhost:8000/ws/avatar"
        self._reconnect_timer = QTimer()
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._try_connect)
        self._reconnect_delay = 1  # 初始重连延迟 1s
        self._max_reconnect_delay = 30
        
        self._heartbeat_timer = QTimer()
        self._heartbeat_timer.timeout.connect(self._send_ping)
        self._heartbeat_timer.setInterval(10000)  # 10s 心跳
        
        self._last_pong = time.time()
        self._is_connected = False
    
    def start(self):
        """启动连接"""
        self._try_connect()
    
    def stop(self):
        """停止连接"""
        self._reconnect_timer.stop()
        self._heartbeat_timer.stop()
        if self._ws:
            self._ws.close()
    
    def _try_connect(self):
        """尝试连接后端"""
        if self._is_connected:
            return
        logger.info(f"正在连接 Live2D 同步服务: {self._url}")
        self._ws.open(QUrl(self._url))
    
    def _on_connected(self):
        """连接成功"""
        self._is_connected = True
        self._reconnect_delay = 1  # 重置重连延迟
        self._heartbeat_timer.start()
        self._last_pong = time.time()
        logger.info("Live2D 同步服务已连接")
        self.connected_signal.emit()
    
    def _on_disconnected(self):
        """连接断开"""
        self._is_connected = False
        self._heartbeat_timer.stop()
        logger.warning("Live2D 同步服务已断开，将自动重连...")
        self.disconnected_signal.emit()
        self._schedule_reconnect()
    
    def _on_error(self, error_code):
        """连接错误"""
        logger.error(f"WebSocket 错误: {error_code}")
        if not self._is_connected:
            self._schedule_reconnect()
    
    def _schedule_reconnect(self):
        """指数退避重连"""
        delay = min(self._reconnect_delay, self._max_reconnect_delay)
        logger.info(f"将在 {delay}s 后重连...")
        self._reconnect_timer.start(delay * 1000)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
    
    def _on_message(self, message: str):
        """处理下行消息"""
        try:
            msg = json.loads(message)
            msg_type = msg.get("type", "")
            data = msg.get("data", {})
            
            if msg_type == "connected":
                logger.info(f"后端已确认连接 (版本: {data.get('version', '?')})")
            
            elif msg_type == "pong":
                self._last_pong = time.time()
            
            elif msg_type == "ping":
                self._send_pong()
            
            elif msg_type == "mouth_sync":
                # 口型同步事件: {value: 0.0-1.0}
                value = data.get("value", 0.0)
                self.mouth_sync_signal.emit(value)
            
            elif msg_type == "emotion_change":
                # 情感变化: {emotion: str, intensity: 0.0-1.0}
                emotion = data.get("emotion", "neutral")
                intensity = data.get("intensity", 1.0)
                self.emotion_change_signal.emit(emotion, intensity)
            
            elif msg_type == "speech_start":
                self.speech_start_signal.emit()
            
            elif msg_type == "speech_end":
                self.speech_end_signal.emit()
            
            elif msg_type == "tts_chunk":
                length = data.get("length", 0)
                self.tts_chunk_signal.emit(length)
            
            else:
                logger.debug(f"未处理的消息类型: {msg_type}")
        
        except json.JSONDecodeError as e:
            logger.error(f"消息解析失败: {e}")
        except Exception as e:
            logger.error(f"处理消息异常: {e}")
    
    def _send_ping(self):
        """发送心跳"""
        if self._is_connected:
            self._ws.sendTextMessage(json.dumps({
                "type": "ping",
                "ts": time.time()
            }))
            # 检查上次 pong 是否超时 (>30s 无响应)
            if time.time() - self._last_pong > 30:
                logger.warning("心跳超时，断开重连")
                self._ws.close()
    
    def _send_pong(self):
        """响应 ping"""
        if self._is_connected:
            self._ws.sendTextMessage(json.dumps({
                "type": "pong",
                "ts": time.time()
            }))
    
    def send_status(self, status_data: dict):
        """上报桌宠状态"""
        if self._is_connected:
            self._ws.sendTextMessage(json.dumps({
                "type": "status",
                "data": status_data,
                "ts": time.time()
            }))


class ConsoleWebPage(QWebEnginePage):
    """自定义Web页面，捕获JavaScript控制台消息"""
    
    def javaScriptConsoleMessage(self, level, msg, line, source):
        level_map = {
            0: 'DEBUG',
            1: 'WARNING',
            2: 'ERROR'
        }
        logger.info(f"[JS {level_map.get(level, 'INFO')}] {msg} (行:{line})")
        super().javaScriptConsoleMessage(level, msg, line, source)


class Live2DWebWidget(QWebEngineView):
    """基于QWebEngineView的Live2D渲染组件"""
    
    def __init__(self, model_path, parent=None):
        super().__init__(parent)
        self._model_path = model_path
        self._model_name = os.path.basename(model_path)
        self._is_initialized = False
        self._mouth_open = 0.0
        self._frame_count = 0
        self._bridge = Live2DBridge()
        self._current_emotion = 'neutral'
        
        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._update_animation)
        self._animation_timer.start(50)
        
        self._init_webview()
    
    def _init_webview(self):
        self.setStyleSheet("background: transparent;")
        
        global _live2d_server_thread, _live2d_server_port
        
        if _live2d_server_thread is None:
            _live2d_server_thread = threading.Thread(target=_start_live2d_server, daemon=True)
            _live2d_server_thread.start()
            time.sleep(1)
        
        viewer_url = f"http://localhost:{_live2d_server_port}/live2d_viewer.html?ts={int(time.time())}"
        
        logger.info(f"Live2D服务器URL: {viewer_url}")
        logger.info(f"模型路径: {self._model_path}")
        logger.info(f"模型名称: {self._model_name}")
        
        self.setPage(ConsoleWebPage())
        
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        
        self.loadFinished.connect(self._on_load_finished)
        
        url = QUrl(viewer_url)
        self.load(url)
        logger.info(f"加载Live2D查看器: {viewer_url}")
    
    def _on_load_finished(self, success):
        if success:
            self._setup_web_channel()
            self._is_initialized = True
            logger.info("Live2D查看器加载完成")
            
            model_full_path = os.path.abspath(self._model_path)
            model_dir_name = os.path.basename(model_full_path)
            logger.info(f"模型路径: {model_full_path}")
            logger.info(f"模型目录名: {model_dir_name}")
            
            js_code = f"""
                console.log('=== 设置模型路径 ===');
                modelBasePath = './{model_dir_name}/';
                console.log('模型基础路径:', modelBasePath);
                console.log('当前URL:', window.location.href);
                console.log('typeof initModel:', typeof initModel);
                
                if (typeof initModel === 'function') {{
                    console.log('调用initModel()');
                    initModel();
                }} else {{
                    console.error('initModel未定义');
                }}
            """
            self.page().runJavaScript(js_code)
        else:
            logger.error("Live2D查看器加载失败")
    
    def _setup_web_channel(self):
        channel = QWebChannel(self.page())
        channel.registerObject('live2dBridge', self._bridge)
        self.page().setWebChannel(channel)
        
        js_code = """
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.live2dBridge = channel.objects.live2dBridge;
            });
        """
        self.page().runJavaScript(js_code)
    
    def _update_animation(self):
        if not self._is_initialized:
            return
        
        try:
            js_code = f"window.setParameter('ParamMouthOpenY', {self._mouth_open});"
            self.page().runJavaScript(js_code)
            
            self._frame_count += 1
        except Exception as e:
            logger.debug(f"更新动画失败: {e}")
    
    def set_mouth_open(self, value):
        self._mouth_open = max(0.0, min(1.0, value))
    
    def set_look_at(self, x, y):
        try:
            js_code = f"window.setLookAt({x}, {y});"
            self.page().runJavaScript(js_code)
        except Exception as e:
            logger.debug(f"设置视线失败: {e}")
    
    def set_expression(self, expression_name):
        try:
            js_code = f"window.setExpression('{expression_name}');"
            self.page().runJavaScript(js_code)
            logger.info(f"设置表情: {expression_name}")
        except Exception as e:
            logger.error(f"设置表情失败: {e}")
    
    def start_motion(self, motion_group):
        try:
            js_code = f"window.startRandomMotion('{motion_group}');"
            self.page().runJavaScript(js_code)
            logger.info(f"触发动作: {motion_group}")
        except Exception as e:
            logger.error(f"触发动作失败: {e}")
    
    def switch_model(self, model_path):
        if os.path.exists(model_path):
            self._model_path = model_path
            self._model_name = os.path.basename(model_path)
            self._is_initialized = False
            
            js_code = f"window.reloadModel('./{self._model_name}/');"
            self.page().runJavaScript(js_code)
            
            return True
        return False
    
    def get_model_info(self):
        info = {}
        def callback(result):
            nonlocal info
            info = result
        
        try:
            self.page().runJavaScript("window.getModelInfo();", callback)
            time.sleep(0.1)
            return info
        except Exception as e:
            logger.error(f"获取模型信息失败: {e}")
            return {}
    
    def set_emotion(self, emotion_name):
        try:
            js_code = f"window.setEmotion('{emotion_name}');"
            self.page().runJavaScript(js_code)
            self._current_emotion = emotion_name
            logger.info(f"设置情感: {emotion_name}")
        except Exception as e:
            logger.error(f"设置情感失败: {e}")
    
    def set_emotion_with_intensity(self, emotion_name, intensity):
        try:
            js_code = f"window.setEmotionWithIntensity('{emotion_name}', {intensity});"
            self.page().runJavaScript(js_code)
            self._current_emotion = emotion_name
            logger.info(f"设置情感: {emotion_name} (强度: {intensity})")
        except Exception as e:
            logger.error(f"设置情感失败: {e}")
    
    def set_glow_color(self, color):
        try:
            js_code = f"window.setGlowColor('{color}');"
            self.page().runJavaScript(js_code)
            logger.info(f"设置光效颜色: {color}")
        except Exception as e:
            logger.error(f"设置光效颜色失败: {e}")
    
    def set_mouth_open(self, value):
        try:
            js_code = f"window.setMouthOpen({value});"
            self.page().runJavaScript(js_code)
            logger.debug(f"设置口型开合度: {value}")
        except Exception as e:
            logger.error(f"设置口型开合度失败: {e}")
    
    def get_current_emotion(self):
        return self._current_emotion


class ServiceManager:
    """服务管理器"""
    
    def __init__(self):
        self.config = self._load_config()
        self.services = {}
        self.running = False
    
    def _load_config(self):
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher_config.json")
        default = {
            "port": 8000,
            "host": "0.0.0.0",
            "auto_start_vts": True,
            "auto_connect_vts": True,
            "enable_vision": True,
            "enable_audio": True,
            "enable_live2d": True,
            "enable_bilibili": False,
            "bilibili_room_id": "",
            "model_name": "Hiyori VTS",
            "theme": "light",
        }
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    default.update(saved)
            except Exception as e:
                logger.warning(f"加载配置失败: {e}")
        
        return default
    
    def save_config(self):
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher_config.json")
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")
    
    def get(self, key, default=None):
        return self.config.get(key, default)
    
    def set(self, key, value):
        self.config[key] = value
        self.save_config()
    
    def start_backend(self):
        logger.info("启动后端服务...")
        try:
            import subprocess
            script_dir = os.path.dirname(os.path.abspath(__file__))
            env = os.environ.copy()
            
            self.services['backend'] = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', 'backend.main:app',
                 '--host', self.config.get('host'),
                 '--port', str(self.config.get('port')),
                 '--log-level', 'info'],
                cwd=script_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"后端服务已启动 (PID: {self.services['backend'].pid})")
            return True
        except Exception as e:
            logger.error(f"启动后端服务失败: {e}")
            return False
    
    def start_vision(self):
        if not self.config.get('enable_vision', True):
            logger.info("跳过视觉服务（已禁用）")
            return False
        
        logger.info("启动视觉服务...")
        try:
            import requests
            response = requests.post(
                f"http://localhost:{self.config.get('port', 8000)}/modules/start",
                json={"module_name": "vision"},
                timeout=10
            )
            if response.status_code == 200:
                logger.info("视觉服务已启动")
                return True
            else:
                logger.error(f"视觉服务启动失败: {response.text}")
                return False
        except Exception as e:
            logger.error(f"启动视觉服务失败: {e}")
            return False
    
    def start_audio(self):
        if not self.config.get('enable_audio', True):
            logger.info("跳过高音频服务（已禁用）")
            return False
        
        logger.info("启动音频服务...")
        try:
            import requests
            response = requests.post(
                f"http://localhost:{self.config.get('port', 8000)}/modules/start",
                json={"module_name": "asr"},
                timeout=10
            )
            if response.status_code == 200:
                logger.info("音频服务已启动")
                return True
            else:
                logger.error(f"音频服务启动失败: {response.text}")
                return False
        except Exception as e:
            logger.error(f"启动音频服务失败: {e}")
            return False
    
    def start_bilibili(self):
        if not self.config.get('enable_bilibili', False):
            logger.info("跳过B站直播（已禁用）")
            return False
        
        room_id = self.config.get('bilibili_room_id', '')
        if not room_id:
            logger.warning("B站直播房间ID未设置")
            return False
        
        logger.info(f"连接B站直播 (房间ID: {room_id})...")
        try:
            from backend.bilibili_client import bilibili_client
            bilibili_client.connect(room_id)
            self.services['bilibili'] = bilibili_client
            logger.info("B站直播连接成功")
            return True
        except Exception as e:
            logger.error(f"连接B站直播失败: {e}")
            return False
    
    async def start_all(self):
        logger.info("=" * 60)
        logger.info("YHLZ 2.0 服务启动")
        logger.info("=" * 60)
        
        self.running = True
        
        results = []
        
        results.append(("后端服务", self.start_backend()))
        
        for i in range(20):
            if self._check_backend_ready():
                logger.info("后端服务就绪")
                break
            logger.info(f"等待后端服务启动... ({i+1}/20)")
            time.sleep(1)
        
        results.append(("音频服务", self.start_audio()))
        results.append(("视觉服务", self.start_vision()))
        results.append(("B站直播", self.start_bilibili()))
        
        logger.info("")
        logger.info("启动结果:")
        for name, success in results:
            status = "✅" if success else "❌"
            logger.info(f"  {status} {name}")
        
        logger.info("=" * 60)
        
        return all(s for _, s in results)
    
    def _check_backend_ready(self):
        try:
            import requests
            response = requests.get(
                f"http://localhost:{self.config.get('port', 8000)}/health",
                timeout=2
            )
            return response.status_code == 200
        except:
            return False
    
    def stop_all(self):
        logger.info("停止所有服务...")
        
        for name, service in self.services.items():
            try:
                import subprocess
                if name == 'backend' and hasattr(service, 'terminate'):
                    service.terminate()
                    service.wait(timeout=5)
                elif name == 'vision' and hasattr(service, 'stop'):
                    service.stop()
                elif name == 'audio' and hasattr(service, 'stop'):
                    service.stop()
                elif name == 'bilibili' and hasattr(service, 'disconnect'):
                    service.disconnect()
                
                logger.info(f"已停止: {name}")
            except Exception as e:
                logger.error(f"停止 {name} 失败: {e}")
        
        self.services.clear()
        self.running = False
        
        logger.info("所有服务已停止")
    
    def stop_module(self, module_name):
        try:
            import requests
            response = requests.post(
                f"http://localhost:{self.config.get('port', 8000)}/modules/stop",
                json={"module_name": module_name},
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"停止模块 {module_name} 失败: {e}")
            return False
    
    def get_module_status(self, module_name):
        try:
            import requests
            response = requests.get(
                f"http://localhost:{self.config.get('port', 8000)}/modules/status",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("modules", {}).get(module_name, {}).get("status", "stopped")
        except Exception as e:
            logger.error(f"获取模块状态失败: {e}")
        return "stopped"


class FaceTracker(QThread):
    """面部捕捉线程"""
    
    face_data_signal = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self._is_running = False
        self._cap = None
    
    def run(self):
        self._is_running = True
        
        try:
            import cv2
            
            self._cap = cv2.VideoCapture(0)
            
            if not self._cap.isOpened():
                logger.error("无法打开摄像头")
                return
            
            while self._is_running:
                success, frame = self._cap.read()
                
                if not success:
                    continue
                
                face_data = self._detect_basic_face(frame)
                if face_data:
                    self.face_data_signal.emit(face_data)
                
                time.sleep(0.05)
                
        except Exception as e:
            logger.error(f"面部捕捉失败: {e}")
            
        finally:
            if self._cap:
                self._cap.release()
    
    def _detect_basic_face(self, frame) -> dict:
        try:
            import cv2
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            
            if len(faces) > 0:
                x, y, w, h = faces[0]
                
                center_x = (x + w // 2) / frame.shape[1]
                center_y = (y + h // 2) / frame.shape[0]
                
                return {
                    "eye_open": 1.0,
                    "mouth_open": 0.0,
                    "head_x": (center_x - 0.5) * 2,
                    "head_y": (center_y - 0.5) * 2,
                    "expression": "NEUTRAL"
                }
            
        except Exception as e:
            logger.debug(f"基础面部检测失败: {e}")
            
        return None
    
    def stop(self):
        self._is_running = False
        self.wait()


class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, service_manager, parent=None):
        super().__init__(parent)
        self._service_manager = service_manager
        self.setWindowTitle("设置")
        self.setFixedSize(400, 350)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        config = self._service_manager.config
        
        port_group = QGroupBox("服务设置")
        port_layout = QFormLayout(port_group)
        
        self.port_edit = QLineEdit(str(config.get('port', 8000)))
        port_layout.addRow("端口:", self.port_edit)
        
        self.host_edit = QLineEdit(config.get('host', '0.0.0.0'))
        port_layout.addRow("绑定地址:", self.host_edit)
        
        layout.addWidget(port_group)
        
        features_group = QGroupBox("功能开关")
        features_layout = QVBoxLayout(features_group)
        
        self.vision_check = QCheckBox("启用视觉功能")
        self.vision_check.setChecked(config.get('enable_vision', True))
        features_layout.addWidget(self.vision_check)
        
        self.audio_check = QCheckBox("启用音频功能")
        self.audio_check.setChecked(config.get('enable_audio', True))
        features_layout.addWidget(self.audio_check)
        
        self.live2d_check = QCheckBox("启用Live2D")
        self.live2d_check.setChecked(config.get('enable_live2d', True))
        features_layout.addWidget(self.live2d_check)
        
        layout.addWidget(features_group)
        
        bilibili_group = QGroupBox("B站直播")
        bilibili_layout = QFormLayout(bilibili_group)
        
        self.bilibili_check = QCheckBox("启用B站直播")
        self.bilibili_check.setChecked(config.get('enable_bilibili', False))
        bilibili_layout.addRow(self.bilibili_check)
        
        self.room_id_edit = QLineEdit(config.get('bilibili_room_id', ''))
        bilibili_layout.addRow("房间ID:", self.room_id_edit)
        
        layout.addWidget(bilibili_group)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_settings)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
    
    def _save_settings(self):
        config = self._service_manager.config
        
        try:
            config['port'] = int(self.port_edit.text())
        except ValueError:
            pass
        
        config['host'] = self.host_edit.text()
        config['enable_vision'] = self.vision_check.isChecked()
        config['enable_audio'] = self.audio_check.isChecked()
        config['enable_live2d'] = self.live2d_check.isChecked()
        config['enable_bilibili'] = self.bilibili_check.isChecked()
        config['bilibili_room_id'] = self.room_id_edit.text()
        
        self._service_manager.save_config()
        
        QMessageBox.information(self, "提示", "设置已保存")
        self.close()


class DesktopAvatar(QWidget):
    """桌面虚拟角色窗口（WebView版）
    
    - 无边框透明窗口 + 置顶
    - WebSocket 实时同步口型/表情/事件
    - 三正弦叠加口型同步
    - 视线状态机 (viewing/thinking/replying)
    """
    
    # 视线状态枚举
    GAZE_VIEWING = "viewing"       # 看聊天区
    GAZE_THINKING = "thinking"     # 思考中
    GAZE_REPLYING = "replying"     # 回复中(直视)
    GAZE_IDLE = "idle"             # 待机(跟随鼠标)
    
    # 视线目标映射 (x, y): 归一化到 [0,1]
    GAZE_TARGETS = {
        GAZE_VIEWING: (0.25, 0.4),    # 看左下(聊天区)
        GAZE_THINKING: (0.65, 0.3),   # 看右上(思考气泡)
        GAZE_REPLYING: (0.5, 0.5),    # 直视用户
        GAZE_IDLE: (0.5, 0.5),        # 默认正中
    }
    
    def __init__(self, service_manager, parent=None):
        super().__init__(parent)
        
        self._service_manager = service_manager
        self._face_tracker = FaceTracker()
        self._is_speaking = False
        self._dragging = False
        self._drag_start_pos = QPoint()
        
        # 口型状态
        self._mouth_phase = 0.0        # 三正弦相位
        self._mouth_target = 0.0       # 目标口型值
        self._mouth_current = 0.0      # 当前口型值(平滑后)
        
        # 视线状态
        self._gaze_state = self.GAZE_IDLE
        self._gaze_x = 0.5
        self._gaze_y = 0.5
        self._gaze_target_x = 0.5
        self._gaze_target_y = 0.5
        
        # 情感状态
        self._current_emotion = "neutral"
        self._emotion_intensity = 1.0
        
        self._model_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            'assets', 'live2d', 'hiyori_vts'
        )
        
        self._init_window()
        self._init_ui()
        self._init_context_menu()
        self._init_ws_client()
        self._init_connections()
        
        logger.info("桌面虚拟角色（WebView版）初始化完成")
    
    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        screen_geometry = QApplication.desktop().screenGeometry()
        self.resize(320, 480)
        
        x = screen_geometry.width() - self.width() - 20
        y = screen_geometry.height() - self.height() - 100
        self.move(x, y)
        
        self.setCursor(Qt.PointingHandCursor)
    
    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        self._live2d_widget = Live2DWebWidget(self._model_path)
        self._live2d_widget.setFixedSize(320, 480)
        layout.addWidget(self._live2d_widget)
        logger.info("使用QWebEngineView渲染Live2D")
        
        self.setLayout(layout)
    
    def _init_context_menu(self):
        self._context_menu = QMenu(self)
        
        settings_action = QAction("⚙️ 设置", self)
        settings_action.triggered.connect(self._show_settings)
        self._context_menu.addAction(settings_action)
        
        self._context_menu.addSeparator()
        
        model_menu = QMenu("🎭 切换模型", self)
        self._context_menu.addMenu(model_menu)
        self._populate_model_menu(model_menu)
        
        self._context_menu.addSeparator()
        
        chat_action = QAction("💬 开始对话", self)
        chat_action.triggered.connect(self._start_chat)
        self._context_menu.addAction(chat_action)
        
        vision_action = QAction("👁️ 视觉监测", self)
        vision_action.triggered.connect(self._toggle_vision)
        self._context_menu.addAction(vision_action)
        
        tracking_action = QAction("🖼️ 面部捕捉", self)
        tracking_action.setCheckable(True)
        tracking_action.setChecked(False)
        tracking_action.toggled.connect(self._toggle_tracking)
        self._context_menu.addAction(tracking_action)
        
        self._context_menu.addSeparator()
        
        quit_action = QAction("❌ 退出", self)
        quit_action.triggered.connect(self._exit_app)
        self._context_menu.addAction(quit_action)
    
    def _populate_model_menu(self, menu):
        live2d_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'live2d')
        if os.path.exists(live2d_dir):
            for item in os.listdir(live2d_dir):
                item_path = os.path.join(live2d_dir, item)
                if os.path.isdir(item_path):
                    json_files = [f for f in os.listdir(item_path) if f.endswith('.model3.json')]
                    if json_files:
                        action = QAction(item, self)
                        action.triggered.connect(lambda checked, path=item_path: self._switch_model(path))
                        menu.addAction(action)
    
    def _switch_model(self, model_path):
        if self._live2d_widget.switch_model(model_path):
            QMessageBox.information(self, "提示", f"已切换到模型: {os.path.basename(model_path)}")
        else:
            QMessageBox.warning(self, "错误", "切换模型失败")
    
    def _init_ws_client(self):
        """初始化 WebSocket 客户端，连接后端 /ws/avatar"""
        self._ws_client = AvatarWSClient(self)
        self._ws_client.connected_signal.connect(self._on_ws_connected)
        self._ws_client.disconnected_signal.connect(self._on_ws_disconnected)
        self._ws_client.mouth_sync_signal.connect(self._on_mouth_sync)
        self._ws_client.emotion_change_signal.connect(self._on_emotion_change)
        self._ws_client.speech_start_signal.connect(self._on_speech_start)
        self._ws_client.speech_end_signal.connect(self._on_speech_end)
        
        # 延迟启动 WS 连接，等后端就绪
        QTimer.singleShot(2000, self._ws_client.start)
    
    def _init_connections(self):
        self._face_tracker.face_data_signal.connect(self._on_face_data)
        
        # 主循环定时器：驱动口型动画 + 视线补间
        self._frame_timer = QTimer()
        self._frame_timer.timeout.connect(self._on_frame_update)
        self._frame_timer.start(16)  # ~60fps
    
    # ==================== 口型同步：三正弦叠加 ====================
    
    def _on_frame_update(self):
        """每帧更新：口型动画 + 视线补间"""
        if not self._live2d_widget or not self._live2d_widget._is_initialized:
            return
        
        # 口型同步
        if self._is_speaking:
            self._mouth_phase += 0.12
            # 三正弦叠加: 0.4*sin(2.5φ) + 0.3*sin(1.8φ) + 0.3*sin(3.3φ)
            # 归一化到 [0, 1]
            raw = (0.4 * math.sin(2.5 * self._mouth_phase) +
                   0.3 * math.sin(1.8 * self._mouth_phase) +
                   0.3 * math.sin(3.3 * self._mouth_phase))
            self._mouth_target = (raw + 1.0) / 2.0  # 映射 [-1,1] -> [0,1]
        else:
            self._mouth_target = 0.0
        
        # 平滑过渡
        self._mouth_current += (self._mouth_target - self._mouth_current) * 0.3
        self._live2d_widget.set_mouth_open(self._mouth_current)
        
        # 视线补间 (ease-out quad)
        t = 0.05
        self._gaze_x += (self._gaze_target_x - self._gaze_x) * t
        self._gaze_y += (self._gaze_target_y - self._gaze_y) * t
        self._live2d_widget.set_look_at(self._gaze_x, self._gaze_y)
    
    # ==================== WebSocket 事件处理 ====================
    
    def _on_ws_connected(self):
        """WS 连接成功"""
        logger.info("Live2D 同步已连接，发送状态上报")
        self._ws_client.send_status({
            "model": os.path.basename(self._model_path),
            "is_speaking": self._is_speaking,
            "emotion": self._current_emotion,
            "gaze_state": self._gaze_state
        })
    
    def _on_ws_disconnected(self):
        """WS 断开"""
        self._is_speaking = False
        self._mouth_target = 0.0
    
    def _on_mouth_sync(self, value: float):
        """后端驱动口型 (RMS 能量值)"""
        self._mouth_target = value
        self._mouth_current += (value - self._mouth_current) * 0.5
    
    def _on_emotion_change(self, emotion: str, intensity: float):
        """情感变化 -> 驱动 Live2D 表情和光效"""
        self._current_emotion = emotion
        self._emotion_intensity = intensity
        
        if self._live2d_widget:
            self._live2d_widget.set_emotion_with_intensity(emotion, intensity)
    
    def _on_speech_start(self):
        """开始说话 -> 启动口型 + 视线切换到直视"""
        self._is_speaking = True
        self._mouth_phase = 0.0
        self.set_gaze_state(self.GAZE_REPLYING)
    
    def _on_speech_end(self):
        """说话结束 -> 口型归零 + 视线恢复"""
        self._is_speaking = False
        self._mouth_target = 0.0
        # 延迟恢复视线，避免突兀
        QTimer.singleShot(500, lambda: self.set_gaze_state(self.GAZE_IDLE))
    
    # ==================== 视线状态机 ====================
    
    def set_gaze_state(self, state: str):
        """切换视线状态"""
        if state not in self.GAZE_TARGETS:
            return
        self._gaze_state = state
        target = self.GAZE_TARGETS[state]
        self._gaze_target_x = target[0]
        self._gaze_target_y = target[1]
        logger.debug(f"视线状态: {state} -> ({self._gaze_target_x:.2f}, {self._gaze_target_y:.2f})")
    
    def _on_face_data(self, face_data: dict):
        if self._live2d_widget:
            head_x = face_data.get('head_x', 0)
            head_y = face_data.get('head_y', 0)
            self._live2d_widget.set_look_at(0.5 + head_x * 0.5, 0.5 + head_y * 0.5)
    
    def _show_settings(self):
        dialog = SettingsDialog(self._service_manager, self)
        dialog.exec_()
    
    def _toggle_tracking(self, enabled):
        if enabled:
            self._face_tracker.start()
            QMessageBox.information(self, "提示", "面部捕捉已启动")
        else:
            self._face_tracker.stop()
            QMessageBox.information(self, "提示", "面部捕捉已停止")
    
    def _start_chat(self):
        """开始对话"""
        self.set_gaze_state(self.GAZE_THINKING)
        
        try:
            import requests
            response = requests.post(
                "http://localhost:8000/modules/start",
                json={"module_name": "asr"},
                timeout=5
            )
            
            asyncio.ensure_future(self._send_chat_message("你好"))
            
            self.set_speaking(True)
            
            QMessageBox.information(self, "提示", "已开始对话")
        except Exception as e:
            logger.error(f"开始对话失败: {e}")
            self.set_gaze_state(self.GAZE_IDLE)
            QMessageBox.warning(self, "错误", f"启动对话失败: {str(e)}")
    
    async def _send_chat_message(self, text):
        try:
            import requests
            response = requests.post(
                "http://localhost:8000/chat",
                json={"text": text, "tool_mode": "auto"},
                stream=True,
                timeout=60
            )
            
            for line in response.iter_lines():
                if line:
                    try:
                        line_text = line.decode('utf-8')
                        if line_text.startswith('data: '):
                            data = json.loads(line_text[6:])
                            if 'is_done' in data and data['is_done']:
                                self.set_speaking(False)
                    except:
                        pass
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self.set_speaking(False)
    
    def _toggle_vision(self):
        try:
            vision_status = self._service_manager.get_module_status("vision")
            
            if vision_status == "running":
                self._service_manager.stop_module("vision")
                QMessageBox.information(self, "提示", "视觉监测已停止")
            else:
                self._service_manager.start_vision()
                QMessageBox.information(self, "提示", "视觉监测已启动")
        except Exception as e:
            logger.error(f"视觉监测操作失败: {e}")
            QMessageBox.warning(self, "错误", f"连接失败: {str(e)}")
    
    def _exit_app(self):
        reply = QMessageBox.question(
            self, "退出确认", "确定要退出YHLZ 2.0吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._service_manager.stop_all()
            QApplication.quit()
    
    def set_speaking(self, is_speaking: bool):
        """设置说话状态（供外部调用）"""
        self._is_speaking = is_speaking
        if is_speaking:
            self._mouth_phase = 0.0
            self.set_gaze_state(self.GAZE_REPLYING)
        else:
            self._mouth_target = 0.0
            QTimer.singleShot(500, lambda: self.set_gaze_state(self.GAZE_IDLE))
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        
        elif event.button() == Qt.RightButton:
            self._context_menu.exec_(event.globalPos())
            event.accept()
    
    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_start_pos)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
    
    def closeEvent(self, event):
        self._face_tracker.stop()
        self._ws_client.stop()
        event.accept()


class Live2DControlAPI:
    """Live2D控制API，供元亨调用"""
    
    _emotion_expression_map = {
        "happy": ["happy", "smile"],
        "sad": ["sad", "cry"],
        "angry": ["angry", "frown"],
        "surprised": ["surprised", "shock"],
        "excited": ["happy", "excited"],
        "neutral": ["default", "normal"]
    }
    
    def __init__(self, avatar):
        self._avatar = avatar
    
    def set_expression(self, expression_name):
        if self._avatar and self._avatar._live2d_widget:
            self._avatar._live2d_widget.set_expression(expression_name)
            return {"success": True, "message": f"已设置表情: {expression_name}"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def set_speaking(self, is_speaking):
        if self._avatar:
            self._avatar.set_speaking(is_speaking)
            return {"success": True, "message": f"说话状态: {'开启' if is_speaking else '关闭'}"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def set_look_at(self, x, y):
        if self._avatar and self._avatar._live2d_widget:
            self._avatar._live2d_widget.set_look_at(x, y)
            return {"success": True, "message": f"视线已设置: ({x}, {y})"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def switch_model(self, model_name):
        if self._avatar:
            live2d_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'live2d', model_name)
            if os.path.exists(live2d_dir):
                self._avatar._switch_model(live2d_dir)
                return {"success": True, "message": f"已切换模型: {model_name}"}
            return {"success": False, "message": f"模型不存在: {model_name}"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def trigger_motion(self, motion_group):
        if self._avatar and self._avatar._live2d_widget:
            self._avatar._live2d_widget.start_motion(motion_group)
            return {"success": True, "message": f"已触发动作: {motion_group}"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def set_emotion(self, emotion_name):
        if self._avatar and self._avatar._live2d_widget:
            self._avatar._live2d_widget.set_emotion(emotion_name)
            expressions = self._emotion_expression_map.get(emotion_name, [])
            for expr in expressions:
                try:
                    self._avatar._live2d_widget.set_expression(expr)
                    break
                except:
                    continue
            return {"success": True, "message": f"已设置情感: {emotion_name}"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def set_emotion_with_intensity(self, emotion_name, intensity):
        if self._avatar and self._avatar._live2d_widget:
            self._avatar._live2d_widget.set_emotion_with_intensity(emotion_name, intensity)
            expressions = self._emotion_expression_map.get(emotion_name, [])
            for expr in expressions:
                try:
                    self._avatar._live2d_widget.set_expression(expr)
                    break
                except:
                    continue
            return {"success": True, "message": f"已设置情感: {emotion_name} (强度: {intensity})"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def set_glow_color(self, color):
        if self._avatar and self._avatar._live2d_widget:
            self._avatar._live2d_widget.set_glow_color(color)
            return {"success": True, "message": f"已设置光效颜色: {color}"}
        return {"success": False, "message": "Live2D未初始化"}
    
    def get_status(self):
        if self._avatar and self._avatar._live2d_widget:
            model_info = self._avatar._live2d_widget.get_model_info()
            return {
                "success": True,
                "model": os.path.basename(self._avatar._model_path),
                "is_speaking": self._avatar._is_speaking,
                "is_initialized": self._avatar._live2d_widget._is_initialized,
                "current_emotion": self._avatar._live2d_widget.get_current_emotion(),
                "model_info": model_info
            }
        return {"success": False, "message": "Live2D未初始化"}
    
    def get_available_models(self):
        live2d_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'live2d')
        models = []
        if os.path.exists(live2d_dir):
            for item in os.listdir(live2d_dir):
                item_path = os.path.join(live2d_dir, item)
                if os.path.isdir(item_path):
                    json_files = [f for f in os.listdir(item_path) if f.endswith('.model3.json')]
                    if json_files:
                        models.append(item)
        return {"success": True, "models": models}


def create_tray_icon(app: QApplication, avatar: DesktopAvatar) -> QSystemTrayIcon:
    tray_icon = QSystemTrayIcon()
    
    menu = QMenu()
    
    show_action = QAction("显示角色", app)
    show_action.triggered.connect(avatar.show)
    menu.addAction(show_action)
    
    hide_action = QAction("隐藏角色", app)
    hide_action.triggered.connect(avatar.hide)
    menu.addAction(hide_action)
    
    exit_action = QAction("退出", app)
    exit_action.triggered.connect(app.quit)
    menu.addAction(exit_action)
    
    tray_icon.setContextMenu(menu)
    tray_icon.show()
    
    return tray_icon


async def start_services(service_manager):
    await service_manager.start_all()


def _check_and_kill_existing_instance():
    ports = [8000]
    killed_pids = set()
    
    try:
        import subprocess
        import os
        
        current_pid = os.getpid()
        
        for port in ports:
            try:
                import requests
                response = requests.get(f"http://localhost:{port}/health", timeout=2)
                if response.status_code == 200:
                    logger.info(f"端口 {port} 已被后端服务占用，跳过终止")
                    return
            except:
                pass
            
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True
            )
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            if pid != str(current_pid) and pid not in killed_pids:
                                try:
                                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
                                    killed_pids.add(pid)
                                    logger.info(f"已终止占用端口 {port} 的进程 (PID: {pid})")
                                except Exception as e:
                                    logger.warning(f"终止进程失败: {e}")
                                
    except Exception as e:
        logger.warning(f"检查端口占用失败: {e}")


def main():
    _check_and_kill_existing_instance()
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    service_manager = ServiceManager()
    
    def run_app():
        avatar = DesktopAvatar(service_manager)
        avatar.show()
        
        tray_icon = create_tray_icon(app, avatar)
        
        app.exec_()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.run_until_complete(start_services(service_manager))
    
    run_app()


if __name__ == "__main__":
    main()