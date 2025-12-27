"""Factory for creating PlayerStore instances based on environment."""

import os
from pathlib import Path
from typing import Optional

from .protocol import PlayerStore
from .sqlite import SQLitePlayerStore


# Singleton instance
_player_store: Optional[PlayerStore] = None


def get_player_store() -> PlayerStore:
    """
    Get the configured PlayerStore instance.

    Uses environment variable LLMMUD_ENV to determine which
    implementation to use:
    - "local" or unset: SQLite (default)
    - "aws": DynamoDB (future)
    """
    global _player_store

    if _player_store is not None:
        return _player_store

    env = os.getenv("LLMMUD_ENV", "local").lower()

    if env == "aws":
        # Future: DynamoDB implementation
        raise NotImplementedError("DynamoDB store not yet implemented")
    else:
        # Default to SQLite
        db_path = Path(os.getenv("PLAYER_DB_PATH", "data/players.db"))
        _player_store = SQLitePlayerStore(db_path)

    return _player_store


async def initialize_player_store() -> PlayerStore:
    """
    Get and initialize the PlayerStore.

    Should be called at application startup.
    """
    store = get_player_store()
    await store.initialize()
    return store


def reset_player_store() -> None:
    """
    Reset the singleton instance.

    Used for testing.
    """
    global _player_store
    _player_store = None
