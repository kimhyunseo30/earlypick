import { useEffect, useState } from 'react'
import type { DailySignalsData } from '../types/dailySignals'

type UseDailySignalsResult = {
  data: DailySignalsData | null
  loading: boolean
  error: string | null
}

export function useDailySignals(): UseDailySignalsResult {
  const [data, setData] = useState<DailySignalsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    async function load() {
      try {
        setLoading(true)
        setError(null)

        const response = await fetch('/daily_signals.json', {
          cache: 'no-store',
        })

        if (!response.ok) {
          throw new Error(`데이터를 불러오지 못했습니다. (${response.status})`)
        }

        const json = (await response.json()) as DailySignalsData

        if (isMounted) {
          setData(json)
        }
      } catch (err) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : '알 수 없는 오류가 발생했습니다.')
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    load()

    return () => {
      isMounted = false
    }
  }, [])

  return { data, loading, error }
}