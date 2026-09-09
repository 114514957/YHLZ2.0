const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("pet", {
  mouseThrough: (on) => ipcRenderer.send("pet-mouse", !!on),
});
