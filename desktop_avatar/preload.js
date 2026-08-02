/**
 * 元亨桌宠 - 预加载脚本
 * 暴露安全的IPC API给渲染进程
 */

const { contextBridge, ipcRenderer } = require('electron');

// 暴露给渲染进程的API
contextBridge.exposeInMainWorld('api', {
  // 窗口控制
  showWindow: () => ipcRenderer.invoke('window:show'),
  hideWindow: (playAnim = true) => ipcRenderer.invoke('window:hide', playAnim),
  closeWindow: () => ipcRenderer.invoke('window:close'),
  getWindowState: () => ipcRenderer.invoke('window:getState'),
  
  // 拖动
  startDrag: (winX, winY, curX, curY) => ipcRenderer.send('drag:start', winX, winY, curX, curY),
  updateDrag: (curX, curY) => ipcRenderer.send('drag:move', curX, curY),
  endDrag: () => ipcRenderer.send('drag:end'),
  
  // 点击穿透
  setClickThrough: (enabled, interactive = false) => ipcRenderer.invoke('clickThrough:set', enabled, interactive),
  toggleClickThrough: () => ipcRenderer.invoke('clickThrough:toggle'),
  
  // 缩放
  setScale: (scale) => ipcRenderer.invoke('window:setScale', scale),
  
  // 配置
  getConfig: () => ipcRenderer.invoke('config:get'),
  updateConfig: (updates) => ipcRenderer.invoke('config:update', updates),
  
  // 模型
  setModel: (path, name) => ipcRenderer.invoke('model:set', path, name),
  
  // 检测
  hitTest: (screenX, screenY) => ipcRenderer.invoke('window:hitTest', screenX, screenY),
  
  // 外部链接
  openExternal: (url) => ipcRenderer.send('open:external', url),
  
  // 事件监听
  onWindowStateChanged: (callback) => {
    ipcRenderer.on('window:state-changed', (_, state) => callback(state));
    return () => ipcRenderer.removeListener('window:state-changed', callback);
  },
  onCursorMoved: (callback) => {
    ipcRenderer.on('cursor:moved', (_, pos) => callback(pos));
    return () => ipcRenderer.removeListener('cursor:moved', callback);
  }
});