"""
Command Registry

Central registry for all game commands.
Commands can be registered with decorators or manually.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

from ..components.position import Position
from .command_actor import CommandCategory


logger = logging.getLogger(__name__)


@dataclass
class CommandDefinition:
    """Definition of a game command."""

    name: str
    handler: Callable
    aliases: List[str] = field(default_factory=list)
    category: CommandCategory = CommandCategory.INFORMATION
    min_position: Position = Position.STANDING
    help_text: str = ""
    usage: str = ""
    admin_only: bool = False
    in_combat: bool = True  # Can be used while in combat
    hidden: bool = False  # Hidden from help listing


class CommandRegistry:
    """
    Central registry for game commands.

    Commands are looked up by name or alias.
    """

    def __init__(self):
        self._commands: Dict[str, CommandDefinition] = {}
        self._aliases: Dict[str, str] = {}  # alias -> command_name
        self._by_category: Dict[CommandCategory, List[str]] = {cat: [] for cat in CommandCategory}

    def register(self, definition: CommandDefinition) -> None:
        """Register a command."""
        name = definition.name.lower()
        self._commands[name] = definition
        self._by_category[definition.category].append(name)

        # Register aliases
        for alias in definition.aliases:
            self._aliases[alias.lower()] = name

        logger.debug(f"Registered command: {name}")

    def get(self, command_name: str) -> Optional[CommandDefinition]:
        """Get a command by name or alias."""
        name = command_name.lower()

        # Check direct command
        if name in self._commands:
            return self._commands[name]

        # Check aliases
        if name in self._aliases:
            return self._commands[self._aliases[name]]

        return None

    def get_all(self) -> Dict[str, CommandDefinition]:
        """Get all registered commands."""
        return self._commands.copy()

    def get_by_category(self, category: CommandCategory) -> List[CommandDefinition]:
        """Get commands in a category."""
        return [
            self._commands[name]
            for name in self._by_category.get(category, [])
            if not self._commands[name].hidden
        ]

    def get_visible_commands(self) -> List[CommandDefinition]:
        """Get all non-hidden commands."""
        return [cmd for cmd in self._commands.values() if not cmd.hidden]


# Global registry instance
_registry: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Get the global command registry."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry


def command(
    name: str,
    aliases: Optional[List[str]] = None,
    category: CommandCategory = CommandCategory.INFORMATION,
    min_position: Position = Position.STANDING,
    help_text: str = "",
    usage: str = "",
    admin_only: bool = False,
    in_combat: bool = True,
    hidden: bool = False,
):
    """
    Decorator to register a command handler.

    Usage:
        @command("look", aliases=["l"], category=CommandCategory.INFORMATION)
        async def cmd_look(player_id: EntityId, args: List[str]) -> str:
            return "You look around..."
    """

    def decorator(func: Callable):
        definition = CommandDefinition(
            name=name,
            handler=func,
            aliases=aliases or [],
            category=category,
            min_position=min_position,
            help_text=help_text or func.__doc__ or "",
            usage=usage or f"{name} [arguments]",
            admin_only=admin_only,
            in_combat=in_combat,
            hidden=hidden,
        )
        get_command_registry().register(definition)
        return func

    return decorator
