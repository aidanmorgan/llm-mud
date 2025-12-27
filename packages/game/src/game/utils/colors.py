"""ANSI color support for MUD text output."""

from enum import Enum
from typing import Dict, Optional
import re


class ANSICode(str, Enum):
    """ANSI escape codes for terminal colors."""

    # Reset
    RESET = "\033[0m"

    # Text styles
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"
    HIDDEN = "\033[8m"
    STRIKETHROUGH = "\033[9m"

    # Regular foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


# MUD color code mapping: {code} -> ANSI escape
# Uses ROM/SMAUG-style color codes
COLOR_CODES: Dict[str, str] = {
    # Reset
    "{x": ANSICode.RESET.value,
    "{X": ANSICode.RESET.value,

    # Regular colors
    "{d": ANSICode.BLACK.value,
    "{D": ANSICode.BRIGHT_BLACK.value,
    "{r": ANSICode.RED.value,
    "{R": ANSICode.BRIGHT_RED.value,
    "{g": ANSICode.GREEN.value,
    "{G": ANSICode.BRIGHT_GREEN.value,
    "{y": ANSICode.YELLOW.value,
    "{Y": ANSICode.BRIGHT_YELLOW.value,
    "{b": ANSICode.BLUE.value,
    "{B": ANSICode.BRIGHT_BLUE.value,
    "{m": ANSICode.MAGENTA.value,
    "{M": ANSICode.BRIGHT_MAGENTA.value,
    "{c": ANSICode.CYAN.value,
    "{C": ANSICode.BRIGHT_CYAN.value,
    "{w": ANSICode.WHITE.value,
    "{W": ANSICode.BRIGHT_WHITE.value,

    # Styles
    "{*": ANSICode.BOLD.value,
    "{/": ANSICode.ITALIC.value,
    "{_": ANSICode.UNDERLINE.value,
    "{~": ANSICode.BLINK.value,
    "{-": ANSICode.DIM.value,

    # Escape literal brace
    "{{": "{",
}

# Semantic color codes for theming
THEME_CODES: Dict[str, Dict[str, str]] = {
    "classic": {
        # Room descriptions
        "{room_name": ANSICode.BRIGHT_CYAN.value,
        "{room_desc": ANSICode.WHITE.value,
        "{room_exit": ANSICode.GREEN.value,

        # Combat
        "{damage_dealt": ANSICode.BRIGHT_RED.value,
        "{damage_taken": ANSICode.RED.value,
        "{heal": ANSICode.BRIGHT_GREEN.value,
        "{combat_miss": ANSICode.BRIGHT_BLACK.value,

        # Chat
        "{say": ANSICode.CYAN.value,
        "{tell": ANSICode.MAGENTA.value,
        "{shout": ANSICode.YELLOW.value,
        "{ooc": ANSICode.BRIGHT_BLACK.value,

        # Items
        "{item_common": ANSICode.WHITE.value,
        "{item_uncommon": ANSICode.GREEN.value,
        "{item_rare": ANSICode.BLUE.value,
        "{item_epic": ANSICode.MAGENTA.value,
        "{item_legendary": ANSICode.YELLOW.value,

        # NPCs
        "{npc_friendly": ANSICode.GREEN.value,
        "{npc_neutral": ANSICode.WHITE.value,
        "{npc_hostile": ANSICode.RED.value,

        # System
        "{error": ANSICode.BRIGHT_RED.value,
        "{warning": ANSICode.YELLOW.value,
        "{success": ANSICode.BRIGHT_GREEN.value,
        "{info": ANSICode.BRIGHT_CYAN.value,
    },
    "dark": {
        "{room_name": ANSICode.BRIGHT_WHITE.value,
        "{room_desc": ANSICode.BRIGHT_BLACK.value,
        "{room_exit": ANSICode.BRIGHT_GREEN.value,
        "{damage_dealt": ANSICode.RED.value,
        "{damage_taken": ANSICode.BRIGHT_RED.value,
        "{heal": ANSICode.GREEN.value,
        "{combat_miss": ANSICode.DIM.value,
        "{say": ANSICode.BRIGHT_CYAN.value,
        "{tell": ANSICode.BRIGHT_MAGENTA.value,
        "{shout": ANSICode.BRIGHT_YELLOW.value,
        "{ooc": ANSICode.DIM.value,
        "{item_common": ANSICode.BRIGHT_BLACK.value,
        "{item_uncommon": ANSICode.BRIGHT_GREEN.value,
        "{item_rare": ANSICode.BRIGHT_BLUE.value,
        "{item_epic": ANSICode.BRIGHT_MAGENTA.value,
        "{item_legendary": ANSICode.BRIGHT_YELLOW.value,
        "{npc_friendly": ANSICode.BRIGHT_GREEN.value,
        "{npc_neutral": ANSICode.WHITE.value,
        "{npc_hostile": ANSICode.BRIGHT_RED.value,
        "{error": ANSICode.BRIGHT_RED.value,
        "{warning": ANSICode.BRIGHT_YELLOW.value,
        "{success": ANSICode.BRIGHT_GREEN.value,
        "{info": ANSICode.BRIGHT_WHITE.value,
    },
    "light": {
        "{room_name": ANSICode.BLUE.value,
        "{room_desc": ANSICode.BLACK.value,
        "{room_exit": ANSICode.GREEN.value,
        "{damage_dealt": ANSICode.RED.value,
        "{damage_taken": ANSICode.RED.value,
        "{heal": ANSICode.GREEN.value,
        "{combat_miss": ANSICode.DIM.value,
        "{say": ANSICode.CYAN.value,
        "{tell": ANSICode.MAGENTA.value,
        "{shout": ANSICode.YELLOW.value,
        "{ooc": ANSICode.DIM.value,
        "{item_common": ANSICode.BLACK.value,
        "{item_uncommon": ANSICode.GREEN.value,
        "{item_rare": ANSICode.BLUE.value,
        "{item_epic": ANSICode.MAGENTA.value,
        "{item_legendary": ANSICode.YELLOW.value,
        "{npc_friendly": ANSICode.GREEN.value,
        "{npc_neutral": ANSICode.BLACK.value,
        "{npc_hostile": ANSICode.RED.value,
        "{error": ANSICode.RED.value,
        "{warning": ANSICode.YELLOW.value,
        "{success": ANSICode.GREEN.value,
        "{info": ANSICode.BLUE.value,
    },
}


