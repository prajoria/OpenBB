"""Story registry."""

from __future__ import annotations

from .portfolio import STORY as PORTFOLIO_STORY
from .techtrade import STORY as TECHTRADE_STORY

STORIES = {
    "portfolio": PORTFOLIO_STORY,
    "techtrade": TECHTRADE_STORY,
}

__all__ = ["STORIES", "PORTFOLIO_STORY", "TECHTRADE_STORY"]
