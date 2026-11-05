import { app, BrowserWindow, shell } from "electron";
import { fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";

// Isolate user data from app code
const DEFAULT_USER_DATA = path.join(os.homedir(), ".local", "share", "grok-ripeoff", "user-data");
const USER_DATA_DIR = process.env.GROK_USER_DATA || DEFAULT_USER_DATA;
app.setPath("userData", path.join(USER_DATA_DIR, "electron"));

app.setName("Grok Ripeoff");
if (process.platform === "linux") {
  app.setDesktopName("grok-ripeoff.desktop");
}

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
  process.exit(0);
}

const START_URL = process.env.ELECTRON_START_URL || "http://127.0.0.1:8787";
const DIRNAME = path.dirname(fileURLToPath(import.meta.url));
const ICON_PNG = path.join(DIRNAME, "..", "icon.png");
const ICON_SVG = path.join(DIRNAME, "..", "icon.svg");

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 960,
    minHeight: 640,
    title: "Grok Ripeoff",
    icon: ICON_PNG || ICON_SVG,
    backgroundColor: "#d9eeff",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => {
    if (mainWindow) mainWindow.show();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  let retryCount = 0;
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url) => {
    console.error(`Failed to load ${url}: ${description} (${code})`);
    if (retryCount < 10) {
      retryCount++;
      setTimeout(() => {
        if (mainWindow) mainWindow.loadURL(START_URL).catch(() => {});
      }, 1000);
    } else {
      if (mainWindow) mainWindow.show();
    }
  });

  mainWindow.loadURL(START_URL).catch((err) => {
    console.error(`Could not reach the bridge at ${START_URL}: ${err.message}`);
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
