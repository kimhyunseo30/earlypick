export type PriceRiskLevel = '낮음' | '보통' | '높음'
export type RecommendationAction = '지금 사입' | '소량 테스트' | '관망' | '대체 검토'
export type MarketGroup =
  | '국내산 채소'
  | '국내산 과일'
  | '수입 원재료'
  | '냉동식품'
  | '커피/음료'

export type OriginType = '국내산' | '수입'

export type DriverTag =
  | '날씨'
  | '출하량'
  | '반입량'
  | '환율'
  | '국제원재료'
  | '수요확산'
  | '검색급등'
  | '계절성'
  | '물류비'

export type Product = {
  id: number
  name: string
  marketGroup: MarketGroup
  category: string
  subCategory: string
  unit: string
  origin?: string
  originType: OriginType
  trendScore: number
  priceRisk: PriceRiskLevel
  prediction: string
  recommendation: RecommendationAction
  currentPrice: number
  priceChangeRate: number
  priceSource?: string
  driverTags: DriverTag[]
}

export type PricePoint = {
  date: string
  price: number
}

export type ProductDetail = Product & {
  description?: string
  trendSummary: string
  forecast7d: string
  forecast14d: string
  recommendationReason: string
  priceHistory: PricePoint[]
}