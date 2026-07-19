const { execSync } = require("child_process");
const path = require("path");
const fs = require("fs");

async function afterPack(context) {
  const { electronPlatformName, appOutDir } = context;

  if (electronPlatformName !== "darwin") return;

  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(appOutDir, `${appName}.app`);
  const venvInside = path.join(appPath, "Contents", ".venv");
  const venvTemp = path.join(appOutDir, ".venv.tmp");

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
}

module.exports = afterPack;
