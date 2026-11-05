"""The scorecard: every idea is logged when it is made, and 24h, 72h and 7 days later checked
against what the price actually did. Over weeks this says which strategies work on this server,
and it is the labelled data any future model would learn from.

For each call and horizon:
  price     the cheapest listing at that time (the nearest hourly snapshot, within 3 hours)
  best      the 80th percentile of the cheapest listing over the whole window: a price you could
            realistically have sold at (the maximum is often one absurd listing)
  ret       selling at ``price`` after the fee, against the entry (the buy price, or the crafting cost)
  best_ret  the same at ``best``
  hit       ``best`` reached the call's target (a craft: sold above its cost after the fee)

Prices come from item_snapshots, which every collect fills for all items, so the bot (or the
collector) must keep running for calls to be scored; a horizon without data for 2 days is marked
as such and left out of the summary.
"""

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .analysis import Idea
from .stats import parse_ts, pct, quantile

HORIZONS = (24, 72, 168)
TOLERANCE = timedelta(hours=3)
GIVE_UP = timedelta(days=2)
RECALL_AFTER = timedelta(hours=24)  # the same idea again within a day is the same call


def _kind(idea: Idea) -> str:
    """The flavour scored separately: the speculation pattern(s), else the strategy."""
    patterns = idea.metrics.get("patterns")
    return "+".join(patterns) if patterns else idea.strategy


def record(conn, server_id: int, ideas: dict[str, list[Idea]], posted: set[tuple[str, int]] = frozenset(),
           now: datetime | None = None) -> int:
    """Log the ideas not already logged in the last day. Returns how many were new."""
    now = now or datetime.now(timezone.utc)
    captured = dict(conn.execute("SELECT item_key, captured_at FROM items WHERE server_id=?", (server_id,)).fetchall())
    new = 0
    for strategy, found in ideas.items():
        for rank, idea in enumerate(found, 1):
            entry, target = idea.metrics.get("entry"), idea.metrics.get("target")
            if not entry or not target:
                continue
            # the time of the data the idea was made from, not the time of the analysis
            called_at = parse_ts(captured[idea.item_key]) if captured.get(idea.item_key) else now
            recent = conn.execute("""SELECT 1 FROM calls WHERE server_id=? AND strategy=? AND item_key=?
                                     AND called_at > ?""",
                                  (server_id, strategy, idea.item_key,
                                   (called_at - RECALL_AFTER).isoformat())).fetchone()
            if recent:
                continue
            conn.execute("""INSERT INTO calls (server_id, strategy, kind, item_key, name, called_at, entry, target,
                                               score, rank, posted, metrics)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (server_id, strategy, _kind(idea), idea.item_key, idea.name, called_at.isoformat(),
                          entry, target, idea.score, rank, int((strategy, idea.item_key) in posted),
                          json.dumps(idea.metrics, default=str)))
            new += 1
    conn.commit()
    return new


def evaluate(conn, server_id: int, fee: float, now: datetime | None = None) -> int:
    """Score every horizon that has passed and not been scored. Returns how many were scored."""
    now = now or datetime.now(timezone.utc)
    latest = conn.execute("SELECT MAX(captured_at) FROM item_snapshots WHERE server_id=?", (server_id,)).fetchone()[0]
    if latest is None:
        return 0
    data_until = parse_ts(latest)
    done = 0
    for call in conn.execute("SELECT * FROM calls WHERE server_id=?", (server_id,)).fetchall():
        called_at = parse_ts(call["called_at"])
        scored = {r[0] for r in conn.execute("SELECT horizon_h FROM outcomes WHERE call_id=?", (call["id"],))}
        todo = [h for h in HORIZONS if h not in scored and called_at + timedelta(hours=h) <= data_until]
        if not todo:
            continue
        # timestamps are compared as times, not strings: the API writes "Z", Python "+00:00"
        history = [(parse_ts(t), p) for t, p in conn.execute(
            "SELECT captured_at, price FROM item_snapshots WHERE server_id=? AND item_key=? AND price > 0",
            (server_id, call["item_key"]))]
        for h in todo:
            due = called_at + timedelta(hours=h)
            snaps = [(t, p) for t, p in history if called_at < t <= due + TOLERANCE]
            at_due = [p for t, p in sorted(snaps) if abs(t - due) <= TOLERANCE]
            if not at_due:
                if now - due > GIVE_UP:  # the collector wasn't running then: no outcome to be had
                    conn.execute("INSERT INTO outcomes VALUES (?,?,NULL,NULL,NULL,NULL,NULL,?)",
                                 (call["id"], h, now.isoformat()))
                continue
            price = at_due[-1]
            best = quantile([p for _, p in snaps], 0.8)
            ret = price * (1 - fee) / call["entry"] - 1
            best_ret = best * (1 - fee) / call["entry"] - 1
            hit = best_ret > 0 if call["strategy"] == "craft" else best >= call["target"]
            conn.execute("INSERT INTO outcomes VALUES (?,?,?,?,?,?,?,?)",
                         (call["id"], h, price, best, ret, best_ret, int(hit), now.isoformat()))
            done += 1
    conn.commit()
    return done


@dataclass
class Line:
    strategy: str
    kind: str
    horizon_h: int
    n: int
    hit_rate: float
    median_ret: float
    median_best_ret: float


def summary(conn, server_id: int, days: float | None = None, now: datetime | None = None,
            strategy: str | None = None) -> tuple[list[Line], int]:
    """Hit rate and median returns per strategy and kind and horizon, for calls made in the last
    ``days`` (all calls when None) of ``strategy`` (all when None); and how many calls are still
    waiting for an outcome."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat() if days else ""
    rows = conn.execute("""SELECT c.strategy, c.kind, o.horizon_h, o.ret, o.best_ret, o.hit
                           FROM calls c JOIN outcomes o ON o.call_id=c.id
                           WHERE c.server_id=? AND c.called_at >= ? AND o.price IS NOT NULL
                             AND c.strategy = COALESCE(?, c.strategy)""",
                        (server_id, since, strategy)).fetchall()
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["strategy"], r["kind"], r["horizon_h"]), []).append(r)
    lines = [Line(s, k, h, len(g), sum(r["hit"] for r in g) / len(g),
                  statistics.median(r["ret"] for r in g), statistics.median(r["best_ret"] for r in g))
             for (s, k, h), g in sorted(groups.items())]
    pending = conn.execute("""SELECT COUNT(*) FROM calls c WHERE c.server_id=? AND c.called_at >= ? AND
                              c.strategy = COALESCE(?, c.strategy) AND
                              (SELECT COUNT(*) FROM outcomes o WHERE o.call_id=c.id) < ?""",
                           (server_id, since, strategy, len(HORIZONS))).fetchone()[0]
    return lines, pending


