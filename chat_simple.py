#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YHLZ 2.0 简单语音聊天界面
使用REST API，更稳定
自动启动后端服务
优化：真正的流式对话体验
"""

import sys
import os
import subprocess
import time
import signal
import json
import numpy as np
import threading
import sounddevice as sd
import soundfile as sf
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QTextEdit, QPushButton, QLabel, QProgressBar, QMessageBox, QInputDialog,
    QDialog, QSlider, QCheckBox, QGroupBox, QFormLayout, QComboBox, QLineEdit,
    QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMetaObject, Q_ARG, QTimer
from PyQt5.QtGui import QFont, QColor, QTextCursor
import requests


SAMPLE_RATE = 24000  # Edge-TTS默认采样率


class BackendManager:
    """后端服务管理器"""
    
    def __init__(self):
        self.backend_process = None
        self.backend_url = "http://localhost:8000"
        
    def start_backend(self):
        """启动后端服务"""
        try:
            # 检查后端是否已经运行
            response = requests.get(f"{self.backend_url}/health", timeout=2)
            if response.status_code == 200:
                print("后端服务已运行")
                return True
        except:
            pass
        
        print("正在启动后端服务...")
        
        # 获取项目根目录
        project_root = os.path.dirname(os.path.abspath(__file__))
        backend_path = os.path.join(project_root, "backend", "main.py")
        venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")
        
        # 启动后端服务
        try:
            self.backend_process = subprocess.Popen(
                [venv_python, backend_path],
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            
            # 等待后端启动
            for i in range(30):  # 等待30秒
                time.sleep(1)
                try:
                    response = requests.get(f"{self.backend_url}/health", timeout=2)
                    if response.status_code == 200:
                        print("后端服务启动成功")
                        return True
                except:
                    pass
            
            print("后端服务启动超时")
            return False
            
        except Exception as e:
            print(f"启动后端服务失败: {e}")
            return False
    
    def stop_backend(self):
        """停止后端服务"""
        if self.backend_process:
            try:
                # 发送终止信号
                self.backend_process.terminate()
                self.backend_process.wait(timeout=5)
                print("后端服务已停止")
            except:
                # 强制终止
                self.backend_process.kill()
                print("后端服务已强制停止")
    
    def is_running(self):
        """检查后端是否运行"""
        try:
            response = requests.get(f"{self.backend_url}/health", timeout=2)
            return response.status_code == 200
        except:
            return False


class VADConfigDialog(QDialog):
    """VAD配置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("语音活动检测（VAD）设置")
        self.setMinimumWidth(550)
        
        # 配置数据
        self.vad_config = {
            "enabled": True,
            "interrupt_enabled": True,
            "energy_threshold": 0.01,
            "silero_threshold": 0.5,
            "frame_size": 1600,
            "min_speech_frames": 2
        }
        
        self.init_ui()
        self.load_vad_config()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 基本设置组
        basic_group = QGroupBox("基本设置")
        basic_layout = QVBoxLayout()
        
        # 启用VAD复选框
        self.vad_enabled_check = QCheckBox("启用语音活动检测（VAD）")
        self.vad_enabled_check.setToolTip("检测音频中是否有语音活动")
        basic_layout.addWidget(self.vad_enabled_check)
        
        # 启用中断复选框
        self.interrupt_enabled_check = QCheckBox("启用VAD中断功能")
        self.interrupt_enabled_check.setToolTip("检测到您说话时自动中断AI的语音播放")
        basic_layout.addWidget(self.interrupt_enabled_check)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # 灵敏度设置组
        sensitivity_group = QGroupBox("灵敏度设置")
        sensitivity_layout = QFormLayout()
        
        # 能量检测阈值
        self.energy_threshold_slider = QSlider(Qt.Horizontal)
        self.energy_threshold_slider.setMinimum(1)
        self.energy_threshold_slider.setMaximum(100)
        self.energy_threshold_slider.setValue(10)
        self.energy_threshold_label = QLabel("0.010")
        sensitivity_layout.addRow("能量检测阈值 (越小越灵敏):", self.energy_threshold_slider)
        sensitivity_layout.addRow("", self.energy_threshold_label)
        
        # Silero VAD阈值
        self.silero_threshold_slider = QSlider(Qt.Horizontal)
        self.silero_threshold_slider.setMinimum(10)
        self.silero_threshold_slider.setMaximum(90)
        self.silero_threshold_slider.setValue(50)
        self.silero_threshold_label = QLabel("0.50")
        sensitivity_layout.addRow("Silero VAD阈值 (越大越灵敏):", self.silero_threshold_slider)
        sensitivity_layout.addRow("", self.silero_threshold_label)
        
        # 最小语音帧数
        self.min_speech_frames_slider = QSlider(Qt.Horizontal)
        self.min_speech_frames_slider.setMinimum(1)
        self.min_speech_frames_slider.setMaximum(10)
        self.min_speech_frames_slider.setValue(2)
        self.min_speech_frames_label = QLabel("2 帧")
        sensitivity_layout.addRow("最小语音帧数 (越大越不易误判):", self.min_speech_frames_slider)
        sensitivity_layout.addRow("", self.min_speech_frames_label)
        
        sensitivity_group.setLayout(sensitivity_layout)
        layout.addWidget(sensitivity_group)
        
        # 连接滑块信号
        self.energy_threshold_slider.valueChanged.connect(self.update_energy_label)
        self.silero_threshold_slider.valueChanged.connect(self.update_silero_label)
        self.min_speech_frames_slider.valueChanged.connect(self.update_frames_label)
        
        # 提示信息
        info_label = QLabel("提示：\n• 启用VAD中断功能后，您可以在AI说话时直接说话打断\n• 调整灵敏度可以减少误触发或漏触发\n• 如果误触发太多，可以调大阈值；如果漏触发，可以调小阈值")
        info_label.setStyleSheet("color: gray; font-size: 11px; padding: 8px; background: #f5f5f5; border-radius: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 按钮
        button_layout = QHBoxLayout()
        reset_button = QPushButton("重置默认")
        reset_button.clicked.connect(self.reset_default)
        ok_button = QPushButton("保存")
        ok_button.clicked.connect(self.save_vad_config)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(reset_button)
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def update_energy_label(self, value):
        threshold = value / 1000.0
        self.energy_threshold_label.setText(f"{threshold:.3f}")
        
    def update_silero_label(self, value):
        threshold = value / 100.0
        self.silero_threshold_label.setText(f"{threshold:.2f}")
        
    def update_frames_label(self, value):
        self.min_speech_frames_label.setText(f"{value} 帧")
        
    def load_vad_config(self):
        """加载VAD配置"""
        try:
            response = requests.get("http://localhost:8000/vad/config", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.vad_config = data.get("config", self.vad_config)
                    # 更新界面
                    self.vad_enabled_check.setChecked(self.vad_config.get("enabled", True))
                    self.interrupt_enabled_check.setChecked(self.vad_config.get("interrupt_enabled", True))
                    self.energy_threshold_slider.setValue(int(self.vad_config.get("energy_threshold", 0.01) * 1000))
                    self.silero_threshold_slider.setValue(int(self.vad_config.get("silero_threshold", 0.5) * 100))
                    self.min_speech_frames_slider.setValue(self.vad_config.get("min_speech_frames", 2))
                    self.update_energy_label(self.energy_threshold_slider.value())
                    self.update_silero_label(self.silero_threshold_slider.value())
                    self.update_frames_label(self.min_speech_frames_slider.value())
        except Exception as e:
            print(f"加载VAD配置失败: {e}")
            
    def save_vad_config(self):
        """保存VAD配置"""
        try:
            config_dict = {
                "enabled": self.vad_enabled_check.isChecked(),
                "interrupt_enabled": self.interrupt_enabled_check.isChecked(),
                "energy_threshold": self.energy_threshold_slider.value() / 1000.0,
                "silero_threshold": self.silero_threshold_slider.value() / 100.0,
                "min_speech_frames": self.min_speech_frames_slider.value()
            }
            
            response = requests.post("http://localhost:8000/vad/config", json=config_dict, timeout=5)
            if response.status_code == 200:
                self.vad_config = config_dict
                self.accept()
                QMessageBox.information(self, "成功", "VAD配置已保存！")
            else:
                QMessageBox.warning(self, "警告", "保存VAD配置失败！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存VAD配置失败: {str(e)}")
            
    def reset_default(self):
        """重置默认配置"""
        self.vad_enabled_check.setChecked(True)
        self.interrupt_enabled_check.setChecked(True)
        self.energy_threshold_slider.setValue(10)
        self.silero_threshold_slider.setValue(50)
        self.min_speech_frames_slider.setValue(2)
        self.update_energy_label(10)
        self.update_silero_label(50)
        self.update_frames_label(2)


class VoiceConfigDialog(QDialog):
    """语音配置对话框"""
    
    # 可用的中文声音列表
    CHINESE_VOICES = {
        "晓晓（女声-温暖）": "zh-CN-XiaoxiaoNeural",
        "晓伊（女声-温柔）": "zh-CN-XiaoyiNeural",
        "晓辰（女声-甜美）": "zh-CN-XiaochenNeural",
        "晓涵（女声-知性）": "zh-CN-XiaohanNeural",
        "晓梦（女声-活泼）": "zh-CN-XiaomengNeural",
        "晓墨（女声-文艺）": "zh-CN-XiaomoNeural",
        "云希（男声-年轻）": "zh-CN-YunxiNeural",
        "云扬（男声-播音）": "zh-CN-YunyangNeural",
        "云健（男声-激情）": "zh-CN-YunjianNeural",
        "云夏（男声-稳重）": "zh-CN-YunxiaNeural",
        "云枫（男声-沉稳）": "zh-CN-YunfengNeural",
        "云皓（男声-磁性）": "zh-CN-YunhaoNeural",
    }
    
    def __init__(self, parent=None, current_voice="zh-CN-XiaoxiaoNeural"):
        super().__init__(parent)
        self.setWindowTitle("语音设置")
        self.setMinimumWidth(550)
        
        # 配置数据
        self.enable_tts = True
        self.current_voice = current_voice
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # TTS设置组
        tts_group = QGroupBox("语音合成设置")
        tts_layout = QVBoxLayout()
        
        # 自动播放复选框
        self.tts_check = QCheckBox("自动播放语音回复")
        self.tts_check.setChecked(self.enable_tts)
        tts_layout.addWidget(self.tts_check)
        
        # 声音选择下拉框
        voice_layout = QHBoxLayout()
        voice_label = QLabel("选择声音:")
        self.voice_combo = QComboBox()
        
        # 添加声音选项
        for voice_name, voice_id in self.CHINESE_VOICES.items():
            self.voice_combo.addItem(voice_name, voice_id)
        
        # 设置当前选中的声音
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == self.current_voice:
                self.voice_combo.setCurrentIndex(i)
                break
        
        voice_layout.addWidget(voice_label)
        voice_layout.addWidget(self.voice_combo)
        tts_layout.addLayout(voice_layout)
        
        tts_group.setLayout(tts_layout)
        layout.addWidget(tts_group)
        
        # VAD设置按钮
        vad_button = QPushButton("🔊 语音活动检测（VAD）设置")
        vad_button.setStyleSheet("background-color: #e3f2fd; color: #1976d2; font-weight: bold; padding: 10px;")
        vad_button.clicked.connect(self.open_vad_settings)
        layout.addWidget(vad_button)
        
        # 提示信息
        info_label = QLabel("提示：不同声音有不同的风格特点\n女声：晓晓（温暖）、晓伊（温柔）、晓辰（甜美）等\n男声：云希（年轻）、云扬（播音）、云健（激情）等")
        info_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(info_label)
        
        # 按钮
        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def open_vad_settings(self):
        """打开VAD设置窗口"""
        vad_dialog = VADConfigDialog(self)
        vad_dialog.exec_()
        
    def get_config(self):
        """获取配置"""
        return {
            "enable_tts": self.tts_check.isChecked(),
            "tts_speed": 1.0,
            "voice": self.voice_combo.currentData()
        }


class PersonalityConfigDialog(QDialog):
    """性格设定对话框"""
    
    SPEAKING_STYLES = {
        "友好亲切": "friendly",
        "正式礼貌": "formal",
        "轻松随意": "casual",
        "古风典雅": "ancient"
    }
    
    TONES = {
        "温暖关怀": "warm",
        "专业严谨": "professional",
        "幽默风趣": "humorous",
        "严肃认真": "serious"
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("性格设定")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        self.personality_data = {}
        self.init_ui()
        self.load_personality()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 基本信息组
        basic_group = QGroupBox("基本信息")
        basic_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["女性", "男性", "中性"])
        self.age_edit = QLineEdit()
        self.occupation_edit = QLineEdit()
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(60)
        
        basic_layout.addRow("名字:", self.name_edit)
        basic_layout.addRow("性别:", self.gender_combo)
        basic_layout.addRow("年龄:", self.age_edit)
        basic_layout.addRow("职业:", self.occupation_edit)
        basic_layout.addRow("描述:", self.description_edit)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # 性格特征组
        traits_group = QGroupBox("性格特征")
        traits_layout = QVBoxLayout()
        
        self.traits_edit = QLineEdit()
        self.traits_edit.setPlaceholderText("用逗号分隔，如：温柔, 耐心, 聪明")
        traits_layout.addWidget(self.traits_edit)
        
        traits_group.setLayout(traits_layout)
        layout.addWidget(traits_group)
        
        # 说话风格组
        style_group = QGroupBox("说话风格")
        style_layout = QFormLayout()
        
        self.style_combo = QComboBox()
        for name, value in self.SPEAKING_STYLES.items():
            self.style_combo.addItem(name, value)
            
        self.tone_combo = QComboBox()
        for name, value in self.TONES.items():
            self.tone_combo.addItem(name, value)
        
        style_layout.addRow("风格:", self.style_combo)
        style_layout.addRow("语气:", self.tone_combo)
        
        style_group.setLayout(style_layout)
        layout.addWidget(style_group)
        
        # 口头禅组
        catchphrases_group = QGroupBox("口头禅")
        catchphrases_layout = QVBoxLayout()
        
        self.catchphrases_edit = QLineEdit()
        self.catchphrases_edit.setPlaceholderText("用逗号分隔，如：好的！, 明白了！")
        catchphrases_layout.addWidget(self.catchphrases_edit)
        
        catchphrases_group.setLayout(catchphrases_layout)
        layout.addWidget(catchphrases_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        save_button = QPushButton("保存")
        save_button.clicked.connect(self.save_personality)
        reset_button = QPushButton("重置默认")
        reset_button.clicked.connect(self.reset_personality)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(reset_button)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def load_personality(self):
        """加载当前性格配置"""
        try:
            response = requests.get("http://localhost:8000/personality", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.name_edit.setText(data.get("name", ""))
                self.gender_combo.setCurrentText(data.get("gender", "女性"))
                self.age_edit.setText(data.get("age", ""))
                self.occupation_edit.setText(data.get("occupation", ""))
                self.description_edit.setPlainText(data.get("description", ""))
                self.traits_edit.setText(", ".join(data.get("personality_traits", [])))
                self.catchphrases_edit.setText(", ".join(data.get("catchphrases", [])))
                
                # 设置风格和语气
                style = data.get("speaking_style", "friendly")
                for i in range(self.style_combo.count()):
                    if self.style_combo.itemData(i) == style:
                        self.style_combo.setCurrentIndex(i)
                        break
                
                tone = data.get("tone", "warm")
                for i in range(self.tone_combo.count()):
                    if self.tone_combo.itemData(i) == tone:
                        self.tone_combo.setCurrentIndex(i)
                        break
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载性格配置失败: {str(e)}")
    
    def save_personality(self):
        """保存性格配置"""
        try:
            traits = [t.strip() for t in self.traits_edit.text().split(",") if t.strip()]
            catchphrases = [c.strip() for c in self.catchphrases_edit.text().split(",") if c.strip()]
            
            data = {
                "name": self.name_edit.text(),
                "gender": self.gender_combo.currentText(),
                "age": self.age_edit.text(),
                "occupation": self.occupation_edit.text(),
                "description": self.description_edit.toPlainText(),
                "personality_traits": traits,
                "speaking_style": self.style_combo.currentData(),
                "tone": self.tone_combo.currentData(),
                "catchphrases": catchphrases
            }
            
            response = requests.post("http://localhost:8000/personality", json=data, timeout=5)
            if response.status_code == 200:
                QMessageBox.information(self, "成功", "性格配置已保存！")
                self.accept()
            else:
                QMessageBox.warning(self, "警告", "保存失败！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存性格配置失败: {str(e)}")
    
    def reset_personality(self):
        """重置性格配置"""
        try:
            response = requests.post("http://localhost:8000/personality/reset", timeout=5)
            if response.status_code == 200:
                self.load_personality()
                QMessageBox.information(self, "成功", "性格配置已重置！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"重置性格配置失败: {str(e)}")


class MemoryManagerDialog(QDialog):
    """记忆管理对话框"""
    
    CATEGORIES = ["general", "user_info", "preference", "event"]
    CATEGORY_NAMES = {
        "general": "通用",
        "user_info": "用户信息",
        "preference": "偏好",
        "event": "事件"
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("记忆管理")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        
        self.memories = []
        self.init_ui()
        self.load_memories()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 搜索栏
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索记忆...")
        self.search_edit.textChanged.connect(self.search_memories)
        search_button = QPushButton("搜索")
        search_button.clicked.connect(self.search_memories)
        
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(search_button)
        layout.addLayout(search_layout)
        
        # 记忆列表
        self.memory_list = QListWidget()
        self.memory_list.itemClicked.connect(self.on_memory_clicked)
        layout.addWidget(self.memory_list)
        
        # 添加记忆区域
        add_group = QGroupBox("添加新记忆")
        add_layout = QVBoxLayout()
        
        self.content_edit = QTextEdit()
        self.content_edit.setMaximumHeight(80)
        self.content_edit.setPlaceholderText("输入记忆内容...")
        
        category_layout = QHBoxLayout()
        category_label = QLabel("类别:")
        self.category_combo = QComboBox()
        for cat in self.CATEGORIES:
            self.category_combo.addItem(self.CATEGORY_NAMES.get(cat, cat), cat)
        
        importance_layout = QHBoxLayout()
        importance_label = QLabel("重要性:")
        self.importance_slider = QSlider(Qt.Horizontal)
        self.importance_slider.setRange(1, 5)
        self.importance_slider.setValue(1)
        self.importance_label = QLabel("1")
        self.importance_slider.valueChanged.connect(lambda v: self.importance_label.setText(str(v)))
        
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo)
        importance_layout.addWidget(importance_label)
        importance_layout.addWidget(self.importance_slider)
        importance_layout.addWidget(self.importance_label)
        
        add_layout.addWidget(self.content_edit)
        add_layout.addLayout(category_layout)
        add_layout.addLayout(importance_layout)
        
        add_button = QPushButton("添加记忆")
        add_button.clicked.connect(self.add_memory)
        add_layout.addWidget(add_button)
        
        add_group.setLayout(add_layout)
        layout.addWidget(add_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        self.edit_button = QPushButton("✏️ 修改")
        self.edit_button.clicked.connect(self.edit_selected_memory)
        self.edit_button.setEnabled(False)
        
        self.delete_button = QPushButton("🗑️ 删除")
        self.delete_button.clicked.connect(self.delete_selected_memory)
        self.delete_button.setEnabled(False)
        
        refresh_button = QPushButton("🔄 刷新")
        refresh_button.clicked.connect(self.load_memories)
        
        clear_button = QPushButton("清空所有")
        clear_button.clicked.connect(self.clear_all_memories)
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
        button_layout.addWidget(refresh_button)
        button_layout.addWidget(clear_button)
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
    def load_memories(self):
        """加载所有记忆"""
        try:
            response = requests.get("http://localhost:8000/memory/list", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.memories = data.get("memories", [])
                self.display_memories()
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载记忆失败: {str(e)}")
    
    def search_memories(self):
        """搜索记忆"""
        query = self.search_edit.text()
        if not query:
            self.load_memories()
            return
        
        try:
            response = requests.get(f"http://localhost:8000/memory/search?query={query}&max_results=20", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.memories = data.get("results", [])
                self.display_memories()
        except Exception as e:
            QMessageBox.warning(self, "警告", f"搜索记忆失败: {str(e)}")
    
    def display_memories(self):
        """显示记忆列表"""
        self.memory_list.clear()
        
        if not self.memories:
            self.memory_list.addItem("暂无记忆")
            return
        
        for mem in self.memories:
            category = self.CATEGORY_NAMES.get(mem.get("category"), mem.get("category"))
            importance = "★" * mem.get("importance", 1)
            created_at = mem.get("created_at", "")[:19] if mem.get("created_at") else ""
            
            # 创建列表项文本
            text = f"【{category}】{importance}\n"
            text += f"{mem.get('content', '')}\n"
            text += f"时间: {created_at}"
            
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, mem)  # 存储完整数据
            self.memory_list.addItem(item)
    
    def on_memory_clicked(self, item):
        """记忆列表项被点击"""
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)
    
    def edit_selected_memory(self):
        """修改选中的记忆"""
        current_item = self.memory_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择要修改的记忆！")
            return
        
        memory = current_item.data(Qt.UserRole)
        if not memory:
            return
        
        # 弹出修改对话框
        dialog = EditMemoryDialog(memory, self)
        if dialog.exec_():
            # 重新加载记忆
            self.load_memories()
    
    def delete_selected_memory(self):
        """删除选中的记忆"""
        current_item = self.memory_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择要删除的记忆！")
            return
        
        memory = current_item.data(Qt.UserRole)
        if not memory:
            return
        
        # 确认删除
        if QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除这条记忆吗？\n\n记忆内容：{memory.get('content', '')[:50]}..."
        ) == QMessageBox.Yes:
            try:
                memory_id = memory.get("id")
                response = requests.delete(f"http://localhost:8000/memory/{memory_id}", timeout=5)
                
                if response.status_code == 200:
                    QMessageBox.information(self, "成功", "记忆已删除！")
                    self.load_memories()
                    self.edit_button.setEnabled(False)
                    self.delete_button.setEnabled(False)
                else:
                    QMessageBox.warning(self, "警告", "删除失败！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除记忆失败: {str(e)}")
    
    def add_memory(self):
        """添加新记忆"""
        content = self.content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "警告", "请输入记忆内容！")
            return
        
        try:
            data = {
                "content": content,
                "category": self.category_combo.currentData(),
                "importance": self.importance_slider.value()
            }
            
            response = requests.post("http://localhost:8000/memory", json=data, timeout=5)
            if response.status_code == 200:
                QMessageBox.information(self, "成功", "记忆已添加！")
                self.content_edit.clear()
                self.load_memories()
            else:
                QMessageBox.warning(self, "警告", "添加失败！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加记忆失败: {str(e)}")
    
    def clear_all_memories(self):
        """清空所有记忆"""
        if QMessageBox.question(self, "确认", "确定要清空所有记忆吗？") == QMessageBox.Yes:
            try:
                response = requests.post("http://localhost:8000/memory/clear", timeout=5)
                if response.status_code == 200:
                    self.memories = []
                    self.display_memories()
                    self.edit_button.setEnabled(False)
                    self.delete_button.setEnabled(False)
                    QMessageBox.information(self, "成功", "记忆库已清空！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"清空记忆失败: {e}")


class EditMemoryDialog(QDialog):
    """修改记忆对话框"""
    
    CATEGORIES = ["general", "user_info", "preference", "event"]
    CATEGORY_NAMES = {
        "general": "通用",
        "user_info": "用户信息",
        "preference": "偏好",
        "event": "事件"
    }
    
    def __init__(self, memory, parent=None):
        super().__init__(parent)
        self.memory = memory
        self.setWindowTitle("修改记忆")
        self.setMinimumWidth(500)
        self.init_ui()
        
        # 填充现有数据
        self.content_edit.setPlainText(memory.get("content", ""))
        
        # 设置类别
        category = memory.get("category", "general")
        index = self.category_combo.findData(category)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        
        # 设置重要性
        importance = memory.get("importance", 1)
        self.importance_slider.setValue(importance)
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 内容编辑
        content_label = QLabel("记忆内容:")
        self.content_edit = QTextEdit()
        self.content_edit.setMaximumHeight(120)
        self.content_edit.setPlaceholderText("输入记忆内容...")
        layout.addWidget(content_label)
        layout.addWidget(self.content_edit)
        
        # 类别选择
        category_layout = QHBoxLayout()
        category_label = QLabel("类别:")
        self.category_combo = QComboBox()
        for cat in self.CATEGORIES:
            self.category_combo.addItem(self.CATEGORY_NAMES.get(cat, cat), cat)
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo)
        layout.addLayout(category_layout)
        
        # 重要性选择
        importance_layout = QHBoxLayout()
        importance_label = QLabel("重要性:")
        self.importance_slider = QSlider(Qt.Horizontal)
        self.importance_slider.setRange(1, 5)
        self.importance_slider.setValue(1)
        self.importance_value_label = QLabel("1")
        self.importance_slider.valueChanged.connect(lambda v: self.importance_value_label.setText(str(v)))
        importance_layout.addWidget(importance_label)
        importance_layout.addWidget(self.importance_slider)
        importance_layout.addWidget(self.importance_value_label)
        layout.addLayout(importance_layout)
        
        # 按钮
        button_layout = QHBoxLayout()
        save_button = QPushButton("💾 保存")
        save_button.clicked.connect(self.save_memory)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def save_memory(self):
        """保存记忆"""
        content = self.content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "警告", "记忆内容不能为空！")
            return
        
        try:
            memory_id = self.memory.get("id")
            data = {
                "content": content,
                "category": self.category_combo.currentData(),
                "importance": self.importance_slider.value()
            }
            
            response = requests.put(
                f"http://localhost:8000/memory/{memory_id}",
                json=data,
                timeout=5
            )
            
            if response.status_code == 200:
                QMessageBox.information(self, "成功", "记忆已修改！")
                self.accept()
            else:
                QMessageBox.warning(self, "警告", "修改失败！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"修改记忆失败: {str(e)}")


class AudioPlayer:
    """音频播放器（支持VAD中断和真正的流式播放）"""

    def __init__(self):
        self.current_stream = None
        self.audio_buffer = np.array([], dtype=np.float32)  # 流式音频缓冲区
        self.is_playing = False
        self.play_lock = threading.Lock()
        self.current_sample_rate = None  # 当前采样率
        self.interrupted = False
        self.on_interrupt_callback = None  # 中断回调
        self.play_thread = None  # 播放线程
        self.streaming = False  # 是否正在流式播放

    def set_interrupt_callback(self, callback):
        """设置中断回调函数"""
        self.on_interrupt_callback = callback

    def play_audio(self, audio_data, sample_rate):
        """播放完整音频（非阻塞）"""
        try:
            self.stop()
            self.interrupted = False
            self.is_playing = True
            self.current_sample_rate = sample_rate

            # 在独立线程中播放
            self.play_thread = threading.Thread(
                target=self._play_thread_func,
                args=(audio_data, sample_rate),
                daemon=True
            )
            self.play_thread.start()
        except Exception as e:
            print(f"播放音频错误: {e}")
            self.is_playing = False

    def _play_thread_func(self, audio_data, sample_rate):
        """播放线程函数"""
        try:
            sd.play(audio_data, sample_rate)
            # 使用循环检查中断，而不是直接wait
            while sd.get_stream().active:
                if self.interrupted:
                    sd.stop()
                    if self.on_interrupt_callback:
                        self.on_interrupt_callback()
                    break
                time.sleep(0.01)
        except Exception as e:
            print(f"播放线程错误: {e}")
        finally:
            self.is_playing = False

    def start_streaming(self, sample_rate):
        """开始流式播放模式"""
        self.streaming = True
        self.current_sample_rate = sample_rate
        self.audio_buffer = np.array([], dtype=np.float32)
        self.interrupted = False
        
        # 启动流式播放线程
        self.play_thread = threading.Thread(
            target=self._stream_play_thread,
            daemon=True
        )
        self.play_thread.start()

    def _stream_play_thread(self):
        """流式播放线程 - 极低延迟版本"""
        try:
            while self.streaming and not self.interrupted:
                with self.play_lock:
                    buffer_len = len(self.audio_buffer)
                
                if buffer_len > 0:
                    # 极低延迟：每次播放0.02秒（约480 samples @ 24kHz）
                    chunk_size = int(self.current_sample_rate * 0.02)
                    if buffer_len >= chunk_size:
                        with self.play_lock:
                            chunk = self.audio_buffer[:chunk_size]
                            self.audio_buffer = self.audio_buffer[chunk_size:]
                        
                        self.is_playing = True
                        sd.play(chunk, self.current_sample_rate)
                        while sd.get_stream().active and not self.interrupted:
                            time.sleep(0.002)  # 更频繁检查中断（2ms）
                    else:
                        time.sleep(0.005)  # 极短等待时间
                else:
                    time.sleep(0.005)
        except Exception as e:
            print(f"流式播放线程错误: {e}")
        finally:
            self.is_playing = False
            self.streaming = False

    def feed_audio(self, audio_chunk):
        """向流式播放缓冲区添加音频数据"""
        if self.streaming and not self.interrupted:
            with self.play_lock:
                self.audio_buffer = np.concatenate([self.audio_buffer, audio_chunk])

    def stop_streaming(self):
        """停止流式播放"""
        self.streaming = False
        self.audio_buffer = np.array([], dtype=np.float32)
        self.stop()

    def stream_audio(self, audio_data, sample_rate):
        """流式播放音频（边接收边播放）"""
        try:
            with self.play_lock:
                self.interrupted = False
                self.current_sample_rate = sample_rate
                
                # 如果还没有在流式播放，启动流式播放模式
                if not self.streaming:
                    # 先保存当前数据，避免被清空
                    temp_audio = audio_data.copy()
                    self.start_streaming(sample_rate)
                    # 恢复数据
                    self.audio_buffer = np.concatenate([self.audio_buffer, temp_audio])
                else:
                    # 添加到缓冲区
                    self.audio_buffer = np.concatenate([self.audio_buffer, audio_data])
                
                print(f"[音频播放] 添加音频块: {len(audio_data)} 样本, 缓冲区大小: {len(self.audio_buffer)}")
                
        except Exception as e:
            print(f"流式播放错误: {e}")
            # 回退到普通播放
            try:
                self.play_audio(audio_data, sample_rate)
            except Exception as fallback_e:
                print(f"回退播放也失败: {fallback_e}")

    def stop(self):
        """停止当前播放"""
        try:
            with self.play_lock:
                self.interrupted = True
                self.is_playing = False
                self.audio_buffer = np.array([], dtype=np.float32)
                sd.stop()
                if self.current_stream:
                    self.current_stream.stop()
                    self.current_stream.close()
                    self.current_stream = None
        except Exception as e:
            print(f"停止播放错误: {e}")

    def wait_until_done(self, timeout=None):
        """等待播放完成"""
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=timeout)


class AudioRecorder:
    """音频录制器，支持VAD检测和流式输出"""
    
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.is_recording = False
        self.audio_buffer = []
        self.vad_active = False
        self.speech_detected = False
        self.silence_start_time = None
        self.silence_threshold = 1.2  # 静音检测阈值（秒）- 需要静音1.2秒才认为语音结束
        self.min_speech_duration = 0.3  # 最小语音时长（秒）- 需要至少0.3秒的语音才算有效
        self.min_speech_ratio = 0.15  # 语音帧占比（至少15%的帧是语音）- 降低要求提高灵敏度
        self.recording_start_time = None
        self.on_audio_chunk_callback = None  # 流式音频回调
        self.silence_count = 0  # 静音帧计数
        self.speech_frames = 0  # 语音帧计数
        self.total_frames = 0  # 总帧数计数
        
    def set_audio_chunk_callback(self, callback):
        """设置音频块回调函数"""
        self.on_audio_chunk_callback = callback
        
    def start_recording(self):
        """开始录音"""
        if self.is_recording:
            return
        self.is_recording = True
        self.audio_buffer = []
        self.speech_detected = False
        self.silence_start_time = None
        self.recording_start_time = time.time()
        self.silence_count = 0
        self.speech_frames = 0
        self.total_frames = 0
        print(f"[录音] 开始录音, 时间={self.recording_start_time}")
        
        # 启动录音线程
        self.recording_thread = threading.Thread(
            target=self._recording_loop,
            daemon=True
        )
        self.recording_thread.start()
        
    def _recording_loop(self):
        """录音循环"""
        try:
            chunk_size = int(self.sample_rate * 0.2)  # 每200ms输出一次，减少回调次数
            last_status_print = 0
            
            def callback(indata, frames, time_info, status):
                nonlocal last_status_print
                if status:
                    # 只打印一次输入溢出错误，避免刷屏
                    if "overflow" in str(status) and (time.time() - last_status_print) > 10:
                        print(f"[音频警告] {status}")
                        last_status_print = time.time()
                
                audio_data = indata.copy()
                self.audio_buffer.append(audio_data)
                
                # 触发流式回调
                if self.on_audio_chunk_callback:
                    chunk = audio_data.flatten().astype(np.float32)
                    self.on_audio_chunk_callback(chunk)
                
                # 改进的VAD检测：基于能量和持续时间
                energy = np.sqrt(np.mean(audio_data ** 2))
                self.total_frames += 1
                
                # 能量阈值（平衡灵敏度和误检）
                energy_threshold = 0.0008  # 降低阈值提高灵敏度
                
                if energy > energy_threshold:
                    self.speech_detected = True
                    self.speech_frames += 1
                    self.silence_start_time = None
                    # 每30帧输出一次语音检测
                    if self.speech_frames % 30 == 0:
                        speech_ratio = self.speech_frames / self.total_frames if self.total_frames > 0 else 0
                        print(f"[VAD] 检测语音 | 能量={energy:.6f} | 语音帧={self.speech_frames} | 占比={speech_ratio*100:.1f}%")
                else:
                    if self.silence_start_time is None:
                        self.silence_start_time = time.time()
                    self.silence_count += 1
                    # 每60帧输出一次静音状态
                    if self.silence_count % 60 == 0:
                        speech_ratio = self.speech_frames / self.total_frames if self.total_frames > 0 else 0
                        silence_duration = time.time() - self.silence_start_time if self.silence_start_time else 0
                        print(f"[VAD] 静音中 | 能量={energy:.6f} | 静音帧={self.silence_count} | 占比={speech_ratio*100:.1f}% | 静音持续={silence_duration:.1f}s")
            
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=chunk_size,
                callback=callback
            ):
                while self.is_recording:
                    time.sleep(0.01)
        except Exception as e:
            print(f"录音错误: {e}")
        
    def stop_recording(self):
        """停止录音并返回音频数据"""
        self.is_recording = False
        if hasattr(self, 'recording_thread') and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=1)
        
        # 保存音频数据
        audio_data = None
        if self.audio_buffer:
            audio_data = np.concatenate(self.audio_buffer, axis=0)
        
        # 重置状态，准备下次录音
        self.audio_buffer = []
        self.speech_detected = False
        self.silence_start_time = None
        self.recording_start_time = None
        self.silence_count = 0
        self.speech_frames = 0
        self.total_frames = 0
        
        return audio_data
    
    def check_silence(self):
        """检查是否处于静音状态足够长时间"""
        if self.silence_start_time is not None:
            silence_duration = time.time() - self.silence_start_time
            return silence_duration >= self.silence_threshold
        return False
    
    def has_speech(self):
        """检查是否检测到语音 - 使用更严格的检测逻辑"""
        if self.recording_start_time is None:
            return False
        
        # 条件1：录音时间足够长
        duration = time.time() - self.recording_start_time
        if duration < self.min_speech_duration:
            return False
        
        # 条件2：语音帧占比足够高
        speech_ratio = 0
        if self.total_frames > 0:
            speech_ratio = self.speech_frames / self.total_frames
            if speech_ratio < self.min_speech_ratio:
                return False
        
        # 条件3：至少检测到过一次语音
        result = self.speech_detected
        
        # 输出调试信息（每5秒输出一次）
        if result and self.total_frames % 50 == 0:
            print(f"[VAD] has_speech=True | 时长={duration:.1f}s | 总帧数={self.total_frames} | 语音帧={self.speech_frames} | 占比={speech_ratio*100:.1f}%")
        
        return result


class SimpleVoiceChatWindow(QMainWindow):
    # 定义信号用于跨线程UI更新
    append_message_signal = pyqtSignal(str, str, str)
    append_text_to_last_signal = pyqtSignal(str)
    update_asr_text_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.audio_player = AudioPlayer()
        self.audio_recorder = AudioRecorder()
        self.backend_manager = BackendManager()
        self.is_conversation_mode = False
        self.is_waiting_for_reply = False
        self.current_asr_text = ""
        
        # 连接信号到槽
        self.append_message_signal.connect(self.append_message)
        self.append_text_to_last_signal.connect(self.append_text_to_last)
        self.update_asr_text_signal.connect(self.update_asr_display)
        
        # 设置音频录制回调（实现流式ASR）
        self.audio_recorder.set_audio_chunk_callback(self._on_audio_chunk)
        
        self.voice_config = {
            "enable_tts": True,
            "tts_speed": 1.0,
            "voice": "zh-CN-XiaoxiaoNeural"
        }
        self.init_ui()
        self.start_and_check_service()
    
    def start_and_check_service(self):
        """自动启动后端服务并检查连接"""
        self.status_label.setText("正在启动后端服务...")
        self.status_label.setStyleSheet("color: orange; font-size: 12px;")
        
        if self.backend_manager.start_backend():
            self.status_label.setText("✅ 服务已就绪 | 当前声音: 晓晓（温暖女声）")
            self.status_label.setStyleSheet("color: green; font-size: 12px;")
            # 启动自动测试
            QTimer.singleShot(1000, self.run_startup_test)
        else:
            self.status_label.setText("❌ 后端服务启动失败，请检查日志")
            self.status_label.setStyleSheet("color: red; font-size: 12px;")
            QMessageBox.warning(self, "警告", "后端服务启动失败，请检查日志文件！")
    
    def run_startup_test(self):
        """启动时自动测试：LLM -> TTS（使用简单TTS，稳定版）"""
        test_text = "信息于你无限,元亨开拓未来,这里是人造知性电子生命元亨,你是否试想过一个没有苦厄,充满希望的世界?"
        print("\n" + "=" * 60)
        print("🚀 启动自动测试")
        print("=" * 60)
        print(f"测试文本: {test_text[:50]}...")
        
        try:
            # 强制启用TTS
            self.voice_config["enable_tts"] = True
            voice = self.voice_config.get("voice", "zh-CN-XiaoxiaoNeural")
            print(f"[测试] TTS启用: {self.voice_config['enable_tts']}, 音色: {voice}")
            
            # 添加测试消息到UI
            self.append_message("系统", "🔄 启动自动测试...", "blue")
            self.append_message("你", test_text, "#0066cc")
            self.append_message("AI", "", "#2d8659")
            self.append_text_to_last_signal.emit(test_text)
            
            print("\n[测试] 使用简单TTS播放开场白...")
            tts_response = requests.post(
                "http://localhost:8000/synthesize",
                json={"text": test_text, "voice": voice},
                timeout=60
            )
            
            if tts_response.status_code == 200:
                result = tts_response.json()
                audio = np.array(result['audio'], dtype=np.float32)
                sample_rate = result['sample_rate']
                print(f"[测试] TTS成功: {len(audio)}样本, {sample_rate}Hz")
                print(f"[测试] 预计时长: {len(audio)/sample_rate:.2f}秒")
                print("[测试] 开始播放...")
                self.audio_player.play_audio(audio, sample_rate)
                print("[测试] 播放完成")
            else:
                print(f"[测试] TTS失败: {tts_response.status_code}")
            
            print("✅ 自动测试完成")
            print("=" * 60 + "\n")
            
        except Exception as e:
            print(f"❌ 自动测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    def closeEvent(self, event):
        """窗口关闭时停止后端服务"""
        self.backend_manager.stop_backend()
        self.audio_player.stop()
        self.audio_recorder.stop_recording()
        event.accept()
        
    def init_ui(self):
        self.setWindowTitle("YHLZ 2.0 - 智能语音助手")
        self.setGeometry(100, 100, 900, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # 顶部布局：标题 + 模式切换
        top_layout = QHBoxLayout()
        
        # 标题
        title_label = QLabel("YHLZ 2.0")
        title_label.setFont(QFont("Arial", 18, QFont.Bold))
        top_layout.addWidget(title_label)
        
        # 右侧模式切换按钮
        mode_layout = QHBoxLayout()
        mode_layout.setAlignment(Qt.AlignRight)
        
        self.mode_switch = QPushButton("💬 文本")
        self.mode_switch.setCheckable(True)
        self.mode_switch.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                padding: 6px 12px;
                border-radius: 15px;
                background-color: #2196F3;
                color: white;
                border: none;
            }
            QPushButton:checked {
                background-color: #4CAF50;
            }
        """)
        self.mode_switch.clicked.connect(self.toggle_mode)
        mode_layout.addWidget(self.mode_switch)
        
        top_layout.addStretch()
        top_layout.addLayout(mode_layout)
        
        main_layout.addLayout(top_layout)
        
        # 状态标签
        self.status_label = QLabel("检查服务连接中...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 12px;")
        main_layout.addWidget(self.status_label)
        
        # ASR实时显示标签（对话模式下显示）
        self.asr_display_label = QLabel("")
        self.asr_display_label.setAlignment(Qt.AlignCenter)
        self.asr_display_label.setStyleSheet("color: #FF9800; font-size: 14px; background: #fff8e1; padding: 5px;")
        self.asr_display_label.hide()
        main_layout.addWidget(self.asr_display_label)
        
        # 主体布局：左侧设置按钮 + 右侧聊天区
        body_layout = QHBoxLayout()
        
        # 左侧设置按钮区域（垂直排列）
        left_layout = QVBoxLayout()
        left_layout.setAlignment(Qt.AlignTop)
        
        # 配置按钮
        self.config_button = QPushButton("⚙️ 设置")
        self.config_button.setMinimumHeight(45)
        self.config_button.setMinimumWidth(100)
        self.config_button.setStyleSheet("font-size: 14px; background-color: #FF9800; color: white;")
        self.config_button.clicked.connect(self.show_voice_config)
        left_layout.addWidget(self.config_button)
        
        # 性格设定按钮
        self.personality_button = QPushButton("🎭 性格设定")
        self.personality_button.setMinimumHeight(45)
        self.personality_button.setMinimumWidth(100)
        self.personality_button.setStyleSheet("font-size: 14px; background-color: #9C27B0; color: white;")
        self.personality_button.clicked.connect(self.show_personality_config)
        left_layout.addWidget(self.personality_button)
        
        # 记忆管理按钮
        self.memory_button = QPushButton("🧠 记忆管理")
        self.memory_button.setMinimumHeight(45)
        self.memory_button.setMinimumWidth(100)
        self.memory_button.setStyleSheet("font-size: 14px; background-color: #00BCD4; color: white;")
        self.memory_button.clicked.connect(self.show_memory_manager)
        left_layout.addWidget(self.memory_button)
        
        # 清空历史按钮
        self.clear_button = QPushButton("🗑️ 清空历史")
        self.clear_button.setMinimumHeight(45)
        self.clear_button.setMinimumWidth(100)
        self.clear_button.setStyleSheet("font-size: 14px; background-color: #f44336; color: white;")
        self.clear_button.clicked.connect(self.clear_history)
        left_layout.addWidget(self.clear_button)
        
        # 添加伸缩空间
        left_layout.addStretch()
        
        # 右侧聊天显示区
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("Microsoft YaHei", 12))
        
        body_layout.addLayout(left_layout)
        body_layout.addWidget(self.chat_display)
        
        main_layout.addLayout(body_layout)
        
        # 底部按钮布局
        button_layout = QHBoxLayout()
        
        # 文本输入按钮
        self.text_button = QPushButton("💬 文本输入")
        self.text_button.setMinimumHeight(50)
        self.text_button.setStyleSheet("font-size: 16px; background-color: #2196F3; color: white;")
        self.text_button.clicked.connect(self.show_text_input)
        button_layout.addWidget(self.text_button)
        
        main_layout.addLayout(button_layout)
        
        # 提示标签
        hint_label = QLabel("提示：点击💬按钮输入文本进行聊天")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet("color: gray;")
        main_layout.addWidget(hint_label)
        
        # 添加欢迎消息
        self.append_message("系统", "欢迎使用 YHLZ 2.0 智能助手！\n\n🌐 支持模式：\n- 💬 文本模式：输入文字与AI对话\n- 🗣️ 对话模式：语音交互（边说边识别）\n\n💡 提示：点击右上角切换聊天模式", "blue")
        
    def update_asr_display(self, text):
        """更新ASR实时显示"""
        if text:
            self.asr_display_label.setText(f"🎤 正在识别: {text}")
            self.asr_display_label.show()
        else:
            self.asr_display_label.hide()
    
    def _on_audio_chunk(self, audio_chunk):
        """音频块回调 - 实现流式ASR识别（低延迟优化）"""
        if not self.is_conversation_mode or self.is_waiting_for_reply:
            return
        
        # 只在检测到语音后才发送，且降低发送频率（每5个音频块发送一次）
        if not hasattr(self, 'audio_chunk_count'):
            self.audio_chunk_count = 0
        self.audio_chunk_count += 1
        if self.audio_chunk_count % 5 != 0:
            return
        
        try:
            audio_list = audio_chunk.tolist()
            response = requests.post(
                "http://localhost:8000/transcribe",
                json={"audio_data": audio_list, "sample_rate": self.audio_recorder.sample_rate},
                timeout=5  # 增加超时时间
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "")
                if text and text.strip():
                    if text.strip().startswith(self.current_asr_text):
                        new_text = text.strip()[len(self.current_asr_text):]
                        if new_text:
                            self.current_asr_text = text.strip()
                            self.update_asr_text_signal.emit(self.current_asr_text)
                    else:
                        self.current_asr_text = text.strip()
                        self.update_asr_text_signal.emit(self.current_asr_text)
        except Exception as e:
            if "timeout" not in str(e).lower():  # 只打印非超时错误
                print(f"流式ASR识别失败: {e}")
        
    def append_message(self, sender, text, color="black"):
        """在聊天窗口添加消息"""
        self.chat_display.moveCursor(QTextCursor.End)
        
        if sender == "你":
            self.chat_display.setTextColor(QColor("#0066cc"))
            self.chat_display.insertHtml("<b>你:</b> ")
        elif sender == "AI":
            self.chat_display.setTextColor(QColor("#2d8659"))
            self.chat_display.insertHtml("<b>AI:</b> ")
        else:
            self.chat_display.setTextColor(QColor(color))
            
        self.chat_display.insertPlainText(text)
        self.chat_display.insertPlainText("\n\n")
        self.chat_display.setTextColor(QColor("black"))
        
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def chat_with_ai(self, text):
        """和AI聊天（使用简单TTS，稳定版）"""
        try:
            response = requests.post(
                "http://localhost:8000/chat",
                json={"text": text},
                stream=True
            )
            
            full_text = ""
            is_first_chunk = True
            
            voice = self.voice_config.get("voice", "zh-CN-XiaoxiaoNeural")
            print(f"[TTS] 准备开始语音合成")
            
            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8')
                    if line_text.startswith('data: '):
                        try:
                            data = json.loads(line_text[6:])
                            if 'content' in data and data['content']:
                                chunk = data['content']
                                if is_first_chunk:
                                    self.append_message_signal.emit("AI", "", "#2d8659")
                                    is_first_chunk = False
                                self.append_text_to_last_signal.emit(chunk)
                                full_text += chunk
                        except Exception as e:
                            pass
            
            # 收到完整回复后，使用简单TTS播放
            if full_text and self.voice_config.get("enable_tts", True):
                print(f"[TTS] 使用简单TTS播放完整回复: {len(full_text)}字符")
                try:
                    tts_response = requests.post(
                        "http://localhost:8000/synthesize",
                        json={"text": full_text, "voice": voice},
                        timeout=60
                    )
                    if tts_response.status_code == 200:
                        tts_result = tts_response.json()
                        audio_np = np.array(tts_result['audio'], dtype=np.float32)
                        sr = tts_result['sample_rate']
                        print(f"[TTS] 开始播放: {len(audio_np)}样本, {sr}Hz")
                        self.audio_player.play_audio(audio_np, sr)
                        
                        # 如果是对话模式，等待播放完成（支持中断）
                        if self.is_conversation_mode:
                            while self.audio_player.is_playing and not self.audio_player.interrupted:
                                time.sleep(0.05)
                    else:
                        print(f"[TTS] 失败: {tts_response.status_code}")
                except Exception as e:
                    print(f"[TTS] 异常: {e}")
                    
            if self.is_conversation_mode:
                self.is_waiting_for_reply = False
                    
        except Exception as e:
            QMessageBox.critical(self, "错误", f"发送消息失败: {e}")
            if self.is_conversation_mode:
                self.is_waiting_for_reply = False

    def _stream_tts(self, text, voice):
        """流式语音合成 - 边接收边播放（极低延迟）"""
        try:
            print(f"[流式TTS] 开始合成: {text[:30]}...")
            response = requests.post(
                "http://localhost:8000/synthesize/stream",
                json={"text": text, "voice": voice},
                stream=True,
                timeout=60
            )
            
            if response.status_code == 200:
                print(f"[流式TTS] 接口响应正常，边接收边播放...")
                
                chunk_count = 0
                sample_rate = None
                first_play = True
                
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line.decode('utf-8'))
                            
                            if 'audio' in data and data['audio']:
                                audio_chunk = np.array(data['audio'], dtype=np.float32)
                                sr = data.get('sample_rate', 44100)
                                
                                if sample_rate is None:
                                    sample_rate = sr
                                    print(f"[流式TTS] 采样率: {sample_rate}Hz")
                                
                                chunk_count += 1
                                
                                # 边接收边播放
                                if first_play:
                                    print(f"[流式TTS] 首块延迟低，立即播放...")
                                    self.audio_player.play_audio(audio_chunk, sample_rate)
                                    first_play = False
                                else:
                                    # 后续块添加到流式播放队列
                                    self.audio_player.stream_audio(audio_chunk, sample_rate)
                                
                                print(f"[流式TTS] 块 {chunk_count}: {len(audio_chunk)}样本")
                                
                            if data.get('is_done', False):
                                print(f"[流式TTS] 流式合成完成，共 {chunk_count} 块")
                                break
                                
                        except Exception as e:
                            print(f"[流式TTS] 解析失败: {e}")
                            print(f"[流式TTS] 行内容: {line[:100]}")
                
                if chunk_count == 0:
                    print(f"[流式TTS] ❌ 没有收到音频数据")
                    
            else:
                print(f"[流式TTS] ❌ 接口错误: {response.status_code}")
                
        except Exception as e:
            print(f"[流式TTS] ❌ 请求失败: {e}")
            import traceback
            traceback.print_exc()

    def append_text_to_last(self, content):
        """向最后一条消息追加内容"""
        self.chat_display.moveCursor(QTextCursor.End)
        self.chat_display.insertPlainText(content)
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def show_text_input(self):
        """显示文本输入对话框"""
        text, ok = QInputDialog.getText(self, "文本输入", "请输入你的问题:")
        if ok and text:
            self.append_message("你", text, "#0066cc")
            self.chat_with_ai(text)
    
    def toggle_mode(self):
        """切换聊天模式"""
        if self.mode_switch.isChecked():
            # 切换到对话模式
            self.mode_switch.setText("🗣️ 对话")
            self.mode_switch.setStyleSheet("""
                QPushButton {
                    font-size: 14px;
                    padding: 6px 12px;
                    border-radius: 15px;
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                }
                QPushButton:checked {
                    background-color: #2196F3;
                }
            """)
            self.is_conversation_mode = True
            # 更新底部按钮
            self.text_button.setText("🗣️ 开始对话")
            self.text_button.setStyleSheet("font-size: 16px; background-color: #4CAF50; color: white;")
            self.text_button.clicked.disconnect()
            self.text_button.clicked.connect(self.start_conversation)
            self.append_message("系统", "已切换到对话模式！点击🗣️按钮开始对话", "green")
        else:
            # 切换到文本模式
            self.mode_switch.setText("💬 文本")
            self.mode_switch.setStyleSheet("""
                QPushButton {
                    font-size: 14px;
                    padding: 6px 12px;
                    border-radius: 15px;
                    background-color: #2196F3;
                    color: white;
                    border: none;
                }
                QPushButton:checked {
                    background-color: #4CAF50;
                }
            """)
            self.is_conversation_mode = False
            # 停止对话模式
            if self.audio_recorder.is_recording:
                self.audio_recorder.stop_recording()
            self.audio_player.stop()
            # 更新底部按钮
            self.text_button.setText("💬 文本输入")
            self.text_button.setStyleSheet("font-size: 16px; background-color: #2196F3; color: white;")
            self.text_button.clicked.disconnect()
            self.text_button.clicked.connect(self.show_text_input)
            self.append_message("系统", "已切换到文本模式！点击💬按钮输入文字聊天", "blue")
            # 隐藏ASR显示
            self.asr_display_label.hide()
            self.current_asr_text = ""
    
    def start_conversation(self):
        """开始真正的语音对话模式"""
        if self.text_button.text() == "⏹️ 结束对话":
            # 结束对话
            self.audio_recorder.stop_recording()
            self.audio_player.stop()
            self.text_button.setText("🗣️ 开始对话")
            self.text_button.setStyleSheet("font-size: 16px; background-color: #4CAF50; color: white;")
            self.append_message("系统", "对话已结束", "orange")
            self.is_waiting_for_reply = False
            # 隐藏ASR显示
            self.asr_display_label.hide()
            self.current_asr_text = ""
        else:
            # 开始对话
            self.text_button.setText("⏹️ 结束对话")
            self.text_button.setStyleSheet("font-size: 16px; background-color: #f44336; color: white;")
            self.append_message("系统", "🎤 正在听你说话...（说完后会自动发送）", "green")
            self.audio_recorder.start_recording()
            self.is_waiting_for_reply = False
            # 启动监听线程
            self.conversation_thread = threading.Thread(
                target=self._conversation_loop,
                daemon=True
            )
            self.conversation_thread.start()
    
    def _conversation_loop(self):
        """对话循环：监听语音→发送→等待回复→播放→继续监听"""
        while self.is_conversation_mode and self.text_button.text() == "⏹️ 结束对话":
            # 等待检测到语音后静音
            speech_detected = False
            first_detection = True
            while self.is_conversation_mode and self.text_button.text() == "⏹️ 结束对话":
                # 检查是否检测到语音
                if self.audio_recorder.has_speech():
                    speech_detected = True
                    if first_detection:
                        first_detection = False
                        print("[对话] 检测到语音开始")
                
                # 如果检测到语音，等待静音结束
                if speech_detected and self.audio_recorder.check_silence():
                    print("[对话] 检测到静音，语音结束")
                    break
                
                # 如果正在播放，检查是否需要中断
                if self.audio_player.is_playing:
                    self._check_interrupt_during_playback()
                    # 如果被中断，重置状态
                    if not self.audio_player.is_playing:
                        speech_detected = False
                        self.current_asr_text = ""
                        self.asr_display_label.hide()
                
                time.sleep(0.1)  # 降低检查频率，减少CPU占用
            
            if not self.is_conversation_mode or self.text_button.text() != "⏹️ 结束对话":
                break
            
            # 检测到语音结束，停止录音
            audio_data = self.audio_recorder.stop_recording()
            
            # 隐藏ASR显示
            self.asr_display_label.hide()
            self.current_asr_text = ""
            
            if audio_data is not None and len(audio_data) > 0:
                # 使用信号更新UI
                self.append_message_signal.emit("系统", "🎙️ 正在识别语音...", "blue")
                
                # 语音识别
                text = self._recognize_speech(audio_data)
                
                if text and text.strip():
                    # 使用信号更新UI
                    self.append_message_signal.emit("你", text.strip(), "#0066cc")
                    self.is_waiting_for_reply = True
                    
                    # 发送到AI
                    QApplication.instance().processEvents()
                    self.chat_with_ai(text.strip())
                    
                    # 等待回复和播放完成
                    while self.is_waiting_for_reply or self.audio_player.is_playing:
                        self._check_interrupt_during_playback()
                        time.sleep(0.05)
                    
                    print("[对话] AI回复完成，准备继续监听")
                    
                    # 继续监听
                    if self.is_conversation_mode and self.text_button.text() == "⏹️ 结束对话":
                        self.append_message_signal.emit("系统", "🎤 正在听你说话...", "green")
                        self.audio_recorder.start_recording()
                else:
                    # 识别为空，重新开始录音
                    print("[对话] 识别为空，重新开始录音")
                    if self.is_conversation_mode and self.text_button.text() == "⏹️ 结束对话":
                        self.audio_recorder.start_recording()
            else:
                # 没有录到音频，重新开始录音
                print("[对话] 没有录到音频，重新开始录音")
                if self.is_conversation_mode and self.text_button.text() == "⏹️ 结束对话":
                    self.audio_recorder.start_recording()
    
    def _recognize_speech(self, audio_data):
        """语音识别"""
        print(f"[语音合成追踪] 开始语音识别，音频长度: {len(audio_data)}")
        print(f"[语音合成追踪] 采样率: {self.audio_recorder.sample_rate}")
        try:
            audio_list = audio_data.flatten().tolist()
            print(f"[语音合成追踪] 转换后长度: {len(audio_list)}")
            print(f"[语音合成追踪] 发送到后端识别...")
            
            response = requests.post(
                "http://localhost:8000/transcribe",
                json={"audio_data": audio_list, "sample_rate": self.audio_recorder.sample_rate},
                timeout=30
            )
            
            print(f"[语音合成追踪] 识别响应状态: {response.status_code}")
            print(f"[语音合成追踪] 响应内容: {response.text[:500]}")
            
            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "")
                print(f"[语音合成追踪] 识别结果: '{text}'")
                if text.strip():
                    return text
                else:
                    print(f"[语音合成追踪] 识别结果为空")
                    self.append_message_signal.emit("系统", "⚠️ 未检测到语音内容", "orange")
            else:
                print(f"[语音合成追踪] 服务器错误: {response.status_code}")
                self.append_message_signal.emit("系统", f"⚠️ 语音识别服务错误: {response.status_code}", "red")
        except requests.exceptions.RequestException as e:
            print(f"[语音合成追踪] 网络请求失败: {e}")
            self.append_message_signal.emit("系统", "⚠️ 网络连接失败，请检查后端服务", "red")
        except Exception as e:
            print(f"[语音合成追踪] 语音识别失败: {type(e).__name__}: {e}")
            self.append_message_signal.emit("系统", "⚠️ 语音识别失败", "red")
        return ""
    
    def _check_interrupt_during_playback(self):
        """播放期间检查是否需要中断"""
        if self.audio_player.is_playing and self.audio_recorder.is_recording:
            # 检查是否检测到新的语音
            if self.audio_recorder.has_speech():
                # 中断播放
                self.audio_player.stop()
                self.append_message_signal.emit("系统", "🔔 检测到你说话，已中断播放", "orange")
                self.is_waiting_for_reply = False
    
    def show_voice_config(self):
        """显示语音配置对话框"""
        current_voice = self.voice_config.get("voice", "zh-CN-XiaoxiaoNeural")
        dialog = VoiceConfigDialog(self, current_voice)
        if dialog.exec_() == QDialog.Accepted:
            self.voice_config = dialog.get_config()
            voice_name = self.voice_config.get("voice", "zh-CN-XiaoxiaoNeural")
            self.status_label.setText(f"✅ 服务已就绪 | 当前声音: {voice_name}")
            self.status_label.setStyleSheet("color: green;")
    
    def show_personality_config(self):
        """显示性格设定对话框"""
        dialog = PersonalityConfigDialog(self)
        dialog.exec_()
    
    def show_memory_manager(self):
        """显示记忆管理对话框"""
        dialog = MemoryManagerDialog(self)
        dialog.exec_()
    
    def clear_history(self):
        """清空对话历史"""
        try:
            response = requests.post("http://localhost:8000/clear-history", timeout=5)
            if response.status_code == 200:
                self.chat_display.clear()
                self.append_message("系统", "对话历史已清空！", "blue")
                QMessageBox.information(self, "成功", "对话历史已清空！")
            else:
                QMessageBox.warning(self, "警告", "清空历史失败！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"清空历史失败: {str(e)}")


def main():
    app = QApplication(sys.argv)
    window = SimpleVoiceChatWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()