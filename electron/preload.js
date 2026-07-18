const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  sendCommand: (cmd) => ipcRenderer.invoke("send-command", cmd),
  getFilePath: (filename, galleryType) => ipcRenderer.invoke("get-file-path", filename, galleryType),
  onProgress: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on("backend-progress", handler);
    return () => ipcRenderer.removeListener("backend-progress", handler);
  },
  onDone: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on("backend-done", handler);
    return () => ipcRenderer.removeListener("backend-done", handler);
  },
  onError: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on("backend-error", handler);
    return () => ipcRenderer.removeListener("backend-error", handler);
  },
  onPreview: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on("backend-preview", handler);
    return () => ipcRenderer.removeListener("backend-preview", handler);
  },
  onThinkingToken: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on("backend-thinking-token", handler);
    return () => ipcRenderer.removeListener("backend-thinking-token", handler);
  },
});
