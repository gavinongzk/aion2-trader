"""The Discord bot: refreshes the data every hour, posts new ideas, answers slash commands and sends
price alerts.

    /deals <strategy> [count]   the top flip, craft or speculation ideas, with reasons
    /item <name>                one item: price, usual price, range, trend, demand, any ideas
    /watch add|remove|list      alerts when an item is listed at or below your price
    /scorecard                  how past calls did at 1, 3 and 7 days
    /timing                     hour-of-day and weekday patterns, market-wide price-level changes
    /refresh                    collect now (needs the Manage Server permission)

The token comes from the DISCORD_TOKEN environment variable or a .env file next to config.toml.
"""

import asyncio
import fcntl
import logging
import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from . import analysis, collect, compare, db, report, scorecard, timing, views, watch
from .api import Client
from .config import Config
from .stats import parse_kina

log = logging.getLogger("aion2.bot")
discord.VoiceClient.warn_nacl = False  # no voice here; skip the PyNaCl warning


def read_token(env_file: str = ".env") -> str:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token and Path(env_file).exists():
        for line in Path(env_file).read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_TOKEN":
                token = value.strip().strip("'\"")
    if not token or token == "paste-your-bot-token-here":
        raise SystemExit("No bot token: put DISCORD_TOKEN=... in .env (see README)")
    return token


class TraderBot(discord.Client):
    def __init__(self, cfg: Config):
        super().__init__(intents=discord.Intents.default())  # slash commands need no privileged intents
        self.cfg = cfg
        self.tree = app_commands.CommandTree(self)
        self.server_id: int | None = None
        self.ideas: dict[str, list[analysis.Idea]] = {}
        self.sections: dict[str, list[str]] = {}  # scorecard, timing, market events
        self.updated_at = None
        self.posted: set[tuple[str, int]] = set()
        self.busy = asyncio.Lock()
        register_commands(self)

    # --- data -----------------------------------------------------------------------------

    def _analyze(self, log_calls: bool = False) -> None:
        conn = db.connect(self.cfg.db)
        try:
            self.server_id, profiles, self.ideas = analysis.analyze_all(conn, self.cfg)
            if log_calls:  # the scorecard: log today's ideas, score the ones that came due
                logged, scored = scorecard.update(conn, self.server_id, self.ideas, self.cfg.sales_fee,
                                                  posted=self.top_keys() - self.posted)
                log.info("scorecard: %d calls logged, %d outcomes scored", logged, scored)
            self.sections = report.insight_sections(conn, self.server_id, profiles, self.cfg)
        finally:
            conn.close()
        self.updated_at = discord.utils.utcnow()

    def _collect_and_analyze(self) -> list[watch.Alert]:
        collect.run(self.cfg, log=log.info)
        self._analyze(log_calls=True)
        if self.cfg.compare.in_bot:  # the valuation and its calls; a failure here mustn't stop the alerts
            try:
                compare.refresh(self.cfg, log=log.info)
            except Exception:
                log.exception("compare failed")
        conn = db.connect(self.cfg.db)
        try:
            return watch.due(conn, self.server_id)
        finally:
            conn.close()

    def top_keys(self) -> set[tuple[str, int]]:
        n = self.cfg.discord.post_top
        return {(s, i.item_key) for s, found in self.ideas.items() for i in found[:n]}

    async def refresh(self) -> None:
        async with self.busy:
            alerts = await asyncio.to_thread(self._collect_and_analyze)
        await self.post_new_ideas()
        await self.send_alerts(alerts)
        await self.post_scorecard()

    # --- lifecycle ------------------------------------------------------------------------

    async def setup_hook(self) -> None:
        guild_id = self.cfg.discord.guild_id
        if guild_id:
            guild = discord.Object(guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        try:  # answer from stored data until the first refresh is done
            await asyncio.to_thread(self._analyze)
            self.posted = self.top_keys()  # don't repost what was already there before a restart
        except SystemExit:
            log.info("no stored data yet; the first refresh will collect it")
        self.refresher.change_interval(minutes=self.cfg.discord.refresh_minutes)
        self.refresher.start()

    @tasks.loop(minutes=60)
    async def refresher(self):
        try:
            await self.refresh()
        except Exception:
            log.exception("refresh failed; trying again next time")

    @refresher.before_loop
    async def _wait_ready(self):
        await self.wait_until_ready()

    async def on_ready(self):
        log.info("logged in as %s; serving server %s", self.user, self.server_id)

    # --- posting --------------------------------------------------------------------------

    async def _channel(self, channel_id: int):
        if not channel_id:
            return None
        try:
            return self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        except discord.DiscordException:
            log.warning("can't reach channel %s", channel_id)
            return None

    async def post_new_ideas(self) -> None:
        channel = await self._channel(self.cfg.discord.channel_id)
        n = self.cfg.discord.post_top
        if channel is not None:
            for strategy, found in self.ideas.items():
                new = [i for i in found[:n] if (strategy, i.item_key) not in self.posted]
                if new:
                    await channel.send(embed=views.ideas_embed(
                        strategy, new, title=f"New: {views.TITLES[strategy]}", updated_at=self.updated_at))
        self.posted = self.top_keys()

    async def post_scorecard(self) -> None:
        """Every ``scorecard_days`` days, once there are outcomes: how past calls did, and timing."""
        channel = await self._channel(self.cfg.discord.channel_id)
        if channel is None or self.server_id is None:
            return
        conn = db.connect(self.cfg.db)
        try:
            lines, _ = scorecard.summary(conn, self.server_id)
            if not lines or not scorecard.due_for_post(conn, self.cfg.discord.scorecard_days):
                return
            await channel.send(embed=views.sections_embed("Weekly scorecard and timing", self.sections,
                                                          self.updated_at))
            scorecard.mark_posted(conn)
        finally:
            conn.close()

    async def send_alerts(self, alerts: list[watch.Alert]) -> None:
        for a in alerts:
            channel = await self._channel(a.channel_id)
            if channel is not None:
                await channel.send(views.alert_text(a),
                                   allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))


