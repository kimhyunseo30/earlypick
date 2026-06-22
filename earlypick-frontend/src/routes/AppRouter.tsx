import { BrowserRouter, Routes, Route } from 'react-router-dom'
import HomePage from '../pages/HomePage'
import TrendsPage from '../pages/TrendsPage'
import ProductDetailPage from '../pages/ProductDetailPage'
import WatchlistPage from '../pages/WatchlistPage'
import InsightsPage from '../pages/InsightsPage'

function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/trends" element={<TrendsPage />} />
        <Route path="/insights" element={<InsightsPage />} />
        <Route path="/products/:productId" element={<ProductDetailPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default AppRouter;