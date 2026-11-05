import { useEffect, useMemo, useState } from 'react'
import { CircleCheck, Clock, FlaskConical, RefreshCw, Scale } from 'lucide-react'

import { EconomyCard } from '@/components/economy-card'
import { HoldingsTable } from '@/components/holdings-table'
import { ItemDetail } from '@/components/item-detail'
import { ItemsTable } from '@/components/items-table'
import { ModelCard } from '@/components/model-card'
import { SectionHeatmap } from '@/components/section-heatmap'
import { ServerIndexChart, type Basis } from '@/components/server-index-chart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { TooltipProvider } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { count, loadComparison, pct, refreshComparison, type Comparison, type Valuation } from '@/lib/data'
import { countRatings, type RatingFilter } from '@/lib/ratings'

type FactionFilter = 'all' | 'Elyos' | 'Asmodian'

export default function App() {
  const [data, setData] = useState<Comparison | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [faction, setFaction] = useState<FactionFilter>('all')
  const [basis, setBasis] = useState<Basis>('region')
  const [selected, setSelected] = useState<Valuation | null>(null)
  const [rating, setRating] = useState<RatingFilter>('buy')
  const [view, setView] = useState<'buy' | 'sell'>('buy')

  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  useEffect(() => {
    loadComparison().then(setData, (e: Error) => setError(e.message))
  }, [])

  const refresh = () => {
    setRefreshing(true)
    setRefreshError(null)
    refreshComparison()
      .then((d) => {
        setData(d)
        setError(null)
        // keep the open item, with its fresh valuation
        setSelected((s) => (s ? (d.buy.find((v) => v.key === s.key) ?? null) : null))
      }, (e: Error) => setRefreshError(e.message))
      .finally(() => setRefreshing(false))
  }

  const byId = useMemo(() => new Map(data?.servers.map((s) => [s.id, s]) ?? []), [data])
  const servers = useMemo(
    () => (data?.servers ?? []).filter((s) => faction === 'all' || s.faction === faction || s.id === data?.home_id),
    [data, faction],
  )
  const counts = useMemo(() => countRatings(data?.buy ?? []), [data])
  const compared = useMemo(() => new Map(data?.items.map((i) => [i.key, i]) ?? []), [data])

  if (error) return <Message title="No comparison data yet" body={<>Run <code className="rounded bg-muted px-1.5 py-0.5">python -m aion2 compare</code> to write reports/compare.json, then reload. ({error})</>} />
  if (!data) return <Message title="Loading…" />

  const home = byId.get(data.home_id)!
  const ranked = [...data.servers].filter((s) => s.index != null).sort((a, b) => a.index! - b.index!)
  const homeRank = ranked.findIndex((s) => s.id === home.id) + 1
  const updated = new Date(data.generated_at)
  const m = data.model

  return (
    <TooltipProvider delayDuration={100}>
      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-8 sm:px-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-muted-foreground">Aion 2 · {data.region}</p>
            <h1 className="text-3xl font-semibold tracking-tight">What's worth buying on {home.name}</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              A fair value for every item, built from {home.name}'s own prices and, where it helps, how the item is priced
              against similar items on the other {data.servers.length - 1} {data.region} servers. Buy below the buy price;
              the backtest below shows how that has done.
            </p>
          </div>
          <div className="grid justify-items-start gap-2 lg:justify-items-end">
            {/* the hosted site is rebuilt every hour; only the local dev server can run a refresh */}
            {import.meta.env.DEV ? (
              <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
                <RefreshCw className={cn(refreshing && 'animate-spin')} />
                {refreshing ? 'Fetching prices…' : 'Refresh'}
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">Updates every hour</span>
            )}
            <div className="text-xs text-muted-foreground">
              Updated {updated.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })} · {count(data.buy.length)} items valued
            </div>
            {refreshError && <div className="max-w-xs text-xs text-critical lg:text-right">Refresh failed: {refreshError}</div>}
          </div>
        </header>

        <section className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          <Kpi
            icon={<CircleCheck className="size-4" />}
            label="Buy now"
            value={`${counts.buy} items`}
            note="listed below their buy price"
            tone="good"
            onClick={() => setRating('buy')}
          />
          <Kpi
            icon={<Clock className="size-4" />}
            label="Wait"
            value={`${counts.wait} items`}
            note="cheap, but still falling"
            tone="warn"
            onClick={() => setRating('wait')}
          />
          <Kpi
            icon={<FlaskConical className="size-4" />}
            label="Past buy signals"
            value={m.buy_return != null ? pct(1 + m.buy_return, 1) : '–'}
            note={
              m.buy_return != null
                ? `median ${m.horizon_days}-day return after fee · ${Math.round((m.buy_win_rate ?? 0) * 100)}% won · ${m.buy_signals} signals`
                : 'not enough history yet'
            }
            tone="good"
          />
          <Kpi
            icon={<Scale className="size-4" />}
            label={`${home.name} price level`}
            value={pct(home.index, 1)}
            note={`vs a typical ${data.region} server · #${homeRank} of ${ranked.length}`}
            tone={home.index! > 1 ? 'dear' : 'cheap'}
          />
        </section>

        <Card>
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
            <div className="grid gap-1.5">
              <CardTitle>{view === 'buy' ? 'Valuations' : 'Your items: what selling them is worth'}</CardTitle>
              <CardDescription>
                {view === 'buy'
                  ? 'Best ratings first, then the most upside. Click an item for its fair value breakdown, the similar items behind it, and its 14-day price.'
                  : 'Add what you hold: the price to list each at, how quickly it tends to sell, and what you get after the fee.'}
              </CardDescription>
            </div>
            <ToggleGroup type="single" variant="outline" value={view} onValueChange={(v) => v && setView(v as 'buy' | 'sell')}>
              <ToggleGroupItem value="buy">Market</ToggleGroupItem>
              <ToggleGroupItem value="sell">My items</ToggleGroupItem>
            </ToggleGroup>
          </CardHeader>
          <CardContent>
            {view === 'buy' ? (
              <ItemsTable items={data.buy} homeName={home.name} filter={rating} onFilter={setRating} counts={counts} onSelect={setSelected} />
            ) : (
              <HoldingsTable items={data.buy} fee={m.fee} onSelect={setSelected} />
            )}
          </CardContent>
        </Card>

        <ModelCard model={m} homeName={home.name} />

        {data.economy && <EconomyCard econ={data.economy} homeName={home.name} fee={m.fee} model={m} />}

        <div className="mt-4 grid gap-1">
          <h2 className="text-xl font-semibold tracking-tight">How {home.name} compares</h2>
          <p className="text-sm text-muted-foreground">
            Context, not a price signal: each server is its own economy. 1.00 is a typical server; blue is cheaper, red is dearer.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup type="single" variant="outline" value={faction} onValueChange={(v) => v && setFaction(v as FactionFilter)}>
            <ToggleGroupItem value="all">All servers</ToggleGroupItem>
            <ToggleGroupItem value="Elyos">Elyos</ToggleGroupItem>
            <ToggleGroupItem value="Asmodian">Asmodian</ToggleGroupItem>
          </ToggleGroup>
          <span className="text-xs text-muted-foreground">{home.name} ★ always shown</span>
        </div>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-2">
              <div>
                <CardTitle>Price index</CardTitle>
                <CardDescription>{basis === 'region' ? 'vs a typical server in the region' : `vs ${home.name}, on items both list`}</CardDescription>
              </div>
              <ToggleGroup type="single" size="sm" variant="outline" value={basis} onValueChange={(v) => v && setBasis(v as Basis)}>
                <ToggleGroupItem value="region">Region</ToggleGroupItem>
                <ToggleGroupItem value="home">{home.name}</ToggleGroupItem>
              </ToggleGroup>
            </CardHeader>
            <CardContent>
              <ServerIndexChart servers={servers} homeId={home.id} basis={basis} homeName={home.name} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>By section</CardTitle>
              <CardDescription>Where each server is cheap or dear: a server can be cheap for gear and dear for materials</CardDescription>
            </CardHeader>
            <CardContent>
              <SectionHeatmap servers={servers} homeId={home.id} />
            </CardContent>
          </Card>
        </section>

        <footer className="pb-4 text-xs text-muted-foreground">
          Data from the public aion2.exchange API. Prices move hourly; check in game before you act.
        </footer>
      </div>
      <ItemDetail
        valuation={selected}
        item={selected ? compared.get(selected.key) : undefined}
        servers={byId}
        homeId={home.id}
        fee={m.fee}
        onClose={() => setSelected(null)}
      />
    </TooltipProvider>
  )
}

const TONES = { cheap: 'text-cheap', dear: 'text-dear', good: 'text-good', warn: 'text-warning' }

function Kpi({
  icon,
  label,
  value,
  note,
  tone,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  value: string
  note: string
  tone?: keyof typeof TONES
  onClick?: () => void
}) {
  return (
    <Card
      className={cn('gap-1 py-4', onClick && 'cursor-pointer transition-colors hover:bg-muted/50')}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
    >
      <CardContent className="grid gap-1 px-4">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span className={tone && TONES[tone]}>{icon}</span>
          {label}
        </div>
        <div className="truncate text-xl font-semibold tracking-tight sm:text-2xl">{value}</div>
        <div className="text-xs text-muted-foreground">{note}</div>
      </CardContent>
    </Card>
  )
}

function Message({ title, body }: { title: string; body?: React.ReactNode }) {
  return (
    <div className="mx-auto grid min-h-svh max-w-lg place-content-center gap-2 px-4 text-center">
      <h1 className="text-xl font-semibold">{title}</h1>
      {body && <p className="text-sm text-muted-foreground">{body}</p>}
    </div>
  )
}
