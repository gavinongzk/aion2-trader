"""The bot's slash commands, as a Vercel function: Discord sends each command here (the
"Interactions Endpoint URL" in its developer portal), so no bot has to stay connected.

It answers from bot.json, which the hourly job writes (``python -m aion2 publish``) and deploys with
this function: ready-made embeds for /deals, /scorecard and /timing, a card for every item, and the
item list for autocomplete. /watch reads and writes the alerts in Supabase, which the hourly job
checks. /refresh starts the hourly job on GitHub.

Environment (Vercel → Project → Settings → Environment Variables): DISCORD_PUBLIC_KEY (from the
developer portal, not secret), SUPABASE_URL, SUPABASE_SERVICE_KEY (the project's secret key,
sb_secret_...), GITHUB_DISPATCH_TOKEN.
"""

import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PING, COMMAND, AUTOCOMPLETE = 1, 2, 4
PONG, MESSAGE, CHOICES = 1, 4, 8
EPHEMERAL = 64
REPO = "gavinongzk/aion2-trader"
NEUTRAL = 0x5B6573


# --- the commands (plain functions of the request and the data, so they can be tested) ---------

def kina(n):
    if n is None:
        return "?"
    sign, n = ("-" if n < 0 else ""), abs(n)
    for size, suffix in ((1e9, "b"), (1e6, "m"), (1e3, "k")):
        if n >= size:
            text = f"{n / size:.2f}".rstrip("0").rstrip(".") if n < size * 100 else f"{n / size:.0f}"
            return f"{sign}{text}{suffix}"
    return f"{sign}{n:.0f}"


def parse_kina(text: str) -> float:
    t = text.strip().lower().replace(",", "").replace("_", "")
    scale = {"k": 1e3, "m": 1e6, "b": 1e9}.get(t[-1:], 1)
    number = float(t[:-1] if scale != 1 else t)
    if number <= 0:
        raise ValueError("price must be above 0")
    return number * scale


def search(data: dict, text: str, limit: int = 25) -> list:
    """Items whose name has every word of ``text``, the most listed first (as the gateway bot did)."""
    words = text.lower().split()
    found = [i for i in data["items"] if i[1] and all(w in i[1].lower() for w in words)]
    return sorted(found, key=lambda i: (-(i[3] or 0), i[1]))[:limit]


def find(data: dict, text: str):
    """An autocomplete value (an item id) or typed text: the best matching item."""
    if text.isdigit():
        hit = next((i for i in data["items"] if i[0] == int(text)), None)
        if hit:
            return hit
    found = search(data, text, 1)
    return found[0] if found else None


def options(interaction: dict) -> dict:
    opts = interaction["data"].get("options", [])
    if opts and opts[0].get("type") == 1:  # a subcommand: /watch add ...
        opts = opts[0].get("options", [])
    return {o["name"]: o.get("value") for o in opts}


def reply(content: str | None = None, embed: dict | None = None, ephemeral: bool = False) -> dict:
    data = {"allowed_mentions": {"parse": []}}
    if content:
        data["content"] = content
    if embed:
        data["embeds"] = [embed]
    if ephemeral:
        data["flags"] = EPHEMERAL
    return {"type": MESSAGE, "data": data}


def handle(interaction: dict, data: dict, supabase=None, dispatch=None) -> dict:
    """The response to one interaction from Discord."""
    kind = interaction["type"]
    if kind == PING:
        return {"type": PONG}
    if kind == AUTOCOMPLETE:
        focused = next((o for o in _all_options(interaction) if o.get("focused")), {"value": ""})
        return {"type": CHOICES, "data": {"choices": [
            {"name": i[1][:100], "value": str(i[0])} for i in search(data, str(focused.get("value", "")))]}}
    name = interaction["data"]["name"]
    opts = options(interaction)
    user = (interaction.get("member") or {}).get("user") or interaction.get("user") or {}
    if name == "deals":
        embed = dict(data["deals"].get(opts["strategy"]) or {"title": "No ideas yet", "fields": []})
        embed["fields"] = embed.get("fields", [])[: int(opts.get("count") or 5)]
        return reply(embed=embed)
    if name == "item":
        item = find(data, str(opts["name"]))
        if item is None:
            return reply(f"No item matches “{opts['name']}”.", ephemeral=True)
        card = data["cards"].get(str(item[0])) or {
            "title": item[1], "color": NEUTRAL, "description": "No price history yet.",
            "fields": [{"name": "Cheapest now", "value": f"{kina(item[2])} ({item[3] or 0} listed)", "inline": True}]}
        return reply(embed=card)
    if name in ("scorecard", "timing"):
        return reply(embed=data[name])
    if name == "watch":
        return watch(interaction, opts, data, supabase, str(user.get("id")))
    if name == "refresh":
        if dispatch is None:
            return reply("Refresh isn't set up (no GitHub token).", ephemeral=True)
        dispatch()
        return reply("Started a refresh: the dashboard and channel update in about 10 minutes.", ephemeral=True)
    return reply("I don't know that command.", ephemeral=True)


