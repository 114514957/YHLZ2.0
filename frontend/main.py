"""
YHLZ AI伙伴 前端主入口 (Frontend Runtime Shell Main)

职责:
    - 桌面主窗口: 核心启动节点按钮 + 伙伴状态层
    - 一键启动 (Startup Core) → 伙伴状态 (Runtime State)
    - 状态驱动动画 (Emotion State Manager → Avatar)
    - 隐藏开发模式: Ctrl+Shift+R → Runtime Console
    - 右键菜单: 设置 / 开发模式 / 退出

设计原则 (V10.1 Frontend Runtime Edition):
    - 不是聊天窗口: 无消息列表, 无输入框
    - 一键启动完整伙伴核心
    - 启动后只显示伙伴状态 (元亨 ONLINE / 思考中 / 学习中 / 待机)
    - 保持原 Live2D 透明桌宠风格

用法:
    python frontend/main.py
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

# 确保 UTF-8 输出 (Windows)
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)

# GUI 组件 (PyQt5 可选, 缺失时提供无 GUI 启动检查)
try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont, QKeySequence
    from PyQt5.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QMenu,
        QPushButton,
        QShortcut,
        QVBoxLayout,
        QWidget,
    )
    GUI_AVAILABLE = True
except ImportError:  # noqa: BLE001
    GUI_AVAILABLE = False
    # 占位 (无 GUI 环境保持类可导入)
    class QPushButton:  # noqa: N801
        pass

    class QWidget:  # noqa: N801
        pass

    class QLabel:  # noqa: N801
        pass

    class QMenu:  # noqa: N801
        pass

    class QDialog:  # noqa: N801
        pass

    class QVBoxLayout:  # noqa: N801
        pass

    class QApplication:  # noqa: N801
        pass


class CoreStartButton(QPushButton):
    """核心启动节点按钮 (◉ 启动元亨)"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("◉\n启动元亨", parent)
        self.setFixedSize(140, 140)
        self.setStyleSheet(
            "QPushButton {"
            "  border-radius: 70px;"
            "  background: rgba(40, 60, 90, 180);"
            "  color: white;"
            "  font-size: 16px;"
            "  border: 2px solid rgba(120, 160, 220, 160);"
            "}"
            "QPushButton:hover {"
            "  background: rgba(60, 90, 130, 200);"
            "}"
            "QPushButton:pressed {"
            "  background: rgba(30, 45, 70, 200);"
            "}"
        )


