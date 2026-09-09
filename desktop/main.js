const { app, BrowserWindow, Tray, Menu, nativeImage, shell } = require("electron");
const path = require("path");

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
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.setAlwaysOnTop(true, "floating");
  win.loadURL(AVATAR_URL);
  win.on("close", (e) => {
    // close to tray
    if (!app.isQuiting) { e.preventDefault(); win.hide(); }
  });
}

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
