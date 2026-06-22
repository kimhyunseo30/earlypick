import type { Product } from '../types/product'
import { trendingProducts, watchlistProducts } from '../data/mockData'

const WATCHLIST_KEY = 'earlypick_watchlist'

function normalizeWatchlistItems(items: unknown): Product[] {
  if (!Array.isArray(items)) return watchlistProducts

  return items
    .map((rawItem) => {
      if (!rawItem || typeof rawItem !== 'object') return null

      const item = rawItem as Partial<Product>
      if (typeof item.id !== 'number') return null

      const latest = trendingProducts.find((product) => product.id === item.id)
      return latest ?? null
    })
    .filter((item): item is Product => item !== null)
}

export function getStoredWatchlist(): Product[] {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY)

    if (!raw) {
      localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlistProducts))
      return watchlistProducts
    }

    const parsed = JSON.parse(raw)
    const normalized = normalizeWatchlistItems(parsed)

    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(normalized))
    return normalized
  } catch (error) {
    console.error('워치리스트 불러오기 실패:', error)
    return watchlistProducts
  }
}

export function saveWatchlist(items: Product[]) {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(items))
  } catch (error) {
    console.error('워치리스트 저장 실패:', error)
  }
}

export function isInWatchlist(productId: number) {
  const items = getStoredWatchlist()
  return items.some((item) => item.id === productId)
}

export function addToWatchlist(productId: number) {
  const items = getStoredWatchlist()

  if (items.some((item) => item.id === productId)) {
    return items
  }

  const target = trendingProducts.find((product) => product.id === productId)

  if (!target) {
    return items
  }

  const nextItems = [...items, target]
  saveWatchlist(nextItems)
  return nextItems
}

export function removeFromWatchlist(productId: number) {
  const items = getStoredWatchlist()
  const nextItems = items.filter((item) => item.id !== productId)
  saveWatchlist(nextItems)
  return nextItems
}

export function toggleWatchlist(productId: number) {
  if (isInWatchlist(productId)) {
    return removeFromWatchlist(productId)
  }

  return addToWatchlist(productId)
}