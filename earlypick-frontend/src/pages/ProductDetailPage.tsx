import { Link, useParams } from 'react-router-dom'
import MainLayout from '../components/layout/MainLayout'
import PageState from '../components/common/PageState'
import { useDailySignals } from '../hooks/useDailysignals'
import type { DailySignalProduct } from '../types/dailySignals'

type PriceVariant = NonNullable<
  NonNullable<DailySignalProduct['priceDetail']>['variants']
>[number]

type SeriesPoint = {
  date: string
  value: number
}

function formatPrice(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return `${Math.round(value).toLocaleString()}원`
}

function formatPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value}%`
}

function getTrendClass(trend?: string | null) {
  if (trend === '상승') return 'trend-up'
  if (trend === '하락') return 'trend-down'
  return 'trend-flat'
}

function getRankClass(direction?: string | null) {
  if (direction === 'up') return 'rank-up'
  if (direction === 'down') return 'rank-down'
  if (direction === 'new') return 'rank-new'
  return 'rank-flat'
}

function getSourceLabel(product: DailySignalProduct) {
  if (product.sourceType === 'top20') return '확산 확인'
  if (product.sourceType === 'rising') return '상승 전조'
  if (product.sourceType === 'sns') return 'SNS 선행'
  return '시장 신호'
}

function getPrimaryVariant(product: DailySignalProduct): PriceVariant | null {
  const variants = product.priceDetail?.variants ?? []

  if (variants.length === 0) return null

  const 상품Variant = variants.find((item) => item.rankName === '상품')
  return 상품Variant ?? variants[0]
}

function getRepresentativeWholesale(product: DailySignalProduct) {
  const variant = getPrimaryVariant(product)

  return (
    variant?.wholesalePriceNow ??
    product.priceDetail?.wholesaleAverageNow ??
    product.wholesalePriceNow ??
    null
  )
}

function getRepresentativeRetail(product: DailySignalProduct) {
  const variant = getPrimaryVariant(product)

  return (
    variant?.retailPriceNow ??
    product.priceDetail?.retailAverageNow ??
    product.retailPriceNow ??
    null
  )
}

function ProductHero({ product }: { product: DailySignalProduct }) {
  const primaryVariant = getPrimaryVariant(product)

  return (
    <section className="detail-hero">
      <div>
        <p className="eyebrow">PRODUCT MARKET DETAIL</p>
        <h1>{product.name}</h1>

        <div className="detail-hero__meta">
          <span>{getSourceLabel(product)}</span>
          {product.todayRank ? <span>{product.todayRank}위</span> : null}
          {product.rankRange ? <span>{product.rankRange}</span> : null}
          {product.rankChangeLabel ? (
            <span className={`rank-change ${getRankClass(product.rankDirection)}`}>
              {product.rankChangeLabel}
            </span>
          ) : null}
        </div>

        <p>
          {product.opportunityReason ??
            product.summary ??
            '검색·쇼핑 반응과 시장 가격 흐름을 함께 확인할 상품입니다.'}
        </p>
      </div>

      <div className="detail-hero__side">
        <span>대표 가격 기준</span>
        <strong>
          {primaryVariant
            ? `${primaryVariant.kindName ?? product.name} · ${primaryVariant.rankName ?? '-'}`
            : product.priceMeta?.label ?? '가격 기준 없음'}
        </strong>
        <small>
          도매 {primaryVariant?.wholesaleUnitName ?? product.priceMeta?.wholesaleUnitName ?? '-'} ·
          소매 {primaryVariant?.retailUnitName ?? product.priceMeta?.retailUnitName ?? '-'}
        </small>
      </div>
    </section>
  )
}

function PriceSummaryCards({ product }: { product: DailySignalProduct }) {
  const primaryVariant = getPrimaryVariant(product)
  const wholesalePrice = getRepresentativeWholesale(product)
  const retailPrice = getRepresentativeRetail(product)

  const wholesaleDate =
    primaryVariant?.wholesaleDate ??
    product.priceDetail?.wholesaleSeries7d?.at(-1)?.date ??
    '-'

  const retailDate =
    primaryVariant?.retailDate ??
    product.priceDetail?.retailSeries7d?.at(-1)?.date ??
    '-'

  return (
    <section className="price-summary-grid">
      <article>
        <span>도매 대표가</span>
        <strong>{formatPrice(wholesalePrice)}</strong>
        <p>
          {primaryVariant?.wholesaleUnitName ??
            product.priceMeta?.wholesaleUnitName ??
            '단위 정보 없음'}
        </p>
      </article>

      <article>
        <span>소매 대표가</span>
        <strong>{formatPrice(retailPrice)}</strong>
        <p>
          {primaryVariant?.retailUnitName ??
            product.priceMeta?.retailUnitName ??
            '단위 정보 없음'}
        </p>
      </article>

      <article>
        <span>도매 변동</span>
        <strong className={getTrendClass(primaryVariant?.wholesaleTrend)}>
          {primaryVariant?.wholesaleTrend ?? '-'}
        </strong>
        <p>{formatPercent(primaryVariant?.wholesaleChangeRate)}</p>
      </article>

      <article>
        <span>가격 기준일</span>
        <strong>{wholesaleDate || retailDate || '-'}</strong>
        <p>도매/소매 최신 제공일 기준</p>
      </article>
    </section>
  )
}

function SimplePriceTrend({
  title,
  series,
}: {
  title: string
  series?: SeriesPoint[]
}) {
  const validSeries = series ?? []
  const maxValue = Math.max(...validSeries.map((item) => item.value), 0)

  return (
    <section className="market-card">
      <div className="market-card__header">
        <div>
          <p className="eyebrow">PRICE TREND</p>
          <h2>{title}</h2>
        </div>
      </div>

      {validSeries.length === 0 ? (
        <div className="detail-empty-box">최근 7일 가격 데이터가 없습니다.</div>
      ) : (
        <div className="simple-trend-list">
          {validSeries.map((item) => {
            const width = maxValue > 0 ? Math.max(6, (item.value / maxValue) * 100) : 0

            return (
              <div className="simple-trend-row" key={`${title}-${item.date}`}>
                <span>{item.date}</span>
                <div>
                  <i style={{ width: `${width}%` }} />
                </div>
                <strong>{formatPrice(item.value)}</strong>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function VariantMarketExplorer({ product }: { product: DailySignalProduct }) {
  const variants = product.priceDetail?.variants ?? []

  const rankOrder: Record<string, number> = {
    특: 1,
    상품: 2,
    중품: 3,
    하품: 4,
  }

  const grouped = variants.reduce<Record<string, PriceVariant[]>>((acc, variant) => {
    const key = variant.kindName || '기타'
    if (!acc[key]) acc[key] = []
    acc[key].push(variant)
    return acc
  }, {})

  const kindNames = Object.keys(grouped).sort((a, b) => a.localeCompare(b, 'ko'))

  return (
    <section className="market-card">
      <div className="market-card__header">
        <div>
          <p className="eyebrow">KAMIS PRICE VARIANTS</p>
          <h2>시장탐색: 품종·등급별 가격</h2>
          <p>
            같은 품목이라도 품종과 등급에 따라 도매가·소매가 기준이 달라집니다.
          </p>
        </div>
        <strong>{variants.length}</strong>
      </div>

      {variants.length === 0 ? (
        <div className="detail-empty-box">
          품종·등급별 가격 데이터가 없습니다.
        </div>
      ) : (
        <div className="variant-group-list">
          {kindNames.map((kindName) => {
            const items = [...grouped[kindName]].sort((a, b) => {
              const rankA = rankOrder[a.rankName ?? ''] ?? 99
              const rankB = rankOrder[b.rankName ?? ''] ?? 99
              return rankA - rankB
            })

            return (
              <article className="variant-group-card" key={kindName}>
                <div className="variant-group-card__title">
                  <h3>{kindName}</h3>
                  <span>{items.length}개 등급</span>
                </div>

                <div className="variant-group-table">
                  <div className="variant-group-table__head">
                    <span>등급</span>
                    <span>도매 단위</span>
                    <span>도매가</span>
                    <span>소매 단위</span>
                    <span>소매가</span>
                    <span>기준일</span>
                  </div>

                  {items.map((variant, index) => (
                    <div
                      className="variant-group-table__row"
                      key={`${variant.kindName}-${variant.rankName}-${index}`}
                    >
                      <span className="variant-rank-pill">{variant.rankName || '-'}</span>

                      <span>{variant.wholesaleUnitName || '-'}</span>

                      <strong>
                        {formatPrice(variant.wholesalePriceNow)}
                        {variant.wholesaleTrend ? (
                          <small className={getTrendClass(variant.wholesaleTrend)}>
                            {variant.wholesaleTrend} {formatPercent(variant.wholesaleChangeRate)}
                          </small>
                        ) : null}
                      </strong>

                      <span>{variant.retailUnitName || '-'}</span>

                      <strong>
                        {formatPrice(variant.retailPriceNow)}
                        {variant.retailTrend ? (
                          <small className={getTrendClass(variant.retailTrend)}>
                            {variant.retailTrend} {formatPercent(variant.retailChangeRate)}
                          </small>
                        ) : null}
                      </strong>

                      <span>{variant.wholesaleDate || variant.retailDate || '-'}</span>
                    </div>
                  ))}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function DecisionCommentCard({ product }: { product: DailySignalProduct }) {
  const comment = product.decisionComment

  if (!comment) {
    return null
  }

  return (
    <section className="decision-card">
      <div className="decision-card__header">
        <div>
          <p className="eyebrow">EARLYPICK VIEW</p>
          <h2>Earlypick 판단</h2>
        </div>

        {comment.interestLabel ? (
          <span className="decision-card__badge">
            {comment.interestLabel}
          </span>
        ) : null}
      </div>

      {comment.summary ? (
        <p className="decision-card__summary">
          {comment.summary}
        </p>
      ) : null}

      <div className="decision-card__grid">
        {comment.recommendedUse ? (
          <article>
            <span>추천 활용</span>
            <strong>{comment.recommendedUse}</strong>
          </article>
        ) : null}

        {comment.marketNote ? (
          <article>
            <span>시장 데이터</span>
            <strong>{comment.marketNote}</strong>
          </article>
        ) : null}

        {comment.caution ? (
          <article>
            <span>확인 포인트</span>
            <strong>{comment.caution}</strong>
          </article>
        ) : null}
      </div>
    </section>
  )
}

function MarketPriceTable({
  title,
  rows,
}: {
  title: string
  rows?: {
    kindName?: string
    rankName?: string
    county?: string
    market?: string
    unitName?: string
    price?: number
    date?: string
  }[]
}) {

  const marketRows = rows ?? []

  return (
    <section className="market-card">
      <div className="market-card__header">
        <div>
          <p className="eyebrow">MARKET PRICE</p>
          <h2>{title}</h2>
        </div>
        <strong>{marketRows.length}</strong>
      </div>

      {marketRows.length === 0 ? (
        <div className="detail-empty-box">시장별 가격 데이터가 없습니다.</div>
      ) : (
        <div className="market-price-table">
          <div className="market-price-table__head">
            <span>품종</span>
            <span>등급</span>
            <span>지역/시장</span>
            <span>단위</span>
            <span>가격</span>
            <span>기준일</span>
          </div>

          {marketRows.map((row, index) => (
            <div className="market-price-table__row" key={`${row.market}-${index}`}>
              <span>{row.kindName || '-'}</span>
              <span>{row.rankName || '-'}</span>
              <span>{row.market || row.county || '-'}</span>
              <span>{row.unitName || '-'}</span>
              <strong>{formatPrice(row.price)}</strong>
              <span>{row.date || '-'}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
function formatQty(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return Math.round(value).toLocaleString()
}

function AuctionMarketCard({ product }: { product: DailySignalProduct }) {
  const auction = product.auctionDetail

  if (!auction) {
    return (
      <section className="market-card">
        <div className="market-card__header">
          <div>
            <p className="eyebrow">AUCTION MARKET</p>
            <h2>전국 도매시장 경락정보</h2>
            <p>전국 공영도매시장 경매 거래 기반 가격·거래물량 정보입니다.</p>
          </div>
        </div>

        <div className="detail-empty-box">
          연결된 경락정보 데이터가 없습니다.
        </div>
      </section>
    )
  }

  return (
    <section className="market-card">
      <div className="market-card__header">
        <div>
          <p className="eyebrow">AUCTION MARKET</p>
          <h2>전국 도매시장 경락정보</h2>
          <p>
          전국 공영도매시장 경매 거래 기반의 가격·거래물량 정보입니다.
          대표 경락가는 이상치를 제거한 뒤 거래물량을 반영해 계산했습니다.
          </p>
        </div>
        <strong>{auction.marketCount ?? 0}</strong>
      </div>

      <div className="auction-summary-grid">
        <article>
          <span>대표 경락가</span>
          <strong>{formatPrice(auction.weightedAvgAuctionPrice)}</strong>
          <p>이상치 제거 후 거래물량 반영</p>
        </article>

        <article>
          <span>최고가</span>
          <strong>{formatPrice(auction.highPrice)}</strong>
          <p>경매 거래 기준</p>
        </article>

        <article>
          <span>최저가</span>
          <strong>{formatPrice(auction.lowPrice)}</strong>
          <p>경매 거래 기준</p>
        </article>

        <article>
          <span>경매 거래물량</span>
          <strong>{formatQty(auction.totalTradeQty)}</strong>
          <p>추정 거래물량</p>
        </article>
      </div>

      <div className="auction-meta-row">
        <span>기준일: {auction.date || '-'}</span>
        <span>전체 거래: {auction.rowCount ?? 0}건</span>
        <span>유효 거래: {auction.validRowCount ?? auction.rowCount ?? 0}건</span>
        <span>이상치 제외: {auction.outlierCount ?? 0}건</span>
        <span>도매시장: {auction.marketCount ?? 0}곳</span>
        <span>품종 수: {auction.varietyCount ?? 0}개</span>
        {auction.auctionQuality?.label ? (
          <span>데이터 신뢰도: {auction.auctionQuality.label}</span>
        ) : null}
      </div>

      {auction.markets && auction.markets.length > 0 ? (
        <div className="auction-market-table">
          <div className="auction-market-table__head">
            <span>시장명</span>
            <span>가중 평균가</span>
            <span>최고가</span>
            <span>최저가</span>
            <span>거래물량</span>
          </div>

          {auction.markets.slice(0, 8).map((market, index) => (
            <div
              className="auction-market-table__row"
              key={`${market.marketCode}-${index}`}
            >
              <span>{market.marketName || '-'}</span>
              <strong>{formatPrice(market.weightedAvgAuctionPrice)}</strong>
              <span>{formatPrice(market.highPrice)}</span>
              <span>{formatPrice(market.lowPrice)}</span>
              <span>{formatQty(market.totalTradeQty)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function SignalAnalysisPanel({ product }: { product: DailySignalProduct }) {
  return (
    <section className="market-card">
      <div className="market-card__header">
        <div>
          <p className="eyebrow">SIGNAL ANALYSIS</p>
          <h2>시그널 분석</h2>
          <p>네이버 순위 변화, 검색 반응, 쇼핑 클릭 추이를 함께 확인합니다.</p>
        </div>
      </div>

      <div className="signal-analysis-grid">
        <article>
          <span>순위 변화</span>
          <strong>{product.rankChangeLabel ?? '-'}</strong>
        </article>

        <article>
          <span>검색 증가율</span>
          <strong>{formatPercent(product.searchGrowthRate)}</strong>
        </article>

        <article>
          <span>쇼핑 클릭 추이</span>
          <strong>{formatPercent(product.shoppingGrowthRate)}</strong>
        </article>

        <article>
          <span>선점점수</span>
          <strong>{product.opportunityScore ?? product.signalScore ?? '-'}</strong>
        </article>
      </div>

      <div className="signal-comment-box">
        <strong>해석</strong>
        <p>
          {product.opportunityReason ??
            '검색·클릭 흐름과 순위 변화를 추가 관찰할 후보입니다.'}
        </p>
      </div>
    </section>
  )
}

export default function ProductDetailPage() {
  const { productId } = useParams()
  const { data, loading, error } = useDailySignals()

  if (loading) {
    return (
      <MainLayout>
        <PageState
          title="상품 데이터를 불러오는 중입니다."
          message="시장탐색과 시그널분석 데이터를 정리하고 있습니다."
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

  const allProducts = [
    ...(data.naverTop20 ?? []),
    ...(data.risingCandidates ?? []),
    ...(data.snsCandidates ?? []),
    ...data.products,
  ]

  const uniqueProducts = allProducts.filter(
    (product, index, arr) => arr.findIndex((item) => item.id === product.id) === index
  )

  const product = uniqueProducts.find((item) => item.id === productId)

  if (!product) {
    return (
      <MainLayout>
        <PageState
          title="상품을 찾을 수 없습니다."
          message="홈 화면에서 다시 상품을 선택해주세요."
        />
        <Link to="/" className="text-link">
          홈으로 돌아가기 →
        </Link>
      </MainLayout>
    )
  }

  return (
    <MainLayout>
      <ProductHero product={product} />

      <PriceSummaryCards product={product} />

      <section className="detail-two-column">
        <SimplePriceTrend
          title="도매 평균가 최근 7일"
          series={product.priceDetail?.wholesaleSeries7d}
        />

        <SimplePriceTrend
          title="소매 평균가 최근 7일"
          series={product.priceDetail?.retailSeries7d}
        />
      </section>

      <DecisionCommentCard product={product} />
      <VariantMarketExplorer product={product} />
      <AuctionMarketCard product={product} />

      <section className="detail-two-column">
        <MarketPriceTable
          title="도매 시장별 가격"
          rows={product.priceDetail?.wholesaleMarkets}
        />

        <MarketPriceTable
          title="소매 시장별 가격"
          rows={product.priceDetail?.retailMarkets}
        />
      </section>

      <SignalAnalysisPanel product={product} />
    </MainLayout>
  )
}