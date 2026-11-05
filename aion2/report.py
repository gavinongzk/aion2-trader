"""Prints the ideas and writes them as Markdown, CSV and JSON (the JSON is what a bot would read)."""

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import scorecard, timing
from .analysis import Idea, shift_days
from .config import Config

TITLES = {
    "flip": "Flip: buy under the usual price, relist",
    "craft": "Craft: sell above crafting cost",
    "speculate": "Speculate: dips, uptrends and squeezes",
}


def estimated_ok(ideas: dict[str, list[Idea]]) -> bool:
    """True when the ideas rest on real sales statistics (no idea says its demand is estimated)."""
    return not any("(est.)" in r for found in ideas.values() for i in found for r in i.reasons)


def insight_sections(conn, server_id: int, profiles: dict, cfg: Config) -> dict[str, list[str]]:
    """The sections after the ideas: the scorecard of past calls, timing, and market-wide events."""
    tz = ZoneInfo(cfg.timezone)
    lines, pending = scorecard.summary(conn, server_id)
    timing_lines = [timing.market_summary(timing.market_hours(profiles.values(), tz))]
    timing_lines += [f"**{p.name}**: {pattern.describe()}" for p, pattern in timing.highlights(profiles.values(), tz)]
    events = [f"{day:%d %b}: {n} items changed price level at once (patch, maintenance or event?)"
              for day, n in shift_days(profiles)[:5]] or ["No market-wide price-level changes in the last 30 days."]
    return {
        "Scorecard: how past calls did": scorecard.render(lines, pending),
        f"Timing ({cfg.timezone})": timing_lines,
        "Market events": events,
    }


def render(server_id: int, ideas: dict[str, list[Idea]], cfg: Config,
           sections: dict[str, list[str]] | None = None) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Aion 2 market ideas, server {server_id}, {stamp}", "",
             f"Sales fee assumed: {cfg.sales_fee:.0%}. Prices in Kina; data from aion2.exchange.", ""]
    if not estimated_ok(ideas):
        lines += ["No sales statistics on this server: demand is estimated from listings that disappear "
                  "between hourly snapshots (bought or withdrawn), and listing depth is unknown.", ""]
    for strategy, title in TITLES.items():
        found = ideas.get(strategy, [])
        lines += [f"## {title}", ""]
        if not found:
            lines += ["Nothing passes the filters right now.", ""]
            continue
        for rank, idea in enumerate(found[: cfg.strategy.top], 1):
            lines.append(f"{rank}. **{idea.name}** `{idea.item_key}`: {idea.headline}")
            lines += [f"   - {reason}" for reason in idea.reasons]
        lines.append("")
    for title, body in (sections or {}).items():
        lines += [f"## {title}", ""] + [f"- {line}" for line in body] + [""]
    return "\n".join(lines)


def write(server_id: int, ideas: dict[str, list[Idea]], cfg: Config,
          sections: dict[str, list[str]] | None = None) -> Path:
    folder = Path(cfg.reports)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    md = folder / f"report-{stamp}.md"
    md.write_text(render(server_id, ideas, cfg, sections), encoding="utf-8")
    (folder / "latest.md").write_text(md.read_text(encoding="utf-8"), encoding="utf-8")

    with open(folder / "latest.csv", "w", newline="", encoding="utf-8") as f:
        out = csv.writer(f)
        out.writerow(["strategy", "rank", "item_key", "name", "score", "headline", "reasons"])
        for strategy, found in ideas.items():
            for rank, idea in enumerate(found, 1):
                out.writerow([strategy, rank, idea.item_key, idea.name, round(idea.score, 4),
                              idea.headline, " | ".join(idea.reasons)])

    payload = {"server_id": server_id, "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "sales_fee": cfg.sales_fee, "ideas": {k: [asdict(i) for i in v] for k, v in ideas.items()}}
    (folder / "latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return md
