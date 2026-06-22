import { NavLink, Link } from 'react-router-dom'

export default function Header() {
  const getNavLinkClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? 'nav-link active' : 'nav-link'

  return (
    <header className="site-header">
      <div className="container header-inner">
        <div className="brand-area">
          <NavLink to="/" className="brand-link">
            <span className="brand-name">EARLYPICK</span>
          </NavLink>
          <p className="brand-subtitle">
            식품 트렌드와 시장 데이터를 연결하는 인사이트 서비스
          </p>
        </div>

        <nav className="main-nav">
          <NavLink to="/" className={getNavLinkClass} end>
            홈
          </NavLink>
          <NavLink to="/trends" className={getNavLinkClass}>
            시장 탐색
          </NavLink>
          <NavLink to="/insights" className={getNavLinkClass}>
            시그널 분석
          </NavLink>
          <NavLink to="/watchlist" className={getNavLinkClass}>
            저장한 품목
          </NavLink>
        </nav>

        <div className="header-cta">
          <Link to="/insights" className="header-button">
            오늘의 신호 보기
          </Link>
        </div>
      </div>
    </header>
  )
}