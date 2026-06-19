# YHLZ 2.0 声音克隆功能指南

## 概述

YHLZ 2.0 现在支持声音克隆功能！你可以使用自己的一段音频作为参考，让AI用该音色进行语音合成。

## 当前状态

### ✅ 已实现的功能
- 声音克隆API框架
- 参考音频加载接口
- 后端API集成
- 基础测试脚本

### ⚠️ 当前限制
- 当前是简化版本，使用Edge-TTS作为基础
- 完整的音色克隆需要下载OpenVoice模型
- 首次使用需要安装额外依赖

## 使用方法

### 方法一：使用测试脚本

```bash
# 1. 确保后端运行
python test_voice_clone.py
```

### 方法二：直接使用API

#### 1. 检查声音克隆状态
```bash
curl http://localhost:8000/voice-clone/status
```

#### 2. 加载参考音频
```python
import requests

# 从文件加载
response = requests.post(
    "http://localhost:8000/voice-clone/load-reference",
    json={
        "audio_path": "your_reference_audio.wav"
    }
)
```

#### 3. 使用克隆音色合成
```python
response = requests.post(
    "http://localhost:8000/voice-clone/synthesize",
    json={
        "text": "你好，这是使用克隆音色的语音",
        "speed": 1.0
    }
)
```

## 完整OpenVoice安装指南

### 1. 安装OpenVoice
```bash
cd d:\YHLZ2.0
venv\Scripts\python.exe -m pip install openvoice
```

### 2. 下载OpenVoice模型

OpenVoice需要以下模型：
- Tone Color Converter (音色转换器)
- Base Speaker (基础音色)

你可以从以下地址下载：
- GitHub: https://github.com/myshell-ai/OpenVoice
- HuggingFace: https://huggingface.co/myshell-ai/OpenVoice

### 3. 配置模型路径

修改 `backend/voice_clone_engine.py` 中的路径配置。

## 参考音频要求

### ✅ 推荐的音频规格
- 时长：10-30秒
- 格式：WAV, MP3
- 采样率：16kHz 或更高
- 内容：清晰的单人语音
- 环境：安静背景，无噪音

### ❌ 不推荐的音频
- 太短（<5秒）
- 背景音乐或噪音
- 多人对话
- 音量过低或过高

## API文档

### 完整的API端点

#### GET /voice-clone/status
获取声音克隆引擎状态

**响应示例：**
```json
{
  "available": true,
  "has_reference": false,
  "reference_audio": null,
  "methods": ["OpenVoice（推荐）", "Edge-TTS预设音色（当前）"]
}
```

#### POST /voice-clone/load-reference
加载参考音频

**请求体：**
```json
{
  "audio_path": "path/to/audio.wav",
  "audio_data": [0.1, 0.2, ...], // 可选，numpy数组
  "sample_rate": 16000
}
```

#### POST /voice-clone/synthesize
使用克隆音色合成语音

**请求体：**
```json
{
  "text": "你好，这是测试文本",
  "output_path": "output.wav", // 可选
  "speed": 1.0
}
```

#### POST /voice-clone/clear
清除已加载的参考音频

## 故障排除

### 问题1：OpenVoice导入失败
```
解决方案：
pip install openvoice torch torchaudio
```

### 问题2：找不到模型文件
```
解决方案：
- 确保模型文件在正确路径
- 或使用简化版本（当前）
```

### 问题3：音色克隆效果不好
```
可能原因：
- 参考音频质量太低
- 音频太短
- 背景噪音太大
```

## 进阶使用

### 切换TTS模式

你可以在 `chat_simple.py` 中添加一个设置，让用户选择：
1. Edge-TTS预设音色（默认）
2. 克隆音色（使用OpenVoice）

### 保存和加载音色配置

你可以扩展功能，让用户：
- 保存多个音色配置
- 快速切换不同的克隆音色
- 导出和导入音色特征

## 开发计划

- [ ] 完整OpenVoice集成
- [ ] 前端界面支持音色选择
- [ ] 音色库管理
- [ ] 批量音色克隆
- [ ] 音色质量评估工具

## 相关资源

- OpenVoice GitHub: https://github.com/myshell-ai/OpenVoice
- Edge-TTS: https://github.com/rany2/edge-tts
- Coqui TTS: https://github.com/coqui-ai/TTS

## 联系与反馈

如遇到问题，请检查后端日志获取详细错误信息。