def _all_options(interaction: dict) -> list:
    opts = interaction["data"].get("options", [])
    if opts and opts[0].get("type") == 1:
        opts = opts[0].get("options", [])
    return opts


def watch(interaction: dict, opts: dict, data: dict, supabase, user_id: str) -> dict:
    if supabase is None:
        return reply("Alerts aren't set up (no Supabase).", ephemeral=True)
    sub = interaction["data"]["options"][0]["name"]
    server = data["server_id"]
    if sub == "list":
        rows = supabase.select("watches", user_id=user_id, server_id=server)
        prices = {i[0]: i for i in data["items"]}
        lines = []
        for r in sorted(rows, key=lambda r: r.get("name") or ""):
            item = prices.get(r["item_key"])
            price = item[2] if item else None
            now = f"now {kina(price)}" if price else "not listed"
            hit = " ✅" if price and price <= r["below"] else ""
            lines.append(f"**{r.get('name') or r['item_key']}**: below {kina(r['below'])} ({now}){hit}")
        embed = {"title": "Your price alerts", "color": NEUTRAL,
                 "description": "\n".join(lines)[:4000] or "None yet. Add one with `/watch add`."}
        return reply(embed=embed, ephemeral=True)
    item = find(data, str(opts.get("item", "")))
    if item is None:
        return reply(f"No item matches “{opts.get('item')}”.", ephemeral=True)
    if sub == "remove":
        gone = supabase.delete("watches", user_id=user_id, server_id=server, item_key=item[0])
        return reply(f"Removed the alert on **{item[1]}**." if gone else "You have no alert on that item.",
                     ephemeral=True)
    try:
        price = parse_kina(str(opts["below"]))
    except ValueError:
        return reply(f"“{opts['below']}” isn't a price: try 250k, 1.5m or 12000.", ephemeral=True)
    mine = supabase.select("watches", user_id=user_id, server_id=server)
    if len(mine) >= data.get("max_watches", 25) and item[0] not in {r["item_key"] for r in mine}:
        return reply(f"You have {len(mine)} alerts, the most allowed; remove one first.", ephemeral=True)
    supabase.upsert("watches", {"user_id": user_id, "server_id": server, "item_key": item[0], "name": item[1],
                                "below": price, "channel_id": str(interaction.get("channel_id")),
                                "last_alert_price": None}, on_conflict="user_id,server_id,item_key")
    return reply(f"I'll ping you here when **{item[1]}** is listed at or below **{kina(price)}** "
                 f"(checked every hour).", ephemeral=True)


# --- services ------------------------------------------------------------------------------

class Supabase:
    def __init__(self, url: str, key: str):
        self.url, self.key = url.rstrip("/"), key

    def _call(self, method, query, body=None, prefer=None):
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if self.key.startswith("eyJ"):  # a legacy service_role key (a JWT); the new sb_secret_ keys go in apikey only
            headers["Authorization"] = f"Bearer {self.key}"
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(f"{self.url}/rest/v1/watches?{urllib.parse.urlencode(query)}", method=method,
                                     headers=headers, data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=5) as res:
            text = res.read()
            return json.loads(text) if text else None

    def select(self, table, **eq):
        return self._call("GET", {"select": "*", **{k: f"eq.{v}" for k, v in eq.items()}})

    def upsert(self, table, row, on_conflict):
        self._call("POST", {"on_conflict": on_conflict}, row, prefer="resolution=merge-duplicates")

    def delete(self, table, **eq):
        return bool(self._call("DELETE", {k: f"eq.{v}" for k, v in eq.items()}, prefer="return=representation"))


def dispatch_refresh(token: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/refresh.yml/dispatches", method="POST",
        data=json.dumps({"ref": "main"}).encode(), headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "User-Agent": "aion2-trader", "X-GitHub-Api-Version": "2022-11-28"})
    urllib.request.urlopen(req, timeout=5).close()


def verified(public_key: str, signature: str, timestamp: str, body: bytes) -> bool:
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
    try:
        VerifyKey(bytes.fromhex(public_key)).verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError):
        return False


_data = None


def load_data() -> dict:
    global _data
    if _data is None:
        here = Path(__file__).resolve().parent
        path = next(p for p in (here.parent / "bot.json", Path.cwd() / "bot.json", here / "bot.json") if p.exists())
        _data = json.loads(path.read_text())
    return _data


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not verified(os.environ.get("DISCORD_PUBLIC_KEY", ""), self.headers.get("X-Signature-Ed25519", ""),
                        self.headers.get("X-Signature-Timestamp", ""), body):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"bad signature")
            return
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        token = os.environ.get("GITHUB_DISPATCH_TOKEN")
        response = handle(json.loads(body), load_data(), Supabase(url, key) if url and key else None,
                          (lambda: dispatch_refresh(token)) if token else None)
        out = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):  # a health check: is the function up, and how fresh is its data
        out = json.dumps({"ok": True, "updated_at": load_data().get("updated_at")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)