# --- commands -------------------------------------------------------------------------------

def register_commands(bot: TraderBot) -> None:
    tree, cfg = bot.tree, bot.cfg

    def no_data():
        return "No market data yet: the first refresh is still running. Try again in a few minutes."

    def find_item(conn, text: str):
        """An autocomplete value (an item id) or typed text: the best matching item row."""
        if text.isdigit():
            row = conn.execute("SELECT item_key, name FROM items WHERE server_id=? AND item_key=?",
                               (bot.server_id, int(text))).fetchone()
            if row:
                return row
        found = analysis.search_items(conn, bot.server_id, text, limit=1)
        return found[0] if found else None

    async def item_autocomplete(interaction: discord.Interaction, current: str):
        if bot.server_id is None:
            return []
        conn = db.connect(cfg.db)
        try:
            rows = analysis.search_items(conn, bot.server_id, current)
        finally:
            conn.close()
        return [app_commands.Choice(name=views.clip(r["name"], 100), value=str(r["item_key"])) for r in rows]

    @tree.command(name="deals", description="Top trade ideas, with the numbers behind them")
    @app_commands.describe(strategy="flip: resell / craft: upgrade / speculate: dips, uptrends, squeezes",
                           count="how many to show (1-10)")
    async def deals(interaction: discord.Interaction, strategy: Literal["flip", "craft", "speculate"],
                    count: app_commands.Range[int, 1, 10] = 5):
        if not bot.ideas:
            await interaction.response.send_message(no_data(), ephemeral=True)
            return
        await interaction.response.send_message(embed=views.ideas_embed(
            strategy, bot.ideas.get(strategy, [])[:count], updated_at=bot.updated_at))

    @tree.command(name="item", description="Price, usual price, trend and demand of one item")
    @app_commands.describe(name="start typing the item's name")
    @app_commands.autocomplete(name=item_autocomplete)
    async def item(interaction: discord.Interaction, name: str):
        if bot.server_id is None:
            await interaction.response.send_message(no_data(), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        def load():
            conn = db.connect(cfg.db)
            try:
                row = find_item(conn, name)
                if row is None:
                    return None, [], []
                min_shift = cfg.strategy.shift_min_change
                profile = analysis.load_profile(conn, bot.server_id, row["item_key"], min_shift)
                if not profile.closes:  # not on the shortlist: fetch its history now (one request)
                    client = Client(cfg.base_url, bot.server_id, cfg.delay_seconds)
                    collect.fetch_cached(client, conn, bot.server_id, collect.price_request(row["item_key"]),
                                         cfg.collect.cache_minutes, log.info)
                    profile = analysis.load_profile(conn, bot.server_id, row["item_key"], min_shift)
                tz = ZoneInfo(cfg.timezone)
                notes = [profile.shift_note()] if profile.shift_note() else []
                for pattern in (timing.hourly(profile.closes, tz), timing.weekly(profile.closes, tz)):
                    if pattern is not None:
                        weak = "" if timing.is_edge(pattern) else " (weak: not reliable yet)"
                        notes.append(f"{pattern.describe()}{weak}")
                return profile, notes, analysis.material_uses(conn, bot.server_id, profile.key)
            finally:
                conn.close()

        profile, notes, uses = await asyncio.to_thread(load)
        if profile is None:
            await interaction.followup.send(f"No item matches “{name}”.")
            return
        ideas = [i for found in bot.ideas.values() for i in found if i.item_key == profile.key]
        await interaction.followup.send(embed=views.item_embed(profile, ideas, bot.updated_at, notes, uses))

    @tree.command(name="scorecard", description="How the bot's past calls turned out, by strategy")
    async def scorecard_cmd(interaction: discord.Interaction):
        if bot.server_id is None:
            await interaction.response.send_message(no_data(), ephemeral=True)
            return
        title = next(k for k in bot.sections if k.startswith("Scorecard"))
        await interaction.response.send_message(embed=views.sections_embed(
            "Scorecard", {title: bot.sections[title]}, bot.updated_at))

    @tree.command(name="timing", description="When items are cheapest and dearest, and market-wide events")
    async def timing_cmd(interaction: discord.Interaction):
        if bot.server_id is None:
            await interaction.response.send_message(no_data(), ephemeral=True)
            return
        shown = {k: v for k, v in bot.sections.items() if not k.startswith("Scorecard")}
        await interaction.response.send_message(embed=views.sections_embed("Timing and market events", shown,
                                                                           bot.updated_at))

    group = app_commands.Group(name="watch", description="Alerts when an item gets cheap")

    @group.command(name="add", description="Alert me when this item is listed at or below a price")
    @app_commands.describe(item="start typing the item's name", below="price in Kina, e.g. 250k or 1.5m")
    @app_commands.autocomplete(item=item_autocomplete)
    async def watch_add(interaction: discord.Interaction, item: str, below: str):
        if bot.server_id is None:
            await interaction.response.send_message(no_data(), ephemeral=True)
            return
        try:
            price = parse_kina(below)
        except ValueError:
            await interaction.response.send_message(f"“{below}” isn't a price: try 250k, 1.5m or 12000.",
                                                    ephemeral=True)
            return
        conn = db.connect(cfg.db)
        try:
            row = find_item(conn, item)
            if row is None:
                await interaction.response.send_message(f"No item matches “{item}”.", ephemeral=True)
                return
            mine = watch.of_user(conn, interaction.user.id, bot.server_id)
            if len(mine) >= cfg.discord.max_watches and row["item_key"] not in {r["item_key"] for r in mine}:
                await interaction.response.send_message(
                    f"You have {len(mine)} alerts, the most allowed; remove one first.", ephemeral=True)
                return
            watch.add(conn, interaction.user.id, bot.server_id, row["item_key"], price, interaction.channel_id)
        finally:
            conn.close()
        await interaction.response.send_message(
            f"I'll ping you here when **{row['name']}** is listed at or below **{views.kina(price)}** "
            f"(checked every {cfg.discord.refresh_minutes} min).", ephemeral=True)

    @group.command(name="remove", description="Stop an alert")
    @app_commands.autocomplete(item=item_autocomplete)
    async def watch_remove(interaction: discord.Interaction, item: str):
        conn = db.connect(cfg.db)
        try:
            row = find_item(conn, item) if bot.server_id is not None else None
            gone = row is not None and watch.remove(conn, interaction.user.id, bot.server_id, row["item_key"])
        finally:
            conn.close()
        await interaction.response.send_message(
            f"Removed the alert on **{row['name']}**." if gone else "You have no alert on that item.",
            ephemeral=True)

    @group.command(name="list", description="Your price alerts")
    async def watch_list(interaction: discord.Interaction):
        conn = db.connect(cfg.db)
        try:
            rows = watch.of_user(conn, interaction.user.id, bot.server_id) if bot.server_id is not None else []
        finally:
            conn.close()
        await interaction.response.send_message(embed=views.watches_embed(rows), ephemeral=True)

    tree.add_command(group)

    @tree.command(name="refresh", description="Collect fresh market data now")
    @app_commands.default_permissions(manage_guild=True)
    async def refresh(interaction: discord.Interaction):
        if bot.busy.locked():
            await interaction.response.send_message("A refresh is already running.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        await bot.refresh()
        counts = ", ".join(f"{len(v)} {k}" for k, v in bot.ideas.items())
        await interaction.followup.send(f"Refreshed: {counts} ideas.", ephemeral=True)

    @tree.error
    async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        cause = getattr(error, "original", error)
        if isinstance(cause, discord.NotFound) and cause.code == 10062:
            # the interaction expired (took over 3 s, or another bot instance answered it): no reply possible
            log.warning("/%s expired before the bot could answer", interaction.command and interaction.command.name)
            return
        log.exception("command failed", exc_info=error)
        message = "Something went wrong with that command; it's in the bot's log."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass  # can't reach the user about it; the log has it


def single_instance(db_path: str):
    """Hold a lock next to the database while the bot runs: two copies of the bot would both receive
    every command, and one of them always fails to answer."""
    lock = open(f"{db_path}.bot.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("The bot is already running (another terminal?). Stop that one with Ctrl+C first.") from None
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def run(cfg: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _lock = single_instance(cfg.db)  # held until the process exits
    try:
        TraderBot(cfg).run(read_token(), log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("Discord rejected the token in .env: copy it again from the Developer Portal "
                         "(Bot → Reset Token)") from None
