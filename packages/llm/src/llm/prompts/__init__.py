"""Prompt templates for content generation."""

from .templates import (
    RoomPromptBuilder,
    MobPromptBuilder,
    ItemPromptBuilder,
    DialoguePromptBuilder,
)

from .system import (
    ROOM_SYSTEM_PROMPT,
    MOB_SYSTEM_PROMPT,
    ITEM_SYSTEM_PROMPT,
    COMBAT_SYSTEM_PROMPT,
    DIALOGUE_SYSTEM_PROMPT,
    SKILL_SYSTEM_PROMPT,
)

__all__ = [
    # Prompt builders
    "RoomPromptBuilder",
    "MobPromptBuilder",
    "ItemPromptBuilder",
    "DialoguePromptBuilder",
    # System prompts
    "ROOM_SYSTEM_PROMPT",
    "MOB_SYSTEM_PROMPT",
    "ITEM_SYSTEM_PROMPT",
    "COMBAT_SYSTEM_PROMPT",
    "DIALOGUE_SYSTEM_PROMPT",
    "SKILL_SYSTEM_PROMPT",
]
