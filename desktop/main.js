const { app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain, screen } = require("electron");
const path = require("path");

// Transparent frameless pet window (YHLZ avatar). Page must be transparent
// (avatar.html pet mode makes both html+body transparent).

let win = null;
let tray = null;
let chatWin = null;

const CONSOLE_URL = "http://127.0.0.1:8321/";
const AVATAR_URL = "http://127.0.0.1:8321/avatar.html?pet=1";
const CHAT_URL = "http://127.0.0.1:8321/chat_popup.html";

function openChat() {
  if (!chatWin || chatWin.isDestroyed()) {
    chatWin = new BrowserWindow({
      width: 560,
      height: 720,
      title: "YHLZ · 对话",
      autoHideMenuBar: true,
      webPreferences: { contextIsolation: true, nodeIntegration: false },
    });
    chatWin.loadURL(CHAT_URL);
    chatWin.on("closed", () => { chatWin = null; });
  } else {
    if (chatWin.isMinimized()) chatWin.restore();
    chatWin.show();
    chatWin.focus();
  }
}

function makeWindow() {
  // Full-display transparent overlay (includes taskbar strip so the pet can
  // roam the whole physical screen); blank areas click through.
  const disp = screen.getPrimaryDisplay();
  const b = disp.bounds;
  win = new BrowserWindow({
    x: b.x,
    y: b.y,
    width: b.width,
    height: b.height,
    transparent: true,
    frame: false,
    resizable: false,
    movable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    focusable: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  win.loadURL(AVATAR_URL);
  win.setIgnoreMouseEvents(true, { forward: true });
  win.on("close", (e) => {
    if (!app.isQuiting) { e.preventDefault(); win.hide(); }
  });
}

ipcMain.on("pet-mouse", (_e, on) => {
  if (win) win.setIgnoreMouseEvents(!!on, { forward: true });
});
ipcMain.on("pet-size", (_e, { w, h }) => {
  if (win) {
    const ww = Math.max(90, Math.min(1600, Math.round(w)));
    const hh = Math.max(90, Math.min(1600, Math.round(h)));
    win.setContentSize(ww, hh, true);
  }
});

async function modelsSubmenu() {
  try {
    const r = await fetch("http://127.0.0.1:8321/avatar-models");
    const j = await r.json();
    return (j.items || []).map((it) => ({
      label: it.name,
      click: () => {
        if (win && win.webContents) {
          win.webContents.executeJavaScript(
            "window.__petSwitchModel && " +
            "window.__petSwitchModel(" + JSON.stringify(it.rel) + ")");
        }
      },
    }));
  } catch (e) {
    return [];
  }
}

function setPetDrag(on) {
  if (!win) return;
  if (on) {
    // renderer claims the mouse only while a drag is held; otherwise the
    // overlay stays click-through so the desktop is always usable.
    win.webContents.executeJavaScript(
      "window.__petSetDrag && window.__petSetDrag(true)");
  } else {
    win.webContents.executeJavaScript(
      "window.__petSetDrag && window.__petSetDrag(false)");
    win.setIgnoreMouseEvents(true, { forward: true });
  }
}

async function makeTray() {
  let icon = path.join(__dirname, "..", "assets", "icons", "yhlz-app2.ico");
  tray = new Tray(nativeImage.createFromPath(icon));
  tray.setToolTip("YHLZ · 元 · 亨 · 利 · 贞");
  const models = await modelsSubmenu();
  const menu = Menu.buildFromTemplate([
    { label: "显示/隐藏桌宠", click: () => { if (win) win.isVisible() ? win.hide() : win.show(); } },
    { type: "separator" },
    { label: "锁定（纯展示/穿透）", type: "radio", checked: true,
      click: () => setPetDrag(false) },
    { label: "拖动元亨", type: "radio",
      click: () => setPetDrag(true) },
    { type: "separator" },
    { label: "对话", click: openChat },
    { label: "切换形象", submenu: models.length ? models : [{ label: "(无模型)", enabled: false }] },
    { label: "打开工作台", click: () => shell.openExternal(CONSOLE_URL) },
    { type: "separator" },
    { label: "退出", click: () => { app.isQuiting = true; app.quit(); } },
  ]);
  tray.setContextMenu(menu);
  tray.on("double-click", () => { if (win) win.isVisible() ? win.hide() : win.show(); });
}

app.isQuiting = false;
app.whenReady().then(() => {
  makeWindow();
  makeTray();
});
app.on("window-all-closed", (e) => { /* keep in tray */ });
