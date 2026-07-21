const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const { spawn, execSync } = require("child_process");
const fs = require("fs");
const { setupAutoUpdater } = require("./updater");

let mainWindow;
let backendProcess;
let pendingCommands = new Map();
let cmdCounter = 0;

function getBaseDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "..");
  }
  return path.join(__dirname, "..");
}

function getPythonPath() {
  const baseDir = getBaseDir();
  const venvPython = process.platform === "win32"
    ? path.join(baseDir, ".venv", "Scripts", "python.exe")
    : path.join(baseDir, ".venv", "bin", "python3");

  try {
    if (fs.existsSync(venvPython)) return venvPython;
  } catch (e) {}

  const findCmd = process.platform === "win32" ? "where python" : "which python3 || which python";
  try {
    const result = execSync(findCmd, { encoding: "utf-8", timeout: 3000 }).trim().split("\n")[0];
    if (result && fs.existsSync(result)) return result;
  } catch (e) {}

  return process.platform === "win32" ? "python" : "python3";
}

function stripQuarantine() {
  if (process.platform !== "darwin") return;
  if (!app.isPackaged) return;

  try {
    const appPath = path.join(process.resourcesPath, "..");
    const result = execSync(`xattr -p com.apple.quarantine "${appPath}" 2>/dev/null`, {
      encoding: "utf-8",
      timeout: 5000,
    }).trim();

    if (result) {
      console.log("[Quarantine] App has quarantine attribute, stripping...");
      execSync(`xattr -cr "${appPath}"`, { stdio: "inherit", timeout: 10000 });
      console.log("[Quarantine] Attributes removed.");
      dialog.showMessageBox({
        type: "info",
        title: "Gatekeeper Fix",
        message: "De quarantine-attributen zijn verwijderd. Herstart de app om verder te gaan.",
        buttons: ["Herstarten"],
      }).then(() => {
        app.relaunch();
        app.quit();
      });
    }
  } catch (e) {
    // No quarantine attribute or xattr not available - all good
  }
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const baseDir = getBaseDir();
    const scriptPath = path.join(baseDir, "electron_backend.py");
    const cwd = baseDir;
    const pythonPath = getPythonPath();

    backendProcess = spawn(pythonPath, [scriptPath], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let resolved = false;
    let stdoutBuffer = "";

    backendProcess.stdout.on("data", (data) => {
      stdoutBuffer += data.toString();
      const lines = stdoutBuffer.split("\n");
      stdoutBuffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (msg.status === "ready" && !resolved) {
            resolved = true;
            resolve();
          } else if (msg.job_id && pendingCommands.has(msg.job_id)) {
            const pending = pendingCommands.get(msg.job_id);
            if (pending.resolve) {
              pending.resolve(msg);
              pendingCommands.delete(msg.job_id);
            }
          }
        } catch (e) {}
      }
    });

    backendProcess.stderr.on("data", (data) => {
      const lines = data.toString().split("\n");
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (msg.job_id && msg.type === "progress" && mainWindow) {
            mainWindow.webContents.send("backend-progress", msg);
          } else if (msg.job_id && msg.type === "done" && mainWindow) {
            mainWindow.webContents.send("backend-done", msg);
          } else if (msg.job_id && msg.type === "error" && mainWindow) {
            mainWindow.webContents.send("backend-error", msg);
          } else if (msg.job_id && msg.type === "preview" && mainWindow) {
            mainWindow.webContents.send("backend-preview", msg);
          } else if (msg.job_id && msg.type === "thinking_token" && mainWindow) {
            mainWindow.webContents.send("backend-thinking-token", msg);
          }
        } catch (e) {
          console.error("[backend]", line);
        }
      }
    });

    backendProcess.on("error", (err) => {
      if (!resolved) {
        resolved = true;
        reject(err);
      }
    });

    backendProcess.on("exit", (code) => {
      if (!resolved) {
        resolved = true;
        reject(new Error(`Backend exited with code ${code}`));
      }
    });

    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        reject(new Error("Timeout starting backend"));
      }
    }, 30000);
  });
}

function sendCommand(cmd) {
  return new Promise((resolve, reject) => {
    if (!backendProcess || backendProcess.killed) {
      reject(new Error("Backend niet gestart"));
      return;
    }

    const jobId = cmd.job_id || `cmd_${++cmdCounter}`;
    cmd.job_id = jobId;

    pendingCommands.set(jobId, { resolve, reject });

    const timeout = setTimeout(() => {
      if (pendingCommands.has(jobId)) {
        pendingCommands.delete(jobId);
        reject(new Error("Timeout"));
      }
    }, 600000);

    pendingCommands.get(jobId).timeout = timeout;

    try {
      backendProcess.stdin.write(JSON.stringify(cmd) + "\n");
    } catch (e) {
      clearTimeout(timeout);
      pendingCommands.delete(jobId);
      reject(e);
    }
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 760,
    minWidth: 800,
    minHeight: 600,
    title: "FTJM Studio",
    backgroundColor: "#0a0a0f",
    icon: path.join(__dirname, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  try {
    stripQuarantine();
    await startBackend();
    console.log("Backend ready");
    createWindow();
    setupAutoUpdater(mainWindow);
  } catch (err) {
    console.error("Failed to start backend:", err);
    const pythonPath = getPythonPath();
    dialog.showErrorBox(
      "Fout",
      `Kon de Python backend niet starten.\n\nPython: ${pythonPath}\nFout: ${err.message}\n\nZorg dat alle Python dependencies zijn geinstalleerd.`
    );
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (backendProcess) backendProcess.kill();
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});

app.on("before-quit", () => {
  if (backendProcess) backendProcess.kill();
});

ipcMain.handle("send-command", async (event, cmd) => {
  return sendCommand(cmd);
});

ipcMain.handle("get-file-path", (event, filename, galleryType) => {
  const baseDir = getBaseDir();
  if (galleryType === "photo") {
    const outputPath = path.join(baseDir, "output", filename);
    if (fs.existsSync(outputPath)) return outputPath;
    const galleryPath = path.join(baseDir, "gallery", "photos", filename);
    if (fs.existsSync(galleryPath)) return galleryPath;
  } else if (galleryType === "video") {
    const outputPath = path.join(baseDir, "output", filename);
    if (fs.existsSync(outputPath)) return outputPath;
    const galleryPath = path.join(baseDir, "gallery", "video", filename);
    if (fs.existsSync(galleryPath)) return galleryPath;
  } else if (galleryType === "audio") {
    const outputPath = path.join(baseDir, "output", filename);
    if (fs.existsSync(outputPath)) return outputPath;
    const galleryPath = path.join(baseDir, "gallery", "audio", filename);
    if (fs.existsSync(galleryPath)) return galleryPath;
  }
  return null;
});
