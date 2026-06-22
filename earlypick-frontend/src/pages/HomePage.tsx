import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import MainLayout from '../components/layout/MainLayout'
import PageState from '../components/common/PageState'
import { useDailySignals } from '../hooks/useDailysignals'
import type { DailySignalProduct } from '../types/dailySignals'

type DashboardTabKey = 'priority' | 'social' | 'rising' | 'confirmed'

type ProductExtraFields = {
  itemGroup?: string
  naverRank?: number | null
  isInNaverTop200?: boolean
  naverRankLabel?: string
  marketDataStatus?: {
    kamisMatched?: boolean
    auctionMatched?: boolean
    reason?: string
  }
  wholesalePriceNow?: number | null
  retailPriceNow?: number | null
  auctionDetail?: unknown
  decisionComment?: {
    summary?: string
    interestLabel?: string
    recommendedUse?: string
    marketNote?: string
    caution?: string
    classificationConfidence?: string
    classificationReason?: string
  }
  canonicalProductName?: string
  risingStage?: string
  risingLevel?: string
  risingScore?: number | null
  risingReason?: string
  daysSeen7d?: number | null
  daysSeen14d?: number | null
  consecutiveDays?: number | null
  bestRank14d?: number | null
  opportunityReason?: string
  worstRank14d?: number | null
  rankVelocity3d?: number | null
  stableSummary?: string
  isNewEntry?: string
  isReentry?: string
  lastSeenDate?: string
  daysSinceLastSeen?: number | null
   aiInsight?: {
    oneLineConclusion?: string
    summary?: string
    diagnosis?: string
    aiStage?: string
    confidenceLevel?: string
    businessMeaning?: string
    reasons?: string[]
    warnings?: string[]
    doNow?: string[]
    doNot?: string[]
    nextCheck?: string[]
    recommendedAction?: string
    caution?: string
    generatedBy?: string
    generatedAt?: string
    
  }
   

}

type DashboardTab = {
  key: DashboardTabKey
  label: string
  count: number
  title: string
  description: string
  products: DailySignalProduct[]
  emptyMessage: string
  limit?: number
}

function asExtra(product: DailySignalProduct): DailySignalProduct & ProductExtraFields {
  return product as DailySignalProduct & ProductExtraFields
}

function getClickTrend(product: DailySignalProduct) {
  const rate = product.shoppingGrowthRate ?? 0

  if (rate >= 10) {
    return {
      label: '쇼핑 관심 증가',
      className: 'trend-up',
    }
  }

  if (rate <= -10) {
    return {
      label: '쇼핑 관심 하락',
      className: 'trend-down',
    }
  }

  return {
    label: '쇼핑 관심 유지',
    className: 'trend-flat',
  }
}

function hasMarketData(product: DailySignalProduct) {
  const item = asExtra(product)

  return Boolean(
    item.marketDataStatus?.kamisMatched ||
      item.marketDataStatus?.auctionMatched ||
      item.wholesalePriceNow != null ||
      item.retailPriceNow != null ||
      item.auctionDetail != null
  )
}

function getItemGroup(product: DailySignalProduct) {
  return asExtra(product).itemGroup || '상품 유형 확인 필요'
}

function getNaverRankLabel(product: DailySignalProduct) {
  const item = asExtra(product)

  if (item.naverRank != null && item.naverRank <= 200) {
    return `네이버 기준 ${item.naverRank}위`
  }

  if (product.todayRank != null) {
    return `네이버 기준 ${product.todayRank}위`
  }

  return item.naverRankLabel || '네이버 Top200 미확인'
}

function getMarketChipLabel(product: DailySignalProduct) {
  if (hasMarketData(product)) {
    return '가격 연결'
  }

  return '가격 미연결'
}

function getMarketChipClass(product: DailySignalProduct) {
  if (hasMarketData(product)) {
    return 'insight-chip insight-chip--market-linked'
  }

  return 'insight-chip insight-chip--market-unlinked'
}

