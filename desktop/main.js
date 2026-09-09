const { app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain } = require("electron");
const path = require("path");

// Transparent frameless pet window (YHLZ avatar). Page must be transparent
// (avatar.html pet mode makes both html+body transparent).

let win = null;
let tray = null;

const CONSOLE_URL = "http://127.0.0.1:8321/";
const AVATAR_URL = "http://127.0.0.1:8321/avatar.html?pet=1";

function makeWindow() {
  win = new BrowserWindow({
    width: 460,
    height: 680,
    transparent: true,
    frame: false,
    resizable: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    hasShadow: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  win.setAlwaysOnTop(true, "floating");
  win.loadURL(AVATAR_URL);
  // by default let the mouse click through the transparent window; the page
  // toggles it back on when the pointer is over the model / drag bar
  win.setIgnoreMouseEvents(true, { forward: true });
  win.on("close", (e) => {
    if (!app.isQuiting) { e.preventDefault(); win.hide(); }
  });
}

ipcMain.on("pet-mouse", (_e, on) => {
  if (win) win.setIgnoreMouseEvents(!!on, { forward: true });
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
