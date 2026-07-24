const { execSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const https = require("https");

const PYTHON_VERSION = "3.11.10";
const PBS_RELEASE = "20241016";

function copyDirSync(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isSymbolicLink()) {
      const realSrc = fs.realpathSync(srcPath);
      if (fs.statSync(realSrc).isDirectory()) {
        copyDirSync(realSrc, destPath);
      } else {
        fs.copyFileSync(realSrc, destPath);
      }
    } else if (entry.isDirectory()) {
      copyDirSync(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function getStandaloneUrl() {
  const platformMap = {
    darwin: "apple-darwin",
    linux: "unknown-linux-gnu",
    win32: "pc-windows-msvc",
  };
  const archMap = { arm64: "aarch64", x64: "x86_64" };

  const p = platformMap[process.platform];
  const a = archMap[process.arch];
  if (!p || !a) throw new Error(`Unsupported: ${process.platform}/${process.arch}`);

  const suffix = process.platform === "win32" ? ".zip" : ".tar.gz";
  return `https://github.com/indygreg/python-build-standalone/releases/download/${PBS_RELEASE}/cpython-${PYTHON_VERSION}+${PBS_RELEASE}-${a}-${p}-install_only${suffix}`;
}

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const follow = (u) => {
      https.get(u, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          return follow(res.headers.location);
        }
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode} for ${u}`));
        }
        const file = fs.createWriteStream(dest);
        res.pipe(file);
        file.on("finish", () => { file.close(resolve); });
        file.on("error", (err) => { fs.unlink(dest, () => {}); reject(err); });
      }).on("error", reject);
    };
    follow(url);
  });
}

async function ensureVenv(projectRoot) {
  const venvDir = path.join(projectRoot, ".venv");
  const venvPython = process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python3");

  if (fs.existsSync(venvPython)) {
    console.log("Existing .venv found, skipping creation.");
    return;
  }

  const cacheDir = path.join(projectRoot, ".cache");
  fs.mkdirSync(cacheDir, { recursive: true });
  const url = getStandaloneUrl();
  const filename = path.basename(url);
  const cachePath = path.join(cacheDir, filename);

  if (!fs.existsSync(cachePath)) {
    console.log(`Downloading standalone Python ${PYTHON_VERSION}...`);
    console.log(`  ${url}`);
    await downloadFile(url, cachePath);
    console.log("  Download complete.");
  } else {
    console.log(`Using cached standalone Python: ${filename}`);
  }

  console.log("Extracting Python into .venv...");
  fs.mkdirSync(venvDir, { recursive: true });
  if (process.platform === "win32") {
    execSync(`tar -xf "${cachePath}" --strip-components=1 -C "${venvDir}"`, { stdio: "inherit" });
  } else {
    execSync(`tar -xzf "${cachePath}" --strip-components=1 -C "${venvDir}"`, { stdio: "inherit" });
  }

  const requirements = path.join(projectRoot, "requirements.txt");
  if (fs.existsSync(requirements)) {
    const pip = process.platform === "win32"
      ? path.join(venvDir, "Scripts", "pip.exe")
      : path.join(venvDir, "bin", "pip3");
    console.log("Installing Python dependencies (this may take a while)...");
    execSync(`"${pip}" install -r "${requirements}"`, {
      stdio: "inherit",
      timeout: 600000,
    });
  }

  console.log(".venv ready.");
}

async function afterPack(context) {
  const { electronPlatformName, appOutDir } = context;
  const projectRoot = path.resolve(appOutDir, "..", "..");

  await ensureVenv(projectRoot);

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

    console.log("Stripping quarantine attributes from .app bundle...");
    execSync(`xattr -cr "${appPath}"`, { stdio: "inherit" });
    console.log("Quarantine attributes removed.");

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
