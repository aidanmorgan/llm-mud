"""Player preferences and settings."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from core import ComponentData


class ColorTheme(str, Enum):
    """Available color themes."""
    NONE = "none"          # No colors
    CLASSIC = "classic"    # Traditional MUD colors
    DARK = "dark"          # Dark theme optimized
    LIGHT = "light"        # Light theme optimized
    CUSTOM = "custom"      # User-defined


class PromptToken(str, Enum):
    """Available tokens for prompt customization."""
    HP = "%h"              # Current HP
    MAX_HP = "%H"          # Maximum HP
    MANA = "%m"            # Current mana
    MAX_MANA = "%M"        # Maximum mana
    STAMINA = "%s"         # Current stamina
    MAX_STAMINA = "%S"     # Maximum stamina
    EXP = "%x"             # Experience points
    EXP_TNL = "%X"         # Experience to next level
    GOLD = "%g"            # Gold on hand
    LEVEL = "%l"           # Current level
    ROOM = "%r"            # Current room name
    ZONE = "%z"            # Current zone name
    EXITS = "%e"           # Available exits
    TIME = "%t"            # Game time
    WEATHER = "%w"         # Current weather
    TARGET = "%T"          # Current target name
    TARGET_HP = "%P"       # Target HP percentage
    NEWLINE = "%n"         # Newline
    PERCENT = "%%"         # Literal %


# Default prompt format
DEFAULT_PROMPT = "<%h/%Hhp %m/%Mmp %s/%Ssp> "
DEFAULT_BATTLE_PROMPT = "<%h/%Hhp %m/%Mmp> [%T: %P%%] "


@dataclass
class AliasData:
    """A command alias."""
    name: str
    expansion: str
    created_at: float = 0.0  # Unix timestamp


@dataclass
class PreferencesData(ComponentData):
    """
    Player preferences and settings.

    Controls display options, auto-actions, and customization.
    """

    # Display preferences
    brief_mode: bool = False           # Short room descriptions
    compact_mode: bool = False         # Reduce whitespace
    color_enabled: bool = True         # Enable ANSI colors
    color_theme: ColorTheme = ColorTheme.CLASSIC

    # Auto-action preferences
    autoloot: bool = False             # Auto-loot corpses
    autogold: bool = True              # Auto-pick gold from corpses
    autosac: bool = False              # Auto-sacrifice corpses
    autoexit: bool = True              # Show exits automatically
    autosplit: bool = False            # Auto-split gold with group
    autoassist: bool = False           # Auto-assist group members in combat

    # Communication preferences
    tell_enabled: bool = True          # Accept tells
    shout_enabled: bool = True         # Hear shouts
    ooc_enabled: bool = True           # Hear OOC channel
    trade_enabled: bool = True         # Hear trade channel
    newbie_enabled: bool = True        # Hear newbie channel

    # Prompt customization
    prompt: str = DEFAULT_PROMPT
    battle_prompt: str = DEFAULT_BATTLE_PROMPT

    # Command aliases
    aliases: Dict[str, AliasData] = field(default_factory=dict)
    max_aliases: int = 50

    # Page length for scrolling (0 = no paging)
    page_length: int = 0

    # Line width for wrapping (0 = no wrapping)
    line_width: int = 80

    # Custom colors (for CUSTOM theme)
    custom_colors: Dict[str, str] = field(default_factory=dict)

    def add_alias(self, name: str, expansion: str) -> bool:
        """
        Add or update an alias.

        Returns True if added, False if at max aliases.
        """
        import time

        if name in self.aliases:
            # Update existing
            self.aliases[name] = AliasData(
                name=name,
                expansion=expansion,
                created_at=time.time()
            )
            return True

        if len(self.aliases) >= self.max_aliases:
            return False

        self.aliases[name] = AliasData(
            name=name,
            expansion=expansion,
            created_at=time.time()
        )
        return True

    def remove_alias(self, name: str) -> bool:
        """Remove an alias. Returns True if removed."""
        if name in self.aliases:
            del self.aliases[name]
            return True
        return False

    def get_alias(self, name: str) -> Optional[str]:
        """Get alias expansion, or None if not found."""
        alias = self.aliases.get(name)
        return alias.expansion if alias else None

    def expand_aliases(self, command: str) -> str:
        """
        Expand aliases in a command string.

        Only expands the first word if it matches an alias.
        """
        if not command:
            return command

        parts = command.split(None, 1)
        first_word = parts[0].lower()

        expansion = self.get_alias(first_word)
        if expansion:
            if len(parts) > 1:
                # Append arguments to expansion
                return f"{expansion} {parts[1]}"
            return expansion

        return command

    def toggle(self, setting: str) -> Optional[bool]:
        """
        Toggle a boolean setting.

        Returns new value, or None if setting not found/not toggleable.
        """
        toggleable = {
            "brief": "brief_mode",
            "compact": "compact_mode",
            "color": "color_enabled",
            "autoloot": "autoloot",
            "autogold": "autogold",
            "autosac": "autosac",
            "autoexit": "autoexit",
            "autosplit": "autosplit",
            "autoassist": "autoassist",
            "tell": "tell_enabled",
            "shout": "shout_enabled",
            "ooc": "ooc_enabled",
            "trade": "trade_enabled",
            "newbie": "newbie_enabled",
        }

        attr_name = toggleable.get(setting.lower())
        if not attr_name:
            return None

        current = getattr(self, attr_name)
        new_value = not current
        setattr(self, attr_name, new_value)
        return new_value

    def get_display_settings(self) -> Dict[str, str]:
        """Get all settings formatted for display."""
        return {
            "Brief Mode": "ON" if self.brief_mode else "OFF",
            "Compact Mode": "ON" if self.compact_mode else "OFF",
            "Color": "ON" if self.color_enabled else "OFF",
            "Color Theme": self.color_theme.value,
            "Auto-loot": "ON" if self.autoloot else "OFF",
            "Auto-gold": "ON" if self.autogold else "OFF",
            "Auto-sac": "ON" if self.autosac else "OFF",
            "Auto-exit": "ON" if self.autoexit else "OFF",
            "Auto-split": "ON" if self.autosplit else "OFF",
            "Auto-assist": "ON" if self.autoassist else "OFF",
            "Tells": "ON" if self.tell_enabled else "OFF",
            "Shouts": "ON" if self.shout_enabled else "OFF",
            "OOC Channel": "ON" if self.ooc_enabled else "OFF",
            "Trade Channel": "ON" if self.trade_enabled else "OFF",
            "Newbie Channel": "ON" if self.newbie_enabled else "OFF",
            "Page Length": str(self.page_length) if self.page_length else "OFF",
            "Line Width": str(self.line_width) if self.line_width else "OFF",
        }


def format_prompt(
    template: str,
    hp: int = 0,
    max_hp: int = 0,
    mana: int = 0,
    max_mana: int = 0,
    stamina: int = 0,
    max_stamina: int = 0,
    exp: int = 0,
    exp_tnl: int = 0,
    gold: int = 0,
    level: int = 1,
    room: str = "",
    zone: str = "",
    exits: str = "",
    time_str: str = "",
    weather: str = "",
    target: str = "",
    target_hp_pct: int = 0,
) -> str:
    """
    Format a prompt template with actual values.

    Replaces tokens with their corresponding values.
    """
    result = template

    replacements = [
        ("%h", str(hp)),
        ("%H", str(max_hp)),
        ("%m", str(mana)),
        ("%M", str(max_mana)),
        ("%s", str(stamina)),
        ("%S", str(max_stamina)),
        ("%x", str(exp)),
        ("%X", str(exp_tnl)),
        ("%g", str(gold)),
        ("%l", str(level)),
        ("%r", room),
        ("%z", zone),
        ("%e", exits),
        ("%t", time_str),
        ("%w", weather),
        ("%T", target if target else "none"),
        ("%P", str(target_hp_pct)),
        ("%n", "\n"),
        ("%%", "%"),
    ]

    for token, value in replacements:
        result = result.replace(token, value)

    return result
