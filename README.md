# YHLZ 2.0 - 智能语音助手

## 🚀 项目简介

**YHLZ 2.0** 采用全新的架构设计：**云端大脑 + 本地轻量感官**

- **云端大脑**: DeepSeek API，流式输出，高效智能
- **本地轻量感官**: ASR/TTS/VAD，释放GPU显存，低延迟

## ✨ 核心特性

### 1. 云端大模型
- ✅ DeepSeek API 集成
- ✅ 强制流式输出
- ✅ 智能对话管理

### 2. 本地感官系统
- ✅ **ASR**: Paraformer-small，强制CPU运行，释放GPU显存
- ✅ **TTS**: SpeechT5，FP16精度 + torch.compile加速
- ✅ **VAD**: Silero VAD，语音活动检测

### 3. 高级交互
- ✅ **全双工打断**: 检测用户说话自动中断输出
- ✅ **无缝拼接**: 音频淡入淡出，消除断层爆音
- ✅ **上下文压缩**: 自动摘要，防止Token溢出

### 4. 安全与容灾
- ✅ **密钥隔离**: API Key仅存于.env环境变量
- ✅ **离线降级**: API断开自动切换本地模式
- ✅ **优雅退出**: 模型自动卸载释放资源

## 📁 项目结构

```
YHLZ2.0/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI主入口
│   ├── config.py            # 配置管理
│   ├── llm_engine.py        # DeepSeek API引擎
│   ├── asr_engine.py        # Paraformer ASR引擎
│   ├── tts_engine.py        # SpeechT5 TTS引擎
│   ├── vad_engine.py        # VAD引擎
│   ├── audio_buffer.py      # 音频缓冲管理器
│   └── context_manager.py   # 上下文管理器
├── gui/                     # GUI界面（待开发）
├── .env.example             # 环境变量示例
├── .env                     # 环境变量（需配置）
├── requirements.txt         # 依赖包
├── start.bat               # Windows启动脚本
└── README.md               # 项目文档
```

## 🔧 快速开始

### 1. 配置环境变量

复制 `.env.example` 为 `.env`，填入您的DeepSeek API Key：

```env
# DeepSeek API 配置
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 模型配置
ASR_MODEL=Paraformer-small
TTS_MODEL=SpeechT5
VAD_MODEL=silero_vad

# 性能配置
ASR_DEVICE=cpu
TTS_DEVICE=cuda
TTS_PRECISION=fp16
USE_TORCH_COMPILE=true

# 上下文配置
MAX_CONTEXT_TOKENS=8000
SUMMARY_THRESHOLD=7000

# 音频配置
TTS_BUFFER_MS=10
SAMPLE_RATE=24000
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务

#### Windows (推荐)
双击运行 `start.bat`

#### 手动启动
```bash
python backend/main.py
```

### 4. 访问API

- **健康检查**: http://localhost:8000/health
- **API文档**: http://localhost:8000/docs
- **缓存统计**: http://localhost:8000/cache-stats

## 📡 API接口

### REST接口

#### 文本聊天
```
POST /chat
Content-Type: application/json

{
  "text": "你好",
  "temperature": 0.7,
  "max_tokens": 2048
}

Response: Server-Sent Events (SSE)
```

#### 语音识别
```
POST /transcribe
Content-Type: application/json

{
  "audio_data": [0.1, 0.2, ...],
  "sample_rate": 16000
}

Response: {"text": "识别结果", "success": true}
```

#### 语音合成
```
POST /synthesize
Content-Type: application/json

{
  "text": "你好"
}

Response: {"audio": [...], "sample_rate": 16000, "success": true}
```

#### 打断播放
```
POST /interrupt
Response: {"success": true, "message": "Audio interrupted"}
```

#### 清空历史
```
POST /clear-history
Response: {"success": true}
```

### WebSocket接口

连接 `ws://localhost:8000/ws` 进行实时语音对话。

## 🎯 使用示例

### Python客户端
```python
import requests
import json

# 文本聊天
response = requests.post("http://localhost:8000/chat", json={
    "text": "你好，介绍一下你自己"
})

for line in response.iter_lines():
    if line:
        print(json.loads(line.decode()[6:]))

# 语音合成
synth_response = requests.post("http://localhost:8000/synthesize", json={
    "text": "你好，很高兴认识你"
})
audio_data = synth_response.json()["audio"]
```

## 🔒 安全建议

1. **不要提交.env文件**: 将.env添加到.gitignore
2. **保护API密钥**: 不要在代码中硬编码API Key
3. **定期更换密钥**: 定期更换您的API密钥
4. **设置使用限额**: 在DeepSeek控制台设置使用限额

## 🚀 性能优化

### ASR优化
- 强制CPU运行: `ASR_DEVICE=cpu`
- 减少CPU竞争: 避免其他重CPU任务

### TTS优化
- 使用FP16精度: `TTS_PRECISION=fp16`
- 启用torch.compile: `USE_TORCH_COMPILE=true`
- 使用CUDA设备: `TTS_DEVICE=cuda`

### 上下文优化
- 调整阈值: `SUMMARY_THRESHOLD=7000`
- 限制token数: `MAX_CONTEXT_TOKENS=8000`

## 📊 监控与调试

### 查看缓存统计
访问 http://localhost:8000/cache-stats

### 查看日志
- 后端日志: `backend.log`
- 控制台输出实时日志

### 健康检查
```bash
curl http://localhost:8000/health
```

## 🔄 从YHLZ 1.x升级

### 主要变化
1. **架构升级**: 从本地LLM改为云端API
2. **ASR优化**: 强制CPU运行，释放GPU
3. **TTS优化**: SpeechT5 + FP16 + torch.compile
4. **安全性提升**: 环境变量管理API密钥
5. **新增功能**: 音频缓冲、智能打断、自动摘要

### 迁移步骤
1. 备份原配置
2. 复制新代码到YHLZ2.0目录
3. 配置.env文件
4. 安装新依赖
5. 启动新服务

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

1. Fork本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 📄 许可证

本项目采用MIT许可证 - 详见LICENSE文件

## 🙏 致谢

- [DeepSeek](https://www.deepseek.com/) - 强大的云端大模型
- [FunASR](https://github.com/alibaba-damo-academy/FunASR) - 语音识别工具包
- [SpeechT5](https://github.com/microsoft/SpeechT5) - 语音合成模型
- [Silero VAD](https://github.com/snakers4/silero-vad) - 语音活动检测

---

**YHLZ 2.0** - 让AI更智能、更自然！ 🎉
