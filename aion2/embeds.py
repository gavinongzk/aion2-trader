"""Discord embeds of ideas, items, watches and alerts, as the plain JSON objects Discord's API takes,
kept within its size limits. The hourly job posts them over Discord's REST API, the slash-command
function on Vercel sends them as replies, and the gateway bot wraps them (``views``): no discord.py
needed here."""

from datetime import datetime

from .analysis import Idea, Profile
from .report import TITLES
from .stats import kina, pct
from .watch import Alert

COLORS = {"flip": 0x2E9E5B, "craft": 0x3B7DD8, "speculate": 0xC77C16}
NEUTRAL = 0x5B6573
FOOTER = "aion2.exchange data · trade ideas, not guarantees"
EMBED_BUDGET = 5500  # Discord allows 6000 characters per embed in all; leave room for titles


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def embed(title: str, color: int = NEUTRAL, updated_at: datetime | None = None, footer: str = FOOTER) -> dict:
    out = {"title": clip(title, 256), "color": color, "footer": {"text": footer}, "fields": []}
    if updated_at is not None:
        out["timestamp"] = updated_at.isoformat()
    return out


def field(e: dict, name: str, value: str, inline: bool = True) -> None:
    e["fields"].append({"name": clip(name, 256), "value": clip(value or "—", 1024), "inline": inline})


def ideas_embed(strategy: str, ideas: list[Idea], *, title: str | None = None,
                updated_at: datetime | None = None, note: str | None = None) -> dict:
    e = embed(title or TITLES[strategy], COLORS[strategy], updated_at)
    if note:
        e["description"] = note
    if not ideas:
        e["description"] = (note + "\n\n" if note else "") + "Nothing passes the filters right now."
        return e
    shown = ideas[:10]
    per_field = min(1024, (EMBED_BUDGET - len(e["title"]) - len(note or "")) // len(shown) - 60)
    for rank, idea in enumerate(shown, 1):
        value = f"**{idea.headline}**\n" + "\n".join(f"• {r}" for r in idea.reasons)
        field(e, f"{rank}. {idea.name}", clip(value, per_field), inline=False)
    return e


def sections_embed(title: str, sections: dict[str, list[str]], updated_at: datetime | None = None) -> dict:
    """One field per section, for the scorecard, timing and market events."""
    e = embed(title, NEUTRAL, updated_at)
    budget = (EMBED_BUDGET - len(title)) // max(1, len(sections)) - 60
    for name, lines in sections.items():
        field(e, name, clip("\n".join(f"• {l}" for l in lines) or "—", min(1024, budget)), inline=False)
    return e


def item_embed(p: Profile, ideas: list[Idea], updated_at: datetime | None = None,
               notes: list[str] = (), uses: list[tuple[str, float, float]] = (),
               valuation: dict | None = None) -> dict:
    e = embed(p.name, NEUTRAL, updated_at, footer=f"item {p.key} · {FOOTER}")
    if not p.price:
        e["description"] = "Not listed on the market right now."
    field(e, "Cheapest now", f"{kina(p.price)} ({p.listings or 0} listed)")
    if valuation:  # the fair value and the world price, from the valuation (see value.py)
        v = valuation
        field(e, "Rating", f"{v['label']}" + (f" · fair value {kina(v['fair'])}" if v.get("fair") else ""))
        if v.get("world"):
            field(e, f"World price ({v['world_servers']} servers)",
                  f"{kina(v['world'])}" + (f" · here {pct(v['world_gap'] - 1)}" if v.get("world_gap") else ""))
        if v.get("reasons"):
            field(e, "Why", "\n".join(f"• {r}" for r in v["reasons"][:4]), inline=False)
    if not p.closes:
        field(e, "History", "No price history yet.", inline=False)
        return e
    lo, hi = p.range14
    field(e, "Usual (7-day median)", kina(p.usual))
    field(e, "14-day range (p10–p90)", f"{kina(lo)} – {kina(hi)}")
    field(e, "7-day trend", f"{pct(p.growth7)}/day" if p.growth7 is not None else "?")
    field(e, "Daily move", f"±{pct(p.volatility, False)}" if p.volatility is not None else "?")
    trend = p.demand_trend
    field(e, "Demand", p.demand() + (f"\n{pct(trend)} vs last week" if trend is not None else ""))
    if p.price and p.usual and not e.get("description"):
        e["description"] = (f"Cheapest is {pct(p.price / p.usual - 1)} vs its usual price, "
                            f"at the {pct(p.position, False)} mark of its 14-day range "
                            f"({p.history_days:.0f} days of history).")
    if notes:
        field(e, "Patterns", "\n".join(f"• {n}" for n in notes), inline=False)
    if uses:
        field(e, "Used in crafts", "\n".join(
            f"• {name}: ~{qty:.0f} per craft, {pct(share, False)} of its cost" for name, qty, share in uses[:6]),
            inline=False)
    for idea in ideas:
        value = f"**{idea.headline}**\n" + "\n".join(f"• {r}" for r in idea.reasons)
        field(e, f"{idea.strategy.capitalize()} idea", value, inline=False)
    return e


def watches_embed(rows) -> dict:
    e = embed("Your price alerts", NEUTRAL, footer=FOOTER)
    if not rows:
        e["description"] = "None yet. Add one with `/watch add`."
        return e
    lines = []
    for r in rows:
        now = f"now {kina(r['price'])}" if r["price"] else "not listed"
        hit = " ✅" if r["price"] and r["price"] <= r["below"] else ""
        lines.append(f"**{r['name']}**: below {kina(r['below'])} ({now}){hit}")
    e["description"] = clip("\n".join(lines), 4000)
    return e


def alert_text(a: Alert) -> str:
    listed = f", {a.listings} listed" if a.listings else ""
    return (f"<@{a.user_id}> **{a.name}** is listed at **{kina(a.price)}** "
            f"(your alert: below {kina(a.below)}{listed}).")
