# AIRI (moeru-ai/airi) 研究报告

> 研究时间：2026-08-02
> 仓库：https://github.com/moeru-ai/airi
> Stars：18.6K | Forks：1.8K | License：MIT

---

## 一、项目概述

AIRI 是一个开源、自托管的 AI 伴侣平台，灵感来自 Neuro-sama。目标是"将虚拟角色带入我们的世界"——让 AI waifu 拥有灵魂容器。

**核心定位**：模块化 AI-VTuber 框架，将核心引擎与可互换的 UI 层/服务插件分离。

### 平台矩阵

| 平台 | 名称 | 技术 | 最佳场景 |
|------|------|------|----------|
| Web | Stage Web | Vue 3 + WebGPU | 快速体验、无需安装 |
| Desktop | Stage Tamagotchi | Electron + CUDA/Metal | 本地模型、屏幕捕获 |
| Mobile | Stage Pocket | Capacitor (iOS/Android) | 移动端交互 |

---

## 二、技术架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────┐
│  Apps (stage-web / stage-tamagotchi / stage-pocket) │
├─────────────────────────────────────────────┤
│  Stage-UI (核心业务组件、composable、store)      │
│  ├── stage-ui-three   (Three.js + VRM)       │
│  ├── stage-ui-live2d  (PixiJS + Live2D)      │
│  └── stage-ui-pixi    (计划中)                │
├─────────────────────────────────────────────┤
│  Core (STT、Memory、Server Runtime、xsAI、Agent) │
├─────────────────────────────────────────────┤
│  Server SDK → Server Runtime (Discord/Telegram等) │
└─────────────────────────────────────────────┘
```

### 2.2 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | Vue 3 + TypeScript |
| 状态管理 | Pinia |
| 构建 | Vite (monorepo: pnpm workspaces) |
| 桌面壳 | Electron（原 Tauri，已迁移） |
| 2D 渲染 | PixiJS + pixi-live2d-display |
| 3D 渲染 | Three.js + WebGPU |
| 通信 | WebSocket + Eventa (IPC/RPC) |
| 样式 | UnoCSS |
| 动画 | animejs |
| 颜色 | culori |
| 包管理 | pnpm (catalog 协议) |

### 2.3 目录结构

```
airi/
├── apps/
│   ├── stage-web/          # Web 应用
│   └── stage-tamagotchi/   # Electron 桌面应用
├── packages/
│   ├── stage-ui/           # 核心业务组件/Store
│   ├── stage-ui-live2d/    # Live2D 渲染 (PixiJS)
│   ├── stage-ui-three/     # Three.js 3D 渲染
│   ├── stage-shared/       # 共享逻辑
│   ├── pipelines-audio/    # 音频处理管线
│   ├── ui/                 # 基础 UI 组件 (reka-ui)
│   └── i18n/               # 国际化
├── engines/
│   └── stage-tamagotchi-godot/  # Godot 引擎 (实验)
├── integrations/
│   └── vscode/             # VS Code 集成
├── services/               # 服务端插件
└── crates/                 # 旧 Tauri 代码 (已废弃)
```

---

## 三、Live2D 渲染方案

### 3.1 核心依赖

```json
{
  "pixi-live2d-display": "catalog:",   // Live2D Cubism 4 SDK for PixiJS
  "@pixi/app": "catalog:",
  "@pixi/core": "catalog:",
  "@pixi/display": "catalog:",
  "@pixi/interaction": "catalog:",
  "pixi-filters": "catalog:",          // 滤镜效果
  "animejs": "catalog:",               // 动画库
  "culori": "catalog:",                // 颜色处理
  "jszip": "catalog:",                 // Zip 模型加载
  "three": "catalog:"                  // 3D 辅助
}
```

**关键发现**：AIRI 的 Live2D 方案与我们的旧 WebView 方案**完全相同**——都使用 `pixi-live2d-display`（PixiJS + Cubism 4 Web SDK）。区别在于 AIRI 将其封装为 Vue 组件 + Pinia Store，而我们用的是原生 HTML + Python QWebEngineView。

### 3.2 组件结构

```
packages/stage-ui-live2d/src/
├── components/
│   └── scenes/
│       ├── Live2D.vue          # 场景入口组件
│       └── live2d/
│           ├── Canvas.vue      # PixiJS Canvas 封装
│           ├── Model.vue       # 模型加载与控制 (27KB!)
│           └── index.ts        # 导出 Live2DCanvas, Live2DModel
├── composables/
│   └── live2d/
│       ├── animation.ts        # 动画控制
│       ├── beat-sync.ts        # 音频节拍同步 (10.6KB)
│       └── index.ts
├── stores/
│   ├── model-parameters.ts     # 模型参数 Store
│   ├── expression-store.ts     # 表情系统 Store (12.2KB)
│   └── view-control.ts         # 视图控制
├── constants/
│   └── emotions.ts             # 情感定义
├── utils/
│   ├── eye-motions.ts          # 眼部运动 (扫视模型)
│   ├── live2d-preview.ts       # 预览工具
│   ├── live2d-zip-loader.ts    # Zip 加载器
│   ├── live2d-opfs-registration.ts  # OPFS 注册
│   └── opfs-loader.ts          # OPFS 加载器
└── tools/
    └── expression-tools.ts     # 表情工具 (LLM 可调用)
