"""Small numeric helpers (stdlib only)."""

import math
import statistics
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone


def parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def percentile_rank(values: list[float], x: float) -> float:
    """Share of ``values`` at or below ``x`` (0 = new low, 1 = new high)."""
    return sum(v <= x for v in values) / len(values)


def growth_per_day(points: list[tuple[datetime, float]]) -> float | None:
    """Least-squares fit of log(price) against time: the average change per day (0.02 = +2%/day)."""
    pts = [(t.timestamp() / 86400, math.log(p)) for t, p in points if p and p > 0]
    if len(pts) < 3:
        return None
    mx = statistics.fmean(x for x, _ in pts)
    my = statistics.fmean(y for _, y in pts)
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in pts) / sxx
    return math.exp(slope) - 1


def daily_volatility(points: list[tuple[datetime, float]]) -> float | None:
    """Standard deviation of the log returns between points, scaled to one day."""
    if len(points) < 4:
        return None
    returns = [math.log(b / a) for (_, a), (_, b) in zip(points, points[1:]) if a > 0 and b > 0]
    gaps = [(t2 - t1).total_seconds() for (t1, _), (t2, _) in zip(points, points[1:])]
    step_days = statistics.median(gaps) / 86400 if gaps else 0
    if len(returns) < 3 or step_days <= 0:
        return None
    return statistics.stdev(returns) / math.sqrt(step_days)


def level_shift(daily: list[tuple[datetime, float]], min_change: float = 0.25,
                min_after: int = 2) -> tuple[datetime, float] | None:
    """The most recent abrupt change of price level in a series of daily medians: the first day of
    the new level and the ratio new/old (0.6 = dropped 40%). A shift needs a jump of ``min_change``
    or more between the medians of up to a week either side, at least ``min_after`` days at the new
    level, quiet days within each side (a jump several times the day-to-day noise) and most of the
    jump happening from one day to the next, which tells a step (a patch, a drop-rate change) from
    a steady slide."""
    logs = [(t, math.log(p)) for t, p in daily if p and p > 0]
    threshold = math.log(1 + min_change)
    for i in range(len(logs) - min_after, 3, -1):  # latest split first, 4+ days before it
        before = [v for _, v in logs[max(0, i - 7):i]]
        after = [v for _, v in logs[i:i + 7]]
        jump = statistics.median(after) - statistics.median(before)
        # ×10 or more is a supply gap (only absurd listings left), not a new level
        if abs(jump) < threshold or abs(jump) > math.log(10):
            continue
        noise = max(_mad(before), _mad(after), 0.05)
        step = logs[i][1] - logs[i - 1][1]
        if abs(jump) >= 4 * noise and step * jump > 0 and abs(step) >= 0.5 * abs(jump):
            return logs[i][0], math.exp(jump)
    return None


def _mad(values: list[float]) -> float:
    m = statistics.median(values)
    return statistics.median(abs(v - m) for v in values)


def robust_sd(values: list[float]) -> float:
    """1.4826 × the median absolute deviation: the standard deviation of normal data, unmoved by outliers."""
    return 1.4826 * _mad(values) if values else 0.0


def weighted_median(values: list[float], weights: list[float]) -> float | None:
    """The value at which half the total weight lies on each side."""
    pairs = sorted((v, w) for v, w in zip(values, weights) if w > 0)
    if not pairs:
        return None
    half, acc = sum(w for _, w in pairs) / 2, 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def rolling_median_ratio(points: list[tuple[datetime, float]], hours: float = 24) -> list[tuple[datetime, float]]:
    """Each price divided by the median of the prices within ±hours/2 of it: what is left once the
    trend is taken out (1.05 = 5% above the local level)."""
    half = timedelta(hours=hours / 2)
    times = [t for t, _ in points]
    out = []
    for t, p in points:
        window = [q for _, q in points[bisect_left(times, t - half):bisect_right(times, t + half)]]
        m = statistics.median(window)
        if m > 0:
            out.append((t, p / m))
    return out


def kina(n: float | None) -> str:
    if n is None:
        return "?"
    sign, n = ("-" if n < 0 else ""), abs(n)
    for size, suffix in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if n >= size:
            text = f"{n / size:.2f}".rstrip("0").rstrip(".") if n < size * 100 else f"{n / size:.0f}"
            return f"{sign}{text}{suffix}"
    return f"{sign}{n:.0f}"


def parse_kina(text: str) -> float:
    """'1.5m' → 1500000, '250k' → 250000, '12,000' → 12000."""
    t = text.strip().lower().replace(",", "").replace("_", "")
    scale = {"k": 1e3, "m": 1e6, "b": 1e9}.get(t[-1:], 1)
    number = float(t[:-1] if scale != 1 else t)
    if number <= 0:
        raise ValueError("price must be above 0")
    return number * scale


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "?"
    return f"{x:+.0%}" if signed else f"{x:.0%}"
