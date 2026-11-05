import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { pct, type Model } from '@/lib/data'

const p = (x: number | null | undefined, digits = 1) => (x == null ? '–' : pct(1 + x, digits))
const share = (x: number | null | undefined) => (x == null ? '–' : `${Math.round(x * 100)}%`)

/** How the fair value is built, and how its history half did when replayed on past days. */
export function ModelCard({ model: m, homeName }: { model: Model; homeName: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>How the fair value works</CardTitle>
        <CardDescription>A small valuation model, checked against what prices actually did.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-2">
        <ol className="grid list-decimal gap-3 pl-5 text-sm">
          <li>
            <span className="font-medium">{homeName}'s own prices.</span>{' '}
            <span className="text-muted-foreground">
              The price level of the last 2 days, recent hours counting most. Its uncertainty is how much the daily price
              usually moves. Asks nobody pays count for less: a cheapest listing that expired unsold caps the value, and with
              no sale seen the range widens.
            </span>
          </li>
          <li>
            <span className="font-medium">Similar items.</span>{' '}
            <span className="text-muted-foreground">
              On the other servers an item keeps a steady price ratio to similar items. That ratio × what those items cost on{' '}
              {homeName} gives a second estimate, in {homeName}'s own price level.
            </span>
          </li>
          <li>
            <span className="font-medium">Blend.</span>{' '}
            <span className="text-muted-foreground">
              Each estimate weighted by how precise it is, with {homeName}'s history counting {m.home_weight}× as much and
              similar items never more than half. When they disagree the range widens.
            </span>
          </li>
          <li>
            <span className="font-medium">Sell</span>{' '}
            <span className="text-muted-foreground">
              when it's Overpriced, trades daily, has sold lately, and the ask is under 2× fair value: list just under the
              cheapest. Further over are asks nobody pays.
            </span>
          </li>
          <li>
            <span className="font-medium">Buy below</span>{' '}
            <span className="text-muted-foreground">
              fair value less a margin of safety: at least {Math.round(m.margin * 100)}%, more when the value is uncertain, and
              always enough that reselling at fair value clears the {Math.round(m.fee * 100)}% fee. Strong buy
              needs both estimates to agree it's cheap. A price still falling says wait.
            </span>
          </li>
        </ol>

        <div className="grid content-start gap-3">
          <div className="text-sm font-medium">Backtest: the history estimate on past days</div>
          {m.evaluations ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Buy signals" value={String(m.buy_signals)} note={`${m.evaluations} item-days replayed`} />
                <Stat label="Won" value={share(m.buy_win_rate)} note={`resold at what sold over the next ${m.horizon_days} days, after fee`} />
                <Stat label="Median return" value={p(m.buy_return)} note={`worst quarter ${p(m.buy_return_p25)} or less`} tone={(m.buy_return ?? 0) > 0 ? 'good' : undefined} />
                <Stat label="Buying anything" value={p(m.all_return)} note="the same, for every item-day" />
                {!!m.sell_signals && (
                  <Stat
                    label="Sell signals"
                    value={`${share(m.sell_better)} vs ${share(m.sell_worse)}`}
                    note={`beat vs lost to holding ${m.horizon_days} days · sold ${share(m.sell_sold)}, then ${p(m.sell_gain_when_sold)} · ${m.sell_signals} signals`}
                    tone="good"
                  />
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                As a forecast of the price {m.horizon_days} days later, the fair value is off by {share(m.error_fair)} (median)
                against {share(m.error_now)} for today's price, and closer {share(m.fair_closer)} of the time: prices here step
                to new levels and stay, so it doesn't predict where a price is going. What it does catch is a listing below the
                recent level, and those have paid.
                {m.buy_return_asks != null && (
                  <>
                    {' '}
                    Resales count at the prices that actually sold (a listing that left before it could expire), not at the
                    asks: resold at the asks, the same buys would show {p(m.buy_return_asks)}, but asks nobody pays aren't
                    money. {m.buy_unsold != null && `${share(m.buy_unsold)} saw no sale at all and count at the lowest ask.`}
                  </>
                )}{' '}
                The similar-items estimate can't be replayed until the other servers have
                history of their own; it builds up each time compare runs. Two weeks of data from one server: treat it as a
                guide, not a guarantee.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Not enough price history yet to replay.</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function Stat({ label, value, note, tone }: { label: string; value: string; note: string; tone?: 'good' }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={tone === 'good' ? 'tabular text-xl font-semibold text-good' : 'tabular text-xl font-semibold'}>{value}</div>
      <div className="text-[11px] text-muted-foreground">{note}</div>
    </div>
  )
}
