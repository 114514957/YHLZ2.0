"""
YHLZ 2.0 Live2D 桌面虚拟角色（pygame + live2d.v3 原生渲染版）
- 无边框透明窗口：pygame.NOFRAME + win32gui 黑色透传
- 原生 Live2D 渲染：live2d.v3 直接 OpenGL 绘制
- 自动眨眼、呼吸、视线跟踪
- 三正弦叠加口型同步
- WebSocket 连接后端实时同步

重要：必须先在 pygame 中创建 OpenGL 窗口，再 import live2d.v3
      否则 DLL 加载顺序冲突导致 ACCESS_VIOLATION 崩溃
"""

import sys
import os
import json
import time
import math
import socket
import threading
import logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Live2D.Pygame")

# ==================== 依赖检查（延迟导入） ====================
# 注意：pygame 和 live2d.v3 必须在窗口创建后按顺序导入，避免 DLL 冲突

try:
    import win32gui
    import win32con
    import win32api
except ImportError:
    logger.error("pywin32 未安装，请执行: pip install pywin32")
    sys.exit(1)

try:
    import websocket
except ImportError:
    websocket = None
    logger.warning("websocket-client 未安装，将无法连接后端同步")


# ==================== 配置 ====================

# 模型目录搜索路径
MODEL_DIRS = [
    Path(__file__).parent / "assets" / "live2d" / "hiyori_vts",
    Path(__file__).parent / "assets" / "live2d" / "haru",
    Path(__file__).parent / "assets" / "live2d" / "mao",
    Path(__file__).parent / "models" / "hiyori_vts",
]

WINDOW_WIDTH = 400
WINDOW_HEIGHT = 560
FPS = 60

# 缩放范围
SCALE_MIN = 0.3
SCALE_MAX = 3.0
SCALE_STEP = 0.1

# 后端 WebSocket 地址
WS_URL = "ws://localhost:8000/ws/avatar"

# 表情光效颜色映射
EMOTION_COLORS = {
    'happy':     (1.0, 0.85, 0.3),
    'sad':       (0.58, 0.44, 0.86),
    'angry':     (1.0, 0.42, 0.42),
    'surprised': (1.0, 0.65, 0.0),
    'excited':   (1.0, 0.27, 0.0),
    'neutral':   (0.25, 0.55, 0.88),
    'tired':     (0.44, 0.50, 0.56),
    'anxious':   (0.53, 0.81, 0.92),
}


# ==================== 模型查找 ====================

def find_model_dir():
    """查找 Live2D 模型目录"""
    for d in MODEL_DIRS:
        if d.exists():
            json_files = list(d.glob("*.model3.json"))
            if json_files:
                logger.info(f"找到模型: {d}")
                return d, json_files[0].name
    logger.error("未找到 Live2D 模型")
    return None, None


# ==================== WebSocket 客户端 ====================

class WSClient:
    """WebSocket 客户端，后台线程运行"""

    def __init__(self, url=WS_URL):
        self.url = url
        self.ws = None
        self.running = False
        self.thread = None
        self._reconnect_delay = 1
        self._max_delay = 30

        # 状态
        self.is_connected = False
        self.mouth_target = 0.0
        self.is_speaking = False
        self.current_emotion = "neutral"
        self.emotion_intensity = 1.0

        self._lock = threading.Lock()

    def start(self):
        if websocket is None:
            logger.warning("websocket-client 未安装，跳过 WebSocket")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass

    def _run(self):
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(ping_interval=10, ping_timeout=5)
            except Exception as e:
                logger.error(f"WebSocket 异常: {e}")

            if not self.running:
                break
            time.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, self._max_delay)

    def _on_open(self, ws):
        logger.info("Live2D 同步服务已连接")
        self.is_connected = True
        self._reconnect_delay = 1

    def _on_close(self, ws, code, msg):
        logger.info(f"WebSocket 断开: {code} {msg}")
        self.is_connected = False

    def _on_error(self, ws, error):
        logger.error(f"WebSocket 错误: {error}")

    def _on_message(self, ws, message):
        try:
            msg = json.loads(message)
            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            with self._lock:
                if msg_type == "mouth_sync":
                    self.mouth_target = data.get("value", 0.0)
                elif msg_type == "speech_start":
                    self.is_speaking = True
                elif msg_type == "speech_end":
                    self.is_speaking = False
                    self.mouth_target = 0.0
                elif msg_type == "emotion_change":
                    self.current_emotion = data.get("emotion", "neutral")
                    self.emotion_intensity = data.get("intensity", 1.0)
        except Exception as e:
            logger.debug(f"消息处理: {e}")

    def get_mouth_target(self):
        with self._lock:
            return self.mouth_target

    def get_is_speaking(self):
        with self._lock:
            return self.is_speaking

    def get_emotion(self):
        with self._lock:
            return self.current_emotion, self.emotion_intensity


