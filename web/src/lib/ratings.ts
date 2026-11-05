import type { Valuation } from '@/lib/data'

export type RatingFilter = 'buy' | 'sell' | 'fair' | 'wait' | 'overpriced' | 'unlisted' | 'all'

export const ratingFilters: Record<RatingFilter, (v: Valuation) => boolean> = {
  buy: (v) => v.label === 'Strong buy' || v.label === 'Buy',
  sell: (v) => v.label === 'Sell',
  fair: (v) => v.label === 'Fair',
  wait: (v) => v.label === 'Wait',
  overpriced: (v) => v.label === 'Overpriced',
  unlisted: (v) => v.label === 'Not listed',
  all: (v) => v.label !== 'Not listed',
}

export function countRatings(items: Valuation[]): Record<RatingFilter, number> {
  const out = { buy: 0, sell: 0, fair: 0, wait: 0, overpriced: 0, unlisted: 0, all: 0 }
  for (const v of items) for (const f of Object.keys(ratingFilters) as RatingFilter[]) if (ratingFilters[f](v)) out[f]++
  return out
}
