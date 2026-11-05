// The shape of reports/compare.json, written by `python -m aion2 compare`.

export type Faction = 'Elyos' | 'Asmodian'

export interface Server {
  id: number
  name: string
  faction: Faction
  region: string
  items: number
  listings: number
  basket: number
  index: number | null // trimmed geometric mean of price / regional median; 1 = typical
  vs_home: number | null // the same, against the home server's prices
  cheapest_count: number
  sections: Record<string, number>
}

export type Tone = 'good' | 'ok' | 'warn' | 'bad' | 'sell' | 'none'
export type Rating = 'Strong buy' | 'Buy' | 'Sell' | 'Fair' | 'Wait' | 'Overpriced' | 'Not listed' | 'Unknown'

/** One estimate of fair value (aion2/value.py): the home server's history, or the similar-item ratios. */
export interface Estimate {
  source: 'history' | 'peers'
  price: number
  low: number // 80% range
  high: number
  sigma: number
  weight: number // share of the blend
  // history only: what sold (aion2/trades.py)
  basis?: 'sales' | 'no sales' | 'expired' | 'asks' | null
  sales?: number // sales seen in its window
  expired?: number // cheapest listings that expired unsold since the last sale
  sold_at?: number | null // the level of the recent sale prices
}

export interface Peer {
  key: number
  name: string
  ratio: number // this item's price ÷ the peer's, median over the other servers
  home_level: number // the peer's usual price on the home server
  implied: number // ratio × home_level
  servers: number
  spread: number // how much the ratio varies across servers (log sd)
  weight: number
}

/** The valuation of one item on the home server and the rating of buying it now. */
export interface Valuation {
  key: number
  name: string
  category: string | null
  section: string | null
  label: Rating
  tone: Tone
  now: number | null
  fair?: number
  low?: number // 80% range of the fair value
  high?: number
  sigma?: number
  margin?: number
  buy_below?: number
  list_at?: number // the fair value, or the recent sale prices when lower; for a Sell, just under the cheapest
  upside?: number | null // fair / now − 1
  z?: number | null
  resale_roi?: number | null
  growth: number | null
  section_trend?: number | null // the item's section index over the week
  fill_1d?: number // listed at the going rate, how often a buyer came within a day...
  fill_3d?: number // ...and within 3 days, over the last ``fill_days`` days
  fill_days?: number
  cheap_hour?: number // local hour it's usually cheapest (only for items whose pattern held up)
  dear_hour?: number
  craft_cost?: number // what it costs to craft, for tracked crafts
  per_day: number | null
  listings: number | null
  estimates: Estimate[]
  peers: Peer[]
  reasons: string[]
  history: [day: string, median: number][]
}

/** How the history estimate did on past days (aion2/value.py backtest). */
export interface Model {
  evaluations: number
  items?: number
  horizon_days: number
  error_fair?: number
  error_now?: number
  fair_closer?: number
  buy_signals?: number
  buy_return?: number | null
  buy_win_rate?: number | null
  buy_return_p25?: number | null
  buy_return_asks?: number | null // the same buys, if resold at the median ask instead of what sold
  buy_unsold?: number | null // share of buys with no sale seen over the horizon
  buy_falling_section?: number // buys made while their section's index fell over the week...
  buy_falling_section_return?: number | null // ...and their median return (tracked, not used)
  all_return?: number
  sell_signals?: number // Sells replayed: listed just under the cheapest, against holding 3 days...
  sell_better?: number | null // ...how often that got more
  sell_worse?: number | null // ...and less (the rest it didn't sell: a tie)
  sell_sold?: number | null
  sell_gain_when_sold?: number | null
  home_weight: number
  margin: number
  fee: number
}

export interface Item {
  key: number
  name: string
  category: string | null
  section: string | null
  median: number
  servers: number
  home_price: number | null
  home_ratio: number | null
  cheapest: { server_id: number; price: number }
  dearest: { server_id: number; price: number }
  spread: number
  prices: Record<string, [price: number, listings: number]>
}

