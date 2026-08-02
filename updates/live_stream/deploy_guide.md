# YHLZ 直播功能插件部署指南

## 目录结构

```
updates/live_stream/
├── __init__.py              # 模块入口
├── backend/                 # 后端引擎
│   ├── __init__.py          # 后端模块入口
│   ├── mouth_sync.py        # 口型同步引擎（音频分析→MouthOpen参数）
│   ├── expression_controller.py  # 表情控制引擎（情感分析→表情切换）
│   ├── topic_generator.py   # 话题生成器（6大类60+话题）
│   ├── live_stream_manager.py  # 直播管理器（核心控制）
│   └── cognitive_avatar_controller.py  # 认知驱动虚拟形象控制器
├── plugins/                 # 插件（可直接复制到项目plugins/）
│   ├── __init__.py          # 插件入口
│   ├── bilibili_live/       # B站直播插件
│   │   ├── __init__.py      # 弹幕监听、礼物监听、弹幕发送
│   │   └── plugin.toml      # enabled=false（默认关闭）
│   ├── vtube_studio/        # VTube Studio插件
│   │   ├── __init__.py      # 表情切换、口型控制、动画触发
│   │   └── plugin.toml      # enabled=false（默认关闭）
│   └── live_control/        # 直播控制面板
│       ├── __init__.py      # 直播开始/结束/休息/配置
│       └── plugin.toml      # enabled=false（默认关闭）
├── config/                  # 配置文件
│   ├── bilibili_live.json   # B站直播间配置
│   ├── vtube_studio.json    # VTS配置
│   └── live_stream.json     # 全局配置
├── install_deps.py          # 依赖安装脚本
└── deploy_guide.md          # 部署指南
```

## 核心功能

### 1. 长时间直播支持（3-4小时）

| 功能 | 说明 |
|------|------|
| **状态管理** | idle → preparing → live → break → ending → ended |
| **能量系统** | 直播时能量逐渐消耗，休息时恢复，低于20%自动休息 |
| **疲劳管理** | 每30分钟自动休息5分钟 |
| **冷场检测** | 30秒无弹幕自动生成话题 |
| **自动话题** | 每5分钟自动生成新话题 |
| **记忆整合** | 直播结束后自动保存直播记录和热门话题到长时记忆 |

### 2. 弹幕互动

| 功能 | 说明 |
|------|------|
| **智能回复** | 基于LLM的智能回复，简短活泼，不超过30字 |
| **表情响应** | 根据弹幕情感自动切换虚拟形象表情 |
| **礼物感谢** | 收到礼物自动感谢并触发开心表情 |
| **回复队列** | 异步回复队列，避免刷屏 |

### 3. 虚拟形象控制

| 功能 | 说明 |
|------|------|
| **口型同步** | 实时音频分析，驱动嘴巴动作 |
| **表情切换** | 11种表情：happy/sad/surprised/neutral/angry/shy/excited/sleepy/confused/laugh/cry |
| **动画触发** | 眨眼、位置调整、模型切换 |
| **动画缓动** | 6种缓动曲线：linear/easeIn/easeOut/easeBoth/overshoot/zip |
| **自动眨眼** | 可配置自动眨眼间隔 |

### 4. 认知驱动虚拟形象

| 功能 | 说明 |
|------|------|
| **认知状态映射** | idle→neutral, processing→focused, high_tension→alert |
| **张力类型驱动** | 危机张力→angry表情, 美学张力→surprised表情 |
| **注意力权重驱动** | 视觉/音频注意力权重→头部动作 |
| **多模态共鸣** | 多模态共鸣时触发身体摇摆动画 |
| **空间感知** | 空间感知激活时触发头部扫视动作 |

### 认知反应规则

| 规则名称 | 触发条件 | 反应类型 | 优先级 |
|----------|----------|----------|--------|
| 危机检测 | 检测到"危机"标签 | THREATENED | 10 |
| 美学检测 | 检测到"美学"标签 | BEAUTY_AWE | 9 |
| 高认知负载 | 认知带宽>0.8 | FOCUSED | 8 |
| 空间感知 | 空间坐标可用 | SURPRISED | 7 |
| 多模态协同 | 跨模态数据可用 | EXCITED | 6 |
| 正常状态 | idle状态 | NEUTRAL | 1 |

### 认知状态→表情映射

| 认知状态 | 表情 | 动画 |
|----------|------|------|
| NEUTRAL | neutral | 无 |
| ALERT | surprised | blink |
| FOCUSED | confused | 无 |
| SURPRISED | surprised | blink |
| EXCITED | excited | wave_hand |
| THREATENED | angry | 无 |
| BEAUTY_AWE | surprised | blink |

### 5. GPT-SoVITS 语音播报（借鉴 bili_voice）

