"""Game utilities."""

from .colors import (
    ANSICode,
    COLOR_CODES,
    THEME_CODES,
    colorize,
    strip_colors,
    strip_ansi,
    visible_length,
    colorize_by_percent,
    format_hp,
    format_item_rarity,
    format_npc_disposition,
    error,
    warning,
    success,
    info,
    room_name,
    room_exit,
    say_text,
    tell_text,
    damage_dealt,
    damage_taken,
    heal_text,
)

__all__ = [
    # ANSI codes
    "ANSICode",
    "COLOR_CODES",
    "THEME_CODES",
    # Color functions
    "colorize",
    "strip_colors",
    "strip_ansi",
    "visible_length",
    "colorize_by_percent",
    "format_hp",
    "format_item_rarity",
    "format_npc_disposition",
    # Convenience formatters
    "error",
    "warning",
    "success",
    "info",
    "room_name",
    "room_exit",
    "say_text",
    "tell_text",
    "damage_dealt",
    "damage_taken",
    "heal_text",
]