function getSourceLabel(product: DailySignalProduct) {
  if (product.sourceType === 'sns') return '소셜 관찰'
  if (product.sourceType === 'top20') return '인기권 확인'
  if (product.sourceType === 'rising') return '상승 관찰'
  return '신호 확인'
}

function getRecommendedUse(product: DailySignalProduct) {
  const item = asExtra(product)
  const shoppingRate = product.shoppingGrowthRate ?? 0
  const searchRate = product.searchGrowthRate ?? 0
  const rankVelocity = item.rankVelocity3d ?? 0
  const sourceType = product.sourceType

  if (sourceType === 'rising') {
    if (shoppingRate <= -10 && rankVelocity > 0) {
      return '네이버 예비 인기권 순위는 상승했지만 쇼핑 관심은 약화되었습니다. 매입·재고 판단은 보류하고 검색·쇼핑 반응이 다시 동반되는지 추가 관찰하는 것이 적합합니다.'
    }

    if (shoppingRate <= -10 && searchRate <= 0) {
      return '순위 관찰은 필요하지만 검색·쇼핑 관심이 약해진 상태입니다. 판매·매입 판단보다는 후보 유지 여부를 추가 확인하는 것이 적합합니다.'
    }

    if (rankVelocity > 0 && shoppingRate >= 10) {
      return '네이버 예비 인기권 순위 상승과 쇼핑 관심 증가가 함께 확인됩니다. 시장 가격과 재고 상황을 함께 확인해 우선 관찰하는 것이 적합합니다.'
    }

    if (rankVelocity > 0) {
      return '네이버 예비 인기권 순위 상승이 확인됩니다. 다만 쇼핑 반응이 충분히 동반되는지 추가 확인한 뒤 운영 판단하는 것이 적합합니다.'
    }

    return item.stableSummary || item.risingReason || 'Top20 진입 전 관찰 후보입니다. 검색·쇼핑 반응이 동반되는지 추가 확인하는 것이 적합합니다.'
  }

  return item.decisionComment?.recommendedUse || '추가 관찰'
}

function toSafeList(value?: string[] | null) {
  return Array.isArray(value) ? value.filter(Boolean) : []
}

function getAiStageLabel(value?: string) {
  if (value === 'MARKET_CHECK') return '시장 데이터 확인'
  if (value === 'PRICE_LINK_CHECK') return '가격 연결 확인'
  if (value === 'PRIORITY') return '우선 관찰'
  if (value === 'OBSERVE') return '관찰 유지'
  if (value === 'HOLD') return '판단 보류'
  if (value === 'EXCLUDED') return '분석 제외'
  if (value === 'WATCH') return '추가 관찰'
  return value || '-'
}

function getConfidenceLabel(value?: string) {
  if (value === 'high') return '높음'
  if (value === 'medium') return '보통'
  if (value === 'low') return '낮음'
  return value || '-'
}

function getAiConclusion(product: DailySignalProduct) {
  const item = asExtra(product)
  const ai = item.aiInsight

  return (
    ai?.oneLineConclusion ||
    ai?.summary ||
    getSummary(product)
  )
}

function getAiRecommendedAction(product: DailySignalProduct) {
  const item = asExtra(product)

  return (
    item.aiInsight?.recommendedAction ||
    item.decisionComment?.recommendedUse ||
    getRecommendedUse(product)
  )
}


function getClassificationLabel(value?: string) {
  if (value === 'high') return '분류 신뢰도 높음'
  if (value === 'medium') return '분류 신뢰도 보통'
  if (value === 'low') return '상품 유형 검토 필요'
  return '상품 유형 확인 필요'
}

function getSummary(product: DailySignalProduct) {
  const item = asExtra(product)
  const trend = getClickTrend(product)

  if (item.decisionComment?.summary) {
    return item.decisionComment.summary
  }

  if (product.sourceType === 'sns') {
    if (item.isInNaverTop200) {
      return `소셜 관찰 후보이며 ${getNaverRankLabel(product)}에서도 확인됩니다.`
    }
    return '소셜 관찰 후보로, 검색·쇼핑 반응을 추가 확인하는 것이 적합합니다.'
  }

  if (product.sourceType === 'top20') {
    return `네이버 인기권에서 확인된 상품이며, 쇼핑 관심은 ${trend.label} 상태입니다.`
  }

  if (hasMarketData(product)) {
    return `쇼핑 관심은 ${trend.label} 상태이며, 시장 가격 데이터를 함께 참고할 수 있습니다.`
  }

  return `쇼핑 관심은 ${trend.label} 상태이며, 시장 가격 연결 여부는 추가 확인이 필요합니다.`
}

