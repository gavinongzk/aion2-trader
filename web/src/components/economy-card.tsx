import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { count, kina, pct, sectionLabel, type Economy, type Model } from '@/lib/data'
import { cn } from '@/lib/utils'

const indexConfig = {
  market: { label: 'All items', color: 'var(--foreground)' },
  section: { label: 'Section', color: 'var(--cheap)' },
} satisfies ChartConfig
const spentConfig = { spent: { label: 'Kina spent', color: 'var(--cheap)' } } satisfies ChartConfig

const day = (d: string) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
const signed = (x: number | null | undefined, digits = 0) => (x == null ? '–' : pct(1 + x, digits))

/** What the server's money is doing: the price level, Kina spent on the market, and each section's
 *  price level against the whole market. Context for the valuations, not a signal (see economy.py). */
export function EconomyCard({ econ, homeName, fee, model }: { econ: Economy; homeName: string; fee: number; model?: Model }) {
  const s = econ.summary
  const sections = Object.keys(econ.sections ?? {}).sort(
    (a, b) => (s?.section_trend[b] ?? -9) - (s?.section_trend[a] ?? -9),
  )
  const [picked, setPicked] = useState(sections[0])
  if (!s || !econ.index || econ.days.length < 2) return null

  const rows = econ.days.map((d, i) => ({
    day: d,
    market: econ.index![i],
    section: picked ? econ.sections![picked][i] : null,
    spent: econ.spent![i],
    sales: econ.sales![i],
  }))

  const levels = rows.flatMap((r) => [r.market, r.section]).filter((x): x is number => x != null && x > 0)
  const domain = [Math.min(...levels) * 0.95, Math.max(...levels) * 1.05]

  return (
    <Card>
      <CardHeader>
        <CardTitle>{homeName}'s economy</CardTitle>
        <CardDescription>
          The money supply itself can't be seen: the API has no Kina balances. What can be seen is the Kina changing hands
          on the market (from the sales inferred from listings) and what the same {econ.basket} items cost each day. Spending
          growing faster than prices means more Kina circulating.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Prices this week" value={signed(s.inflation_week)} note={`${signed(s.inflation_window)} over ${econ.days.length} days`} />
          <Stat
            label="Kina spent / day"
            value={kina(s.spent_per_day)}
            note={`${signed(s.spent_growth)} vs the week before`}
          />
          <Stat label="Sales / day" value={s.sales_per_day == null ? '–' : count(s.sales_per_day)} note={`${signed(s.sales_growth)} vs the week before`} />
          <Stat
            label="Fee sink / day"
            value={kina(s.fee_sink_per_day)}
            note={`Kina the ${Math.round(fee * 100)}% market fee removes`}
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div className="grid content-start gap-3">
            <div className="text-sm font-medium">Price level by section, against all items</div>
            <ToggleGroup type="single" size="sm" variant="outline" value={picked} onValueChange={(v) => v && setPicked(v)} className="flex-wrap justify-start">
              {sections.map((k) => (
                <ToggleGroupItem key={k} value={k}>
                  {sectionLabel(k)}
                  <span className={cn('tabular text-xs', (s.section_trend[k] ?? 0) >= 0 ? 'text-dear' : 'text-cheap')}>
                    {signed(s.section_trend[k])}
                  </span>
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <ChartContainer config={indexConfig} className="aspect-auto h-56 w-full">
              <LineChart data={rows} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="day" tickLine={false} axisLine={false} minTickGap={28} tickFormatter={day} />
                <YAxis width={44} tickLine={false} axisLine={false} scale="log" domain={domain} allowDataOverflow tickFormatter={(x: number) => pct(x)} className="tabular" />
                <ReferenceLine y={1} stroke="var(--muted-foreground)" strokeDasharray="3 3" />
                <Tooltip
                  cursor={{ stroke: 'var(--muted-foreground)', strokeDasharray: '3 3' }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const r = payload[0].payload as (typeof rows)[number]
                    return (
                      <div className="grid gap-1 rounded-lg border bg-background px-3 py-2 text-xs shadow-xl">
                        <div className="text-muted-foreground">{day(r.day)}</div>
                        <Legend color="var(--foreground)" label="All items" value={pct(r.market)} />
                        {picked && <Legend color="var(--cheap)" label={sectionLabel(picked)} value={pct(r.section)} />}
                      </div>
                    )
                  }}
                />
                <Line dataKey="market" stroke="var(--color-market)" strokeWidth={2} dot={false} connectNulls />
                <Line dataKey="section" stroke="var(--color-section)" strokeWidth={2} dot={false} connectNulls />
              </LineChart>
            </ChartContainer>
            <div className="flex gap-4 text-xs text-muted-foreground">
              <Legend color="var(--foreground)" label="All items" />
              {picked && <Legend color="var(--cheap)" label={sectionLabel(picked)} />}
              <span>vs the first day</span>
            </div>
          </div>

          <div className="grid content-start gap-3">
            <div className="text-sm font-medium">Kina spent on the market per day</div>
            <ChartContainer config={spentConfig} className="aspect-auto h-56 w-full lg:mt-10">
              <BarChart data={rows} margin={{ left: 0, right: 8, top: 8, bottom: 0 }} barCategoryGap={2}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="day" tickLine={false} axisLine={false} minTickGap={28} tickFormatter={day} />
                <YAxis width={44} tickLine={false} axisLine={false} tickFormatter={(x: number) => kina(x)} className="tabular" />
                <Tooltip
                  cursor={{ fill: 'var(--muted)', opacity: 0.5 }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null
                    const r = payload[0].payload as (typeof rows)[number]
                    return (
                      <div className="grid gap-0.5 rounded-lg border bg-background px-3 py-2 text-xs shadow-xl">
                        <div className="text-muted-foreground">{day(r.day)}</div>
                        <div className="tabular font-medium">{kina(r.spent)} Kina</div>
                        <div className="tabular text-muted-foreground">{count(r.sales)} sales · {kina(r.spent * fee)} to the fee</div>
                      </div>
                    )
                  }}
                />
                <Bar dataKey="spent" fill="var(--color-spent)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ChartContainer>
            <p className="text-xs text-muted-foreground">
              A lower bound: only sales of the cheapest listing are seen, and only for items priced on most days.
            </p>
            {econ.sales_by_hour && <SalesByHour hours={econ.sales_by_hour} />}
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Context, not a signal yet. In the backtest, buys made while their section was falling that week did worse
          {model?.buy_falling_section_return != null && ` (${signed(model.buy_falling_section_return, 1)} median, ${model.buy_falling_section} buys)`},
          but too few to change the ratings on. Each buy call logs its section's trend, so the scorecard will show whether
          it holds up.
        </p>
      </CardContent>
    </Card>
  )
}

/** When buyers are about: the share of sales in each local hour. List in the busy hours. */
function SalesByHour({ hours }: { hours: number[] }) {
  const total = hours.reduce((a, b) => a + b, 0)
  if (!total) return null
  const rows = hours.map((n, h) => ({ hour: `${String(h).padStart(2, '0')}:00`, share: n / total }))
  const busiest = [...rows].sort((a, b) => b.share - a.share).slice(0, 3).map((r) => r.hour).sort()
  const quiet = Math.min(...rows.map((r) => r.share))
  const peak = Math.max(...rows.map((r) => r.share))
  return (
    <div className="grid gap-2 pt-2">
      <div className="text-sm font-medium">When things sell</div>
      <p className="text-xs text-muted-foreground">
        Busiest around {busiest.join(', ')}: about {(peak / quiet).toFixed(1)}× the sales of the quietest hour. List then, when
        buyers are about. (Asks don't get cheaper at any hour across the market: that didn't hold from one week to the next.)
      </p>
      <ChartContainer config={{ share: { label: 'Share of sales', color: 'var(--cheap)' } }} className="aspect-auto h-28 w-full">
        <BarChart data={rows} margin={{ left: 14, right: 14, top: 4, bottom: 0 }} barCategoryGap={1}>
          <XAxis dataKey="hour" tickLine={false} axisLine={false} interval={5} />
          <YAxis hide domain={[0, 'dataMax']} />
          <Tooltip
            cursor={{ fill: 'var(--muted)', opacity: 0.5 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const r = payload[0].payload as (typeof rows)[number]
              return (
                <div className="rounded-lg border bg-background px-3 py-2 text-xs shadow-xl">
                  <span className="text-muted-foreground">{r.hour}</span> <span className="tabular font-medium">{(r.share * 100).toFixed(1)}% of sales</span>
                </div>
              )
            }}
          />
          <Bar dataKey="share" fill="var(--color-share)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartContainer>
    </div>
  )
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tabular text-xl font-semibold">{value}</div>
      <div className="text-[11px] text-muted-foreground">{note}</div>
    </div>
  )
}

function Legend({ color, label, value }: { color: string; label: string; value?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-0.5 w-3 rounded-full" style={{ background: color }} aria-hidden />
      {label}
      {value && <span className="tabular ml-auto pl-3 font-medium text-foreground">{value}</span>}
    </span>
  )
}
