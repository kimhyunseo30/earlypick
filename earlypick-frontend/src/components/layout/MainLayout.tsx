import type { ReactNode } from 'react'
import Header from './Header'

type MainLayoutProps = {
  children: ReactNode
}

function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="app-shell">
      <Header />
      <main className="main-content">
        <div className="container">{children}</div>
      </main>
    </div>
  )
}

export default MainLayout