def render(lines: list[Line], pending: int, min_n: int = 1) -> list[str]:
    """Plain lines, one per strategy/kind, with the three horizons side by side."""
    if not lines:
        return [f"No outcomes yet: {pending} call(s) waiting. The first ones are scored 24 hours after they're made."]
    by_kind: dict[tuple, dict[int, Line]] = {}
    for line in lines:
        by_kind.setdefault((line.strategy, line.kind), {})[line.horizon_h] = line
    out = []
    for (strategy, kind), horizons in by_kind.items():
        cells = []
        for h in HORIZONS:
            line = horizons.get(h)
            label = f"{h // 24}d"
            cells.append(f"{label}: {pct(line.hit_rate, False)} hit, median {pct(line.median_ret)} (n={line.n})"
                         if line and line.n >= min_n else f"{label}: —")
        name = kind if strategy == "speculate" else strategy if kind == strategy else f"{strategy} ({kind})"
        out.append(f"{name}: " + " · ".join(cells))
    out.append(f"{pending} call(s) still waiting for an outcome.")
    return out


def due_for_post(conn, every_days: float, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    row = conn.execute("SELECT value FROM meta WHERE key='scorecard_posted_at'").fetchone()
    return row is None or now - parse_ts(row["value"]) >= timedelta(days=every_days)


def mark_posted(conn, now: datetime | None = None) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('scorecard_posted_at', ?)",
                 ((now or datetime.now(timezone.utc)).isoformat(),))
    conn.commit()


def update(conn, server_id: int, ideas: dict[str, list[Idea]], fee: float,
           posted: set[tuple[str, int]] = frozenset()) -> tuple[int, int]:
    """Log today's ideas and score what has come due: (calls logged, outcomes scored)."""
    return record(conn, server_id, ideas, posted), evaluate(conn, server_id, fee)
