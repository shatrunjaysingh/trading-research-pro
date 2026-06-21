import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/sidebar/Sidebar'
import { BottomNav } from '../components/mobile/BottomNav'
import { PWAInstallPrompt } from '../components/mobile/PWAInstallPrompt'

export function AppLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div className="flex h-[100dvh] overflow-hidden">
      {/* Desktop sidebar — hidden on mobile */}
      <div className="hidden md:flex flex-shrink-0">
        <Sidebar />
      </div>

      {/* Mobile drawer overlay */}
      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
          />
          {/* Drawer panel */}
          <div className="relative w-72 h-full overflow-y-auto shadow-2xl">
            <Sidebar onClose={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden" style={{ background: 'var(--color-canvas)' }}>
        {/* Mobile top bar */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 bg-sidebar border-b border-white/10 safe-top flex-shrink-0">
          <button
            onClick={() => setDrawerOpen(true)}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-white hover:bg-white/10 transition-colors text-xl"
            aria-label="Open menu"
          >
            ☰
          </button>
          <span className="text-white font-extrabold text-sm tracking-tight flex-1">📈 TradingResearch Pro</span>
        </header>

        {/* Scrollable content — add bottom padding on mobile for nav bar */}
        <div className="flex-1 overflow-y-auto pb-[env(safe-area-inset-bottom,0px)] md:pb-0">
          <div className="pb-16 md:pb-0">
            <Outlet />
          </div>
        </div>
      </div>

      {/* Mobile bottom nav — fixed at bottom */}
      <div className="md:hidden">
        <BottomNav />
      </div>

      {/* PWA install prompt */}
      <PWAInstallPrompt />
    </div>
  )
}