# ==================== 主程序 ====================

class Live2DDesktopAvatar:
    """Live2D 桌面虚拟角色"""

    def __init__(self):
        self.model = None
        self.model_dir = None
        self.model_json = None
        self.running = False
        self.ws_client = WSClient()

        # 口型状态
        self.mouth_phase = 0.0
        self.mouth_current = 0.0

        # 视线状态
        self.gaze_state = "idle"
        self.gaze_x = 0.5
        self.gaze_y = 0.5
        self.gaze_target_x = 0.5
        self.gaze_target_y = 0.5

        # 缩放与偏移
        self.scale = 1.0          # 当前缩放倍率
        self.offset_x = 0.0       # 模型水平偏移（归一化）
        self.offset_y = 0.0       # 模型垂直偏移
        self.canvas_w = 1.0       # 模型原生画布宽
        self.canvas_h = 1.0       # 模型原生画布高
        self.win_w = WINDOW_WIDTH
        self.win_h = WINDOW_HEIGHT

        # 拖动状态
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.win_x = 0
        self.win_y = 0

        # 右键菜单
        self.show_menu = False
        self.menu_x = 0
        self.menu_y = 0
        self.menu_hovered = -1  # 当前悬停的菜单项索引
        self.menu_items = [
            ("放大", "zoom_in"),
            ("缩小", "zoom_out"),
            ("重置缩放", "reset_scale"),
            ("重置位置", "reset_pos"),
            ("显示帧率", "toggle_fps"),
            ("退出桌宠", "quit"),
        ]
        self._font_cache = None
        self._menu_textures = {}  # 缓存的菜单文字纹理

        # 调试
        self.show_fps = False
        self._frame_count = 0
        self._fps_timer = time.time()
        self._current_fps = 0

    def init_window(self):
        """初始化 pygame 无边框透明窗口"""
        os.environ['SDL_VIDEO_WINDOW_POS'] = "0,0"

        import pygame
        from pygame.locals import DOUBLEBUF, OPENGL, NOFRAME, RESIZABLE

        pygame.init()
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
        pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
        pygame.display.gl_set_attribute(pygame.GL_ALPHA_SIZE, 8)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)

        # 窗口大小取屏幕高度 60%，保持宽高比
        screen_w = win32api.GetSystemMetrics(0)
        screen_h = win32api.GetSystemMetrics(1)
        target_h = int(screen_h * 0.6)
        target_w = int(target_h * (WINDOW_WIDTH / WINDOW_HEIGHT))
        self.win_w = target_w
        self.win_h = target_h

        self.screen = pygame.display.set_mode(
            (self.win_w, self.win_h),
            NOFRAME | DOUBLEBUF | OPENGL | RESIZABLE,
            vsync=1
        )
        pygame.display.set_caption("元亨桌宠")

        # 获取窗口句柄，设置透明和置顶
        self.hwnd = pygame.display.get_wm_info()['window']

        ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_LAYERED
        ex_style |= win32con.WS_EX_TOPMOST
        ex_style |= win32con.WS_EX_TOOLWINDOW
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)

        # 黑色透传：将 RGB(0,0,0) 变为透明
        win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 0, win32con.LWA_COLORKEY)

        # 窗口位置：右下角
        self.win_x = screen_w - self.win_w - 20
        self.win_y = screen_h - self.win_h - 80
        win32gui.SetWindowPos(
            self.hwnd, win32con.HWND_TOPMOST,
            self.win_x, self.win_y,
            self.win_w, self.win_h,
            win32con.SWP_SHOWWINDOW
        )

        self.clock = pygame.time.Clock()
        logger.info(f"窗口初始化完成: {self.win_w}x{self.win_h}")

    def init_live2d(self):
        """初始化 Live2D 并加载模型（必须在 init_window 之后调用）"""
        self.model_dir, self.model_json = find_model_dir()
        if not self.model_dir:
            return False

        import live2d.v3 as l2d

        logger.info("初始化 Live2D...")
        l2d.init()
        l2d.glInit()

        self.model = l2d.LAppModel()
        self.model.SetAutoBreathEnable(True)
        self.model.SetAutoBlinkEnable(True)

        # 使用绝对路径加载模型（不用 os.chdir，避免崩溃）
        model_json_path = str(self.model_dir / self.model_json)
        try:
            logger.info(f"加载模型: {model_json_path}")
            self.model.LoadModelJson(model_json_path)
            self.model.Resize(self.win_w, self.win_h)

            # 获取模型原生画布尺寸，计算初始缩放
            self.canvas_w, self.canvas_h = self.model.GetCanvasSize()
            model_aspect = self.canvas_w / self.canvas_h if self.canvas_h > 0 else 1.0
            win_aspect = self.win_w / self.win_h
            if model_aspect > win_aspect:
                self.scale = self.win_w / self.canvas_w
            else:
                self.scale = self.win_h / self.canvas_h
            self.model.SetScale(self.scale)

            logger.info(f"Live2D 模型加载成功 (canvas: {self.canvas_w:.1f}x{self.canvas_h:.1f}, scale: {self.scale:.2f})")
            return True
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _make_window_transparent(self):
        """确保窗口透明属性生效"""
        ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
        win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 0, win32con.LWA_COLORKEY)

    def handle_event(self, event):
        """处理 pygame 事件"""
        import pygame
        if event.type == pygame.QUIT:
            self.running = False

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # 左键
                mx, my = pygame.mouse.get_pos()
                if self.show_menu:
                    idx = self._hit_test_menu(mx, my)
                    if idx >= 0:
                        self._execute_menu(idx)
                    self.show_menu = False
                else:
                    self.dragging = True
                    self.drag_start_x, self.drag_start_y = mx, my
                    rect = win32gui.GetWindowRect(self.hwnd)
                    self.win_x, self.win_y = rect[0], rect[1]

            elif event.button == 3:  # 右键
                self.show_menu = True
                self.menu_x, self.menu_y = pygame.mouse.get_pos()
                self.menu_hovered = -1

            elif event.button == 4:  # 滚轮上
                self._handle_scroll(1)
            elif event.button == 5:  # 滚轮下
                self._handle_scroll(-1)

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False

        elif event.type == pygame.MOUSEMOTION:
            mx, my = pygame.mouse.get_pos()
            self.gaze_target_x = mx / self.win_w
            self.gaze_target_y = my / self.win_h

            if self.model:
                self.model.Drag(mx, my)

            if self.show_menu:
                self.menu_hovered = self._hit_test_menu(mx, my)
            elif self.dragging:
                dx = mx - self.drag_start_x
                dy = my - self.drag_start_y
                self.win_x += dx
                self.win_y += dy
                win32gui.SetWindowPos(
                    self.hwnd, win32con.HWND_TOPMOST,
                    self.win_x, self.win_y,
                    self.win_w, self.win_h,
                    win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                )
                self.drag_start_x, self.drag_start_y = mx, my

        elif event.type == pygame.VIDEORESIZE:
            self.win_w = event.w
            self.win_h = event.h
            if self.model:
                self.model.Resize(self.win_w, self.win_h)
                # 重新计算适配缩放
                model_aspect = self.canvas_w / self.canvas_h if self.canvas_h > 0 else 1.0
                win_aspect = self.win_w / self.win_h
                if model_aspect > win_aspect:
                    self.scale = self.win_w / self.canvas_w
                else:
                    self.scale = self.win_h / self.canvas_h
                self.model.SetScale(self.scale)
            self._make_window_transparent()

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_f:
                self.show_fps = not self.show_fps
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self._handle_scroll(1)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self._handle_scroll(-1)
            elif event.key == pygame.K_0:
                self._reset_scale()
            elif event.key == pygame.K_r:
                self._reset_position()

    def _handle_scroll(self, direction):
        """滚轮缩放"""
        if not self.model:
            return
        self.scale += direction * SCALE_STEP
        self.scale = max(SCALE_MIN, min(SCALE_MAX, self.scale))
        self.model.SetScale(self.scale)
        logger.debug(f"缩放: {self.scale:.1f}x")

    def _reset_scale(self):
        """重置缩放到适配窗口"""
        if not self.model:
            return
        model_aspect = self.canvas_w / self.canvas_h if self.canvas_h > 0 else 1.0
        win_aspect = self.win_w / self.win_h
        if model_aspect > win_aspect:
            self.scale = self.win_w / self.canvas_w
        else:
            self.scale = self.win_h / self.canvas_h
        self.model.SetScale(self.scale)
        logger.info(f"缩放已重置: {self.scale:.1f}x")

    def _reset_position(self):
        """重置窗口位置到右下角"""
        screen_w = win32api.GetSystemMetrics(0)
        screen_h = win32api.GetSystemMetrics(1)
        self.win_x = screen_w - self.win_w - 20
        self.win_y = screen_h - self.win_h - 80
        win32gui.SetWindowPos(
            self.hwnd, win32con.HWND_TOPMOST,
            self.win_x, self.win_y,
            self.win_w, self.win_h,
            win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
        )
        logger.info("位置已重置")

    # ==================== 气泡右键菜单 ====================

    BUBBLE_W = 120
    BUBBLE_H = 32
    BUBBLE_GAP = 6
    BUBBLE_RADIUS = 16
    FONT_SIZE = 16

    def _hit_test_menu(self, mx, my):
        """检测鼠标是否在某个菜单项上，返回索引或 -1"""
        for i, (text, _) in enumerate(self.menu_items):
            bx = self.menu_x - self.BUBBLE_W // 2
            by = self.menu_y - (len(self.menu_items) - i) * (self.BUBBLE_H + self.BUBBLE_GAP)
            if bx <= mx <= bx + self.BUBBLE_W and by <= my <= by + self.BUBBLE_H:
                return i
        return -1

    def _execute_menu(self, idx):
        """执行菜单项"""
        if idx < 0 or idx >= len(self.menu_items):
            return
        _, action = self.menu_items[idx]
        logger.info(f"菜单: {self.menu_items[idx][0]}")
        if action == "zoom_in":
            self._handle_scroll(1)
        elif action == "zoom_out":
            self._handle_scroll(-1)
        elif action == "reset_scale":
            self._reset_scale()
        elif action == "reset_pos":
            self._reset_position()
        elif action == "toggle_fps":
            self.show_fps = not self.show_fps
        elif action == "quit":
            self.running = False

    def _render_menu(self):
        """渲染气泡右键菜单（OpenGL 2D 叠加）"""
        import pygame
        from OpenGL.GL import (
            glMatrixMode, glPushMatrix, glPopMatrix, glLoadIdentity,
            glOrtho, glEnable, glDisable, glBlendFunc, glColor4f,
            glBegin, glEnd, glVertex2f, glTexCoord2f,
            glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
            glDeleteTextures,
            GL_PROJECTION, GL_MODELVIEW, GL_TEXTURE_2D, GL_BLEND,
            GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_QUADS,
            GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_LINEAR,
            GL_RGBA, GL_UNSIGNED_BYTE, GL_TRIANGLE_FAN,
        )
        import math as _math

        if not self._font_cache:
            self._font_cache = pygame.font.SysFont("microsoft yahei", self.FONT_SIZE, bold=True)

        # 切换到 2D 正交投影
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.win_w, self.win_h, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDisable(GL_TEXTURE_2D)

        n = len(self.menu_items)
        for i, (text, _) in enumerate(self.menu_items):
            bx = self.menu_x - self.BUBBLE_W // 2
            by = self.menu_y - (n - i) * (self.BUBBLE_H + self.BUBBLE_GAP)
            hovered = (i == self.menu_hovered)

            # 气泡背景
            if hovered:
                glColor4f(0.35, 0.60, 0.95, 0.92)
            else:
                glColor4f(0.12, 0.14, 0.20, 0.88)

            self._draw_rounded_rect(bx, by, self.BUBBLE_W, self.BUBBLE_H, self.BUBBLE_RADIUS)

            # 气泡边框
            if hovered:
                glColor4f(0.50, 0.75, 1.0, 0.85)
            else:
                glColor4f(0.25, 0.28, 0.35, 0.70)
            self._draw_rounded_rect_outline(bx, by, self.BUBBLE_W, self.BUBBLE_H, self.BUBBLE_RADIUS, 1.5)

            # 文字
            tex_id = self._get_text_texture(text, hovered)
            if tex_id:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tex_id)
                glColor4f(1.0, 1.0, 1.0, 1.0)
                tw, th = self._font_cache.size(text)
                tx = bx + (self.BUBBLE_W - tw) / 2
                ty = by + (self.BUBBLE_H - th) / 2
                glBegin(GL_QUADS)
                glTexCoord2f(0, 0); glVertex2f(tx, ty)
                glTexCoord2f(1, 0); glVertex2f(tx + tw, ty)
                glTexCoord2f(1, 1); glVertex2f(tx + tw, ty + th)
                glTexCoord2f(0, 1); glVertex2f(tx, ty + th)
                glEnd()
                glDisable(GL_TEXTURE_2D)

        # 恢复 3D 投影
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
        glDisable(GL_BLEND)

    def _draw_rounded_rect(self, x, y, w, h, r):
        """绘制圆角矩形（填充）"""
        from OpenGL.GL import glBegin, glEnd, glVertex2f, GL_TRIANGLE_FAN
        import math as _math
        segments = 8
        # 主体矩形
        glBegin(GL_TRIANGLE_FAN)
        glVertex2f(x + r, y + r)
        glVertex2f(x + w - r, y + r)
        glVertex2f(x + w - r, y + h - r)
        glVertex2f(x + r, y + h - r)
        glEnd()
        # 四个角
        for cx, cy, start_ang in [
            (x + r, y + r, _math.pi),
            (x + w - r, y + r, _math.pi * 1.5),
            (x + w - r, y + h - r, 0),
            (x + r, y + h - r, _math.pi * 0.5),
        ]:
            glBegin(GL_TRIANGLE_FAN)
            glVertex2f(cx, cy)
            for j in range(segments + 1):
                a = start_ang + j * (_math.pi / 2) / segments
                glVertex2f(cx + _math.cos(a) * r, cy - _math.sin(a) * r)
            glEnd()

    def _draw_rounded_rect_outline(self, x, y, w, h, r, thickness):
        """绘制圆角矩形边框"""
        from OpenGL.GL import glBegin, glEnd, glVertex2f, glLineWidth, GL_LINE_LOOP
        import math as _math
        glLineWidth(thickness)
        segments = 12
        # 上边
        glBegin(GL_LINE_LOOP)
        for j in range(segments + 1):
            a = _math.pi + j * (_math.pi / 2) / segments
            glVertex2f(x + r + _math.cos(a) * r, y + r - _math.sin(a) * r)
        for j in range(segments + 1):
            a = _math.pi * 1.5 + j * (_math.pi / 2) / segments
            glVertex2f(x + w - r + _math.cos(a) * r, y + r - _math.sin(a) * r)
        for j in range(segments + 1):
            a = 0 + j * (_math.pi / 2) / segments
            glVertex2f(x + w - r + _math.cos(a) * r, y + h - r - _math.sin(a) * r)
        for j in range(segments + 1):
            a = _math.pi * 0.5 + j * (_math.pi / 2) / segments
            glVertex2f(x + r + _math.cos(a) * r, y + h - r - _math.sin(a) * r)
        glEnd()

    def _get_text_texture(self, text, hovered):
        """获取文字纹理（缓存）"""
        import pygame
        from OpenGL.GL import (
            glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
            GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
            GL_LINEAR, GL_RGBA, GL_UNSIGNED_BYTE,
        )
        cache_key = f"{text}_{hovered}"
        if cache_key in self._menu_textures:
            return self._menu_textures[cache_key]

        color = (255, 255, 255, 255) if hovered else (200, 200, 210, 255)
        surf = self._font_cache.render(text, True, color[:3])
        w, h = surf.get_size()

        # 创建 RGBA surface
        rgba = pygame.Surface((w, h), pygame.SRCALPHA)
        rgba.blit(surf, (0, 0))

        data = pygame.image.tostring(rgba, "RGBA", True)

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)

        self._menu_textures[cache_key] = tex_id
        return tex_id

    def update_mouth(self, dt):
        """更新口型动画：三正弦叠加"""
        is_speaking = self.ws_client.get_is_speaking()
        mouth_target = self.ws_client.get_mouth_target()

        if is_speaking and mouth_target > 0.01:
            # 后端驱动口型
            self.mouth_current += (mouth_target - self.mouth_current) * 0.5
        elif is_speaking:
            # 三正弦叠加自动口型
            self.mouth_phase += 0.12
            raw = (0.4 * math.sin(2.5 * self.mouth_phase) +
                   0.3 * math.sin(1.8 * self.mouth_phase) +
                   0.3 * math.sin(3.3 * self.mouth_phase))
            self.mouth_current = (raw + 1.0) / 2.0  # [-1,1] → [0,1]
        else:
            self.mouth_current *= 0.85  # 指数衰减归零

        if self.model:
            self.model.SetParameterValue("ParamMouthOpenY", self.mouth_current, 1.0)

    def update_gaze(self, dt):
        """更新视线：ease-out quad 补间"""
        t = 0.05
        self.gaze_x += (self.gaze_target_x - self.gaze_x) * t
        self.gaze_y += (self.gaze_target_y - self.gaze_y) * t

        if self.model:
            angle_x = (self.gaze_x - 0.5) * 30.0
            angle_y = (self.gaze_y - 0.5) * 30.0
            eye_x = (self.gaze_x - 0.5) * 1.0
            eye_y = (self.gaze_y - 0.5) * 1.0

            self.model.SetParameterValue("ParamAngleX", angle_x, 1.0)
            self.model.SetParameterValue("ParamAngleY", angle_y, 1.0)
            self.model.SetParameterValue("ParamEyeBallX", eye_x, 1.0)
            self.model.SetParameterValue("ParamEyeBallY", eye_y, 1.0)

    def render(self):
        """渲染一帧"""
        import live2d.v3 as l2d
        import pygame
        l2d.clearBuffer(0.0, 0.0, 0.0, 0.0)

        if self.model:
            self.model.Update()
            self.model.Draw()

        # 渲染气泡菜单（2D 叠加）
        if self.show_menu:
            self._render_menu()

        pygame.display.flip()

    def run(self):
        """主循环"""
        import pygame
        self.init_window()
        self._make_window_transparent()

        if not self.init_live2d():
            logger.error("模型加载失败，退出")
            return

        self.ws_client.start()
        self.running = True
        logger.info("桌宠主循环启动")

        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                self.handle_event(event)

            self.update_mouth(dt)
            self.update_gaze(dt)
            self.render()

            # FPS 统计
            self._frame_count += 1
            if time.time() - self._fps_timer > 2.0:
                self._current_fps = self._frame_count / (time.time() - self._fps_timer)
                self._frame_count = 0
                self._fps_timer = time.time()
                if self.show_fps:
                    pygame.display.set_caption(f"元亨桌宠 - FPS: {self._current_fps:.0f}")

        self.cleanup()

    def cleanup(self):
        """清理资源"""
        import live2d.v3 as l2d
        import pygame
        from OpenGL.GL import glDeleteTextures
        logger.info("正在清理...")
        self.ws_client.stop()
        # 清理菜单纹理
        for tex_id in self._menu_textures.values():
            try:
                glDeleteTextures([tex_id])
            except:
                pass
        self._menu_textures.clear()
        if self.model:
            self.model = None
        l2d.dispose()
        pygame.quit()
        logger.info("桌宠已退出")


# ==================== 入口 ====================

if __name__ == "__main__":
    avatar = Live2DDesktopAvatar()
    avatar.run()