```

### 3.3 模型参数系统

```typescript
// stores/model-parameters.ts
export const defaultModelParameters = {
  angleX: 0, angleY: 0, angleZ: 0,        // 头部角度
  leftEyeOpen: 1, rightEyeOpen: 1,          // 眼睛开合
  leftEyeSmile: 0, rightEyeSmile: 0,        // 笑眼
  leftEyebrowLR: 0, rightEyebrowLR: 0,      // 眉毛水平
  leftEyebrowY: 0, rightEyebrowY: 0,        // 眉毛垂直
  leftEyebrowAngle: 0, rightEyebrowAngle: 0, // 眉毛角度
  leftEyebrowForm: 0, rightEyebrowForm: 0,  // 眉毛形状
  mouthOpen: 0, mouthForm: 0,               // 嘴型
  cheek: 0,                                  // 脸颊
  bodyAngleX: 0, bodyAngleY: 0, bodyAngleZ: 0, // 身体角度
  breath: 0,                                 // 呼吸
}
```

**亮点**：参数通过 `BroadcastChannel` 跨组件同步，支持多窗口联动。

### 3.4 表情系统（重点学习）

```typescript
// stores/expression-store.ts (核心设计)
export type ExpressionBlendMode = 'Add' | 'Multiply' | 'Overwrite'

export interface ExpressionEntry {
  name: string              // 人类可读名称
  parameterId: string       // Live2D 参数 ID
  blend: ExpressionBlendMode // 混合模式
  currentValue: number      // 当前运行值
  defaultValue: number      // 应用级默认值
  modelDefault: number      // moc3/exp3 原始默认值
  targetValue: number       // exp3 目标值
  resetTimer?: ReturnType<typeof setTimeout>  // 自动重置计时器
}

