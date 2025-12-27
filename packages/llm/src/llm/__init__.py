"""
LLM-MUD LLM Integration Package

Provides a provider-agnostic interface for LLM content generation,
with support for structured output via Pydantic schemas and PydanticAI agents.
"""

from .provider import LLMProvider, GenerationResult, GenerationError
from .schemas import (
    GeneratedRoom,
    GeneratedMob,
    GeneratedItem,
    MobPersonality,
    GeneratedDialogue,
)
from .theme import Theme, ThemeConstraints

# PydanticAI agents
from .agents import (
    room_agent,
    mob_agent,
    item_agent,
    combat_agent,
    dialogue_agent,
    get_agent,
    AGENTS,
)

# Caching
from .cache import (
    CachedAgent,
    get_cache,
    create_cached_agent,
)

__all__ = [
    # Provider
    "LLMProvider",
    "GenerationResult",
    "GenerationError",
    # Schemas
    "GeneratedRoom",
    "GeneratedMob",
    "GeneratedItem",
    "MobPersonality",
    "GeneratedDialogue",
    # Theme
    "Theme",
    "ThemeConstraints",
    # PydanticAI agents
    "room_agent",
    "mob_agent",
    "item_agent",
    "combat_agent",
    "dialogue_agent",
    "get_agent",
    "AGENTS",
    # Caching
    "CachedAgent",
    "get_cache",
    "create_cached_agent",
]
