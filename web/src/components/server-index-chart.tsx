import { Bar, BarChart, Cell, LabelList, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts'

import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import { count, pct, type Server } from '@/lib/data'

export type Basis = 'region' | 'home'

const config = { delta: { label: 'vs typical' } } satisfies ChartConfig

interface Row {
  server: Server
  name: string
  ratio: number
  delta: number // percent away from 1.0, the bar length
  home: boolean
}

/** Diverging bars from par (0%): how much dearer or cheaper each server is, cheapest at the top. */
export function ServerIndexChart({
  servers,
  homeId,
  basis,
  homeName,
}: {
  servers: Server[]
  homeId: number
  basis: Basis
  homeName: string
}) {
  const rows: Row[] = servers
    .map((s) => ({ s, ratio: basis === 'home' ? s.vs_home : s.index }))
    .filter((r): r is { s: Server; ratio: number } => r.ratio != null)
    .sort((a, b) => a.ratio - b.ratio)
    .map(({ s, ratio }) => ({
      server: s,
      name: s.id === homeId ? `${s.name} ★` : s.name,
      ratio,
      delta: (ratio - 1) * 100,
      home: s.id === homeId,
    }))

  // symmetric, so par sits in the middle, with room for the value labels past each bar
  const reach = Math.ceil((Math.max(10, ...rows.map((r) => Math.abs(r.delta))) * 1.25) / 5) * 5
  const domain = [-reach, reach]

  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: rows.length * 26 + 40 }}>
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 12, top: 4, bottom: 4 }} barCategoryGap={2}>
        <XAxis
          type="number"
          dataKey="delta"
          domain={domain}
          tickFormatter={(v: number) => (v === 0 ? 'par' : `${v > 0 ? '+' : ''}${v}%`)}
          tickLine={false}
          axisLine={false}
          className="tabular"
        />
        <YAxis
          type="category"
          dataKey="name"
          width={104}
          tickLine={false}
          axisLine={false}
          interval={0}
          tick={({ x, y, payload }) => {
            const home = rows.find((r) => r.name === payload.value)?.home
            return (
              <text x={x} y={y} dy={4} textAnchor="end" fontSize={12} className={home ? 'fill-foreground font-semibold' : 'fill-muted-foreground'}>
                {payload.value}
              </text>
            )
          }}
        />
        <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
        <Tooltip
          cursor={{ fill: 'var(--muted)', opacity: 0.6 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const r = payload[0].payload as Row
            return (
              <div className="grid min-w-48 gap-1.5 rounded-lg border bg-background px-3 py-2 text-xs shadow-xl">
                <div className="font-medium">
                  {r.server.name} <span className="text-muted-foreground">· {r.server.faction}</span>
                </div>
                <Line label={basis === 'home' ? `vs ${homeName}` : 'vs region'} value={pct(r.ratio, 1)} />
                {basis === 'home' && <Line label="vs region" value={pct(r.server.index, 1)} />}
                <Line label="Items compared" value={count(r.server.basket)} />
                <Line label="Cheapest server for" value={`${r.server.cheapest_count} items`} />
                <Line label="Listings" value={count(r.server.listings)} />
              </div>
            )
          }}
        />
        <Bar dataKey="delta" radius={4} minPointSize={2}>
          {rows.map((r) => (
            <Cell
              key={r.server.id}
              fill={r.delta < 0 ? 'var(--cheap)' : 'var(--dear)'}
              fillOpacity={r.home ? 1 : 0.78}
              stroke={r.home ? 'var(--foreground)' : 'none'}
              strokeWidth={r.home ? 1.5 : 0}
            />
          ))}
          <LabelList
            dataKey="ratio"
            content={({ x, y, width, height, value }) => {
              // label past the bar's far end: left of a cheaper bar, right of a dearer one
              const [x0, w, y0, h, ratio] = [Number(x), Number(width), Number(y), Number(height), Number(value)]
              const left = Math.min(x0, x0 + w)
              const right = Math.max(x0, x0 + w)
              const cheaper = ratio < 1
              return (
                <text
                  x={cheaper ? left - 6 : right + 6}
                  y={y0 + h / 2}
                  dy={4}
                  textAnchor={cheaper ? 'end' : 'start'}
                  fontSize={11}
                  className="tabular fill-muted-foreground"
                >
                  {pct(ratio)}
                </text>
              )
            }}
          />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular font-medium">{value}</span>
    </div>
  )
}
