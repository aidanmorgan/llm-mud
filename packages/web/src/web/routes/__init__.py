"""Web routes for the LLM-MUD application."""

from .auth import router as auth_router
from .game import router as game_router

__all__ = [
    "auth_router",
    "game_router",
]
