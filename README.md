# aion2-trader

Finds Aion 2 market opportunities for resellers, crafters and speculators, using the public
read-only API of [aion2.exchange](https://aion2.exchange/api/docs). Every idea comes with the
numbers behind it. Python 3.11+, no dependencies.

## Run it

```bash
cp config.example.toml config.toml
python3 -m aion2 servers          # find your server id, put it in config.toml
python3 -m aion2 run              # collect + report
```

`collect` and `report` also work on their own (`report` re-analyses stored data without any
request). The first run fetches series for ~120 items at one request a second, so it takes a few
minutes; runs within the next 50 minutes reuse what is stored. The site updates hourly, so running
more often than that gains nothing.

Output goes to `reports/`: a dated Markdown report, plus `latest.md`, `latest.csv` and
`latest.json` (the JSON is meant for a Discord bot to read).

**Set `sales_fee`** in `config.toml` to the real market fee. Every margin depends on it.

## Discord bot

The bot refreshes the data every hour, posts ideas that are new to a strategy's top 5 in a
channel, and answers:

| Command | What it does |
|---|---|
| `/deals strategy:flip count:5` | top flip, craft or speculate ideas with their reasons |
| `/item name:…` | one item: cheapest, usual price, 14-day range, trend, demand, any idea on it (autocompletes names) |
| `/watch add item:… below:250k` | pings you in that channel when the item is listed at or below the price |
| `/watch list`, `/watch remove` | your alerts (only you see the replies) |
| `/scorecard` | how past calls did after 1, 3 and 7 days, per strategy and pattern |
| `/timing` | items with an hour-of-day or weekday edge; days when many prices changed level at once |
| `/refresh` | collect now; only members with Manage Server see it |

Every `scorecard_days` (7) the bot also posts the scorecard and timing summary in the channel,
once there are outcomes to show.

### Set it up (once)

1. **Create the bot.** Open the [Discord Developer Portal](https://discord.com/developers/applications),
   click New Application, name it, open **Bot**, then **Reset Token** and copy the token.
2. **Keep the token secret.** Copy `.env.example` to `.env` and paste it there:
   `DISCORD_TOKEN=...`. Never paste the token into chat or commit it; if it leaks, reset it.
3. **Invite it.** In the portal, open **OAuth2 → URL Generator**, tick the scopes `bot` and
   `applications.commands`, and the permissions *Send Messages*, *Embed Links* and *View Channels*.
   Open the generated link and pick your server.
4. **Point it at your server and channel.** In Discord, turn on Settings → Advanced → Developer
   Mode, then right-click your server → Copy Server ID (`guild_id`) and the channel for posts →
   Copy Channel ID (`channel_id`). Put both in the `[discord]` section of `config.toml`.
5. **Install and start it.**

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python -m aion2 bot
   ```

The bot runs as long as that command runs. To keep it up all the time, run it on an always-on
machine (a small VPS, a Raspberry Pi, or a host such as Railway or Fly.io) with the same files,
`config.toml` and `.env`.

## Comparing servers

```bash
python3 -m aion2 compare          # fetch every comparable server's item list, write reports/compare.json
```

One request per server (20 for an Asia region), reused for `cache_minutes`. For each item listed on
`min_servers`+ servers it records every server's price (the 24h median of its cheapest listing,
ignoring servers with fewer than `min_listings` listings) and the ratio to the regional median. Each
server gets a **price index**: the geometric mean of its items' ratios, trimmed 10% at each end, so
1.15 means things there cost about 15% more than on a typical comparable server. Set `[compare]
scope = "faction"` to compare with your faction's servers only. The Kina-per-Quna rate isn't
compared: the API has no Quna data for these servers yet.

### What is it worth? (fair value)

`compare` also values every item on your server (`aion2/value.py`), like a small investment model.
Each server is its own economy, so the fair value comes from your server's prices first:

1. **Your server's history**: the price level of the last 2 days, recent hours weighted most
   (half-life 6 hours). Its uncertainty is the daily price spread over 14 days, widened when the
   recent level has jumped away from the 14-day one.
2. **Similar items** (relative value): on the other servers an item keeps a steady price ratio to
   similar items in its category (within 4× of its price). That ratio × what those items cost on
   your server is a second estimate, in your server's price level. The most consistent ratios count most.
3. **Blend**: each weighted by its precision, history counting `home_weight` (2×) as much and
   similar items never more than `max_peer_share` (half). Disagreement widens the range.

**Asks nobody pays.** The API has asking prices only, no sales, so `trades.py` infers them from the
hourly cheapest price and listing count. Listings expire after 2 days, so a listing can leave by being
bought or by lapsing: the cheapest listing leaving within ~40 hours of appearing is a sale at its
price; leaving at about 2 days old, an expiry (nobody paid it). For a drop with the cheapest price
unchanged, listings are followed in cohorts by when they were listed: each sale takes a random
listing, so a cohort's unsold share shrinks with every sale, and what's left of it 2 days later is
the expected expiry; the rest are sales.
On Hadala the cheapest listing goes within 12 hours 94% of the time, so expiry is mostly the fate
of the dearer asks. This is used four ways:
- an item is a buy only if it's also below its recent **sale prices** (less the margin), when it has
  3+ sales in 2 days: asks well above what sells don't make today's price a bargain
- **resell at** is the recent sale price when it's below the fair value
- a cheapest listing that **expired unsold** caps the fair value; with **no sale** in 2 days the range widens
- **sells/day** leaves out likely expiries (about 22% lower for a typical item than counting every drop)

Valuing from the sale prices directly did worse in the backtest: sales lag a dip, so the value stays
high just as the price falls. The fair value stays on the asks; the sales are a check on it.

From that: **buy below** = fair value less a margin of safety (`margin`, 10%, or half the
uncertainty if wider, and always enough that reselling at fair value clears `sales_fee` plus 3%:
about 15% at a 12% fee); **resell at** = fair value, shown after `sales_fee`. Ratings: *Strong buy*
(1.5+ sigma under, and similar items agree it's cheap), *Buy* (under the buy price), *Fair*,
*Overpriced* (above fair value + margin), *Wait* (cheap but still falling).

**Backtest.** The history estimate is replayed once a day on the past and checked 3 days later
(`horizon_days`). A buy is resold at the median price of what sold over those 3 days (with no sale,
at the lowest ask): resold at the asks instead, the same buys looked about twice as good, but asks
nobody pays aren't money. The backtest picked the settings above: a 14-day level had no edge at all,
because prices here step to new levels and stay. With a 12% fee, on Hadala data to 2026-11-03: buy
signals returned +7.1% median, 55% won (164 signals), against −14.5% for buying anything; without
the sale-price check +5.5%, 53% won (196). The check helped on both halves of the items. As a
forecast of the price itself the fair value is no better than today's price: its use is spotting
listings below the recent level. Similar items can't be replayed until the other servers have
history; it builds up each time `compare` runs.

**The economy** (`economy.py`, the dashboard's economy section). The API has no Kina balances, so
the money supply can't be measured. What can is the other side of MV = PQ, on a fixed basket of the
items priced on 90% of the last 21 days (218 on Hadala): the **Kina spent** on the market each day
(from the inferred sales), the **price level** (a trimmed-mean index of what the basket costs), the
same index **per section**, and the **fee sink** (12% of spending: Kina the market destroys). On
Hadala to 2026-11-03: prices +56% in 3 weeks (+21% in the last week), uneven (skins 3.4× and armor
+40% this week, accessories −12%); spending about 600M Kina a day, +46% on the week before, with
sales +20%: spending outgrowing prices means more Kina circulating, as on any young server.

None of it changes the ratings yet. Buys made while their section's index fell over the week did
worse in the backtest (−3% median against +7% for all buys, in both halves of the items), but there
were only 29 of them. The market index and spending are the same for every item on a day, and two
weeks of days can't test them. Each buy call logs its section's trend, so the scorecard will show
whether it becomes a signal; the item reasons mention a section moving 5%+ in a week.

**Other features, tested** (Hadala data to 2026-11-04). Each was tested before touching a rating:
- **Time of day.** Market-wide, asks aren't cheaper at any hour: the hourly swing is under 1.5% and
  the first and second halves of the data disagree on which hours are cheap (correlation −0.09).
  Per item it's real but rare: 7 items had a strong pattern in the first half, 6 kept it in the
  second (a 5% swing). Those items say when they're usually cheapest. **Sales** do have a clock:
  21:00–00:00 Singapore time sees about 1.8× the sales of 05:00–08:00, so list in the evening.
  Weekdays: three and a half weeks is too few to say.
- **Time to sell.** For each item, how often a listing at the going rate found a buyer within a
  day and within 3 days, over the last 2 weeks. It didn't predict which buys paid (buys of slow
  fillers did no worse), so it's shown as resale information, not used in the rating.
- **Craft cost** (`value.craft_costs`, the 19 tracked crafts: each material's expected quantity × its
  market level or listed price). Every craft that went 10%+ under its craft cost rose within 3 days,
  median +32% (16 item-days, 5 crafts, each one up): crafters stop making it at a loss, so the cost
  is a floor. Only 16 cases, so it's a reason, not a rating, and such items are logged as
  "below cost" calls on the scorecard to see if it holds. Crafting that pays 20%+ is a weak sign the
  other way (about −1% over 3 days).
- **The similar-items estimate, and price moves that start on other servers.** Not testable yet:
  the other servers' snapshots only have prices since 2026-11-02 (the rows before are empty), and
  a replay needs about a week. `compare` stores them every run, so both can be tested from about
  2026-11-09.

**Sell.** An item that's Overpriced (above fair value plus the margin), trades at least daily, has
sold in the last 2 days, and whose cheapest ask is under 1.5 sigma and 2× over fair value is rated
**Sell**: if you hold one, list just under the cheapest. Tested as you'd do it: list at 97% of the
cheapest; it sold if a sale at that price or more came within 3 days (buyers take the cheapest
first), otherwise you sell later anyway (a tie); against holding and selling at the median sale of
the 3 days after. Over 134 signals it got more than holding 46% of the time and less 27%; it sold
73% of the time, for a median 7.8% more. Both halves of the items agree. What didn't work:
- any price over fair value (no margin): lost more often than it won (35% vs 46%)
- a supply **squeeze** (listings at half their weekly median or less): adds nothing to "over fair
  value"; a squeeze alone says hold (selling then lost 52% of the time, won 27%)
- far over fair value: listings next to an ask that high mostly didn't sell (36%), and on items
  that trade less than daily a withdrawn troll ask looks like a sale at an absurd price
- "it's been selling over fair value" (the going rate): by then the cheapest ask had usually fallen
  already; and momentum (a falling price didn't keep falling, a rising one didn't keep rising)

For any item you hold, the dashboard's **Sell** view lists the price to list at, how often a
listing at the going rate sold within 1 and 3 days, and the take after the fee.

The edge is in items that trade: slow sellers (under 0.5 listings taken a day) lost money in the
backtest, about the fee itself, and won only about a third of the time. Their reasons say so: buy those to use, not to resell.

**Live scorecard.** Every Buy / Strong buy is logged as a `value` call (entry: today's price,
target: fair value) and scored after 1, 3 and 7 days like the bot's other calls; slow sellers are
scored apart (`buy+slow`). `compare` does this, and the bot runs `compare` on each refresh
(`[compare] in_bot`). `/scorecard` and `python -m aion2 scorecard` show the results.

### The web app

`web/` is a Vite + React + TypeScript app (Tailwind, shadcn/ui, TanStack Table, Recharts) that
reads `reports/compare.json`. It opens on the valuations (rating filters, best first; an item shows
its buy-below / fair / resell prices, a football-field chart of the estimates, the similar items
used and its 14-day price), then how the model works with its backtest, then how your server
compares with the others.

```bash
cd web && npm install && npm run dev      # http://localhost:5173
npm run build                             # static site in web/dist, compare.json included
```

## The three strategies

**Flip.** An item listed below what it usually sells for. The resale price is the lower of its
28-day average sale price and its 30-day median listed price. It only "buys" listings cheap enough
to clear `flip_min_roi` after the fee, up to `hold_days` of sales (max `max_qty`). It flags a
listing that is far below the next one (likely to go fast), a falling price and falling sales.

**Craft.** Crafts from `/api/crafts` (Artisan's Splendent items for your server's race) whose
market price after the fee beats the site's expected crafting cost. It skips crafts with an
unpriced material, shows how often the craft was profitable over 14 days and the biggest
material costs (bought or crafted), and ranks by profit × how well the output sells × consistency.

**Speculate.** Needs 5+ days of history and 1+ sale a day.
- *dip*: the price is in the bottom 15% of its 30-day range, and sales aren't collapsing.
  Target: back to the 30-day median.
- *uptrend*: rising 1.5%+/day over 7 days with listings falling and sales not falling.
- *squeeze*: listings at half their 7-day average or less, before the price has jumped.

A falling price with falling sales ("falling knife") is never called a dip, and a single stray
cheap listing is left to the flip list.

## How it works

```
/api/items (all, 1000 a page) ─┐
/api/crafts ───────────────────┼─> SQLite (aion2.db) ─> analysis ─> reports/
shortlist: prices 30d, volume, ┘
listings ladder; craft series
```

- `aion2/collect.py`: what is fetched. The shortlist mixes the most underpriced items, the biggest
  24h movers, the busiest items, your `watchlist` and the best crafts.
- `aion2/analysis.py`: the signals and the reason text; thresholds are in `config.toml`.
- Every collect also keeps a snapshot of the whole item list in `item_snapshots`, so you build up
  your own history over time.

## Learning what works

**Scorecard** (`aion2/scorecard.py`). Every idea is logged when it's made (once a day at most per
item) with its entry and target price, then scored 24h, 72h and 7 days later from the hourly
snapshots: the price then, the 80th percentile of the price over the window (a realistic exit),
the return after the fee, and whether the target was reached (a craft: whether it sold above cost).
`python -m aion2 scorecard` or `/scorecard` shows hit rates and median returns per strategy and
speculation pattern. Use it to tune the thresholds in `config.toml`; the `calls` and `outcomes`
tables are also the labelled data a future model would train on. Calls are only scored while the
bot (or the collector) keeps running.

**Timing** (`aion2/timing.py`). Each hourly price is divided by the median of the 24 hours around it
(so a trend doesn't look like a time-of-day effect) and grouped by hour in `timezone`. An item has an
edge when its cheapest and dearest hours are 5%+ apart and held on 60%+ of days. Weekday patterns
need 3 weeks of each weekday.

**Price-level shifts.** A sudden 25%+ jump of the daily median that holds for 2+ days (not a steady
slide, not noise) starts a new level: the usual price, range, trend and dips only use the days since,
and dips and uptrends wait 3 days for the new level to settle. Many items shifting on the same day
shows up under "Market events" (a patch or maintenance).

**Materials and crafts.** Every recipe material is collected too. When a craft's cost moved 8%+ in
3 days and its sale price didn't keep up, the craft idea says so (margin widening or squeeze) and
names the materials behind it; `/item` on a material lists the crafts that use it.

## Servers without sales statistics (e.g. Hadala Asia)

Some servers only have hourly snapshots of each item's cheapest price and listing count (the
site's `latest_stats_fetched_at` is empty). The tool detects this and then:
- estimates demand as **listings taken per day**: listings that disappear between hourly
  snapshots, bought or withdrawn. It counts listings, not units, so treat it as a rough guide;
- only fetches price history (one request an item instead of three);
- can't see listing depth, so a flip shows the cheapest unit only; check the stack in game.

## Reading the prices

The cheapest listing jumps when cheap stock sells out or someone lists at an absurd price, and a
new market drifts a lot in a month. So "usual" price means the **7-day median**, a flip resells at
the lowest of that, the **2-day median** and the average sale price, the range is the 10th to 90th
percentile of 14 days, trends use daily medians, and anything falling 3%+/day is never a "dip".

## Tests

```bash
python3 -m unittest
```

These are trade ideas from public market data, not guarantees: prices can move before you act.


## Hosting: hourly in the cloud, free

`.github/workflows/refresh.yml` runs every hour on GitHub Actions: `python -m aion2 run` and
`compare` with `config.cloud.toml` (config.toml without the Discord section), then builds `web/`
and deploys it to Vercel as a static site with the new `compare.json` inside. No server of your
own: the database (`aion2.db`, the price history) is carried from run to run in the Actions cache,
and backed up daily to the `db-backup` release as `aion2.db.gz` (restored from there if the cache is
lost). On the hosted site the Refresh button is gone (it updates itself) and *My items* is kept in
your browser instead of `reports/holdings.json`.

The repository is public so the Actions minutes are free (a run takes about 5 minutes; a private
repository gets 2,000 minutes a month, short of hourly). Nothing private is in it: `.env` (the
Discord token), `config.toml` (your Discord ids) and the database are git-ignored, and the seeded
database had its `watches` table (Discord user ids) emptied.

The Discord bot doesn't run in the cloud (Actions jobs end; a bot has to stay connected). Run it
on your own machine as before: it keeps its own database, separate from the cloud one.

Setup, once: a Vercel token (vercel.com → Account Settings → Tokens) as the repository secret
`VERCEL_TOKEN`, and `orgId` / `projectId` from `web/.vercel/project.json` (written by the first
`vercel deploy`) as `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID`. Run it by hand from the Actions tab
(*refresh* → *Run workflow*).
