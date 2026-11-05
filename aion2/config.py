"""Settings, read from a TOML file; every key has a default."""

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Collect:
    shortlist: int = 150            # items that get price history, volume and listings fetched
    craft_details: int = 30         # crafts that get their cost-over-time series fetched
    min_units_sold_28d: int = 20    # ignore items that barely trade
    min_listings: int = 2           # the same, on a server without sales statistics
    cache_minutes: int = 50         # reuse a stored response younger than this
    watchlist: list[int] = field(default_factory=list)  # item ids always in the shortlist


@dataclass
class Strategy:
    top: int = 10                   # ideas shown per strategy
    min_per_day: float = 0.5        # units sold (or listings taken) a day, below which an item is too slow
    hold_days: float = 3.0          # how many days of sales a flip may buy up
    max_qty: int = 20               # most units a flip buys
    flip_min_roi: float = 0.10
    craft_min_roi: float = 0.05
    min_history_days: float = 5.0   # speculation needs at least this much price history
    dip_percentile: float = 0.15    # "dip" = price in the lowest 15% of the last 30 days
    momentum_per_day: float = 0.015 # "uptrend" = price rising 1.5%/day or more over 7 days
    squeeze_ratio: float = 0.5      # "squeeze" = listings at half their 7-day average or less
    shift_min_change: float = 0.25  # a sudden 25%+ change of the daily median starts a new price level


@dataclass
class Discord:
    channel_id: int = 0             # where the hourly ideas go (0: no posting, commands only)
    guild_id: int = 0               # your Discord server: commands show up there at once (0: everywhere, slower)
    refresh_minutes: int = 60       # how often the bot collects and re-analyses
    post_top: int = 5               # ideas per strategy considered for the hourly post
    max_watches: int = 25           # price alerts per person
    scorecard_days: float = 7       # how often the scorecard and timing summary is posted


@dataclass
class Compare:
    scope: str = "region"           # compare with the home server's region ("region") or its faction only ("faction")
    min_servers: int = 5            # an item joins the comparison when listed on this many servers
    min_listings: int = 2           # a server's price counts when it has this many listings
    in_bot: bool = True             # the bot also runs compare each refresh (about 20 requests), logging the valuation's calls


@dataclass
class Value:
    home_weight: float = 2.0        # your server's own history counts this many times the peer estimate, at equal precision
    max_peer_share: float = 0.5     # the peer estimate never gets more than half the weight while there is history
    margin: float = 0.10            # margin of safety: buy at least this far below fair value (more when it's uncertain)
    peers: int = 8                  # similar items a peer estimate uses, the most consistent first
    min_common_servers: int = 4     # a peer counts when both items are listed on this many other servers
    level_days: float = 2.0         # history estimate: the price level of the last 2 days...
    half_life_days: float = 0.25    # ...with a price's weight halving every 6 hours (picked by the backtest)
    horizon_days: float = 3.0       # backtest: how far ahead the fair value is checked
    use_sales: bool = True          # discount asks nobody paid: inferred sales and expiries (see trades.py)


@dataclass
class Config:
    base_url: str = "https://aion2.exchange/api"
    server: int | str | None = None # id or name, e.g. "Hadala Asia"; None: the API's default server
    db: str = "aion2.db"
    reports: str = "reports"
    delay_seconds: float = 1.0      # pause between API requests
    sales_fee: float = 0.05         # market fee taken from the seller; check the real one in game
    timezone: str = "Asia/Singapore"  # for hour-of-day and weekday patterns: where the server's players are
    collect: Collect = field(default_factory=Collect)
    strategy: Strategy = field(default_factory=Strategy)
    discord: Discord = field(default_factory=Discord)
    compare: Compare = field(default_factory=Compare)
    value: Value = field(default_factory=Value)


def _fill(cls, data: dict):
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"unknown setting(s) in [{cls.__name__.lower()}]: {', '.join(sorted(unknown))}")
    values = {}
    for name, value in data.items():
        sub = {"collect": Collect, "strategy": Strategy, "discord": Discord,
               "compare": Compare, "value": Value}.get(name) if cls is Config else None
        values[name] = _fill(sub, value) if sub else value
    return cls(**values)


def load(path: str | Path | None) -> Config:
    if path is None or not Path(path).exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if data.get("server") == 0:
        data["server"] = None
    return _fill(Config, data)
