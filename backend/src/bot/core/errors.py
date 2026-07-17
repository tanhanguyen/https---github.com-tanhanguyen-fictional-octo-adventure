"""Domain errors."""
from __future__ import annotations


class BotError(Exception):
    """Base class for domain errors."""


class ConfigError(BotError):
    pass


class FeedError(BotError):
    pass


class OrderError(BotError):
    pass
