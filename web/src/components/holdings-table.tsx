import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'

import { Verdict } from '@/components/verdict'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { kina, pct, type Valuation } from '@/lib/data'
import { loadHoldings, sale, saveHoldings, type Holding } from '@/lib/holdings'
import { cn } from '@/lib/utils'

const share = (x: number | undefined) => (x == null ? '–' : `${Math.round(x * 100)}%`)

/** What you hold and what selling it is worth now: the price to list at, how often a listing there
 *  found a buyer, and the take after the fee. There's no "sell now" signal (none held up in the
 *  backtest), so this is about the price, not the day. */
export function HoldingsTable({
  items,
  fee,
  onSelect,
}: {
  items: Valuation[]
  fee: number
  onSelect: (item: Valuation) => void
}) {
  const [list, setList] = useState<Holding[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [qty, setQty] = useState('1')
  const [paid, setPaid] = useState('')

  useEffect(() => {
    loadHoldings().then(setList, (e: Error) => setError(e.message))
  }, [])

  const byKey = useMemo(() => new Map(items.map((v) => [v.key, v])), [items])
  const byName = useMemo(() => new Map(items.map((v) => [v.name.toLowerCase(), v])), [items])
  const picked = byName.get(name.trim().toLowerCase())

  const update = (next: Holding[]) => {
    setList(next)
    saveHoldings(next).then(() => setError(null), (e: Error) => setError(`Not saved: ${e.message}`))
  }
  const add = () => {
    const n = Math.max(1, Math.round(Number(qty) || 1))
    if (!picked || !list) return
    const price = paid.trim() ? Number(paid.replace(/[,\s]/g, '')) : null
    const existing = list.find((h) => h.key === picked.key)
    update(
      existing
        ? list.map((h) => (h.key === picked.key ? { ...h, qty: h.qty + n, paid: price ?? h.paid } : h))
        : [...list, { key: picked.key, name: picked.name, qty: n, paid: price }],
    )
    setName('')
    setQty('1')
    setPaid('')
  }

  if (!list) return <p className="text-sm text-muted-foreground">{error ?? 'Loading…'}</p>

  const rows = list.map((h) => ({ h, v: byKey.get(h.key), s: sale(h, byKey.get(h.key), fee) }))
  const total = rows.reduce((a, r) => a + (r.s.total ?? 0), 0)
  const profits = rows.filter((r) => r.s.profit != null)
  const profit = profits.reduce((a, r) => a + r.s.profit!, 0)

  return (
    <div className="grid gap-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          add()
        }}
      >
        <label className="grid min-w-56 flex-1 gap-1 text-xs text-muted-foreground">
          Item you hold
          <Input list="holding-items" value={name} onChange={(e) => setName(e.target.value)} placeholder="Start typing a name…" />
          <datalist id="holding-items">
            {items.map((v) => (
              <option key={v.key} value={v.name} />
            ))}
          </datalist>
        </label>
        <label className="grid w-20 gap-1 text-xs text-muted-foreground">
          How many
          <Input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <label className="grid w-36 gap-1 text-xs text-muted-foreground">
          Paid each (optional)
          <Input inputMode="numeric" value={paid} onChange={(e) => setPaid(e.target.value)} placeholder="e.g. 250000" />
        </label>
        <Button type="submit" disabled={!picked}>
          <Plus /> Add
        </Button>
      </form>
      {name && !picked && <p className="text-xs text-muted-foreground">Pick a name from the list.</p>}
      {error && <p className="text-xs text-critical">{error}</p>}

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">List at</TableHead>
              <TableHead className="text-right" title="how often a listing at the going rate sold within 1 and 3 days">Sold in 1d · 3d</TableHead>
              <TableHead className="text-right">You get</TableHead>
              <TableHead className="text-right">Profit</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(({ h, v, s }) => (
              <TableRow key={h.key} className={cn(v && 'cursor-pointer')} onClick={() => v && onSelect(v)}>
                <TableCell className="min-w-56 whitespace-normal">
                  <div className="font-medium">{h.name}</div>
                  {v && <Verdict label={v.label} className="text-xs text-muted-foreground" />}
                  <div className="mt-1 max-w-80 text-xs text-muted-foreground">{note(v, s.price)}</div>
                </TableCell>
                <TableCell className="tabular text-right">{h.qty}</TableCell>
                <TableCell className="tabular text-right font-medium">{kina(s.price)}</TableCell>
                <TableCell className="tabular text-right text-muted-foreground">
                  {v?.fill_3d != null ? `${share(v.fill_1d)} · ${share(v.fill_3d)}` : '–'}
                </TableCell>
                <TableCell className="tabular text-right">
                  <div>{kina(s.total)}</div>
                  {h.qty > 1 && <div className="text-[11px] text-muted-foreground">{kina(s.net)} each</div>}
                </TableCell>
                <TableCell className={cn('tabular text-right', s.profit != null && (s.profit >= 0 ? 'text-good' : 'text-critical'))}>
                  {s.profit == null ? <span className="text-muted-foreground">–</span> : <>
                    <div>{s.profit >= 0 ? '+' : '−'}{kina(Math.abs(s.profit))}</div>
                    <div className="text-[11px]">{pct(1 + s.roi!)}</div>
                  </>}
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${h.name}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      update(list.filter((x) => x.key !== h.key))
                    }}
                  >
                    <Trash2 />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                  Add the items you hold to see what selling them is worth.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
          {rows.length > 0 && (
            <TableFooter>
              <TableRow>
                <TableCell colSpan={4}>All of it, after the {Math.round(fee * 100)}% fee</TableCell>
                <TableCell className="tabular text-right font-semibold">{kina(total)}</TableCell>
                <TableCell className={cn('tabular text-right font-semibold', profits.length && (profit >= 0 ? 'text-good' : 'text-critical'))}>
                  {profits.length ? `${profit >= 0 ? '+' : '−'}${kina(Math.abs(profit))}` : '–'}
                </TableCell>
                <TableCell />
              </TableRow>
            </TableFooter>
          )}
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        List at = what's been selling lately, or the fair value when lower. Sold in 1d · 3d = how often a listing at the going
        rate sold within a day and within 3 days, over the last 2 weeks. Profit counts only the items with a price paid. List in the
        evening (21:00–00:00), when the most sales happen. There's no signal for which day to sell: none beat waiting in the backtest.
      </p>
    </div>
  )
}

/** The one thing worth knowing before you list it. */
function note(v: Valuation | undefined, price: number | null): string {
  if (!v) return 'Not valued now: no recent prices.'
  if (v.label === 'Sell') return `Sell signal: list at ${kina(price)}, just under the cheapest. It's well over fair value now.`
  if (v.now != null && price != null && v.now < price * 0.97)
    return `Someone's listing at ${kina(v.now)} now: match that to sell fast, or list at ${kina(price)} and wait.`
  if (v.craft_cost != null && v.now != null && v.now > v.craft_cost * 1.2)
    return `Crafting it pays (costs ${kina(v.craft_cost)}): more will be made, so the price may drift down.`
  if (v.fill_3d != null && v.fill_3d < 0.5) return 'Sells slowly: expect to wait, or undercut.'
  if (v.label === 'Not listed') return 'Nobody is selling it now: you set the price.'
  return 'Cheapest listing is at or above this: listing here should sell first.'
}
