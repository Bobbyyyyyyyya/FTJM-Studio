const { autoUpdater } = require("electron-updater");
const { app, dialog, BrowserWindow } = require("electron");
const path = require("path");

let updateWindow = null;

function setupAutoUpdater(mainWindow) {
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on("checking-for-update", () => {
    console.log("[Updater] Controleren op updates...");
  });

  autoUpdater.on("update-available", (info) => {
    console.log("[Updater] Update beschikbaar:", info.version);
    dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "Update beschikbaar",
      message: `Er is een nieuwe versie beschikbaar: v${info.version}`,
      buttons: ["Downloaden", "Later"],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.downloadUpdate();
        showDownloadProgress(mainWindow);
      }
    });
  });

  autoUpdater.on("update-not-available", (info) => {
    console.log("[Updater] Geen update beschikbaar.");
  });

  autoUpdater.on("download-progress", (progress) => {
    const msg = `Downloaden: ${Math.round(progress.percent)}%`;
    console.log(`[Updater] ${msg}`);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend-progress", {
        type: "progress",
        job_id: "__updater__",
        progress: progress.percent,
        message: msg,
      });
    }
  });

  autoUpdater.on("update-downloaded", (info) => {
    console.log("[Updater] Update gedownload:", info.version);
    dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "Update gereed",
      message: `Update v${info.version} is gedownload. De app wordt nu herstart om de update te installeren.`,
      buttons: ["Herstarten", "Later"],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.quitAndInstall();
      }
    });
  });

  autoUpdater.on("error", (err) => {
    console.error("[Updater] Fout:", err.message);
  });

  // Check bij startup, na 5 seconden
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((err) => {
      console.log("[Updater] Kon niet controleren:", err.message);
    });
  }, 5000);

  // Elke 30 minuten controleren
  setInterval(() => {
    autoUpdater.checkForUpdates().catch(() => {});
  }, 30 * 60 * 1000);
}

module.exports = { setupAutoUpdater };
