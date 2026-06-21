import { useState, useEffect } from 'react'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function PWAInstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault()
      setDeferredPrompt(e as BeforeInstallPromptEvent)
    }
    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  if (!deferredPrompt || dismissed) return null

  const handleInstall = async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const { outcome } = await deferredPrompt.userChoice
    if (outcome === 'accepted' || outcome === 'dismissed') {
      setDeferredPrompt(null)
      setDismissed(true)
    }
  }

  return (
    <div className="fixed bottom-20 md:bottom-4 left-4 right-4 md:left-auto md:right-4 md:w-80 z-50 pwa-prompt">
      <div className="bg-surface border border-surface-border rounded-2xl shadow-2xl p-4 flex items-center gap-3">
        <div className="w-12 h-12 bg-sidebar rounded-xl flex items-center justify-center flex-shrink-0">
          <span className="text-2xl">📈</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-ink text-sm">Add to Home Screen</div>
          <div className="text-xs text-ink-muted mt-0.5 truncate">Install TradingResearch Pro for quick access</div>
        </div>
        <div className="flex flex-col gap-1.5 flex-shrink-0">
          <button
            onClick={handleInstall}
            className="btn-primary text-xs px-3 py-1.5"
          >
            Install
          </button>
          <button
            onClick={() => setDismissed(true)}
            className="text-xs text-ink-faint hover:text-ink-muted transition-colors text-center"
          >
            Not now
          </button>
        </div>
      </div>
    </div>
  )
}
