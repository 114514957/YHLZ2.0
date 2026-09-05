/**
 * 元亨桌面虚拟形象 - Electron主进程
 * 借鉴桌面灵(zhuomianling)项目架构
 * 
 * 核心特性:
 * - 透明无边框窗口
 * - 窗口置顶 (screen-saver级别)
 * - 点击穿透切换
 * - 拖动调整位置
 * - 缩放适配DPI
 * - 位置持久化
 * - 关闭动画
 */

const { app, BrowserWindow, ipcMain, screen, shell } = require('electron');
const path = require('path');
const fs = require('fs');

// ============ 配置 ============
const CONFIG = {
  window: {
    width: 380,
    height: 480,
    edgeMargin: 28,
    minVisibleWidth: 80,
    minVisibleHeight: 80,
    defaultScale: 1.0,
  },
  animation: {
    closeDuration: 330,
    frameInterval: 16,
    cursorTrackingInterval: 50,
  },
  path: {
    userDataDir: 'yuanheng-avatar',
    configFile: 'avatar-config.json',
  }
};

let petWindow = null;
let clickThrough = false;
let clickThroughInteractive = false;
let currentConfig = null;
let cursorTrackingTimer = null;
let isQuitting = false;
let dragStart = null;

// ============ 配置管理 ============
function getUserDataPath() {
  const userDataDir = path.join(app.getPath('appData'), CONFIG.path.userDataDir);
  if (!fs.existsSync(userDataDir)) {
    fs.mkdirSync(userDataDir, { recursive: true });
  }
  return userDataDir;
}

function loadConfig() {
  const configPath = path.join(getUserDataPath(), CONFIG.path.configFile);
  try {
    if (fs.existsSync(configPath)) {
      return JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    }
  } catch (e) {
    console.error('加载配置失败:', e);
  }
  return getDefaultConfig();
}

function saveConfig(config) {
  const configPath = path.join(getUserDataPath(), CONFIG.path.configFile);
  try {
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf-8');
    currentConfig = config;
    return true;
  } catch (e) {
    console.error('保存配置失败:', e);
    return false;
  }
}

function getDefaultConfig() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const workArea = primaryDisplay.workArea;
  const scale = CONFIG.window.defaultScale;
  const width = Math.round(CONFIG.window.width * scale);
  const height = Math.round(CONFIG.window.height * scale);
  
  return {
    version: '1.0',
    position: {
      x: workArea.x + workArea.width - width - CONFIG.window.edgeMargin,
      y: workArea.y + workArea.height - height - CONFIG.window.edgeMargin
    },
    size: { width, height },
    scale: scale,
    model: {
      modelPath: '',
      modelName: '元亨'
    },
    ui: {
      theme: 'dark',
      showChat: true,
      showSubtitle: true
    }
  };
}

// ============ 窗口管理 ============
function getWindowBounds(config) {
  const scale = config.scale || CONFIG.window.defaultScale;
  const size = config.size || {
    width: Math.round(CONFIG.window.width * scale),
    height: Math.round(CONFIG.window.height * scale)
  };
  
  const position = config.position || {
    x: screen.getPrimaryDisplay().workArea.width - size.width - CONFIG.window.edgeMargin,
    y: screen.getPrimaryDisplay().workArea.height - size.height - CONFIG.window.edgeMargin
  };
  
  const workArea = screen.getDisplayMatching({
    x: position.x,
    y: position.y,
    width: size.width,
    height: size.height
  }).workArea;
  
  return clampToWorkArea(position.x, position.y, size.width, size.height, workArea);
}

function clampToWorkArea(x, y, width, height, workArea) {
  const minW = Math.min(width, CONFIG.window.minVisibleWidth);
  const minH = Math.min(height, CONFIG.window.minVisibleHeight);
  
  return {
    x: Math.min(Math.max(x, workArea.x - width + minW), workArea.x + workArea.width - minW),
    y: Math.min(Math.max(y, workArea.y - height + minH), workArea.y + workArea.height - minH),
    width,
    height
  };
}

function createPetWindow() {
  const config = currentConfig || loadConfig();
  const bounds = getWindowBounds(config);
  
  petWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    x: bounds.x,
    y: bounds.y,
    frame: false,
    transparent: true,
    resizable: false,
    maximizable: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: true,
    backgroundColor: '#00000000',
    title: '元亨桌宠',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true
    }
  });
  
  applyWindowState();
  registerDisplayListeners();
  setupWindowEvents();
  
  const petHtmlPath = path.join(__dirname, 'pet.html');
  petWindow.loadFile(petHtmlPath);
  
  return petWindow;
}

function applyWindowState() {
  if (!petWindow || petWindow.isDestroyed()) return;
  
  petWindow.setAlwaysOnTop(true, 'screen-saver');
  petWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  petWindow.setIgnoreMouseEvents(clickThrough && !clickThroughInteractive, { forward: true });
  petWindow.setResizable(false);
  petWindow.setMenuBarVisibility(false);
}