export interface ExpressionGroupDefinition {
  name: string
  parameters: {
    parameterId: string
    blend: ExpressionBlendMode
    value: number
  }[]
}
```

**设计亮点**：
1. **三种混合模式**：Add（叠加）、Multiply（乘算）、Overwrite（覆盖）
2. **自动重置计时器**：表情触发后自动回退到默认值
3. **模型默认值 vs 应用默认值**：允许用户自定义默认表情
4. **LLM 可调用**：导出的表情状态可供 LLM 通过工具调用读取

### 3.5 情感映射

```typescript
// constants/emotions.ts
export enum Emotion {
  Happy = 'happy',       // → Happy 动作
  Sad = 'sad',           // → Sad 动作
  Angry = 'angry',       // → Angry 动作
  Think = 'think',       // → Think 动作
  Surprise = 'surprised',// → Surprise 动作
  Awkward = 'awkward',   // → Awkward 动作
  Question = 'question', // → Question 动作
  Curious = 'curious',   // → Curious 动作
  Neutral = 'neutral',   // → Idle 动作
}
```

9 种情感，每种映射到对应的 Live2D Motion 组。同时也有 VRM 的表情映射。

### 3.6 眼部运动模型

```typescript
// utils/eye-motions.ts
// 基于概率分布的随机扫视间隔
// 概率分布：7.5%→800ms, 11%→1200ms, 12.5%→1600ms, ...
// 每次扫视间隔 = 基础值 + random(0, 400ms)
```

这是一个简单的概率模型，无需复杂的状态机，效果却自然。

---

## 四、可借鉴的设计模式

### 4.1 Store 驱动架构

AIRI 使用 Pinia Store 管理所有 Live2D 状态，通过 `BroadcastChannel` 实现多窗口/多组件同步。这对我们多模块 GUI 设计有参考价值。

### 4.2 表情系统

**三种混合模式**是最大亮点：
- `Add`：在现有参数上叠加（适合短暂表情）
- `Multiply`：按比例缩放（适合强度调节）
- `Overwrite`：直接覆盖（适合强表情切换）

配合 `resetTimer` 自动回退，避免了手动管理表情生命周期的麻烦。

### 4.3 节拍同步

`beat-sync.ts`（10.6KB）实现了音频节拍检测，用于驱动角色随音乐律动。适合未来扩展。

### 4.4 模型加载

支持 Zip 包直接加载、OPFS（Origin Private File System）缓存、空像素裁剪等优化。

### 4.5 Web Native 优先

全部使用 Web 技术栈（WebGPU、WebAudio、Web Workers、WebAssembly），跨平台零成本。Electron 桌面端原生支持 CUDA/Metal 加速。

---

## 五、与 YHLZ2.0 的对比

| 维度 | AIRI | YHLZ2.0 当前 |
|------|------|-------------|
| 渲染引擎 | PixiJS + pixi-live2d-display | live2d-py (native) + pygame |
| 桌面壳 | Electron | 原生 Python (pygame + win32) |
| 窗口透明 | Web 原生透明 | win32 LWA_COLORKEY 黑色透传 |
| 表情系统 | 3 种混合模式 + 自动回退 | 直接设置参数 |
| 情感数量 | 9 种（映射到 Motion） | 7 种（映射到光效颜色） |
| 眼部运动 | 概率扫视模型 | 状态机 + ease-out 补间 |
| 口型同步 | 音频节拍检测 | 三正弦叠加 |
| 状态管理 | Pinia + BroadcastChannel | 类属性 |
| 多模型支持 | Live2D + VRM | 仅 Live2D |
| 模型加载 | Zip + OPFS 缓存 | 目录文件加载 |
| 插件系统 | MCP 协议 | 无 |
| 游戏集成 | Minecraft + Factorio | 无 |
| LLM 提供者 | 40+ (xsAI 统一接口) | 单一后端 |

---

## 六、可立即采用的改进

### 6.1 表情混合模式

当前 YHLZ2.0 的表情是直接设置参数值，可以借鉴 AIRI 的三种混合模式：

```python
class ExpressionBlendMode(Enum):
    ADD = "add"           # 在现有值上叠加
    MULTIPLY = "multiply" # 按比例缩放
    OVERWRITE = "overwrite" # 直接覆盖

class ExpressionEntry:
    parameter_id: str
    blend: ExpressionBlendMode
    target_value: float
    reset_timer: float = 0  # 自动回退时间（秒）
```

### 6.2 眼部扫视概率模型

替换当前的状态机，改用概率分布：

```python
EYE_SACCADE_PROB = [
    (0.075, 800),   # 7.5% 概率 → 800ms 基础间隔
    (0.110, 1200),
    (0.125, 1600),
    (0.140, 2000),
    (0.125, 2400),
    (0.050, 2800),
    (0.040, 3200),
    (0.030, 3600),
    (0.020, 4000),
    (1.000, 4400),  # 兜底
]

def random_saccade_interval():
    r = random.random()
    for prob, base_ms in EYE_SACCADE_PROB:
        if r <= prob:
            return base_ms + random.random() * 400
    return 4400 + random.random() * 400
```

### 6.3 情感→Motion 映射表

当前只有情感→光效颜色，可以增加情感→Motion 映射：

```python
EMOTION_MOTION_MAP = {
    "happy": "Happy",
    "sad": "Sad",
    "angry": "Angry",
    "think": "Think",
    "surprised": "Surprise",
    "neutral": "Idle",
}
```

---

## 七、不适合采用的方案

1. **Electron 桌面壳**：YHLZ2.0 是 Python 原生项目，迁移到 Electron 成本过高且不符合技术栈
2. **PixiJS Web 渲染**：我们已从 WebView 方案迁移到 native live2d-py，性能更好
3. **MCP 插件系统**：当前项目规模不需要
4. **游戏集成**：非核心需求

---

## 八、总结

AIRI 是一个极其成熟的 AI-VTuber 框架，在以下几个方面值得 YHLZ2.0 学习：

1. **表情系统**：三种混合模式 + 自动回退，精妙且实用
2. **眼部运动**：概率扫视模型，简单有效
3. **情感→动作映射**：系统化的映射表
4. **Store 架构思想**：虽然我们不用 Pinia，但可以参考其 Store 模式组织状态
5. **节拍同步**：未来可扩展方向

AIRI 的 Live2D 方案（PixiJS + pixi-live2d-display）与我们已废弃的 WebView 方案相同，验证了 native live2d-py 方案在性能上的优势。