| 功能 | 说明 |
|------|------|
| **优先级队列** | SC/礼物/舰长优先播报，普通弹幕排队 |
| **文本模板** | 自定义消息格式，支持变量替换 |
| **文本替换规则** | 支持正则/精确匹配的文本替换 |
| **音量增益** | dB级音量调整，避免爆音 |
| **队列管理** | 可配置队列长度，自动清理旧任务 |
| **状态追踪** | 播报状态实时反馈（pending/playing/done/cancelled） |

### 消息类型支持

| 消息类型 | 触发条件 | 优先级 | 默认模板 |
|----------|----------|--------|----------|
| DANMU_MSG | 普通弹幕 | NORMAL | `{uname} 说，{content}` |
| SEND_GIFT | 礼物（首条） | HIGH | `感谢 {uname} 的{num}个{gift_name}` |
| COMBO_SEND | 连击礼物 | HIGH | `感谢 {uname} 的{num}个{gift_name}` |
| SUPER_CHAT_MESSAGE | SC（>=设定价格） | HIGH | `感谢 {uname} 的{price}元SC，{content}` |
| GUARD_BUY | 大航海 | HIGH | `感谢 {uname} 的{num}个{guard_name}` |
| INTERACT_WORD_V2 | 进场/关注/分享 | NORMAL | `欢迎 {uname} 进入直播间` |
| LIKE_INFO_V3_CLICK | 点赞 | NORMAL | `感谢 {uname} 的点赞` |

### 事件驱动架构（借鉴 bili_voice）

```
原始弹幕消息 → LiveEvent工厂 → 事件类型判断 → 权限检查 → 数据标准化 → 模板格式化 → TTS排队
                                                                              ↓
                                                                  优先级队列（高优先）
                                                                              ↓
                                                                  Gradio推理 → 音频下载 → 本地播放
```

## 安装步骤

### 1. 安装依赖

```bash
python updates/live_stream/install_deps.py
```

或者手动安装：

```bash
pip install websockets requests pyvts numpy scipy pyaudio aiohttp pydub
```

### 2. 复制插件到项目

```bash
cp -r updates/live_stream/plugins/bilibili_live plugins/
cp -r updates/live_stream/plugins/vtube_studio plugins/
cp -r updates/live_stream/plugins/live_control plugins/
```

### 3. 修改插件配置

修改 `plugins/bilibili_live/plugin.toml`：

```toml
entry = "plugins.bilibili_live:BilibiliLivePlugin"
enabled = true
```

修改 `plugins/vtube_studio/plugin.toml`：

```toml
entry = "plugins.vtube_studio:VTubeStudioPlugin"
enabled = true
```

修改 `plugins/live_control/plugin.toml`：

```toml
entry = "plugins.live_control:LiveControlPlugin"
enabled = true
```

### 4. 配置B站Cookie

编辑 `config/bilibili_live.json`：

```json
{
    "room_id": 你的直播间ID,
    "sessdata": "你的SESSDATA",
    "bili_jct": "你的bili_jct",
    "buvid3": "你的buvid3",
    "auto_reply_enabled": true,
    "topic_interval": 300,
    "reply_delay": 2
}
```

### 5. 配置VTube Studio

编辑 `config/vtube_studio.json`：

```json
{
    "enabled": true,
    "token_path": "./config/vts_token.txt",
    "mouth_sync_enabled": true,
    "expression_control_enabled": true,
    "auto_blink_enabled": true,
    "blink_interval": 3000
}
```

### 6. 配置直播参数

编辑 `config/live_stream.json`：

```json
{
    "enabled": true,
    "platform": "bilibili",
    "cold_threshold": 30,
    "topic_interval": 300,
    "break_interval": 1800,
    "break_duration": 300,
    "energy_decay_rate": 0.005,
    "energy_recovery_rate": 0.02
}
```

### 7. 配置 GPT-SoVITS 语音播报（借鉴 bili_voice）

编辑 `config/gpt_sovits.json`：

```json
{
    "enabled": true,
    "gradio_server_url": "http://localhost:9872/",
    "sovits_model": "你的SoVITS模型权重路径",
    "gpt_model": "你的GPT模型权重路径",
    "text_lang": "中文",
    "ref_audio_path": "参考音频路径",
    "ref_text_path": "参考文本路径",
    "tts_volume": 0.0,
    "max_queue_size": 5,
    "enable_danmaku": true,
    "enable_gift": true,
    "enable_super_chat": true,
    "enable_guard": true,
    "enable_entry": false,
    "enable_follow": false,
    "enable_share": false,
    "enable_like_click": false,
    "min_price_yuan": 0.0,
    "template_danmaku": "{uname} 说，{content}",
    "template_gift": "感谢 {uname} 的{num}个{gift_name}",
    "template_super_chat": "感谢 {uname} 的{price}元SC，{content}",
    "replacement_rules": [
        {"key": "主播", "value": "我", "match_case": false, "whole_word": true, "use_regex": false}
    ]
}
```