class RuntimeStatusWidget(QWidget):
    """运行状态层 (伙伴状态反馈)"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._name_label = QLabel("元亨")
        self._state_label = QLabel("IDLE")
        self._detail_label = QLabel("待机")
        for lbl in (self._name_label, self._state_label,
                    self._detail_label):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: white;")
            self._layout.addWidget(lbl)
        self._name_label.setStyleSheet(
            "color: white; font-size: 22px; font-weight: bold;"
        )
        self._state_label.setStyleSheet(
            "color: #6fd06f; font-size: 16px; font-weight: bold;"
        )

    def update_state(self, snapshot: Dict[str, Any]) -> None:
        """按运行时状态快照更新显示"""
        state = snapshot.get("state", "idle")
        state_map = {
            "idle": "IDLE", "initializing": "INITIALIZING",
            "online": "ONLINE", "thinking": "THINKING",
            "learning": "LEARNING", "waiting": "WAITING",
            "error": "ERROR",
        }
        detail_map = {
            "idle": "待机", "initializing": "初始化中",
            "online": "在线", "thinking": "思考中",
            "learning": "学习中", "waiting": "等待中",
            "error": "错误",
        }
        self._state_label.setText(state_map.get(state, state))
        self._detail_label.setText(detail_map.get(state, state))
        color = "#6fd06f" if state in ("online", "thinking",
                                       "learning") else \
            ("#e0b060" if state == "waiting" else
             ("#e07070" if state == "error" else "#b0b0b0"))
        self._state_label.setStyleSheet(
            f"color: {color}; font-size: 16px; font-weight: bold;"
        )


class MainWindow(QWidget):
    """主窗口 (透明/无边框/核心启动节点)"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("元亨")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        from frontend.runtime import (
            RuntimeEvent,
            RuntimeEventBus,
            RuntimeState,
            TraceManager,
        )
        from frontend.runtime.event import RUNTIME_EVENTS
        from frontend.startup import StartupCore
        from frontend.avatar import EmotionStateManager
        from frontend.monitor import RuntimeConsole
        from frontend.settings import SettingsManager

        self.runtime_state = RuntimeState()
        self.event_bus = RuntimeEventBus()
        self.trace = TraceManager()
        self.startup = StartupCore()
        self.emotion = EmotionStateManager()
        self.console = RuntimeConsole()
        self.settings = SettingsManager()
        self._init_ui()
        self._init_shortcuts()
        self._init_tray_menu()
        # 状态联动: Runtime State → 情绪 → 界面
        self.runtime_state.on_change(self._on_state_change)
        self.runtime_state.on_change(self.status_widget.update_state)
        self.emotion.on_change(self._on_emotion_change)

    def _init_ui(self) -> None:
        self.setFixedSize(320, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.status_widget = RuntimeStatusWidget()
        self.start_button = CoreStartButton()
        self.start_button.clicked.connect(self._on_start_clicked)
        layout.addWidget(self.status_widget)
        layout.addStretch()
        layout.addWidget(self.start_button, alignment=Qt.AlignCenter)
        layout.addStretch()

    def _init_shortcuts(self) -> None:
        # 隐藏开发模式: Ctrl+Shift+R → Runtime Console
        self.dev_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+R"), self,
        )
        self.dev_shortcut.activated.connect(self._open_console)

    def _init_tray_menu(self) -> None:
        self.menu = QMenu(self)
        self.menu.addAction("设置", self._open_settings)
        self.menu.addAction("开发模式 (Ctrl+Shift+R)",
                            self._open_console)
        self.menu.addSeparator()
        self.menu.addAction("退出", self.close)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.menu.exec_(self.mapToGlobal(pos)),
        )

    # ── 启动流程 ────────────────────────────────────────────────
    def _on_start_clicked(self) -> None:
        """核心启动节点点击 → 一键启动"""
        self.runtime_state.set_state("initializing")
        self.start_button.setEnabled(False)
        self.start_button.setText("启动中...")

        def _run_startup():
            try:
                results = self.startup.run()
                ok = all(
                    r["ok"] or r.get("skipped", False)
                    for r in results
                )
                self.trace.trace(
                    self.trace.begin_task("startup"),
                    "SYSTEM_READY" if ok else "ERROR",
                    "一键启动完成" if ok else "启动失败",
                )
                self.event_bus.publish(RuntimeEvent(
                    "SYSTEM_READY" if ok else "ERROR",
                    "一键启动完成" if ok else "启动失败",
                    {"steps": results},
                ))
                self.runtime_state.set_state(
                    "online" if ok else "error",
                )
            finally:
                self.start_button.setEnabled(True)
                self.start_button.setText("◉\n启动元亨")

        import threading
        threading.Thread(target=_run_startup, daemon=True).start()

    def _on_state_change(self, snapshot: Dict[str, Any]) -> None:
        """状态变更 → 情绪驱动"""
        self.emotion.on_companion_state(
            snapshot.get("state", "idle"),
        )

    def _on_emotion_change(self, snapshot: Dict[str, Any]) -> None:
        """情绪变更 → (后续可接 Live2D 渲染)"""
        logger.debug(
            f"[Avatar] emotion={snapshot.get('emotion')} "
            f"reason={snapshot.get('reason')}",
        )

    # ── 开发模式 ────────────────────────────────────────────────
    def _open_console(self) -> None:
        """打开 Runtime Console (隐藏开发模式)"""
        console = RuntimeConsoleDialog(self)
        console.exec_()

    def _open_settings(self) -> None:
        """打开设置"""
        dialog = QDialog(self)
        dialog.setWindowTitle("设置")
        label = QLabel(
            "基础 / AI / Memory / Developer 设置\n"
            "(由 SettingsManager 管理, 持久化到 frontend_settings.json)",
            dialog,
        )
        layout = QVBoxLayout(dialog)
        layout.addWidget(label)
        dialog.resize(360, 180)
        dialog.exec_()

    # ── 拖拽 ────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if hasattr(self, "_drag_pos") and \
                event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:
        if hasattr(self, "_drag_pos"):
            del self._drag_pos


class RuntimeConsoleDialog(QDialog):
    """Runtime Console (开发模式)"""

    def __init__(self, main_window: MainWindow,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Runtime Console [Developer]")
        self.setMinimumSize(420, 320)
        layout = QVBoxLayout(self)
        self.report_label = QLabel("")
        self.report_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px;"
        )
        self.report_label.setWordWrap(True)
        layout.addWidget(self.report_label)
        self._main = main_window
        self.refresh()

    def refresh(self) -> None:
        """刷新控制台 (System/AI/Memory/Trace)"""
        report = self._main.console.report()
        lines = [
            "═══ System ═══",
            f"Backend: {report['system']['backend']}",
            f"Latency: {report['system']['latency_ms']} ms",
            f"GPU: {report['system']['gpu_percent']}%",
            f"Memory: {report['system']['memory_percent']}%",
            "",
            "═══ AI ═══",
            f"Model: {report['ai']['model'] or '-'}",
            f"Route: {report['ai']['route']}",
            f"Token: {report['ai']['token_usage']}",
            "",
            "═══ Memory ═══",
            f"Read: {report['memory']['read']}",
            f"Write: {report['memory']['write']}",
            f"Conflict: {report['memory']['conflict']}",
            "",
            "═══ Trace ═══",
            f"Trace ID: {report['trace']['trace_id'] or '-'}",
            f"Task ID: {report['trace']['task_id'] or '-'}",
            f"Runtime ID: {report['trace']['runtime_id'] or '-'}",
        ]
        self.report_label.setText("\n".join(lines))


def main() -> int:
    """前端主入口"""
    if not GUI_AVAILABLE:
        print("[Frontend] PyQt5 不可用, 仅执行无界面启动检查")
        from frontend.startup import StartupCore
        results = StartupCore().run()
        for r in results:
            print(
                f"  [{'✓' if r['ok'] else '✗'}] {r['step']}: "
                f"{r['detail']}"
            )
        return 0 if all(r["ok"] for r in results) else 1

    app = QApplication(sys.argv)
    app.setApplicationName("元亨")
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
