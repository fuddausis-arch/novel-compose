import { useEffect, useState } from 'react'
import { Minus, Square, Maximize2, X, PenLine } from 'lucide-react'

interface ElectronAPI {
  isElectron: boolean
  platform: string
  windowMinimize: () => void
  windowMaximize: () => void
  windowClose: () => void
  isWindowMaximized: () => Promise<boolean>
  onWindowMaximizeChange: (callback: (value: boolean) => void) => () => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export function TitleBar() {
  const api = window.electronAPI
  const [isMaximized, setIsMaximized] = useState(false)

  useEffect(() => {
    if (!api || api.platform === 'darwin') return
    api.isWindowMaximized().then(setIsMaximized)
    const unsubscribe = api.onWindowMaximizeChange(setIsMaximized)
    return unsubscribe
  }, [api])

  // macOS 保留系统标题栏，不渲染自定义标题栏
  if (!api || api.platform === 'darwin') return null

  return (
    <div
      className="flex h-9 w-full shrink-0 select-none items-center justify-between border-b border-border bg-surface"
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
    >
      {/* 左侧：图标 + 标题 */}
      <div className="flex items-center gap-2 px-3">
        <PenLine className="h-4 w-4 text-primary" />
        <span className="text-xs font-medium text-foreground">NovelCompose</span>
      </div>

      {/* 中间：拖拽区，双击最大化 */}
      <div
        className="flex flex-1 items-center self-stretch"
        onDoubleClick={() => api.windowMaximize()}
      />

      {/* 右侧：窗口按钮（no-drag） */}
      <div className="flex items-center" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
        <button
          type="button"
          onClick={() => api.windowMinimize()}
          className="inline-flex h-9 w-11 items-center justify-center text-muted transition-colors hover:bg-foreground/5 hover:text-foreground"
          aria-label="最小化"
        >
          <Minus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => api.windowMaximize()}
          className="inline-flex h-9 w-11 items-center justify-center text-muted transition-colors hover:bg-foreground/5 hover:text-foreground"
          aria-label={isMaximized ? '还原' : '最大化'}
        >
          {isMaximized ? <Square className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </button>
        <button
          type="button"
          onClick={() => api.windowClose()}
          className="inline-flex h-9 w-11 items-center justify-center text-muted transition-colors hover:bg-danger hover:text-white"
          aria-label="关闭"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