### 8. 注册工具

在 `backend/tools.py` 中添加工具注册：

```python
from updates.live_stream.backend import LiveStreamManager
from updates.live_stream.plugins import BilibiliLivePlugin, VTubeStudioPlugin, LiveControlPlugin

bilibili_plugin = BilibiliLivePlugin()
vtube_plugin = VTubeStudioPlugin()
live_manager = LiveStreamManager()

live_manager.set_plugins(bilibili_plugin, vtube_plugin)
live_manager.set_engines(
    mouth_sync=mouth_sync_engine,
    expression_ctrl=expression_controller,
    topic_gen=topic_generator
)

live_control_plugin = LiveControlPlugin()
live_control_plugin.set_live_manager(live_manager)

register_tool(
    name="live_start",
    description="开始直播",
    func=live_control_plugin.start_live
)

register_tool(
    name="live_end",
    description="结束直播",
    func=live_control_plugin.end_live
)

register_tool(
    name="live_send",
    description="发送弹幕",
    func=live_control_plugin.send_message
)
```

## 使用方法

### 启动直播

```python
from updates.live_stream.plugins import LiveControlPlugin

plugin = LiveControlPlugin()

await plugin.start_live(
    room_id=12345678,
    sessdata="xxx",
    bili_jct="xxx",
    buvid3="xxx"
)
```

### 结束直播

```python
await plugin.end_live()
```

### 配置直播参数

```python
await plugin.config_live(
    cold_threshold=30,
    topic_interval=300,
    break_interval=1800,
    response_delay=2
)
```

### 获取直播统计

```python
stats = plugin.get_stats()
print(stats)
```

## 直播流程

```
1. 启动直播 → 连接B站弹幕 + 连接VTube Studio
2. 直播进行中：
   - 监听弹幕 → 情感分析 → 表情切换 → LLM回复 → 发送弹幕
   - 监听礼物 → 自动感谢 → 开心表情
   - 定时生成话题（每5分钟）
   - 冷场检测（30秒无弹幕）
   - 能量管理（每1分钟更新）
3. 休息时间（每30分钟自动休息5分钟）：
   - 发送休息消息
   - 恢复能量
4. 结束直播：
   - 发送告别消息
   - 断开连接
   - 保存直播记忆（时长、弹幕数、礼物数、热门话题）
```

## 注意事项

1. **B站Cookie**：需要从浏览器开发者工具获取，有效期约30天
2. **VTube Studio**：需要在本地运行，并在设置中允许API访问
3. **首次授权**：首次连接VTube Studio会弹出授权对话框，请确认授权
4. **Live2D模型参数**：建议配置以下参数：
   - MouthOpen (0-1): 嘴巴张开程度
   - EyeBlink (0-1): 眨眼
5. **表情热键**：需要在VTube Studio中提前配置：
   - happy_expression
   - sad_expression
   - surprised_expression
   - neutral_expression
   - angry_expression
   - shy_expression
   - excited_expression
6. **长时间直播建议**：
   - 确保网络稳定
   - 关闭不必要的后台程序
   - 配置定时休息（推荐每30分钟休息5分钟）
   - 监控能量值，低于20%会自动休息

## 插件状态

| 插件 | 默认状态 | 说明 |
|------|----------|------|
| bilibili_live | enabled=false | B站弹幕插件 |
| vtube_studio | enabled=false | 虚拟形象插件 |
| live_control | enabled=false | 直播控制插件 |

启用方法：修改 `plugin.toml` 中的 `enabled = true`

## 配置参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| cold_threshold | 30 | 冷场检测阈值（秒） |
| topic_interval | 300 | 话题生成间隔（秒） |
| break_interval | 1800 | 自动休息间隔（秒） |
| break_duration | 300 | 休息时长（秒） |
| energy_decay_rate | 0.005 | 能量消耗速率（每分钟） |
| energy_recovery_rate | 0.02 | 能量恢复速率（每分钟） |
| response_delay | 2 | 回复延迟（秒） |

## 扩展功能

可以通过以下方式扩展直播功能：

1. **添加更多话题**：在 `topic_generator.py` 的 `topics` 字典中添加新话题
2. **添加更多表情**：在 `expression_controller.py` 的 `expressions` 字典中添加新表情
3. **添加更多平台**：创建新的直播平台插件（如抖音、快手）
4. **添加更多互动**：在 `live_stream_manager.py` 中添加新的互动逻辑