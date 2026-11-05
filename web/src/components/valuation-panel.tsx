import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'

import { Trend } from '@/components/trend'
import { Verdict } from '@/components/verdict'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import { Tooltip as Tip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { count, kina, pct, type Valuation } from '@/lib/data'
import { cn } from '@/lib/utils'

const config = { median: { label: 'Daily median', color: 'var(--cheap)' } } satisfies ChartConfig

/** The valuation of one item: rating, recommended prices, the estimates behind the fair value,
 *  the similar items used, and 14 days of its price. */
export function ValuationPanel({ v, homeName, fee }: { v: Valuation; homeName: string; fee: number }) {
  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-muted/30 p-4">
        <div>
          <div className="text-xs font-medium text-muted-foreground">
            {v.label === 'Sell' ? `Hold one? On ${homeName} now` : `Buy on ${homeName} now?`}
          </div>
          <Verdict label={v.label} large />
          {v.upside != null && (
            <div className="tabular mt-1 text-xs text-muted-foreground">
              {v.upside >= 0 ? `${pct(1 + v.upside)} to fair value` : `${pct(1 / (1 + v.upside))} over fair value`}
            </div>
          )}
        </div>
        <div className="text-right">
          <div className="text-xs text-muted-foreground">Cheapest now</div>
          <div className="tabular text-2xl font-semibold">{kina(v.now)}</div>
        </div>
      </div>

      {v.fair != null && (
        <div className="grid grid-cols-3 gap-2">
          <Price label="Buy below" value={v.buy_below} note={`${Math.round((v.margin ?? 0) * 100)}% margin of safety`} tone="good" />
          <Price label="Fair value" value={v.fair} note={`80%: ${kina(v.low)}–${kina(v.high)}`} />
          <Price
            label={v.label === 'Sell' ? 'Sell at' : 'Resell at'}
            value={v.list_at}
            note={
              (v.label === 'Sell' ? 'just under the cheapest · ' : v.list_at != null && v.fair != null && v.list_at < v.fair ? 'recent sales · ' : '') +
              (v.resale_roi != null && v.now ? `${pct(1 + v.resale_roi)} after ${Math.round(fee * 100)}% fee` : 'when you own one')
            }
          />
        </div>
      )}

      {v.estimates.length > 0 && v.fair != null && <FootballField v={v} homeName={homeName} />}

      <ul className="grid gap-1.5 text-sm">
        {v.reasons.map((r) => (
          <li key={r} className="flex gap-2">
            <span className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" aria-hidden />
            {r}
          </li>
        ))}
      </ul>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <Fact label="Trend (7 days)" value={<Trend growth={v.growth} />} />
        <Fact label="Sells/day" value={v.per_day == null ? 'unknown' : v.per_day.toFixed(1)} />
        <Fact label="Sold (2 days)" value={<Sold v={v} />} />
        <Fact label="Listings" value={v.listings ?? '–'} />
        {v.fill_3d != null && (
          <Fact
            label="Resale finds a buyer"
            value={
              <span>
                {Math.round(v.fill_1d! * 100)}% <span className="text-muted-foreground">in a day</span> · {Math.round(v.fill_3d * 100)}%{' '}
                <span className="text-muted-foreground">in 3</span>
              </span>
            }
          />
        )}
        {v.craft_cost != null && (
          <Fact
            label="Craft cost"
            value={
              <span>
                {kina(v.craft_cost)}
                {v.now != null && (
                  <span className={cn('ml-1 text-xs', v.now < v.craft_cost * 0.9 ? 'text-good' : 'text-muted-foreground')}>
                    price {pct(v.now / v.craft_cost)}
                  </span>
                )}
              </span>
            }
          />
        )}
        {v.cheap_hour != null && (
          <Fact label="Usually cheapest" value={`${String(v.cheap_hour).padStart(2, '0')}:00`} />
        )}
      </div>

      {v.peers.length > 0 && <Peers v={v} homeName={homeName} />}
      {v.history.length >= 2 && <History v={v} homeName={homeName} />}
    </div>
  )
}

/** Each estimate's 80% range on one price scale, the blend below them, and lines at today's price
 *  and the buy-below price: the banker's "football field". */