function formatPrice(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${value.toLocaleString()}원`
}


function DashboardWorkspace({
  tab,
}: {
  tab: DashboardTab
}) {
  const visibleProducts = useMemo(() => {
    return tab.limit ? tab.products.slice(0, tab.limit) : tab.products
  }, [tab])

  const [selectedId, setSelectedId] = useState<string | null>(
    visibleProducts[0]?.id ?? null
  )

  useEffect(() => {
    if (!visibleProducts.length) {
      setSelectedId(null)
      return
    }

    const exists = visibleProducts.some((item) => item.id === selectedId)
    if (!exists) {
      setSelectedId(visibleProducts[0].id)
    }
  }, [visibleProducts, selectedId])

  const selectedProduct =
    visibleProducts.find((item) => item.id === selectedId) ?? visibleProducts[0] ?? null

  const selectedExtra = selectedProduct ? asExtra(selectedProduct) : null

  return (
    <section className="command-workspace">
      <div className="queue-panel">
        <div className="panel-head">
          <div>
            <p className="panel-eyebrow">SIGNAL QUEUE</p>
            <h2>{tab.title}</h2>
            <p>{tab.description}</p>
          </div>

          <div className="panel-count">
            <strong>
              {tab.limit && tab.products.length > tab.limit
                ? `${visibleProducts.length}/${tab.products.length}`
                : tab.products.length}
            </strong>
            <span>
              {tab.limit && tab.products.length > tab.limit ? 'shown' : 'items'}
            </span>
          </div>
        </div>

        {visibleProducts.length === 0 ? (
          <div className="dashboard-empty-box">{tab.emptyMessage}</div>
        ) : (
          <div className="queue-list">
            {visibleProducts.map((product) => {
              const trend = getClickTrend(product)
              const active = product.id === selectedProduct?.id

              return (
                <button
                  key={product.id}
                  type="button"
                  className={active ? 'queue-item queue-item--active' : 'queue-item'}
                  onClick={() => setSelectedId(product.id)}
                >
                  <div className="queue-item__header">
                    <strong>{product.name}</strong>
                    <span className={`status-pill ${trend.className}`}>
                      {trend.label}
                    </span>
                  </div>

                  <div className="queue-item__meta">
                    {product.todayRank != null ? <span>{product.todayRank}위</span> : null}
                    {product.rankChangeLabel ? <span>{product.rankChangeLabel}</span> : null}
                    {asExtra(product).risingScore != null ? (
                      <span>점수 {asExtra(product).risingScore}</span>
                    ) : null}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      <div className="insight-panel">
        {!selectedProduct || !selectedExtra ? (
          <div className="dashboard-empty-box">
            선택 가능한 상품이 없습니다.
          </div>
        ) : (
          <>
            <div className="insight-panel__hero">
              <div>
                <p className="panel-eyebrow">SELECTED INSIGHT</p>
                <h2>{selectedProduct.name}</h2>

                <div className="insight-badges">
                  <span className="insight-chip insight-chip--type">
                    <span className="insight-chip__icon">▣</span>
                    {getItemGroup(selectedProduct)}
                  </span>

                  <span className={`insight-chip insight-chip--trend ${getClickTrend(selectedProduct).className}`}>
                    <span className="insight-chip__icon">✦</span>
                    {getClickTrend(selectedProduct).label}
                  </span>

                  <span className="insight-chip insight-chip--naver">
                    <span className="insight-chip__icon">▮</span>
                    {getNaverRankLabel(selectedProduct)}
                  </span>

                  <span className={getMarketChipClass(selectedProduct)}>
                    <span className="insight-chip__icon">↔</span>
                    {getMarketChipLabel(selectedProduct)}
                  </span>
                </div>
              </div>

              <Link
                to={`/products/${selectedProduct.id}`}
                className="signal-detail-button"
              >
                상세 보기
              </Link>
            </div>

            <div className="insight-flow">
            {selectedExtra.aiInsight ? (
              <section className="insight-flow-section ai-diagnosis-hero">
                <div className="insight-flow-icon ai-diagnosis-icon">AI</div>

                <div className="ai-diagnosis-body">
                  <div className="ai-diagnosis-heading">
                    <span>GENERATIVE AI INSIGHT</span>
                    <h3>EarlyPick AI 진단</h3>
                  </div>

                  <p className="ai-one-line">
                    {getAiConclusion(selectedProduct)}
                  </p>

                  <div className="ai-status-grid">
                    <article>
                      <span>AI 판단</span>
                      <strong>
                        {selectedExtra.aiInsight.diagnosis ||
                          getAiStageLabel(selectedExtra.aiInsight.aiStage)}
                      </strong>
                    </article>

                    <article>
                      <span>신뢰도</span>
                      <strong>
                        {getConfidenceLabel(selectedExtra.aiInsight.confidenceLevel)}
                      </strong>
                    </article>

                    <article>
                      <span>행동 단계</span>
                      <strong>{getAiStageLabel(selectedExtra.aiInsight.aiStage)}</strong>
                    </article>
                  </div>

                  {selectedExtra.aiInsight.businessMeaning ? (
                    <div className="ai-business-box">
                      <strong>실무 의미</strong>
                      <p>{selectedExtra.aiInsight.businessMeaning}</p>
                    </div>
                  ) : null}

                  <div className="ai-action-columns">
                    {toSafeList(selectedExtra.aiInsight.doNow).length ? (
                      <div className="ai-action-card ai-action-card--do">
                        <strong>지금 할 일</strong>
                        <ul>
                          {toSafeList(selectedExtra.aiInsight.doNow).slice(0, 3).map((item, index) => (
                            <li key={`do-now-${index}`}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {toSafeList(selectedExtra.aiInsight.doNot).length ? (
                      <div className="ai-action-card ai-action-card--dont">
                        <strong>하지 말 것</strong>
                        <ul>
                          {toSafeList(selectedExtra.aiInsight.doNot).slice(0, 3).map((item, index) => (
                            <li key={`do-not-${index}`}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>

                  {toSafeList(selectedExtra.aiInsight.nextCheck).length ? (
                    <div className="ai-next-check-box">
                      <strong>다음 확인 조건</strong>
                      <ul>
                        {toSafeList(selectedExtra.aiInsight.nextCheck).slice(0, 3).map((item, index) => (
                          <li key={`next-check-${index}`}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {toSafeList(selectedExtra.aiInsight.warnings).length ? (
                    <div className="ai-warning-box">
                      <strong>AI 주의 신호</strong>
                      <p>{toSafeList(selectedExtra.aiInsight.warnings)[0]}</p>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : (
              <section className="insight-flow-section ai-diagnosis-hero">
                <div className="insight-flow-icon ai-diagnosis-icon">AI</div>
                <div>
                  <div className="ai-diagnosis-heading">
                    <span>GENERATIVE AI INSIGHT</span>
                    <h3>EarlyPick AI 진단</h3>
                  </div>
                  <p className="ai-one-line">{getSummary(selectedProduct)}</p>
                </div>
              </section>
            )}

            <section className="insight-flow-section ai-recommend-section">
              <div className="insight-flow-icon">◎</div>
              <div>
                <h3>AI 추천 행동</h3>
                <p>{getAiRecommendedAction(selectedProduct)}</p>
              </div>
            </section>

            <section className="insight-flow-section">
              <div className="insight-flow-icon">⌁</div>
              <div>
                <h3>데이터 근거</h3>

                {selectedExtra.aiInsight?.reasons?.length ? (
                  <ul className="ai-reason-list">
                    {selectedExtra.aiInsight.reasons.slice(0, 4).map((reason, index) => (
                      <li key={`ai-reason-${index}`}>{reason}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{getSummary(selectedProduct)}</p>
                )}
              </div>
            </section>

            {selectedProduct.sourceType === 'rising' ? (
              <section className="insight-flow-section">
                <div className="insight-flow-icon">↗</div>
                <div>
                  <h3>상승 신호 분석</h3>
                  <p>
                    {selectedExtra.stableSummary ||
                      selectedExtra.opportunityReason ||
                      'Top20 진입 전 움직임을 관찰하는 후보입니다.'}
                  </p>

                  <div className="rising-feature-grid">
                    <article>
                      <span>상승 단계</span>
                      <strong>{selectedExtra.risingLevel || selectedExtra.risingStage || '-'}</strong>
                    </article>

                    <article>
                      <span>상승 점수</span>
                      <strong>{selectedExtra.risingScore ?? selectedProduct.opportunityScore ?? '-'}</strong>
                    </article>

                    <article>
                      <span>최근 7일 등장</span>
                      <strong>
                        {selectedExtra.daysSeen7d != null ? `${selectedExtra.daysSeen7d}일` : '-'}
                      </strong>
                    </article>

                    <article>
                      <span>연속 등장</span>
                      <strong>
                        {selectedExtra.consecutiveDays != null ? `${selectedExtra.consecutiveDays}일` : '-'}
                      </strong>
                    </article>

                    <article>
                      <span>3일 순위 속도</span>
                      <strong>
                        {selectedExtra.rankVelocity3d != null
                          ? `${selectedExtra.rankVelocity3d > 0 ? '+' : ''}${selectedExtra.rankVelocity3d}단계`
                          : '-'}
                      </strong>
                    </article>

                    <article>
                      <span>14일 최고 순위</span>
                      <strong>
                        {selectedExtra.bestRank14d != null ? `${selectedExtra.bestRank14d}위` : '-'}
                      </strong>
                    </article>
                  </div>
                </div>
              </section>
            ) : null}

            <section className="insight-flow-section">
              <div className="insight-flow-icon">◔</div>
              <div>
                <h3>가격 데이터 연결 상태</h3>
                <p>
                  {selectedExtra.decisionComment?.marketNote ||
                    selectedExtra.marketDataStatus?.reason ||
                    '시장 데이터 연결 여부를 추가 확인하세요.'}
                </p>

                <div className="price-inline-list">
                  <span>
                    <em>도매가</em>
                    <strong>{formatPrice(selectedExtra.wholesalePriceNow)}</strong>
                  </span>
                  <span>
                    <em>소매가</em>
                    <strong>{formatPrice(selectedExtra.retailPriceNow)}</strong>
                  </span>
                </div>
              </div>
            </section>

            <section className="insight-flow-section">
              <div className="insight-flow-icon">✓</div>
              <div>
                <h3>해석 주의</h3>
                <p>
                  {selectedExtra.aiInsight?.caution ||
                    selectedExtra.decisionComment?.caution ||
                    '네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다.'}
                </p>
              </div>
            </section>
          </div>

            <div className="insight-footer-line">
              <span>{getSourceLabel(selectedProduct)}</span>
              <span>
                {getClassificationLabel(selectedExtra.decisionComment?.classificationConfidence)}
              </span>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

export default function HomePage() {
  const { data, loading, error } = useDailySignals()
  const [activeTab, setActiveTab] = useState<DashboardTabKey>('priority')

  if (loading) {
    return (
      <MainLayout>
        <PageState
          title="시장 데이터를 불러오는 중입니다."
          message="소셜 관찰 후보, 상승 관찰 상품, 인기권 확인 상품을 정리하고 있습니다."
        />
      </MainLayout>
    )
  }

  if (error || !data) {
    return (
      <MainLayout>
        <PageState
          title="데이터를 불러오지 못했습니다."
          message={error ?? 'daily_signals.json 파일을 확인해주세요.'}
        />
      </MainLayout>
    )
  }

  const naverTop20 = data.naverTop20?.length ? data.naverTop20 : data.products
  const risingCandidates = data.risingCandidates ?? []
  const snsCandidates = data.snsCandidates ?? []

  const risingForMarket = risingCandidates.filter(
    (product) => product.excludeFromOpportunity !== true
  )

  const coreCandidates = [...risingForMarket]
    .filter((product) => (product.opportunityScore ?? product.signalScore ?? 0) >= 60)
    .sort((a, b) => {
      const scoreA = a.opportunityScore ?? a.signalScore ?? 0
      const scoreB = b.opportunityScore ?? b.signalScore ?? 0
      return scoreB - scoreA
    })
    .slice(0, 6)

  const risingSorted = [...risingForMarket].sort((a, b) => {
    const scoreA = a.opportunityScore ?? a.signalScore ?? 0
    const scoreB = b.opportunityScore ?? b.signalScore ?? 0
    return scoreB - scoreA
  })

  const allProductsMap = new Map<string, DailySignalProduct>()
  ;[...naverTop20, ...risingForMarket, ...snsCandidates].forEach((product) => {
    allProductsMap.set(product.id, product)
  })
  const allProducts = Array.from(allProductsMap.values())

  const dashboardTabs: DashboardTab[] = [
    {
      key: 'priority',
      label: '우선 검토',
      count: coreCandidates.length,
      title: 'Priority Picks',
      description: '시장 반응과 가격 데이터를 함께 확인할 우선 검토 상품입니다.',
      products: coreCandidates,
      emptyMessage: '오늘은 우선 검토할 후보가 없습니다.',
    },
    {
      key: 'social',
      label: '소셜 관찰',
      count: snsCandidates.length,
      title: 'Social Signals',
      description: '인스타그램·틱톡·유튜브 등에서 관찰한 식품 후보입니다.',
      products: snsCandidates,
      emptyMessage: '오늘 등록된 소셜 후보가 없습니다.',
      limit: 10,
    },
    {
      key: 'rising',
      label: '상승 관찰',
      count: risingSorted.length,
      title: 'Rising Watch',
      description: 'Top20 밖 움직임 후보 중 우선 확인할 상품입니다.',
      products: risingSorted,
      emptyMessage: '오늘 관찰할 움직임 후보가 없습니다.',
      limit: 15,
    },
    {
      key: 'confirmed',
      label: '인기권 확인',
      count: naverTop20.length,
      title: 'Confirmed Demand',
      description: '네이버 쇼핑인사이트 인기권에서 확인된 상품입니다.',
      products: naverTop20,
      emptyMessage: '인기권 상품 데이터가 없습니다.',
    },
  ]

  const activeDashboard =
    dashboardTabs.find((tab) => tab.key === activeTab) ?? dashboardTabs[0]

  return (
    <MainLayout>
      <main className="command-layout">
        <aside className="command-sidebar">
          <div className="command-sidebar__brand">
            <div className="command-brand-mark">
              <div className="command-brand-icon">⌁</div>

              <div>
                <span>EARLYPICK</span>
                <strong>COMMAND CENTER</strong>
              </div>
            </div>
          </div>

          <div className="command-sidebar__meta">
            <span>
              <em>네이버 기준일</em>
              <strong>{data.naverSignalDate ?? data.dateLabel ?? '-'}</strong>
            </span>

            <span>
              <em>가격 기준일</em>
              <strong>{data.priceAsOfDate || '-'}</strong>
            </span>

            <span>
              <em>분석 실행일</em>
              <strong>{data.analysisDate || '-'}</strong>
            </span>

            <span>
              <em>전체 후보</em>
              <strong>{allProducts.length}</strong>
            </span>
          </div>

          <nav className="command-sidebar__tabs">
            {dashboardTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={
                  activeTab === tab.key
                    ? 'sidebar-tab sidebar-tab--active'
                    : 'sidebar-tab'
                }
                onClick={() => setActiveTab(tab.key)}
              >
                <span>{tab.label}</span>
                <strong>{tab.count}</strong>
              </button>
            ))}
          </nav>
        </aside>

        <section className="command-main">
          <DashboardWorkspace tab={activeDashboard} />
        </section>
      </main>
    </MainLayout>
  )
}