/** The home server's economy (aion2/economy.py): one value per day in ``days``, on a fixed basket. */
export interface Economy {
  days: string[]
  basket?: number
  index?: (number | null)[] // what the basket costs, 1.0 on the first day
  sections?: Record<string, (number | null)[]>
  sales?: number[] // inferred sales per day
  spent?: number[] // Kina spent on them per day
  fee_sink?: number[] // Kina the market fee removed per day
  sales_by_hour?: number[] // sales by local hour of day, over the window
  summary?: {
    inflation_week: number | null
    inflation_window: number | null
    spent_per_day: number | null
    spent_growth: number | null // this week's daily spending vs the week before
    sales_per_day: number | null
    sales_growth: number | null
    fee_sink_per_day: number | null
    section_trend: Record<string, number | null>
  }
}

export interface Comparison {
  generated_at: string
  home_id: number
  region: string
  min_servers: number
  min_listings: number
  servers: Server[]
  items: Item[]
  buy: Valuation[]
  model: Model
  economy?: Economy
}

export async function loadComparison(): Promise<Comparison> {
  const res = await fetch(`${import.meta.env.BASE_URL}compare.json`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`compare.json: ${res.status}`)
  return res.json()
}

/** Ask the dev server to fetch fresh prices and rebuild compare.json (`python -m aion2 compare`). */
export async function refreshComparison(): Promise<Comparison> {
  const res = await fetch(`${import.meta.env.BASE_URL}refresh`, { method: 'POST' })
  if (!res.ok) throw new Error((await res.text()) || `refresh: ${res.status}`)
  return loadComparison()
}

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 })
const whole = new Intl.NumberFormat('en', { maximumFractionDigits: 0 })

/** Kina, short: 1.25M, 980K, 450. */
export const kina = (v: number | null | undefined) => (v == null ? '–' : v < 1000 ? whole.format(v) : compact.format(v))
export const count = (v: number) => whole.format(v)

/** A ratio as a signed percentage: 1.153 -> "+15%", 0.94 -> "−6%"; past 3× as a multiple: "36×". */
export function pct(ratio: number | null | undefined, digits = 0) {
  if (ratio == null) return '–'
  if (ratio >= 3) return `${ratio.toFixed(ratio < 10 ? 1 : 0)}×`
  const p = (ratio - 1) * 100
  if (Math.abs(p) < 0.5 / 10 ** digits) return '±0%'
  return `${p > 0 ? '+' : '−'}${Math.abs(p).toFixed(digits)}%`
}

/**
 * Diverging color for a ratio: blue below 1 (cheaper), red above (dearer), gray at par.
 * ``full`` is the log-ratio that reaches the full pole color (default: ±30%).
 */
export function ratioColor(ratio: number | null | undefined, full = Math.log(1.3)) {
  if (ratio == null) return 'transparent'
  const t = Math.max(-1, Math.min(1, Math.log(ratio) / full))
  const pole = t < 0 ? 'var(--cheap)' : 'var(--dear)'
  return `color-mix(in oklab, ${pole} ${Math.round(Math.abs(t) * 100)}%, var(--par))`
}

/** Text that stays readable on ``ratioColor``: white once the fill is strong. */
export const ratioInk = (ratio: number | null | undefined, full = Math.log(1.3)) =>
  ratio != null && Math.abs(Math.log(ratio) / full) > 0.6 ? 'text-white' : 'text-foreground'

export const SECTION_LABELS: Record<string, string> = {
  weapons: 'Weapons',
  armor: 'Armor',
  accessories: 'Accessories',
  consumables: 'Consumables',
  materials: 'Materials',
  skins: 'Skins',
  other: 'Other',
}

export const sectionLabel = (s: string | null) =>
  s ? (SECTION_LABELS[s] ?? s.charAt(0).toUpperCase() + s.slice(1)) : 'Other'

/** Best ratings first: the order the buy list sorts by. */
export const RATING_ORDER: Rating[] = ['Strong buy', 'Buy', 'Sell', 'Fair', 'Wait', 'Overpriced', 'Not listed', 'Unknown']