function FootballField({ v, homeName }: { v: Valuation; homeName: string }) {
  const rows = [
    ...v.estimates.map((e) => ({
      name: e.source === 'history' ? `${homeName} history` : 'Similar items',
      ...e,
      blend: false,
    })),
    { name: 'Fair value', price: v.fair!, low: v.low!, high: v.high!, weight: 1, blend: true },
  ]
  const marks = [...rows.flatMap((r) => [r.low, r.high]), v.now ?? v.fair!, v.buy_below!]
  // a peer range can be enormous: keep the scale within 4× of the fair value either way
  const lo = Math.max(Math.min(...marks), v.fair! / 4) * 0.92
  const hi = Math.min(Math.max(...marks), v.fair! * 4) * 1.06
  const at = (x: number) => `${Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100))}%`

  return (
    <div className="grid gap-1.5">
      <div className="text-xs font-medium text-muted-foreground">Where the fair value comes from (80% ranges)</div>
      <div className="relative grid gap-2 pt-5 pb-5">
        {v.now != null && <Marker x={at(v.now)} label={`now ${kina(v.now)}`} className="border-foreground" strong />}
        <Marker x={at(v.buy_below!)} label={`buy < ${kina(v.buy_below)}`} className="border-good border-dashed" below />
        {rows.map((r) => (
          <div key={r.name} className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-2 text-xs">
            <span className={cn('truncate', r.blend ? 'font-semibold text-foreground' : 'text-muted-foreground')}>{r.name}</span>
            <Tip>
              <TooltipTrigger asChild>
                <div className="relative h-5">
                  <div
                    className={cn('absolute top-1 h-3 rounded-[4px]', r.blend ? 'bg-foreground/80' : 'bg-muted-foreground/35')}
                    style={{ left: at(r.low), width: `calc(${at(r.high)} - ${at(r.low)})`, minWidth: 4 }}
                  />
                  <div
                    className={cn('absolute top-0 h-5 w-[3px] -translate-x-1/2 rounded-full', r.blend ? 'bg-background ring-1 ring-foreground' : 'bg-foreground')}
                    style={{ left: at(r.price) }}
                  />
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {r.name}: {kina(r.price)} (80% range {kina(r.low)}–{kina(r.high)})
              </TooltipContent>
            </Tip>
            <span className="tabular text-right text-muted-foreground">{r.blend ? '' : `${Math.round(r.weight * 100)}%`}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-[7.5rem_1fr_2.5rem] gap-2 text-[10px] text-muted-foreground">
        <span />
        <div className="tabular flex justify-between">
          <span>{kina(lo)}</span>
          <span>{kina(hi)}</span>
        </div>
        <span className="text-right">weight</span>
      </div>
    </div>
  )
}

function Marker({ x, label, className, strong, below }: { x: string; label: string; className?: string; strong?: boolean; below?: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-y-0 ml-[calc(7.5rem+0.5rem)] w-[calc(100%-7.5rem-2.5rem-1rem)]">
      <div className={cn('absolute inset-y-0 border-l', className)} style={{ left: x }}>
        <span
          className={cn(
            'tabular absolute -translate-x-1/2 text-[10px] whitespace-nowrap',
            below ? '-bottom-4' : 'top-0',
            strong ? 'font-semibold text-foreground' : 'text-muted-foreground',
          )}
        >
          {label}
        </span>
      </div>
    </div>
  )
}

function Peers({ v, homeName }: { v: Valuation; homeName: string }) {
  return (
    <div className="grid gap-1.5">
      <div className="text-xs font-medium text-muted-foreground">
        Similar items: their price on {homeName} × this item's usual ratio to them on other servers
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="py-1.5 text-left font-medium">Item</th>
            <th className="py-1.5 text-right font-medium">On {homeName}</th>
            <th className="py-1.5 text-right font-medium">Ratio</th>
            <th className="py-1.5 text-right font-medium">Implies</th>
            <th className="py-1.5 text-right font-medium">Weight</th>
          </tr>
        </thead>
        <tbody>
          {v.peers.map((p) => (
            <tr key={p.key} className="border-b last:border-0">
              <td className="py-1.5">{p.name}</td>
              <td className="tabular py-1.5 text-right text-muted-foreground">{kina(p.home_level)}</td>
              <td className="tabular py-1.5 text-right" title={`median over ${p.servers} servers, varies ±${Math.round(p.spread * 100)}%`}>
                {p.ratio.toFixed(2)}×
              </td>
              <td className="tabular py-1.5 text-right font-medium">{kina(p.implied)}</td>
              <td className="tabular py-1.5 text-right text-muted-foreground">{Math.round(p.weight * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function History({ v, homeName }: { v: Valuation; homeName: string }) {
  const data = v.history.map(([day, median]) => ({ day, median }))
  const marks = [v.now, v.low, v.high, ...data.map((d) => d.median)].filter((x): x is number => x != null)
  // keep one absurd day from flattening the chart: cap the axis at 3× the fair value
  const ceiling = Math.min(Math.max(...marks), (v.fair ?? Math.max(...marks)) * 3)
  const label = (value: string, strong = false) => ({
    value,
    position: 'right' as const,
    fontSize: 10,
    fontWeight: strong ? 600 : 400,
    fill: strong ? 'var(--foreground)' : 'var(--muted-foreground)',
  })
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted-foreground">{homeName}, daily median over 14 days</div>
      <ChartContainer config={config} className="aspect-auto h-44 w-full">
        <LineChart data={data} margin={{ left: 0, right: 72, top: 8, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="day"
            tickLine={false}
            axisLine={false}
            minTickGap={24}
            tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
          />
          <YAxis domain={[0, ceiling]} allowDataOverflow width={48} tickLine={false} axisLine={false} tickFormatter={(x: number) => kina(x)} className="tabular" />
          {v.low != null && v.high != null && (
            <ReferenceArea y1={v.low} y2={Math.min(v.high, ceiling)} fill="var(--muted-foreground)" fillOpacity={0.1} label={{ ...label('fair range'), position: 'insideTopLeft' }} />
          )}
          {v.buy_below != null && <ReferenceLine y={v.buy_below} stroke="var(--good)" strokeDasharray="4 3" label={label(`buy < ${kina(v.buy_below)}`)} />}
          {v.now != null && <ReferenceLine y={Math.min(v.now, ceiling)} stroke="var(--foreground)" label={label(`now ${kina(v.now)}`, true)} />}
          <Tooltip
            cursor={{ stroke: 'var(--muted-foreground)', strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const p = payload[0].payload as { day: string; median: number }
              return (
                <div className="rounded-lg border bg-background px-3 py-2 text-xs shadow-xl">
                  <div className="text-muted-foreground">{new Date(p.day).toLocaleDateString(undefined, { dateStyle: 'medium' })}</div>
                  <div className="tabular font-medium">{count(p.median)} Kina</div>
                </div>
              )
            }}
          />
          <Line dataKey="median" stroke="var(--color-median)" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--background)' }} />
        </LineChart>
      </ChartContainer>
    </div>
  )
}

function Price({ label, value, note, tone }: { label: string; value?: number; note: string; tone?: 'good' }) {
  return (
    <div className={cn('rounded-lg border p-3', tone === 'good' && 'border-good/40 bg-good/5')}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tabular text-lg font-semibold">{kina(value)}</div>
      <div className="text-[11px] text-muted-foreground">{note}</div>
    </div>
  )
}

/** Sales seen in the history estimate's window, at what price, and asks that expired unsold. */
function Sold({ v }: { v: Valuation }) {
  const h = v.estimates.find((e) => e.source === 'history')
  if (!h || h.basis == null || h.basis === 'asks') return <span className="text-muted-foreground">unknown</span>
  if (!h.sales) return <span className="text-warning">none seen</span>
  return (
    <span>
      {h.sales}
      {h.sold_at != null && <span className="text-muted-foreground"> · ~{kina(h.sold_at)}</span>}
      {!!h.expired && <span className="text-muted-foreground"> · {h.expired} expired</span>}
    </span>
  )
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tabular font-medium">{value}</div>
    </div>
  )
}