function setupWindowEvents() {
  if (!petWindow) return;
  
  petWindow.on('closed', () => {
    petWindow = null;
    stopCursorTracking();
    clickThrough = false;
    clickThroughInteractive = false;
    dragStart = null;
    broadcastState();
  });
  
  petWindow.on('show', applyWindowState);
  petWindow.on('focus', applyWindowState);
  petWindow.on('blur', applyWindowState);
}

function registerDisplayListeners() {
  screen.on('display-metrics-changed', () => {
    if (petWindow && !petWindow.isDestroyed()) {
      enforceWindowSize();
    }
  });
  
  screen.on('display-removed', () => {
    if (petWindow && !petWindow.isDestroyed()) {
      enforceWindowSize();
    }
  });
}

function enforceWindowSize() {
  if (!petWindow || petWindow.isDestroyed()) return;
  
  const bounds = petWindow.getBounds();
  const scale = currentConfig?.scale || CONFIG.window.defaultScale;
  const targetSize = {
    width: Math.round(CONFIG.window.width * scale),
    height: Math.round(CONFIG.window.height * scale)
  };
  
  const workArea = screen.getDisplayMatching(bounds).workArea;
  const centerX = bounds.x + bounds.width / 2;
  const bottomY = bounds.y + bounds.height;
  
  const newX = Math.round(centerX - targetSize.width / 2);
  const newY = Math.round(bottomY - targetSize.height);
  
  const newBounds = clampToWorkArea(newX, newY, targetSize.width, targetSize.height, workArea);
  
  if (bounds.x !== newBounds.x || bounds.y !== newBounds.y || 
      bounds.width !== newBounds.width || bounds.height !== newBounds.height) {
    petWindow.setBounds(newBounds);
    persistPosition(newBounds);
  }
}

function persistPosition(bounds) {
  if (!currentConfig) return;
  
  currentConfig.position = { x: bounds.x, y: bounds.y };
  currentConfig.size = { width: bounds.width, height: bounds.height };
  saveConfig(currentConfig);
}

// ============ 拖动功能 ============
function startDrag(windowX, windowY, cursorX, cursorY) {
  if (!petWindow || petWindow.isDestroyed()) return;
  
  const bounds = petWindow.getBounds();
  dragStart = {
    cursor: { x: cursorX, y: cursorY },
    window: { x: bounds.x, y: bounds.y }
  };
  
  if (clickThrough) {
    setClickThrough(false, false);
  }
}

function updateDrag(cursorX, cursorY) {
  if (!dragStart || !petWindow || petWindow.isDestroyed()) return;
  
  const dx = cursorX - dragStart.cursor.x;
  const dy = cursorY - dragStart.cursor.y;
  
  const newX = dragStart.window.x + dx;
  const newY = dragStart.window.y + dy;
  
  const bounds = petWindow.getBounds();
  const workArea = screen.getDisplayMatching({
    x: newX, y: newY, width: bounds.width, height: bounds.height
  }).workArea;
  
  const clamped = clampToWorkArea(newX, newY, bounds.width, bounds.height, workArea);
  petWindow.setPosition(clamped.x, clamped.y);
}

function endDrag() {
  if (dragStart && petWindow && !petWindow.isDestroyed()) {
    persistPosition(petWindow.getBounds());
  }
  dragStart = null;
}

// ============ 点击穿透 ============
function setClickThrough(enabled, interactive = false) {
  clickThrough = enabled;
  clickThroughInteractive = interactive;
  applyWindowState();
  broadcastState();
}

function toggleClickThrough() {
  setClickThrough(!clickThrough, false);
}

// ============ 游标追踪 ============
function startCursorTracking() {
  if (cursorTrackingTimer) return;
  
  emitCursorPosition();
  cursorTrackingTimer = setInterval(emitCursorPosition, CONFIG.animation.cursorTrackingInterval);
}

function stopCursorTracking() {
  if (cursorTrackingTimer) {
    clearInterval(cursorTrackingTimer);
    cursorTrackingTimer = null;
  }
}

function emitCursorPosition() {
  if (!petWindow || petWindow.isDestroyed()) return;
  
  const point = screen.getCursorScreenPoint();
  const [winX, winY] = petWindow.getPosition();
  
  petWindow.webContents.send('cursor:moved', {
    screenX: point.x,
    screenY: point.y,
    windowX: point.x - winX,
    windowY: point.y - winY
  });
}

// ============ 状态广播 ============
function getState() {
  return {
    visible: Boolean(petWindow && !petWindow.isDestroyed() && petWindow.isVisible()),
    clickThrough,
    position: petWindow ? petWindow.getBounds() : null,
    config: currentConfig
  };
}

function broadcastState() {
  if (petWindow && !petWindow.isDestroyed()) {
    petWindow.webContents.send('window:state-changed', getState());
  }
}

