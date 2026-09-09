const { app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain, screen } = require("electron");
const path = require("path");

// Transparent frameless pet window (YHLZ avatar). Page must be transparent
// (avatar.html pet mode makes both html+body transparent).

let win = null;
let tray = null;

const CONSOLE_URL = "http://127.0.0.1:8321/";
const AVATAR_URL = "http://127.0.0.1:8321/avatar.html?pet=1";

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

function makeTray() {
  let icon = path.join(__dirname, "..", "assets", "icons", "yhlz-app2.ico");
  tray = new Tray(nativeImage.createFromPath(icon));
  tray.setToolTip("YHLZ · 元 · 亨 · 利 · 贞");
  const menu = Menu.buildFromTemplate([
    { label: "显示/隐藏桌宠", click: () => { if (win) win.isVisible() ? win.hide() : win.show(); } },
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
