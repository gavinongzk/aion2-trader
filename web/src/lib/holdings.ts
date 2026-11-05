import type { Valuation } from '@/lib/data'

/** An item you hold, to sell. Running locally (``npm run dev``) the dev server saves the list in
 *  reports/holdings.json; on the hosted site there's no server, so it stays in this browser. */
export interface Holding {
  key: number
  name: string
  qty: number
  paid?: number | null // per unit, if you remember it
}

const STORAGE_KEY = 'aion2-holdings'

export async function loadHoldings(): Promise<Holding[]> {
  if (!import.meta.env.DEV) {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    } catch {
      return []
    }
  }
  const res = await fetch(`${import.meta.env.BASE_URL}holdings.json`, { cache: 'no-store' })
  return res.ok ? res.json() : []
}

export async function saveHoldings(list: Holding[]): Promise<void> {
  if (!import.meta.env.DEV) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
      return
    } catch {
      throw new Error('this browser blocks local storage')
    }
  }
  const res = await fetch(`${import.meta.env.BASE_URL}holdings.json`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(list),
  })
  if (!res.ok) throw new Error((await res.text()) || `holdings: ${res.status}`)
}

/** What selling one holding is worth now: listed at the resale price, after the market fee. */
export function sale(h: Holding, v: Valuation | undefined, fee: number) {
  const price = v?.list_at ?? v?.fair ?? v?.now ?? null
  const net = price == null ? null : price * (1 - fee)
  return {
    price,
    net,
    total: net == null ? null : net * h.qty,
    profit: net == null || h.paid == null ? null : (net - h.paid) * h.qty,
    roi: net == null || !h.paid ? null : net / h.paid - 1,
  }
}
