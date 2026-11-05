import { Bar, BarChart, Cell, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'

import { ValuationPanel } from '@/components/valuation-panel'
import { Badge } from '@/components/ui/badge'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { count, kina, pct, ratioColor, ratioInk, sectionLabel, type Item, type Server, type Valuation } from '@/lib/data'
import { cn } from '@/lib/utils'

const config = { price: { label: 'Cheapest price' } } satisfies ChartConfig

interface Row {
  id: number
  name: string
  faction: string
  price: number
  listings: number
  ratio: number
  home: boolean
}

/** One item: its valuation on the home server, then its price on every comparable server. */
export function ItemDetail({
  valuation,
  item,
  servers,
  homeId,
  fee,
  onClose,
}: {
  valuation: Valuation | null
  item?: Item
  servers: Map<number, Server>
  homeId: number
  fee: number
  onClose: () => void
}) {
  const homeName = servers.get(homeId)?.name ?? 'your server'
  const rows: Row[] = item
    ? Object.entries(item.prices)
        .map(([id, [price, listings]]) => {
          const s = servers.get(Number(id))
          return {
            id: Number(id),
            name: s?.name ?? id,
            faction: s?.faction ?? '',
            price,
            listings,
            ratio: price / item.median,
            home: Number(id) === homeId,
          }
        })
        .sort((a, b) => a.price - b.price)
    : []
  // a log scale would hide the gap people care about; cap the axis so one absurd price doesn't flatten the rest
  const cap = item ? Math.min(Math.max(...rows.map((r) => r.price)), item.median * 4) : 0

  return (
    <Sheet open={valuation != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {valuation && (
          <>
            <SheetHeader>
              <SheetTitle className="text-xl">{valuation.name}</SheetTitle>
              <SheetDescription>{valuation.category ?? sectionLabel(valuation.section)}</SheetDescription>
            </SheetHeader>
            <div className="px-4">
              <ValuationPanel v={valuation} homeName={homeName} fee={fee} />
            </div>
          </>
        )}
        {valuation && item && (
          <>
            <div className="grid gap-1 px-4 pt-4">
              <h3 className="text-sm font-semibold">On other servers, for reference</h3>
              <p className="text-xs text-muted-foreground">
                Each server is its own economy, so these prices don't set {homeName}'s fair value directly: only the
                ratios between similar items do. Median <span className="tabular">{kina(item.median)}</span> over{' '}
                {item.servers} servers; they usually differ {item.spread.toFixed(1)}× (p90 ÷ p10).
              </p>
            </div>

            <div className="px-4">
              <ChartContainer config={config} className="aspect-auto w-full" style={{ height: rows.length * 24 + 32 }}>
                <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 8, top: 4, bottom: 4 }} barCategoryGap={2}>
                  <XAxis
                    type="number"
                    dataKey="price"
                    domain={[0, cap]}
                    allowDataOverflow
                    tickFormatter={(v: number) => kina(v)}
                    tickLine={false}
                    axisLine={false}
                    className="tabular"
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={96}
                    interval={0}
                    tickLine={false}
                    axisLine={false}
                    tick={({ x, y, payload }) => {
                      const isHome = rows.find((r) => r.name === payload.value)?.home
                      return (
                        <text x={x} y={y} dy={4} textAnchor="end" fontSize={12} className={isHome ? 'fill-foreground font-semibold' : 'fill-muted-foreground'}>
                          {payload.value}
                          {isHome && ' ★'}
                        </text>
                      )
                    }}
                  />
                  <ReferenceLine
                    x={item.median}
                    stroke="var(--foreground)"
                    strokeDasharray="3 3"
                    label={{ value: 'median', position: 'top', fontSize: 10, fill: 'var(--muted-foreground)' }}
                  />
                  <Tooltip
                    cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null
                      const r = payload[0].payload as Row
                      return (
                        <div className="grid gap-1 rounded-lg border bg-background px-3 py-2 text-xs shadow-xl">
                          <div className="font-medium">
                            {r.name} <span className="text-muted-foreground">· {r.faction}</span>
                          </div>
                          <div className="tabular">{count(r.price)} Kina</div>
                          <div className="text-muted-foreground">
                            {pct(r.ratio, 1)} vs median · {r.listings} listings
                          </div>
                        </div>
                      )
                    }}
                  />
                  <Bar dataKey="price" radius={4}>
                    {rows.map((r) => (
                      <Cell
                        key={r.id}
                        fill={ratioColor(r.ratio)}
                        stroke={r.home ? 'var(--foreground)' : 'none'}
                        strokeWidth={r.home ? 1.5 : 0}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ChartContainer>
            </div>

            <div className="px-4 pb-6">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 text-left font-medium">Server</th>
                    <th className="py-2 text-right font-medium">Price</th>
                    <th className="py-2 text-right font-medium">vs median</th>
                    <th className="py-2 text-right font-medium">Listings</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className={cn('border-b last:border-0', r.home && 'font-semibold')}>
                      <td className="py-1.5">
                        {r.name}
                        {r.home && ' ★'}{' '}
                        <span className="text-xs font-normal text-muted-foreground">{r.faction}</span>
                      </td>
                      <td className="tabular py-1.5 text-right">{count(r.price)}</td>
                      <td className="py-1.5 text-right">
                        <Badge variant="outline" className={cn('tabular border-0', ratioInk(r.ratio))} style={{ background: ratioColor(r.ratio) }}>
                          {pct(r.ratio)}
                        </Badge>
                      </td>
                      <td className="tabular py-1.5 text-right text-muted-foreground">{r.listings}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
