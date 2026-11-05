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
let retryCount = 0;

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
      webviewTag: false,
      navigateOnDragDrop: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
    }
  });

  // Safe external link handling: allow only http/https schemes
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "https:" || parsed.protocol === "http:") {
        shell.openExternal(url);
      } else {
        console.warn(`Blocked attempt to open untrusted scheme: ${url}`);
      }
    } catch {
      console.warn(`Blocked malformed URL: ${url}`);
    }
    return { action: "deny" };
  });

  // Guard in-window navigation: do not allow navigating away from the local app
  mainWindow.webContents.on("will-navigate", (event, navigationUrl) => {
    try {
      const allowedOrigin = new URL(START_URL).origin;
      const targetOrigin = new URL(navigationUrl).origin;
      if (targetOrigin !== allowedOrigin) {
        event.preventDefault();
        shell.openExternal(navigationUrl);
      }
    } catch {
      event.preventDefault();
    }
  });

  // Handle load failure: only act on main frame errors, ignoring aborted loads and subframes
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame || code === -3) {
      // Ignore subframe failures (e.g. noVNC or iframes) and user-aborted navigations
      return;
    }
    console.error(`Failed to load ${url}: ${description} (${code})`);

    if (retryCount < 10) {
      retryCount++;
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.loadURL(START_URL).catch(() => {});
        }
      }, 1000);
    } else {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.show();
      }
    }
  });

  mainWindow.webContents.on("did-finish-load", () => {
    retryCount = 0;
  });

  mainWindow.loadURL(START_URL).catch((err) => {
    console.error(`Could not reach the bridge at ${START_URL}: ${err.message}`);
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.on("second-instance", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    if (!mainWindow.isVisible()) mainWindow.show();
    mainWindow.focus();
  }
});

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
