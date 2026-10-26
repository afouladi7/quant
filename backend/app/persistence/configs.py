"""Save and restore user-editable configurations in persistent mode."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.fx.config import BookConfig, RoutingWeights
from app.marketmaker.config import MMConfig
from app.portfolio.futures import FuturesSpec
from app.portfolio.service import HedgeRule

if TYPE_CHECKING:
    from app.state import AppContainer

log = logging.getLogger(__name__)


def save_all(c: "AppContainer") -> None:
    c.sink.save_config("mm.config", c.mm.config)
    c.sink.save_config("fx.books", {n: b.config for n, b in c.fx.books.items()})
    c.sink.save_config("fx.weights", c.fx.weights)
    c.sink.save_config("portfolio.futures_spec", c.portfolio.futures_spec)
    c.sink.save_config("portfolio.hedge_rule", c.portfolio.rule)


def restore_all(c: "AppContainer") -> list[str]:
    restored = []
    try:
        if (v := c.sink.load_config("mm.config")) is not None:
            c.mm.update_config(MMConfig(**v))
            restored.append("mm.config")
        if (v := c.sink.load_config("fx.books")) is not None:
            for cfg in v.values():
                c.fx.set_book_config(BookConfig(**cfg))
            restored.append("fx.books")
        if (v := c.sink.load_config("fx.weights")) is not None:
            c.fx.weights = RoutingWeights(**v)
            restored.append("fx.weights")
        if (v := c.sink.load_config("portfolio.futures_spec")) is not None:
            c.portfolio.set_futures_spec(FuturesSpec(**v))
            restored.append("portfolio.futures_spec")
        if (v := c.sink.load_config("portfolio.hedge_rule")) is not None:
            c.portfolio.rule = HedgeRule(**v)
            restored.append("portfolio.hedge_rule")
    except (ValidationError, ValueError, TypeError) as exc:
        log.warning("ignoring an invalid saved configuration", extra={"error": str(exc)})
    return restored
