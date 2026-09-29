'use strict';
const { app, BrowserWindow, Notification, ipcMain, dialog, shell, Menu } = require('electron');
const path = require('node:path');
const { PLATFORM, resourcePaths, defaultDataRoot, layout } = require('./paths');
const manifest = require('../manifest.json');
const { runChecks } = require('./bootstrap/checks');
const { describePlan, runSetup, isSetupComplete } = require('./bootstrap/run');
const { BackendServer } = require('./server');
const { loadConfig, updateConfig, ensureWritableDir } = require('./config');

// Only these links can be opened from the first-run screen.
const EXTERNAL = {
  'nvidia-drivers': 'https://www.nvidia.com/drivers',
  issues: 'https://github.com/inikolax/remiqora/issues/new',
};
const SETUP_PAGE = path.join(__dirname, '..', 'renderer', 'index.html');

// Tests point the app at throwaway folders.
if (process.env.REMIQORA_USER_DATA) app.setPath('userData', process.env.REMIQORA_USER_DATA);

let win = null;
let ctx = null;
let server = null;
let setupAbort = null;
let quitting = false;
let savedPort = null;

function buildContext(dataRoot) {
  return {
    L: layout(dataRoot, PLATFORM, manifest),
    manifest,
    platform: PLATFORM,
    resources: resourcePaths(app.isPackaged),
    // Test switch: skip the multi-gigabyte components, e.g. REMIQORA_SKIP_COMPONENTS=ace-step,demucs,weights
    skip: (process.env.REMIQORA_SKIP_COMPONENTS || '').split(',').map((s) => s.trim()).filter(Boolean),
  };
}

function requiredSetupBytes(plan) {
  const pending = plan.filter((component) => !component.done);
  if (!pending.length) return 0;
  if (pending.length === plan.length) return manifest.requirements.minFreeBytes;
  if (pending.every((component) => !component.network)) {
    return Math.max(50e6, Math.ceil(pending.reduce((sum, component) => sum + component.weight, 0) * 1.2));
  }
  return Math.max(1e9, Math.ceil(pending.reduce((sum, component) => sum + component.weight, 0) * 1.2));
}

const send = (payload) => { if (win && !win.isDestroyed()) win.webContents.send('setup:event', payload); };

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 620,
    show: false,
    title: 'Remiqora',
    backgroundColor: '#0f0f14',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => { win = null; });

  // External links open in the system browser; the window only ever shows the setup page or our own backend.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const own = url.startsWith('file:') || (server && server.url && url.startsWith(server.url));
    if (!own) {
      event.preventDefault();
      if (/^https?:\/\//.test(url)) shell.openExternal(url);
    }
  });
  if (!app.isPackaged && process.env.REMIQORA_DEVTOOLS) win.webContents.openDevTools({ mode: 'detach' });
}

function showSetup(query = {}) {
  return win.loadFile(SETUP_PAGE, { query });
}

/** Starts the backend, then swaps the window over to the real app. */
async function launch() {
  send({ type: 'starting' });
  server = new BackendServer(ctx);
  server.on('exit', (code) => {
    if (quitting) return;
    showSetup({ state: 'crashed', message: `The backend stopped (exit code ${code}).` });
  });
  try {
    const url = await server.start({ preferredPort: savedPort });
    if (server.port !== savedPort) {
      savedPort = server.port;
      await updateConfig(app.getPath('userData'), { port: savedPort });
    }
    // The backend usually reuses its port after an app update. A versioned
    // document URL prevents Chromium from resurrecting an older index.html
    // (and its old hashed JS) from the previous installation's disk cache.
    await win.loadURL(`${url}?desktop_version=${encodeURIComponent(app.getVersion())}`);
  } catch (err) {
    showSetup({ state: 'crashed', message: err.message });
  }
}

async function startSetup() {
  if (setupAbort) return;
  setupAbort = new AbortController();
  const run = { ...ctx, signal: setupAbort.signal };
  try {
    await runSetup(run, send);
    send({ type: 'finished', complete: await isSetupComplete(ctx) });
  } catch (err) {
    if (setupAbort.signal.aborted) send({ type: 'paused' });
    else send({ type: 'failed', componentId: err.componentId || null, message: err.message });
  } finally {
    setupAbort = null;
  }
}

