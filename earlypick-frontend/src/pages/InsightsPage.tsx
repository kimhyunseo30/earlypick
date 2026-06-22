import { Link } from 'react-router-dom'
import MainLayout from '../components/layout/MainLayout'
import PageState from '../components/common/PageState'
import { useDailySignals } from '../hooks/useDailysignals'

export default function InsightsPage() {
  const { data, loading, error } = useDailySignals()

  if (loading) {
    return (
      <MainLayout>
        <PageState title="시그널 그룹을 불러오는 중입니다." message="오늘의 분류 결과를 가져오고 있습니다." />
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

  const groups = {
    early: data.products.filter((p) => p.signalGroup === 'early'),
    conversion: data.products.filter((p) => p.signalGroup === 'conversion'),
    overheated: data.products.filter((p) => p.signalGroup === 'overheated'),
  }

  const groupMeta = {
    early: {
      title: '초기 선점 후보',
      subtitle: '검색이 먼저 붙고 쇼핑이 뒤따르는 상품',
    },
    conversion: {
      title: '구매전환 강한 후보',
      subtitle: '검색과 쇼핑 클릭이 함께 움직이는 상품',
    },
    overheated: {
      title: '과열 주의 후보',
      subtitle: '검색 급등 대비 쇼핑 추종이 약한 상품',
    },
  }

  return (
    <MainLayout>
      <section className="insight-hero">
        <div className="insight-hero__content">
          <p className="eyebrow">TODAY'S SIGNAL GROUPS</p>
          <h1>오늘 Top20을 패턴 기준으로 분류해 보세요</h1>
          <p className="insight-hero__description">
            과거 학습 패턴을 기준으로 오늘 올라온 상품을 초기 선점, 구매전환 강함,
            과열 주의 세 그룹으로 나눠 실무적으로 해석할 수 있게 만든 화면입니다.
          </p>

          <div className="insight-hero__actions">
            <Link to="/trends" className="primary-button">
              시장 탐색 보기
            </Link>
            <Link to="/watchlist" className="secondary-button">
              저장한 품목 보기
            </Link>
          </div>
        </div>

        <div className="insight-summary-grid">
          <article className="insight-summary-card">
            <span>분석 기준일</span>
            <strong>{data.dateLabel}</strong>
            <p>오늘 화면에 반영된 운영 기준 날짜입니다.</p>
          </article>
          <article className="insight-summary-card">
            <span>초기 선점</span>
            <strong>{data.summary.earlyCount}</strong>
            <p>검색 선행 신호가 확인된 상품 수</p>
          </article>
          <article className="insight-summary-card">
            <span>구매전환 강함</span>
            <strong>{data.summary.conversionCount}</strong>
            <p>검색과 쇼핑 동조성이 강한 상품 수</p>
          </article>
          <article className="insight-summary-card">
            <span>과열 주의</span>
            <strong>{data.summary.overheatedCount}</strong>
            <p>검색 급등 대비 쇼핑 추종이 약한 상품 수</p>
          </article>
        </div>
      </section>

      {(['early', 'conversion', 'overheated'] as const).map((key) => (
        <section key={key} className="section-block group-section">
          <div className="section-heading">
            <p className="eyebrow">SIGNAL GROUP</p>
            <h2>{groupMeta[key].title}</h2>
            <p>{groupMeta[key].subtitle}</p>
          </div>

          <div className="insight-card-grid">
            {groups[key].map((product) => (
              <article key={product.id} className="insight-card">
                <div className="insight-card__top">
                  <span className="category-badge">{product.marketGroup}</span>
                  <span className="score-badge">#{product.todayRank}</span>
                </div>

                <h3>{product.name}</h3>
                <p className="insight-card__note">{product.summary}</p>

                <div className="insight-metric-grid">
                  <div className="insight-metric-box">
                    <span>검색 선행</span>
                    <strong>{product.searchLeadDays}일</strong>
                  </div>
                  <div className="insight-metric-box">
                    <span>전환 강도</span>
                    <strong>{product.conversionScore}</strong>
                  </div>
                  <div className="insight-metric-box">
                    <span>유지력</span>
                    <strong>{product.persistenceScore}</strong>
                  </div>
                  <div className="insight-metric-box">
                    <span>버블 위험</span>
                    <strong>{product.bubbleRiskScore}</strong>
                  </div>
                </div>

                <div className="driver-tag-list">
                  {product.drivers.map((tag) => (
                    <span key={tag} className="driver-tag">
                      {tag}
                    </span>
                  ))}
                </div>

                <div className="insight-card__footer">
                  <div className="insight-action-pill">{product.action}</div>
                  <Link to={`/products/${product.id}`} className="text-link">
                    상세 보기 →
                  </Link>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}

      <section className="section-block insight-two-column">
        <div className="panel-card">
          <div className="section-heading">
            <p className="eyebrow">HOW TO READ</p>
            <h2>읽는 기준</h2>
          </div>

          <div className="guide-list">
            <div className="guide-item">
              <strong>초기 선점</strong>
              <p>검색량이 먼저 붙고 쇼핑 클릭이 뒤따르면 초기 시그널 후보로 봅니다.</p>
            </div>
            <div className="guide-item">
              <strong>구매전환 강함</strong>
              <p>검색과 쇼핑이 같이 움직이고 유지력이 좋으면 구매전환형으로 봅니다.</p>
            </div>
            <div className="guide-item">
              <strong>과열 주의</strong>
              <p>검색만 과도하게 치고 올라가고 쇼핑이 약하면 과열 가능성을 봅니다.</p>
            </div>
          </div>
        </div>

        <div className="panel-card panel-card--soft">
          <div className="section-heading">
            <p className="eyebrow">TODAY'S NOTES</p>
            <h2>해석 메모</h2>
          </div>

          <div className="insight-note-list">
            <div className="insight-note-item">
              <span className="insight-note-dot" />
              <p>두쫀쿠는 SNS 바이럴과 품절 이슈가 겹친 이벤트형 패턴으로 해석합니다.</p>
            </div>
            <div className="insight-note-item">
              <span className="insight-note-dot" />
              <p>버터떡은 검색 이후 쇼핑 클릭이 안정적으로 따라붙는 전환형 상품입니다.</p>
            </div>
            <div className="insight-note-item">
              <span className="insight-note-dot" />
              <p>참외는 초기 시그널 후보로, 아직 피크 전 구간인지 추가 확인이 필요합니다.</p>
            </div>
          </div>
        </div>
      </section>
    </MainLayout>
  )
}