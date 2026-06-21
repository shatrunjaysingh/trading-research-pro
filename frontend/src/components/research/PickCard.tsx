import { useState } from 'react'
import { clsx } from 'clsx'
import { fetchStockSnapshot } from '../../api/analysis'
import { generatePickReport } from '../../utils/generateReport'
import type { ApiPick, FreePick } from '../../types'

export function DownloadButton({ ticker, pick, mode, sectorLabel }: {
  ticker: string
  pick: FreePick | ApiPick
  mode: 'free' | 'api'
  sectorLabel: string
}) {
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState(false)

  async function handleDownload(e: React.MouseEvent) {
    e.stopPropagation()
    setLoading(true)
    setErr(false)
    try {
      const snapshot = await fetchStockSnapshot(ticker)
      generatePickReport(pick, snapshot, sectorLabel, mode)
    } catch {
      setErr(true)
      setTimeout(() => setErr(false), 3000)
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handleDownload}
      disabled={loading}
      title="Download PDF report"
      className={clsx(
        'flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold transition-all flex-shrink-0',
        err
          ? 'border-red-300 text-red-600 bg-red-50'
          : loading
          ? 'border-surface-border text-ink-faint bg-surface-muted cursor-not-allowed'
          : 'border-surface-border text-ink-muted bg-surface hover:border-primary/50 hover:text-primary hover:bg-primary/5',
      )}
    >
      {loading
        ? <><span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />Fetching…</>
        : err
        ? <>✕ Failed</>
        : <>⬇ Report</>}
    </button>
  )
}
