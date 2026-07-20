const { execSync } = require("child_process");
const path = require("path");
const fs = require("fs");

function copyDirSync(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isSymbolicLink()) {
      const target = fs.readlinkSync(srcPath);
      fs.symlinkSync(target, destPath);
    } else if (entry.isDirectory()) {
      copyDirSync(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

async function afterPack(context) {
  const { electronPlatformName, appOutDir } = context;
  const projectRoot = path.resolve(appOutDir, "..", "..");

  if (electronPlatformName === "darwin") {
    const appName = context.packager.appInfo.productFilename;
    const appPath = path.join(appOutDir, `${appName}.app`);
    const venvInside = path.join(appPath, "Contents", ".venv");
    const venvSource = path.join(projectRoot, ".venv");
    const venvTemp = path.join(appOutDir, ".venv.tmp");

    if (!fs.existsSync(venvInside) && fs.existsSync(venvSource)) {
      console.log("Copying .venv into .app bundle...");
      copyDirSync(venvSource, venvInside);
    }

    if (fs.existsSync(venvInside)) {
      console.log("Moving .venv out of .app bundle for signing...");
      fs.renameSync(venvInside, venvTemp);
    }

    console.log(`Ad-hoc signing: ${appPath}`);
    execSync(`codesign --force --deep --sign - "${appPath}"`, { stdio: "inherit" });
    console.log("Ad-hoc signing complete");

    if (fs.existsSync(venvTemp)) {
      console.log("Restoring .venv into .app bundle...");
      fs.renameSync(venvTemp, venvInside);
    }

    console.log("Verifying .venv in app bundle...");
    const pythonBin = path.join(venvInside, "bin", "python3");
    if (!fs.existsSync(pythonBin)) {
      console.warn("WARNING: .venv/bin/python3 not found in app bundle!");
    } else {
      console.log(".venv bundled successfully.");
    }
  } else if (electronPlatformName === "win32") {
    const venvDest = path.join(appOutDir, "win-unpacked", ".venv");
    const venvSource = path.join(projectRoot, ".venv");

    if (!fs.existsSync(venvDest) && fs.existsSync(venvSource)) {
      console.log("Copying .venv into Windows build...");
      copyDirSync(venvSource, venvDest);
      console.log(".venv bundled successfully (Windows).");
    }
  } else if (electronPlatformName === "linux") {
    const venvDest = path.join(appOutDir, "linux-unpacked", ".venv");
    const venvSource = path.join(projectRoot, ".venv");

    if (!fs.existsSync(venvDest) && fs.existsSync(venvSource)) {
      console.log("Copying .venv into Linux build...");
      copyDirSync(venvSource, venvDest);
      console.log(".venv bundled successfully (Linux).");
    }
  }
}

module.exports = afterPack;