# Pattern to match color codes
COLOR_PATTERN = re.compile(r"\{[a-zA-Z*/_~\-{]|\{[a-z_]+")


def colorize(text: str, theme: str = "classic", enabled: bool = True) -> str:
    """
    Convert MUD color codes to ANSI escape sequences.

    Args:
        text: Text containing {x style color codes
        theme: Color theme to use (classic, dark, light)
        enabled: If False, strips all color codes instead

    Returns:
        Text with ANSI escape codes (or stripped if disabled)
    """
    if not text:
        return text

    # Get theme colors (fall back to classic)
    theme_colors = THEME_CODES.get(theme, THEME_CODES["classic"])

    def replace_code(match: re.Match) -> str:
        code = match.group(0)

        if not enabled:
            # Strip the code entirely (except {{)
            if code == "{{":
                return "{"
            return ""

        # Try basic color code first
        if code in COLOR_CODES:
            return COLOR_CODES[code]

        # Try theme semantic code
        if code in theme_colors:
            return theme_colors[code]

        # Unknown code - leave as-is
        return code

    result = COLOR_PATTERN.sub(replace_code, text)

    # Ensure reset at end if colors were used
    if enabled and ("\033[" in result) and not result.endswith(ANSICode.RESET.value):
        result += ANSICode.RESET.value

    return result


def strip_colors(text: str) -> str:
    """Remove all MUD color codes from text."""
    return colorize(text, enabled=False)


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape codes from text."""
    ansi_pattern = re.compile(r"\033\[[0-9;]*m")
    return ansi_pattern.sub("", text)


def visible_length(text: str) -> int:
    """Get the visible length of text (excluding color codes)."""
    stripped = strip_ansi(strip_colors(text))
    return len(stripped)


def colorize_by_percent(
    value: int,
    max_value: int,
    low_color: str = "{R",
    mid_color: str = "{Y",
    high_color: str = "{G",
) -> str:
    """
    Return color code based on percentage of max value.

    Useful for HP bars, etc.
    """
    if max_value <= 0:
        return high_color

    percent = (value / max_value) * 100

    if percent <= 25:
        return low_color
    elif percent <= 50:
        return mid_color
    else:
        return high_color


def format_hp(current: int, maximum: int) -> str:
    """Format HP with color based on percentage."""
    color = colorize_by_percent(current, maximum)
    return f"{color}{current}{{{'}x'}/{maximum}"


def format_item_rarity(rarity: str) -> str:
    """Get color code for item rarity."""
    rarity_colors = {
        "common": "{item_common",
        "uncommon": "{item_uncommon",
        "rare": "{item_rare",
        "epic": "{item_epic",
        "legendary": "{item_legendary",
    }
    return rarity_colors.get(rarity.lower(), "{w")


def format_npc_disposition(disposition: str) -> str:
    """Get color code for NPC disposition."""
    disposition_colors = {
        "friendly": "{npc_friendly",
        "neutral": "{npc_neutral",
        "hostile": "{npc_hostile",
    }
    return disposition_colors.get(disposition.lower(), "{w")


# Convenience functions for common colorizations
def error(text: str) -> str:
    """Format text as error."""
    return f"{{error{text}{{x"


def warning(text: str) -> str:
    """Format text as warning."""
    return f"{{warning{text}{{x"


def success(text: str) -> str:
    """Format text as success."""
    return f"{{success{text}{{x"


def info(text: str) -> str:
    """Format text as info."""
    return f"{{info{text}{{x"


def room_name(text: str) -> str:
    """Format room name."""
    return f"{{room_name{text}{{x"


def room_exit(text: str) -> str:
    """Format exit name."""
    return f"{{room_exit{text}{{x"


def say_text(text: str) -> str:
    """Format spoken text."""
    return f"{{say{text}{{x"


def tell_text(text: str) -> str:
    """Format tell text."""
    return f"{{tell{text}{{x"


def damage_dealt(text: str) -> str:
    """Format damage dealt."""
    return f"{{damage_dealt{text}{{x"


def damage_taken(text: str) -> str:
    """Format damage taken."""
    return f"{{damage_taken{text}{{x"


def heal_text(text: str) -> str:
    """Format healing."""
    return f"{{heal{text}{{x"
