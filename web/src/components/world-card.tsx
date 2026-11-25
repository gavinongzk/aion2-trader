import { Verdict } from '@/components/verdict'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { kina, pct, type Model, type Valuation } from '@/lib/data'
import { cn } from '@/lib/utils'

const share = (x: number | null | undefined) => (x == null ? '–' : `${Math.round(x * 100)}%`)
const DEAR = 1.15
const RANK_SERVERS = 8 // the lists rank items on this many other servers: on fewer, the world price is a few listings

/** The world server: the same item here against the other servers. A merged market should pull
 *  prices together, so cheaper here is the time to buy and dearer here the time to sell. */
export function WorldCard({
  items,
  homeName,
  fee,
  model: m,
  onSelect,
}: {
  items: Valuation[]
  homeName: string
  fee: number
  model: Model
  onSelect: (item: Valuation) => void
}) {
  const priced = items.filter((v) => v.world_gap != null && v.now != null)
  const cheaper = priced
    .filter((v) => v.world_upside != null && v.world_upside > 0)
    .sort((a, b) => b.world_upside! - a.world_upside!)
  const dearer = priced.filter((v) => v.world_gap! >= DEAR).sort((a, b) => b.world_gap! - a.world_gap!)
  const solid = (v: Valuation) => (v.world_servers ?? 0) >= RANK_SERVERS
  if (!priced.length) return null

  return (
    <Card className="border-cheap/40">
      <CardHeader>
        <CardTitle>World server: cheaper or dearer than everywhere else</CardTitle>
        <CardDescription>
          Each item on {homeName} against the same item on the other servers. When the world server merges the markets,
          prices should meet: buy what's cheap here before it does, sell what's dear here before it falls.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Cheaper here, room after the fee" value={`${cheaper.length} items`} note={`of ${priced.length} on 5+ other servers`} tone="cheap" />
          <Stat label="Dearer here by 15%+" value={`${dearer.length} items`} note={`${dearer.filter((v) => v.label === 'Sell').length} rated Sell: they trade daily`} tone="dear" />
          <Stat
            label="Sells for being dearer"
            value={m.world_sell_better != null ? `${share(m.world_sell_better)} vs ${share(m.world_sell_worse)}` : '–'}
            note={m.world_sell_signals ? `beat vs lost to holding 3 days · ${m.world_sell_signals} signals` : 'not enough history yet'}
          />
          <Stat
            label="Cheaper-here buys, before a merge"
            value={m.world_bet_win_rate != null ? `${share(m.world_bet_win_rate)} won` : '–'}
            note={m.world_bet_signals ? `in 3 days, after the fee · ${m.world_bet_signals} signals: the gain needs the merge` : 'not enough history yet'}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <WorldTable
            title="Cheaper here: buy before the merge"
            note={`Ranked by the gain after the ${Math.round(fee * 100)}% fee if it settles at the cheaper quarter of the other servers. Items on ${RANK_SERVERS}+ servers.`}
            rows={cheaper.filter(solid).slice(0, 12)}
            empty="Nothing is enough cheaper here to clear the fee."
            onSelect={onSelect}
            last={(v) => <span className="font-medium text-good">{pct(1 + v.world_upside!)}</span>}
            lastLabel="If it meets"
          />
          <WorldTable
            title="Dearer here: sell before the merge"
            note={`Ranked by how much dearer, items on ${RANK_SERVERS}+ servers. Sell means it trades daily: list just under the cheapest.`}
            rows={dearer.filter(solid).slice(0, 12)}
            empty="Nothing is 15%+ dearer here."
            onSelect={onSelect}
            last={(v) => <span className="text-muted-foreground">{v.label === 'Sell' ? kina(v.list_at) : '–'}</span>}
            lastLabel="List at"
          />
        </div>

        <p className="text-xs text-muted-foreground">
          The world price is the median of the other servers; the merge target is their cheaper quarter, since every
          server's sellers would meet in one market (a guess: there's been no merge to learn from). In the backtest
          ({m.world_days ?? 0} days of other-server prices), selling when 15%+ dearer here held up; buying when cheaper here
          mostly just lost the fee before a merge, so those are bets on the merge. A buy that's also cheaper here is a
          Strong buy.
        </p>
      </CardContent>
    </Card>
  )
}

function WorldTable({
  title,
  note,
  rows,
  empty,
  onSelect,
  last,
  lastLabel,
}: {
  title: string
  note: string
  rows: Valuation[]
  empty: string
  onSelect: (item: Valuation) => void
  last: (v: Valuation) => React.ReactNode
  lastLabel: string
}) {
  return (
    <div className="grid content-start gap-2">
      <div>
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-muted-foreground">{note}</div>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-right">Here</TableHead>
              <TableHead className="text-right">World</TableHead>
              <TableHead className="text-right">vs world</TableHead>
              <TableHead className="text-right">{lastLabel}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((v) => (
              <TableRow key={v.key} className="cursor-pointer" onClick={() => onSelect(v)}>
                <TableCell className="whitespace-normal">
                  <div className="min-w-36 font-medium">{v.name}</div>
                  <Verdict label={v.label} className="text-xs text-muted-foreground" />
                </TableCell>
                <TableCell className="tabular text-right">{kina(v.now)}</TableCell>
                <TableCell className="tabular text-right">
                  <div>{kina(v.world)}</div>
                  <div className="text-[11px] text-muted-foreground">{v.world_servers} servers</div>
                </TableCell>
                <TableCell className={cn('tabular text-right font-medium', v.world_gap! < 1 ? 'text-cheap' : 'text-dear')}>
                  {pct(v.world_gap)}
                </TableCell>
                <TableCell className="tabular text-right">{last(v)}</TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="h-16 text-center text-muted-foreground">
                  {empty}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'cheap' | 'dear' }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn('tabular text-xl font-semibold', tone === 'cheap' && 'text-cheap', tone === 'dear' && 'text-dear')}>{value}</div>
      <div className="text-[11px] text-muted-foreground">{note}</div>
    </div>
  )
}
