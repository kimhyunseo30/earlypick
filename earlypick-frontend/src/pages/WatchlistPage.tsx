import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import MainLayout from '../components/layout/MainLayout'
import type { Product } from '../types/product'
import { getStoredWatchlist, removeFromWatchlist } from '../utils/Watchlist'

export default function WatchlistPage() {
  const [items, setItems] = useState<Product[]>([])

  useEffect(() => {
    setItems(getStoredWatchlist())
  }, [])

  const handleRemove = (id: number) => {
    const nextItems = removeFromWatchlist(id)
    setItems(nextItems)
  }

  return (
    <MainLayout>
      <section className="section-block">
        <div className="section-heading">
          <p className="eyebrow">SAVED ITEMS</p>
          <h1>저장한 품목</h1>
          <p>계속 추적하고 싶은 국내산 채소·과일과 수입 원재료를 모아두는 공간입니다.</p>
        </div>

        {items.length === 0 ? (
          <div className="empty-card">
            <h2>저장한 품목이 없습니다.</h2>
            <p>탐색 화면에서 관심 있는 품목을 담아두면 나중에 한 번에 비교하기 쉽습니다.</p>
            <Link to="/trends" className="primary-button">
              시장 탐색하러 가기
            </Link>
          </div>
        ) : (
          <div className="watchlist-grid">
            {items.map((item) => (
              <article key={item.id} className="product-card">
                <div className="card-top">
                  <span className="category-badge">{item.marketGroup}</span>
                  <span className="score-badge">트렌드 {item.trendScore}</span>
                </div>

                <h3>{item.name}</h3>

                <p className="product-meta">
                  {item.category} · {item.subCategory} · {item.unit}
                  {item.origin ? ` · ${item.origin}` : ''}
                </p>

                <p className="product-summary">{item.prediction}</p>

                <div className="product-quick-info">
                  <div>
                    <span>추천 액션</span>
                    <strong>{item.recommendation}</strong>
                  </div>
                  <div>
                    <span>가격 리스크</span>
                    <strong>{item.priceRisk}</strong>
                  </div>
                </div>

                <div className="driver-tag-list">
                  {(item.driverTags ?? []).map((tag) => (
                    <span key={tag} className="driver-tag">
                      {tag}
                    </span>
                  ))}
                </div>

                <div className="card-actions">
                  <Link to={`/products/${item.id}`} className="text-link">
                    상세 보기
                  </Link>

                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => handleRemove(item.id)}
                  >
                    저장 목록에서 제거
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </MainLayout>
  )
}