"""The online bot's side of each hourly run: ``publish`` writes reports/bot.json, everything the
slash-command function on Vercel answers from (ready-made embeds for /deals, /scorecard, /timing and
every item's /item card, plus the item list for autocomplete); ``notify`` posts what the gateway bot
used to post: new ideas, price alerts (the watches live in Supabase) and the weekly scorecard.

The slash commands themselves (``COMMANDS``) are registered with Discord once, by
``python -m aion2 commands``; Discord then sends them to the function, not to a bot that has to
stay connected."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import analysis, db, discord_rest, embeds, report, scorecard, timing, watch
from .config import Config
from .supa import Supabase

STRING, INTEGER = 3, 4
COMMANDS = [
    {"name": "deals", "description": "Top trade ideas, with the numbers behind them", "options": [
        {"type": STRING, "name": "strategy", "description": "flip: resell / craft: upgrade / speculate: dips, uptrends, squeezes",
         "required": True, "choices": [{"name": s, "value": s} for s in ("flip", "craft", "speculate")]},
        {"type": INTEGER, "name": "count", "description": "how many to show (1-10)", "min_value": 1, "max_value": 10}]},
    {"name": "item", "description": "Price, fair value, world price, trend and demand of one item", "options": [
        {"type": STRING, "name": "name", "description": "start typing the item's name", "required": True,
         "autocomplete": True}]},
    {"name": "scorecard", "description": "How the bot's past calls turned out, by strategy"},
    {"name": "timing", "description": "When items are cheapest and dearest, and market-wide events"},
    {"name": "watch", "description": "Alerts when an item gets cheap", "options": [
        {"type": 1, "name": "add", "description": "Alert me when this item is listed at or below a price", "options": [
            {"type": STRING, "name": "item", "description": "start typing the item's name", "required": True,
             "autocomplete": True},
            {"type": STRING, "name": "below", "description": "price in Kina, e.g. 250k or 1.5m", "required": True}]},
        {"type": 1, "name": "remove", "description": "Stop an alert", "options": [
            {"type": STRING, "name": "item", "description": "the item", "required": True, "autocomplete": True}]},
        {"type": 1, "name": "list", "description": "Your price alerts"}]},
    {"name": "refresh", "description": "Collect fresh market data now", "default_member_permissions": "32"},
]


def publish(cfg: Config, log=print) -> Path:
    """Write reports/bot.json from the stored data and the latest compare.json."""
    conn = db.connect(cfg.db)
    try:
        server_id, profiles, ideas = analysis.analyze_all(conn, cfg)
        sections = report.insight_sections(conn, server_id, profiles, cfg)
        valuations = {}
        compare_path = Path(cfg.reports) / "compare.json"
        if compare_path.exists():
            valuations = {v["key"]: v for v in json.loads(compare_path.read_text()).get("buy", [])}
        now = datetime.now(timezone.utc)
        tz = ZoneInfo(cfg.timezone)
        cards = {}
        for key, p in profiles.items():
            notes = [p.shift_note()] if p.shift_note() else []
            for pattern in (timing.hourly(p.closes, tz), timing.weekly(p.closes, tz)):
                if pattern is not None:
                    notes.append(pattern.describe() + ("" if timing.is_edge(pattern) else " (weak: not reliable yet)"))
            mine = [i for found in ideas.values() for i in found if i.item_key == key]
            cards[str(key)] = embeds.item_embed(p, mine, now, notes, analysis.material_uses(conn, server_id, key),
                                                valuation=valuations.get(key))
        score = {k: v for k, v in sections.items() if k.startswith("Scorecard")}
        data = {
            "updated_at": now.isoformat(), "server_id": server_id,
            "refresh_minutes": cfg.discord.refresh_minutes, "max_watches": cfg.discord.max_watches,
            "deals": {s: embeds.ideas_embed(s, found[:10], updated_at=now) for s, found in ideas.items()},
            "scorecard": embeds.sections_embed("Scorecard", score, now),
            "timing": embeds.sections_embed("Timing and market events",
                                            {k: v for k, v in sections.items() if k not in score}, now),
            "items": [[r["item_key"], r["name"], r["price"], r["listings"]] for r in conn.execute(
                "SELECT item_key, name, price, listings FROM items WHERE server_id=? ORDER BY name", (server_id,))],
            "cards": cards,
        }
    finally:
        conn.close()
    path = Path(cfg.reports) / "bot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")))
    log(f"bot data: {len(cards)} item cards, {sum(len(v['fields']) for v in data['deals'].values())} ideas")
    return path


def notify(cfg: Config, token: str, channel_id: int | str | None, supabase: Supabase | None, log=print) -> None:
    """Post new ideas, due price alerts and the weekly scorecard, as the gateway bot did each refresh."""
    conn = db.connect(cfg.db)
    try:
        server_id, profiles, ideas = analysis.analyze_all(conn, cfg)
        n = cfg.discord.post_top
        top = sorted({f"{s}:{i.item_key}" for s, found in ideas.items() for i in found[:n]})
        row = conn.execute("SELECT value FROM meta WHERE key='posted_ideas'").fetchone()
        posted = set(json.loads(row["value"])) if row else None  # None: first run, post nothing old
        now = datetime.now(timezone.utc)
        if channel_id and posted is not None:
            for strategy, found in ideas.items():
                new = [i for i in found[:n] if f"{strategy}:{i.item_key}" not in posted]
                if new:
                    discord_rest.send(token, channel_id, embed=embeds.ideas_embed(
                        strategy, new, title=f"New: {report.TITLES[strategy]}", updated_at=now))
                    log(f"posted {len(new)} new {strategy} ideas")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('posted_ideas', ?)", (json.dumps(top),))
        conn.commit()

        if supabase is not None:
            watches = supabase.select("watches", server_id=server_id)
            alerts, updates = watch.check(watches, watch.prices(conn, server_id))
            for a in alerts:
                discord_rest.send(token, a.channel_id, content=embeds.alert_text(a), mention_users=True)
            for user, key, price in updates:
                supabase.update("watches", {"last_alert_price": price}, user_id=user, server_id=server_id, item_key=key)
            log(f"alerts: {len(alerts)} sent, {len(watches)} watches")

        lines, _ = scorecard.summary(conn, server_id)
        if channel_id and lines and scorecard.due_for_post(conn, cfg.discord.scorecard_days):
            sections = report.insight_sections(conn, server_id, profiles, cfg)
            discord_rest.send(token, channel_id, embed=embeds.sections_embed("Weekly scorecard and timing", sections, now))
            scorecard.mark_posted(conn)
            log("posted the weekly scorecard")
    finally:
        conn.close()


def discord_settings(cfg: Config) -> tuple[str | None, str | None, str | None]:
    """(token, channel id, guild id): the environment first (the cloud job's secrets), then config."""
    channel = os.environ.get("DISCORD_CHANNEL_ID") or (str(cfg.discord.channel_id) if cfg.discord.channel_id else None)
    guild = os.environ.get("DISCORD_GUILD_ID") or (str(cfg.discord.guild_id) if cfg.discord.guild_id else None)
    return os.environ.get("DISCORD_TOKEN"), channel, guild