function registerIpc() {
  ipcMain.handle('app:notify-track', (_event, title, body) => {
    if (!Notification.isSupported()) return false;
    const notice = new Notification({ title: String(title).slice(0, 120), body: String(body).slice(0, 180) });
    notice.on('click', () => { if (win && !win.isDestroyed()) { win.show(); win.focus(); } });
    notice.show();
    return true;
  });
  ipcMain.handle('setup:context', async () => {
    const plan = await describePlan(ctx);
    return {
      version: app.getVersion(),
      platform: PLATFORM,
      // Every preferred language, like the app itself: Russian anywhere in the list selects Russian.
      // REMIQORA_LANG=en|ru forces the language (screenshots, trying another language on this machine).
      languages: process.env.REMIQORA_LANG ? [process.env.REMIQORA_LANG] : [app.getLocale(), ...app.getPreferredSystemLanguages()],
      dataRoot: ctx.L.root,
      plan,
      totalBytes: plan.filter((c) => !c.done).reduce((sum, c) => sum + c.weight, 0),
    };
  });
  ipcMain.handle('setup:checks', async (_e, dataRoot) => {
    const root = dataRoot || ctx.L.root;
    const plan = await describePlan(buildContext(root));
    return runChecks({
      platform: PLATFORM, dataRoot: root, manifest,
      requiredBytes: requiredSetupBytes(plan),
      checkNetwork: plan.some((component) => !component.done && component.network !== false),
    });
  });
  ipcMain.handle('setup:choose-folder', async () => {
    const r = await dialog.showOpenDialog(win, { properties: ['openDirectory', 'createDirectory'] });
    if (r.canceled || !r.filePaths[0]) return null;
    const picked = r.filePaths[0];
    return path.basename(picked).toLowerCase() === 'remiqora' ? picked : path.join(picked, 'Remiqora');
  });
  ipcMain.handle('setup:set-root', async (_e, dir) => {
    try {
      await ensureWritableDir(dir);
    } catch (err) {
      return { ok: false, message: err.message };
    }
    ctx = buildContext(dir);
    await updateConfig(app.getPath('userData'), { dataRoot: dir });
    return { ok: true };
  });
  ipcMain.handle('setup:start', async () => {
    // Remember the chosen folder right away: an interrupted setup resumes there on the next start.
    await ensureWritableDir(ctx.L.root);
    await updateConfig(app.getPath('userData'), { dataRoot: ctx.L.root });
    startSetup();
  });
  ipcMain.handle('setup:pause', () => { if (setupAbort) setupAbort.abort(new Error('paused')); });
  ipcMain.handle('setup:launch', () => launch());
  ipcMain.handle('setup:open-external', (_e, key) => { if (EXTERNAL[key]) shell.openExternal(EXTERNAL[key]); });
  ipcMain.handle('setup:open-logs', () => shell.openPath(ctx.L.logs));
  ipcMain.handle('setup:show-data', () => shell.openPath(ctx.L.root));
}

async function boot() {
  const config = await loadConfig(app.getPath('userData'));
  savedPort = config.port || null;
  ctx = buildContext(config.dataRoot || defaultDataRoot());
  registerIpc();
  Menu.setApplicationMenu(process.platform === 'darwin'
    ? Menu.buildFromTemplate([{ role: 'appMenu' }, { role: 'editMenu' }, { role: 'viewMenu' }, { role: 'windowMenu' }])
    : null);
  createWindow();
  // A complete install is enough to open the app, including when an older
  // installer never saved dataRoot in Electron's small config file.
  if (await isSetupComplete(ctx, { ignoreSkipped: true })) await launch();
  else await showSetup();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  });
  app.whenReady().then(boot).catch((err) => { dialog.showErrorBox('Remiqora', err.stack || String(err)); app.exit(1); });

  app.on('window-all-closed', () => app.quit());

  // Stop the model servers through the backend before the process goes away, otherwise a GPU process can be left behind.
  app.on('before-quit', (event) => {
    if (quitting) return;
    quitting = true;
    if (setupAbort) setupAbort.abort(new Error('quit'));
    if (server) {
      event.preventDefault();
      server.stop().finally(() => app.quit());
    }
  });
}
