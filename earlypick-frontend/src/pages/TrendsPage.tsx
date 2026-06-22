import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import MainLayout from '../components/layout/MainLayout'
import PageState from '../components/common/PageState'
import { useDailySignals } from '../hooks/useDailysignals'
import type { SignalGroup } from '../types/dailySignals'

type FilterOption = '전체' | SignalGroup

export default function TrendsPage() {
  const { data, loading, error } = useDailySignals()
  const [selectedFilter, setSelectedFilter] = useState<FilterOption>('전체')

  if (loading) {
    return (
      <MainLayout>
        <PageState title="오늘의 Top20을 불러오는 중입니다." message="최신 순위와 시그널 데이터를 가져오고 있습니다." />
      </MainLayout>
    )
  }

  if (error || !data) {
    return (
      <MainLayout>
        <PageState title="데이터를 불러오지 못했습니다." message={error ?? 'daily_signals.json 파일을 확인해주세요.'} />
      </MainLayout>
    )
  }

  const filteredProducts = useMemo(() => {
    if (selectedFilter === '전체') return data.products
    return data.products.filter((product) => product.signalGroup === selectedFilter)
  }, [data.products, selectedFilter])

  const filterLabels: Record<FilterOption, string> = {
    전체: '전체',
    early: '초기 선점',
    conversion: '구매전환 강함',
    overheated: '과열 주의',
  }

  return (
    <MainLayout>
      <section className="trends-hero">
        <div className="trends-hero__content">
          <p className="eyebrow">TODAY'S TOP20</p>
          <h1>오늘 들어온 식품 Top20을 시그널 중심으로 탐색하세요</h1>
          <p className="trends-hero__description">
            과거 패턴 학습을 바탕으로 오늘 올라온 상품의 검색 반응, 쇼핑 클릭, 전환 강도,
            버블 위험을 함께 보며 탐색할 수 있는 화면입니다.
          </p>
        </div>

        <div className="trends-hero__stats">
          <div className="trends-stat-card">
            <span>분석 상품 수</span>
            <strong>{data.summary.analyzedCount}</strong>
          </div>
          <div className="trends-stat-card">
            <span>초기 선점</span>
            <strong>{data.summary.earlyCount}</strong>
          </div>
          <div className="trends-stat-card">
            <span>구매전환 강함</span>
            <strong>{data.summary.conversionCount}</strong>
          </div>
          <div className="trends-stat-card">
            <span>과열 주의</span>
            <strong>{data.summary.overheatedCount}</strong>
          </div>
        </div>
      </section>

      <section className="section-block trends-layout">
        <aside className="trends-sidebar">
          <div className="trends-sidebar-card">
            <div className="section-heading">
              <h2>시그널 필터</h2>
              <p>오늘 상품을 해석 방식 기준으로 나눠 볼 수 있습니다.</p>
            </div>

            <div className="trends-filter-list">
              {(['전체', 'early', 'conversion', 'overheated'] as FilterOption[]).map((filter) => (
                <button
                  key={filter}
                  type="button"
                  className={`trends-filter-button ${
                    selectedFilter === filter ? 'active' : ''
                  }`}
                  onClick={() => setSelectedFilter(filter)}
                >
                  {filterLabels[filter]}
                </button>
              ))}
            </div>
          </div>

          <div className="trends-sidebar-card trends-sidebar-card--soft">
            <div className="section-heading">
              <h2>해석 기준</h2>
            </div>

            <div className="guide-list">
              <div className="guide-item">
                <strong>초기 선점</strong>
                <p>검색이 먼저 붙고 쇼핑 클릭이 뒤따르는 패턴입니다.</p>
              </div>
              <div className="guide-item">
                <strong>구매전환 강함</strong>
                <p>검색과 쇼핑이 함께 움직이며 실제 구매 검토 단계에 가까운 흐름입니다.</p>
              </div>
              <div className="guide-item">
                <strong>과열 주의</strong>
                <p>검색 급등 대비 쇼핑 추종이 약하거나 이벤트성이 큰 상품입니다.</p>
              </div>
            </div>
          </div>
        </aside>

        <div className="trends-main">
          <div className="trends-toolbar">
            <div>
              <p className="trends-toolbar__label">현재 필터</p>
              <h2>{filterLabels[selectedFilter]}</h2>
            </div>

            <div className="trends-toolbar__chips">
              {(['전체', 'early', 'conversion', 'overheated'] as FilterOption[]).map((filter) => (
                <button
                  key={filter}
                  type="button"
                  className={`filter-chip ${selectedFilter === filter ? 'active' : ''}`}
                  onClick={() => setSelectedFilter(filter)}
                >
                  {filterLabels[filter]}
                </button>
              ))}
            </div>
          </div>

          <div className="trends-card-grid">
            {filteredProducts.map((product) => (
              <article key={product.id} className="product-card trends-product-card">
                <div className="card-top">
                  <span className="category-badge">{product.signalLabel}</span>
                  <span className="score-badge">#{product.todayRank}</span>
                </div>

                <div className="trends-product-card__title">
                  <h3>{product.name}</h3>
                  <span
                    className={`risk-badge ${
                      product.priceRisk === '높음'
                        ? 'risk-high'
                        : product.priceRisk === '보통'
                        ? 'risk-medium'
                        : 'risk-low'
                    }`}
                  >
                    리스크 {product.priceRisk}
                  </span>
                </div>

                <p className="product-meta">
                  {product.marketGroup} · {product.category} · {product.subCategory}
                  {product.origin ? ` · ${product.origin}` : ''}
                </p>

                <p className="product-summary">{product.summary}</p>

                <div className="trends-product-metrics">
                  <div className="trends-product-metric">
                    <span>검색</span>
                    <strong>{product.searchRatioToday}</strong>
                  </div>
                  <div className="trends-product-metric">
                    <span>쇼핑</span>
                    <strong>{product.shoppingRatioToday}</strong>
                  </div>
                  <div className="trends-product-metric">
                    <span>추천 액션</span>
                    <strong>{product.action}</strong>
                  </div>
                </div>

                <div className="driver-tag-list">
                  {product.drivers.map((tag) => (
                    <span key={tag} className="driver-tag">
                      {tag}
                    </span>
                  ))}
                </div>

                <Link to={`/products/${product.id}`} className="text-link">
                  상품 상세 보기 →
                </Link>
              </article>
            ))}
          </div>
        </div>
      </section>
    </MainLayout>
  )
}