// ============ 窗口动画 ============
function animateClose() {
  return new Promise((resolve) => {
    if (!petWindow || petWindow.isDestroyed()) {
      resolve();
      return;
    }
    
    const startOpacity = petWindow.getOpacity();
    const startTime = performance.now();
    const duration = CONFIG.animation.closeDuration;
    const frameInterval = CONFIG.animation.frameInterval;
    
    const animate = () => {
      if (!petWindow || petWindow.isDestroyed()) {
        resolve();
        return;
      }
      
      const progress = Math.min(1, (performance.now() - startTime) / duration);
      const easeOut = 1 - progress * progress;
      
      petWindow.setOpacity(startOpacity * easeOut);
      
      if (progress >= 1) {
        petWindow.hide();
        petWindow.setOpacity(startOpacity);
        resolve();
        return;
      }
      
      setTimeout(animate, frameInterval);
    };
    
    animate();
  });
}

function showPetWindow() {
  if (petWindow && !petWindow.isDestroyed()) {
    petWindow.show();
    petWindow.focus();
    applyWindowState();
    startCursorTracking();
  } else {
    createPetWindow();
    petWindow.show();
    petWindow.focus();
    startCursorTracking();
  }
  broadcastState();
}

async function hidePetWindow(playAnimation = true) {
  if (!petWindow || petWindow.isDestroyed()) return;
  
  if (playAnimation) {
    await animateClose();
  }
  
  petWindow.hide();
  stopCursorTracking();
  broadcastState();
}

// ============ IPC 通信 ============
function registerIPC() {
  // 窗口控制
  ipcMain.handle('window:show', () => showPetWindow());
  ipcMain.handle('window:hide', async (_, playAnim = true) => {
    await hidePetWindow(playAnim);
  });
  ipcMain.handle('window:close', async () => {
    await hidePetWindow(true);
    if (!isQuitting) {
      isQuitting = true;
      app.quit();
    }
  });
  ipcMain.handle('window:getState', () => getState());
  
  // 拖动
  ipcMain.on('drag:start', (_, windowX, windowY, cursorX, cursorY) => {
    startDrag(windowX, windowY, cursorX, cursorY);
  });
  ipcMain.on('drag:move', (_, cursorX, cursorY) => {
    updateDrag(cursorX, cursorY);
  });
  ipcMain.on('drag:end', () => endDrag());
  
  // 点击穿透
  ipcMain.handle('clickThrough:set', (_, enabled, interactive) => {
    setClickThrough(enabled, interactive);
  });
  ipcMain.handle('clickThrough:toggle', () => {
    toggleClickThrough();
    return clickThrough;
  });
  
  // 缩放
  ipcMain.handle('window:setScale', (_, scale) => {
    if (!currentConfig) return;
    currentConfig.scale = scale;
    saveConfig(currentConfig);
    enforceWindowSize();
  });
  
  // 配置
  ipcMain.handle('config:get', () => currentConfig || loadConfig());
  ipcMain.handle('config:update', (_, updates) => {
    if (!currentConfig) currentConfig = loadConfig();
    currentConfig = { ...currentConfig, ...updates };
    saveConfig(currentConfig);
    enforceWindowSize();
    return currentConfig;
  });
  
  // 模型
  ipcMain.handle('model:set', (_, modelPath, modelName) => {
    if (!currentConfig) currentConfig = loadConfig();
    currentConfig.model = { modelPath, modelName };
    saveConfig(currentConfig);
    return true;
  });
  
  // 外部链接
  ipcMain.on('open:external', (_, url) => {
    shell.openExternal(url);
  });
  
  // 检测光标是否在窗口内 (用于智能切换点击穿透)
  ipcMain.handle('window:hitTest', (_, screenX, screenY) => {
    if (!petWindow || petWindow.isDestroyed()) return false;
    const bounds = petWindow.getBounds();
    return screenX >= bounds.x && screenX <= bounds.x + bounds.width &&
           screenY >= bounds.y && screenY <= bounds.y + bounds.height;
  });
}

// ============ 应用生命周期 ============
function initApp() {
  const gotLock = app.requestSingleInstanceLock();
  
  if (!gotLock) {
    app.quit();
    return;
  }
  
  app.on('second-instance', () => {
    if (petWindow && !petWindow.isDestroyed()) {
      if (petWindow.isMinimized()) petWindow.restore();
      if (!petWindow.isVisible()) petWindow.show();
      petWindow.focus();
    }
  });
  
  app.whenReady().then(() => {
    currentConfig = loadConfig();
    registerIPC();
    
    showPetWindow();
    
    console.log('✅ 元亨桌面虚拟形象已启动');
    console.log('   点击桌面图标或按Alt+Tab可见窗口');
  });
  
  app.on('before-quit', async (e) => {
    if (!isQuitting) {
      isQuitting = true;
      e.preventDefault();
      
      if (petWindow) {
        await animateClose();
        petWindow.destroy();
      }
      
      app.exit(0);
    }
  });
  
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
  
  app.on('activate', () => {
    if (!petWindow || petWindow.isDestroyed()) {
      showPetWindow();
    }
  });
}

// 启动
initApp();