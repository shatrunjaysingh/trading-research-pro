import { useState, useRef, useEffect } from 'react'

interface InfoTooltipProps {
  text: string
  className?: string
  side?: 'top' | 'bottom'
  align?: 'center' | 'left' | 'right'
}

export function InfoTooltip({ text, className, side = 'top', align = 'center' }: InfoTooltipProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  const alignClass =
    align === 'left'  ? 'left-0' :
    align === 'right' ? 'right-0' :
    'left-1/2 -translate-x-1/2'

  const posClass   = side === 'bottom' ? 'top-6'    : 'bottom-6'
  const arrowSide  = side === 'bottom' ? 'bottom-full border-b-slate-900' : 'top-full border-t-slate-900'

  return (
    <div
      ref={containerRef}
      className={`relative inline-flex items-center ${className ?? ''}`}
    >
      <button
        type="button"
        onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        aria-label="More information"
        className="w-4 h-4 rounded-full bg-surface-muted border border-surface-border text-ink-faint hover:bg-primary/10 hover:text-primary hover:border-primary/40 flex items-center justify-center text-[10px] font-bold leading-none transition-colors flex-shrink-0 select-none"
      >
        i
      </button>

      {open && (
        <div
          role="tooltip"
          className={`absolute ${posClass} ${alignClass} z-50 w-56 bg-slate-900 text-slate-100 text-xs rounded-xl p-3 shadow-2xl leading-relaxed pointer-events-none`}
        >
          {text}
          <div className={`absolute border-4 border-transparent left-1/2 -translate-x-1/2 ${arrowSide}`} />
        </div>
      )}
    </div>
  )
}
