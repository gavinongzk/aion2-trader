"""Discord embeds of ideas, items, watches and alerts, kept within Discord's size limits."""

from datetime import datetime

import discord

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


def ideas_embed(strategy: str, ideas: list[Idea], *, title: str | None = None,
                updated_at: datetime | None = None, note: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=title or TITLES[strategy], color=COLORS[strategy], timestamp=updated_at)
    embed.set_footer(text=FOOTER)
    if note:
        embed.description = note
    if not ideas:
        embed.description = (note + "\n\n" if note else "") + "Nothing passes the filters right now."
        return embed
    shown = ideas[:10]
    per_field = min(1024, (EMBED_BUDGET - len(embed.title or "") - len(note or "")) // len(shown) - 60)
    for rank, idea in enumerate(shown, 1):
        value = f"**{idea.headline}**\n" + "\n".join(f"• {r}" for r in idea.reasons)
        embed.add_field(name=clip(f"{rank}. {idea.name}", 256), value=clip(value, per_field), inline=False)
    return embed


def sections_embed(title: str, sections: dict[str, list[str]], updated_at: datetime | None = None) -> discord.Embed:
    """One field per section, for the scorecard, timing and market events."""
    embed = discord.Embed(title=title, color=NEUTRAL, timestamp=updated_at)
    embed.set_footer(text=FOOTER)
    budget = (EMBED_BUDGET - len(title)) // max(1, len(sections)) - 60
    for name, lines in sections.items():
        embed.add_field(name=clip(name, 256), value=clip("\n".join(f"• {l}" for l in lines) or "—",
                                                         min(1024, budget)), inline=False)
    return embed


def item_embed(p: Profile, ideas: list[Idea], updated_at: datetime | None = None,
               notes: list[str] = (), uses: list[tuple[str, float, float]] = ()) -> discord.Embed:
    embed = discord.Embed(title=clip(p.name, 256), color=NEUTRAL, timestamp=updated_at)
    embed.set_footer(text=f"item {p.key} · {FOOTER}")
    if not p.price:
        embed.description = "Not listed on the market right now."
    embed.add_field(name="Cheapest now", value=f"{kina(p.price)} ({p.listings or 0} listed)")
    if not p.closes:
        embed.add_field(name="History", value="No price history yet.", inline=False)
        return embed
    lo, hi = p.range14
    embed.add_field(name="Usual (7-day median)", value=kina(p.usual))
    embed.add_field(name="14-day range (p10–p90)", value=f"{kina(lo)} – {kina(hi)}")
    embed.add_field(name="7-day trend", value=f"{pct(p.growth7)}/day" if p.growth7 is not None else "?")
    embed.add_field(name="Daily move", value=f"±{pct(p.volatility, False)}" if p.volatility is not None else "?")
    trend = p.demand_trend
    embed.add_field(name="Demand", value=p.demand() + (f"\n{pct(trend)} vs last week" if trend is not None else ""))
    if p.price and p.usual:
        embed.description = (f"Cheapest is {pct(p.price / p.usual - 1)} vs its usual price, "
                             f"at the {pct(p.position, False)} mark of its 14-day range "
                             f"({p.history_days:.0f} days of history).")
    if notes:
        embed.add_field(name="Patterns", value=clip("\n".join(f"• {n}" for n in notes), 1024), inline=False)
    if uses:
        embed.add_field(name="Used in crafts", value=clip("\n".join(
            f"• {name}: ~{qty:.0f} per craft, {pct(share, False)} of its cost" for name, qty, share in uses[:6]),
            1024), inline=False)
    for idea in ideas:
        value = f"**{idea.headline}**\n" + "\n".join(f"• {r}" for r in idea.reasons)
        embed.add_field(name=f"{idea.strategy.capitalize()} idea", value=clip(value, 1024), inline=False)
    return embed


def watches_embed(rows) -> discord.Embed:
    embed = discord.Embed(title="Your price alerts", color=NEUTRAL)
    if not rows:
        embed.description = "None yet. Add one with `/watch add`."
        return embed
    lines = []
    for r in rows:
        now = f"now {kina(r['price'])}" if r["price"] else "not listed"
        hit = " ✅" if r["price"] and r["price"] <= r["below"] else ""
        lines.append(f"**{r['name']}**: below {kina(r['below'])} ({now}){hit}")
    embed.description = clip("\n".join(lines), 4000)
    return embed


def alert_text(a: Alert) -> str:
    listed = f", {a.listings} listed" if a.listings else ""
    return (f"<@{a.user_id}> **{a.name}** is listed at **{kina(a.price)}** "
            f"(your alert: below {kina(a.below)}{listed}).")
