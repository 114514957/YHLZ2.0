# 元亨桌面虚拟形象

基于Electron的透明桌宠应用，借鉴[桌面灵(zhuomianling)](https://github.com/qiyueblues-design/zhuomianling)项目架构。

## 核心特性

- **透明无边框窗口** - 完全透明背景，只显示模型
- **窗口置顶** - `screen-saver`级别置顶，不被其他窗口遮挡
- **点击穿透** - 可切换穿透模式，不阻挡桌面操作
- **拖动调整** - 左键拖动移动位置
- **位置持久化** - 自动保存窗口位置
- **缩放适配** - 支持DPI缩放和窗口大小调整
- **关闭动画** - 平滑淡出动画
- **Live2D加载** - 支持Cubism 2/3/4/5模型
- **表情映射** - 点击、拖动触发模型动作

## 架构设计

```
┌─────────────────────────────────────────────────┐
│                  Electron 主进程                 │
│  main.js                                        │
│  ├── 窗口管理 (透明/置顶/穿透)                    │
│  ├── 位置持久化 (JSON配置)                        │
│  ├── 拖动处理 (IPC通信)                          │
│  ├── 关闭动画 (透明度渐变)                        │
│  └── 显示监听 (分辨率变化自适应)                    │
└────────────────────┬────────────────────────────┘
                     │ IPC
┌────────────────────▼────────────────────────────┐
│                 渲染进程 (pet.html)               │
│  ├── Live2D加载 (Pixi.js + Cubism SDK)           │
│  ├── 模型交互 (点击/拖动/动作)                    │
│  ├── 右键菜单 (穿透/锁定/缩放)                    │
│  ├── 字幕气泡                                    │
│  └── 状态指示 (语音/思考/倾听)                     │
└─────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 安装依赖
npm install

# 开发模式运行
npm start

# 构建Windows应用
npm run build
```

## 参考实现要点

### 1. 透明窗口创建

```javascript
const win = new BrowserWindow({
    frame: false,           // 无边框
    transparent: true,      // 透明背景
    hasShadow: false,       // 无阴影
    skipTaskbar: true,      // 不显示在任务栏
    alwaysOnTop: true,      // 置顶
    backgroundColor: '#00000000',  // 完全透明
});
```

### 2. 点击穿透

```javascript
// 切换穿透模式
win.setIgnoreMouseEvents(enabled, { forward: true });
// forward: true 让鼠标事件穿透窗口
```

### 3. 拖动实现

```javascript
// 渲染进程发送拖动事件
ipcRenderer.send('drag:start', winX, winY, curX, curY);
ipcRenderer.send('drag:move', curX, curY);
ipcRenderer.send('drag:end');

// 主进程处理拖动
ipcMain.on('drag:move', (_, curX, curY) => {
    const dx = curX - dragStart.cursor.x;
    const dy = curY - dragStart.cursor.y;
    win.setPosition(dragStart.window.x + dx, dragStart.window.y + dy);
});
```

### 4. 关闭动画

```javascript
function animateClose() {
    return new Promise((resolve) => {
        const startOpacity = win.getOpacity();
        const startTime = performance.now();
        const duration = 330;
        
        const animate = () => {
            const progress = Math.min(1, (performance.now() - startTime) / duration);
            const eased = 1 - progress * progress;
            win.setOpacity(startOpacity * eased);
            
            if (progress >= 1) {
                win.hide();
                win.setOpacity(startOpacity);
                resolve();
                return;
            }
            setTimeout(animate, 16);
        };
        animate();
    });
}
```

### 5. 位置持久化

```javascript
function persistPosition(bounds) {
    const config = loadConfig();
    config.position = { x: bounds.x, y: bounds.y };
    saveConfig(config);
}
```

## 与Python后端集成

桌宠窗口通过HTTP API与Python后端通信：

```python
# Python后端
@app.post("/api/avatar/expression")
async def set_expression(expression: str):
    # 通过Electron IPC触发表情
    pass

@app.post("/api/avatar/motion")  
async def play_motion(motion: str):
    # 触发动作
    pass
```

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 桌面框架 | Electron 28+ | 透明窗口、置顶、系统集成 |
| 渲染 | Pixi.js 6+ | WebGL渲染Live2D模型 |
| Live2D | pixi-live2d-display | Cubism 2/4支持 |
| 通信 | IPC | 主进程与渲染进程通信 |
| 存储 | JSON文件 | 配置持久化 |

## 项目结构

```
desktop_avatar/
├── main.js          # Electron主进程
├── preload.js       # 预加载脚本
├── pet.html         # 渲染进程
├── package.json     # 项目配置
├── start.bat        # Windows启动脚本
└── assets/          # 图标等资源
```

## 借鉴自桌面灵的实现

1. **窗口状态管理** - `applyPetWindowState()` 统一管理窗口属性
2. **显示适配** - `registerDisplayRecoveryListeners()` 监听显示器变化
3. **边界限制** - `clampPetWindowBoundsToWorkArea()` 防止窗口跑出屏幕
4. **拖动流程** - start → move → end 三阶段拖动
5. **点击穿透** - 智能切换穿透模式
6. **状态广播** - `broadcastState()` 统一状态更新

## 许可证

MIT License