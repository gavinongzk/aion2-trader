"""discord.py embeds for the gateway bot: the JSON embeds of ``embeds``, wrapped."""

import discord

from . import embeds
from .embeds import COLORS, EMBED_BUDGET, FOOTER, NEUTRAL, TITLES, alert_text, clip, kina  # noqa: F401 (re-exported)


def ideas_embed(*args, **kwargs) -> discord.Embed:
    return discord.Embed.from_dict(embeds.ideas_embed(*args, **kwargs))


def sections_embed(*args, **kwargs) -> discord.Embed:
    return discord.Embed.from_dict(embeds.sections_embed(*args, **kwargs))


def item_embed(*args, **kwargs) -> discord.Embed:
    return discord.Embed.from_dict(embeds.item_embed(*args, **kwargs))


def watches_embed(*args, **kwargs) -> discord.Embed:
    return discord.Embed.from_dict(embeds.watches_embed(*args, **kwargs))
