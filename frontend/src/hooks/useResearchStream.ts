import { useState, useCallback } from 'react'
import { streamResearch, type RunResearchParams } from '../api/research'
import type { Section, SSEEvent } from '../types'

export function useResearchStream() {
  const [isStreaming, setIsStreaming]   = useState(false)
  const [progress,   setProgress]      = useState<string[]>([])
  const [sections,   setSections]      = useState<Section[]>([])
  const [error,      setError]         = useState<string | null>(null)
  const [isDone,     setIsDone]        = useState(false)

  const run = useCallback(async (params: RunResearchParams) => {
    setIsStreaming(true)
    setProgress([])
    setSections([])
    setError(null)
    setIsDone(false)

    try {
      for await (const event of streamResearch(params)) {
        switch (event.type) {
          case 'progress':
            setProgress(p => [...p, event.message])
            break
          case 'section':
            setSections(s => [...s, event.section])
            break
          case 'error':
            setError(event.message)
            break
          case 'done':
            setIsDone(true)
            break
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Stream failed')
    } finally {
      setIsStreaming(false)
    }
  }, [])

  return { run, isStreaming, progress, sections, error, isDone }
}
