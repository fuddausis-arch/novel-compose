const { app, BrowserWindow, dialog, ipcMain } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')
const http = require('http')

const isDev = !app.isPackaged || !!process.env.VITE_DEV_SERVER_URL || process.env.NODE_ENV === 'development'

let backendProcess = null
let backendReady = false

// 加载动画页面（后端就绪前显示）
const LOADING_HTML = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body { margin:0; background:#0a0a0f; color:#e0e0e0; font-family:system-ui,sans-serif;
  display:flex; align-items:center; justify-content:center; height:100vh; }
.spinner { width:40px; height:40px; border:3px solid rgba(255,255,255,0.1);
  border-top-color:#6366f1; border-radius:50%; animation:spin 0.8s linear infinite; }
.text { margin-left:16px; font-size:14px; color:#9ca3af; }
@keyframes spin { to { transform:rotate(360deg); } }
</style></head>
<body><div class="spinner"></div><div class="text">正在启动后端服务…</div></body></html>`

// 日志目录：打包模式 %APPDATA%/NovelAgent/logs，开发模式项目根
function getLogDir() {
  if (app.isPackaged) {
    const logDir = path.join(app.getPath('appData'), 'NovelAgent', 'logs')
    if (!fs.existsSync(logDir)) {
      try { fs.mkdirSync(logDir, { recursive: true }) } catch (_) { /* ignore */ }
    }
    return logDir
  }
  return path.join(__dirname, '..', '..')
}

function getBackendExePath() {
  // 打包后：resources/novel-agent-server/novel-agent-server.exe
  const exeName = process.platform === 'win32' ? 'novel-agent-server.exe' : 'novel-agent-server'
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'novel-agent-server', exeName)
  }
  return null
}

function startBackend() {
  const exePath = getBackendExePath()
  if (!exePath) return

  console.log('Starting backend:', exePath)
  // 打包模式下：优先读取安装目录 resources/config.yaml，方便用户修改配置
  if (app.isPackaged) {
    const resourcesDir = path.dirname(path.dirname(exePath))
    const configPath = path.join(resourcesDir, 'config.yaml')
    if (fs.existsSync(configPath)) {
      process.env.NOVEL_CONFIG_PATH = configPath
      console.log('Using config:', configPath)
    }
  }

  // 日志文件路径（每次启动覆盖，便于排查启动期问题）
  const logFile = path.join(getLogDir(), 'backend.log')
  let logStream = null
  try {
    logStream = fs.createWriteStream(logFile, { flags: 'w' })
  } catch (e) {
    console.error('Failed to open log file:', e.message)
  }

  backendProcess = spawn(exePath, [], {
    cwd: path.dirname(exePath),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: false,
    env: { ...process.env },
  })

  const writeLog = (prefix, data) => {
    const text = data.toString()
    console.log(`[backend] ${prefix}${text.trim()}`)
    if (logStream) {
      try { logStream.write(`[${new Date().toISOString()}] ${prefix}${text}`) } catch (_) { /* ignore */ }
    }
  }

  backendProcess.stdout.on('data', (data) => writeLog('', data))
  backendProcess.stderr.on('data', (data) => writeLog('STDERR: ', data))

  backendProcess.on('exit', (code) => {
    console.log(`Backend exited with code ${code}`)
    if (logStream) {
      try { logStream.write(`\n[EXIT] code=${code} at ${new Date().toISOString()}\n`) } catch (_) { /* ignore */ }
      try { logStream.end() } catch (_) { /* ignore */ }
    }
    backendProcess = null
  })

  backendProcess.on('error', (err) => {
    console.error('Failed to spawn backend:', err.message)
    if (logStream) {
      try { logStream.write(`\n[SPAWN ERROR] ${err.message}\n`) } catch (_) { /* ignore */ }
    }
  })
}

// 等待后端就绪：最多 maxRetries * intervalMs 毫秒
// 默认 90 次 × 2 秒 = 180 秒，覆盖 PyInstaller 首次解压 + 杀软扫描 + 模型加载场景
function waitForBackend(maxRetries = 90, intervalMs = 2000) {
  return new Promise((resolve, reject) => {
    let retries = 0
    const check = () => {
      const req = http.get('http://127.0.0.1:8000/api/projects', (res) => {
        if (res.statusCode === 200) {
          resolve()
        } else {
          retry()
        }
        res.destroy()
      })
      req.on('error', () => retry())
      req.setTimeout(2000, () => {
        req.destroy()
        retry()
      })
    }
    const retry = () => {
      retries++
      if (retries >= maxRetries) {
        reject(new Error(`Backend failed to start within ${Math.round(maxRetries * intervalMs / 1000)} seconds`))
        return
      }
      setTimeout(check, intervalMs)
    }
    check()
  })
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    frame: false,
    backgroundColor: '#0a0a0f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev) {
    win.loadURL('http://localhost:5173')
    win.webContents.openDevTools()
  } else if (backendReady) {
    // 后端已就绪：加载实际页面
    win.loadURL('http://127.0.0.1:8000')
  } else {
    // 后端尚未就绪：先显示加载动画，后端就绪后会主动 loadURL 刷新
    win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(LOADING_HTML))
  }
  return win
}

app.whenReady().then(async () => {
  // 先创建窗口：打包模式下立即显示加载动画，不再串行等待后端
  const win = createWindow()

  // 自定义标题栏 IPC：窗口控制
  ipcMain.handle('window:is-maximized', () => win.isMaximized())
  ipcMain.on('window:minimize', () => { if (!win.isDestroyed()) win.minimize() })
  ipcMain.on('window:maximize', () => {
    if (win.isDestroyed()) return
    win.isMaximized() ? win.unmaximize() : win.maximize()
  })
  ipcMain.on('window:close', () => { if (!win.isDestroyed()) win.close() })
  win.on('maximize', () => win.webContents.send('window:maximize-change', true))
  win.on('unmaximize', () => win.webContents.send('window:maximize-change', false))

  if (!isDev) {
    startBackend()
    try {
      await waitForBackend()
      backendReady = true
      // 后端就绪，通知窗口刷新到实际页面
      if (!win.isDestroyed()) {
        win.loadURL('http://127.0.0.1:8000')
      }
    } catch (e) {
      console.error(e.message)
      // 启动失败时弹出对话框，告知用户日志位置便于排查
      const logFile = path.join(getLogDir(), 'backend.log')
      const msg = `后端服务启动失败或超时。\n\n请将以下日志文件发回开发方以便排查：\n${logFile}\n\n错误：${e.message}`
      try {
        dialog.showErrorBox('后端启动失败', msg)
      } catch (_) { /* ignore */ }
    }
  }
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    backendProcess.kill('SIGTERM')
    const pid = backendProcess.pid
    setTimeout(() => {
      try { process.kill(pid, 'SIGKILL') } catch {}
    }, 3000)
    backendProcess = null
  }
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
})
