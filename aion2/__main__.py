"""python -m aion2 {servers,collect,report,run,scorecard,compare,publish,commands,bot} [--config config.toml]"""

import argparse

from . import analysis, collect, compare, config, db, report, scorecard
from .api import Client


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m aion2", description=__doc__)
    parser.add_argument("command", choices=["servers", "collect", "report", "run", "scorecard", "compare",
                                            "publish", "commands", "bot"],
                        help="servers: list them; collect: fetch data; report: analyse it; run: both; "
                             "scorecard: how past calls did; compare: prices across comparable servers; "
                             "publish: write bot.json and post to Discord (with DISCORD_TOKEN); "
                             "commands: register the slash commands with Discord; bot: the gateway Discord bot")
    parser.add_argument("--config", default="config.toml", help="settings file (default: config.toml)")
    args = parser.parse_args(argv)
    cfg = config.load(args.config)

    if args.command == "servers":
        listing = Client(cfg.base_url, delay=0).get("/servers")
        for s in listing["servers"]:
            mark = " (default)" if s["server_id"] == listing["default"] else ""
            data = "" if s.get("has_data") else "  [no data]"
            print(f"{s['server_id']:>6}  {s['name']:<24} {s.get('faction') or '':<10} "
                  f"{s.get('region_name') or ''}{mark}{data}")
        return
    if args.command == "compare":
        print(f"\nSaved {compare.run(cfg)}")
        return
    if args.command in ("publish", "commands"):
        from . import publish
        from .supa import Supabase
        token, channel, guild = publish.discord_settings(cfg)
        token = token or publish_token()
        if args.command == "commands":
            if not token:
                raise SystemExit("No bot token: set DISCORD_TOKEN or put it in .env")
            done = publish.discord_rest.register_commands(token, publish.COMMANDS, guild)
            print(f"Registered {len(done)} commands" + (f" in server {guild}" if guild else " (global)"))
            return
        print(f"Saved {publish.publish(cfg)}")
        if token:
            publish.notify(cfg, token, channel, Supabase.from_env())
        else:
            print("No DISCORD_TOKEN: nothing posted")
        return
    if args.command == "bot":
        from . import bot  # needs discord.py; the other commands don't
        bot.run(cfg)
        return
    if args.command in ("collect", "run"):
        collect.run(cfg)
    if args.command in ("report", "run", "scorecard"):
        conn = db.connect(cfg.db)
        server_id, profiles, ideas = analysis.analyze_all(conn, cfg)
        logged, scored = scorecard.update(conn, server_id, ideas, cfg.sales_fee)
        if args.command == "scorecard":
            lines, pending = scorecard.summary(conn, server_id)
            print("\n".join(scorecard.render(lines, pending)))
            return
        sections = report.insight_sections(conn, server_id, profiles, cfg)
        path = report.write(server_id, ideas, cfg, sections)
        print(report.render(server_id, ideas, cfg, sections))
        print(f"\nSaved {path} (+ latest.md, latest.csv, latest.json); "
              f"scorecard: {logged} new calls logged, {scored} outcomes scored")


def publish_token(env_file: str = ".env") -> str | None:
    """The bot token from .env, as the gateway bot reads it (locally; the cloud job has DISCORD_TOKEN)."""
    try:
        for line in open(env_file):
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_TOKEN" and value.strip() not in ("", "paste-your-bot-token-here"):
                return value.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return None


if __name__ == "__main__":
    main()
