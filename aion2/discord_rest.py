"""Discord over plain HTTPS, for the hourly job: send messages and register slash commands with the
bot's token, without staying connected the way the gateway bot (``bot``) does."""

import json
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/gavinongzk/aion2-trader, 1)"


class DiscordError(Exception):
    pass


def request(token: str, method: str, path: str, body=None, tries: int = 3):
    data = None if body is None else json.dumps(body).encode()
    for attempt in range(tries):
        req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "Authorization": f"Bot {token}", "User-Agent": USER_AGENT, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                text = res.read()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            detail = e.read(500).decode("utf-8", "replace")
            if e.code == 429 and attempt + 1 < tries:  # rate limited: Discord says how long to wait
                time.sleep(float(json.loads(detail or "{}").get("retry_after", 1)) + 0.1)
                continue
            raise DiscordError(f"{method} {path}: {e.code} {detail}") from None


def send(token: str, channel_id: int | str, content: str | None = None, embed: dict | None = None,
         mention_users: bool = False) -> None:
    body = {"allowed_mentions": {"parse": ["users"] if mention_users else []}}
    if content:
        body["content"] = content
    if embed:
        body["embeds"] = [embed]
    request(token, "POST", f"/channels/{channel_id}/messages", body)


def register_commands(token: str, commands: list[dict], guild_id: int | str | None = None) -> list:
    """Replace the bot's slash commands with ``commands``: in one server (at once) or everywhere
    (can take an hour to show)."""
    app = request(token, "GET", "/oauth2/applications/@me")["id"]
    path = f"/applications/{app}/guilds/{guild_id}/commands" if guild_id else f"/applications/{app}/commands"
    return request(token, "PUT", path, commands)
