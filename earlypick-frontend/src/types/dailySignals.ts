export type SignalGroup = 'early' | 'conversion' | 'overheated'
export type RiskLevel = '낮음' | '보통' | '높음'
export type SourceType = 'top20' | 'rising' | 'sns'

export type SeriesPoint = {
  date: string
  value: number
}

export type MarketPriceRow = {
  county: string
  market: string
  price: number
  date: string
}

export type DailySignalProduct = {
  id: string
  name: string
  todayRank: number | null

  
  marketGroup: string
  category: string
  subCategory: string
  originType: '국내산' | '수입'
  unit: string
  origin?: string
  sourceType?: 'top20' | 'rising' | 'sns' | string
  source?: string
  sourceNote?: string
  productGroup?: string
  subGroup?: string
  excludeFromOpportunity?: boolean

   // 추가: 네이버 Top200 확인 정보
  naverRank?: number | null;
  isInNaverTop200?: boolean;
  naverRankLabel?: string;

  // 추가: 상품 유형 분류 정보
  itemType?: string;
  itemGroup?: string;
  classificationMethod?: string;
  classificationConfidence?: string;
  classificationReason?: string;

  signalGroup: SignalGroup
  signalLabel: string
  signalScore: number
  action: string

  priceRisk: RiskLevel
  weatherRisk?: RiskLevel
  fxRisk?: RiskLevel

  searchRatioToday: number
  shoppingRatioToday: number
  searchLeadDays: number
  conversionScore: number
  persistenceScore: number
  bubbleRiskScore: number

  drivers: string[]
  eventTags: string[]

  summary: string
  detailReason: string
  forecast7d: string
  forecast14d: string

  priceNow?: number | null
  priceChangeRate?: number | null
  priceSource?: string | null

  wholesalePriceNow?: number | null
  retailPriceNow?: number | null
  wholesaleTrend?: string | null
  retailTrend?: string | null
  wholesaleChangeRate?: number | null
  retailChangeRate?: number | null
  priceComment?: string | null

  priceDetail?: {
    wholesaleAverageNow?: number | null
    retailAverageNow?: number | null
    wholesaleSeries7d?: SeriesPoint[]
    retailSeries7d?: SeriesPoint[]
    wholesaleMarkets?: MarketPriceRow[]
    retailMarkets?: MarketPriceRow[]
    variants?: {
      itemName?: string
      kindName?: string
      rankName?: string
      itemcode?: string
      kindcode?: string
      productrankcode?: string
      wholesaleUnitName?: string | null
      retailUnitName?: string | null
      wholesalePriceNow?: number | null
      retailPriceNow?: number | null
      wholesaleChangeRate?: number | null
      retailChangeRate?: number | null
      wholesaleTrend?: string | null
      retailTrend?: string | null
      wholesaleDate?: string | null
      retailDate?: string | null
  }[]
  }

  series: {
    search: SeriesPoint[]
    shopping: SeriesPoint[]
    price?: SeriesPoint[]
  }

   priceMeta?: {
    itemName?: string
    kindName?: string
    rankName?: string
    retailUnitName?: string
    wholesaleUnitName?: string
    label?: string
  }
  rankRange?: string | null

  clickEfficiency?: number
  opportunityScore?: number
  opportunityReason?: string
  searchGrowthRate?: number
  shoppingGrowthRate?: number
  previousRank?: number | null
  rankChange?: number | null
  rankDirection?: 'up' | 'down' | 'flat' | 'new' | 'none'
  rankChangeLabel?: string

  auctionDetail?: {
    source?: string
    date?: string
    avgAuctionPrice?: number
    weightedAvgAuctionPrice?: number
    highPrice?: number
    lowPrice?: number
    totalTradeQty?: number
    rowCount?: number
    validRowCount?: number
    outlierCount?: number
    rawHighPrice?: number
    rawLowPrice?: number
    marketCount?: number
    corpCount?: number
    varietyCount?: number
    auctionQuality?: {
      level?: 'none' | 'high' | 'medium' | 'low' | 'very_low' | string
      label?: string
      reason?: string
    }
    markets?: {
      marketCode?: string
      marketName?: string
      weightedAvgAuctionPrice?: number
      highPrice?: number
      lowPrice?: number
      totalTradeQty?: number
      rowCount?: number
      validRowCount?: number
      outlierCount?: number
      rawHighPrice?: number
      rawLowPrice?: number
      corpCount?: number
    }[]
    varieties?: {
      varietyName?: string
      unitName?: string
      weightedAvgAuctionPrice?: number
      highPrice?: number
      lowPrice?: number
      totalTradeQty?: number
      rowCount?: number
      validRowCount?: number
      outlierCount?: number
      rawHighPrice?: number
      rawLowPrice?: number
      marketCount?: number
    }[]
  }

  marketDataStatus?: {
    kamisMatched?: boolean
    auctionMatched?: boolean
    marketType?: string
    reason?: string
  }

  decisionComment?: {
  summary?: string
  interestLabel?: string
  recommendedUse?: string
  marketNote?: string
  caution?: string
 }
  

}

export type DailySignalsData = {
  generatedAt: string
  dateLabel: string
  naverSignalDate?: string
  priceAsOfDate?: string
  analysisDate?: string
  
  summary: {
    analyzedCount: number
    earlyCount: number
    conversionCount: number
    overheatedCount: number
    priceRiskCount: number
  }
  snsSummary?: {
    candidateCount: number
    earlyCount: number
    conversionCount: number
    overheatedCount: number
  }
  risingSummary?: {
    candidateCount: number
    earlyCount: number
    conversionCount: number
    overheatedCount: number
  }
  highlights: {
    early: string[]
    conversion: string[]
    overheated: string[]
  }
  snsHighlights?: {
    early: string[]
    conversion: string[]
    overheated: string[]
  }
  products: DailySignalProduct[]
  naverTop20?: DailySignalProduct[]
  risingCandidates?: DailySignalProduct[]
  snsCandidates?: DailySignalProduct[]
}