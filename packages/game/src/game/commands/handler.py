"""
Command Handler

Ray actor that processes player commands.

Supports both:
- Local CommandRegistry (legacy, for single-process)
- Distributed CommandRegistryActor with handler resolution via importlib
"""

import importlib
import logging
from typing import Dict, Optional, Callable

import ray
from ray.actor import ActorHandle

from core import EntityId
from .parser import CommandParser
from .registry import get_command_registry, CommandCategory
from .command_actor import (
    get_command_registry_actor,
    DistributedCommandDefinition,
    CommandCategory as DistributedCommandCategory,
    Position,
)

logger = logging.getLogger(__name__)


# Handler cache for resolved handlers
_handler_cache: Dict[str, Callable] = {}


def resolve_handler(handler_module: str, handler_name: str) -> Callable:
    """
    Resolve a handler reference to an actual callable.

    Uses importlib to dynamically import the module and get the function.
    Results are cached to avoid repeated imports.
    """
    cache_key = f"{handler_module}:{handler_name}"

    if cache_key in _handler_cache:
        return _handler_cache[cache_key]

    try:
        module = importlib.import_module(handler_module)
        handler = getattr(module, handler_name)
        _handler_cache[cache_key] = handler
        return handler
    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to resolve handler {handler_module}:{handler_name}: {e}")
        raise


@ray.remote
class CommandHandler:
    """
    Actor that handles player command execution.

    Receives commands from the Gateway, parses them,
    validates player state, and executes the appropriate handler.

    Uses local CommandRegistry for command lookup.
    """

    def __init__(self):
        self._parser = CommandParser()
        self._registry = get_command_registry()

        # Register built-in commands
        self._register_builtin_commands()

    def _register_builtin_commands(self) -> None:
        """Register all built-in commands."""
        # Import command modules to trigger decorator-based registration
        # These imports have side effects (registering commands)
        from . import movement  # noqa: F401
        from . import combat  # noqa: F401
        from . import info  # noqa: F401
        from . import communication  # noqa: F401
        from . import social  # noqa: F401
        from . import portal  # noqa: F401
        from . import admin  # noqa: F401
        from . import olc  # noqa: F401
        from . import channels  # noqa: F401
        from . import items  # noqa: F401
        from . import position  # noqa: F401
        from . import skills  # noqa: F401
        from . import economy  # noqa: F401
        from . import creation  # noqa: F401
        from . import journey  # noqa: F401
        from . import group  # noqa: F401
        from . import socials  # noqa: F401
        from . import world  # noqa: F401
        from . import config  # noqa: F401
        from . import quests  # noqa: F401
        from . import crafting  # noqa: F401
        from . import level  # noqa: F401
        from . import fishing  # noqa: F401
        from . import cooking  # noqa: F401
        from . import proficiency  # noqa: F401

    async def handle_command(self, player_id: EntityId, raw_input: str) -> str:
        """
        Handle a player command.

        Returns the response text to send to the player.
        """
        # Parse the command
        parsed = self._parser.parse(raw_input)

        if not parsed.command:
            return ""

        # Look up command
        cmd_def = self._registry.get(parsed.command)

        if not cmd_def:
            return f"Unknown command: {parsed.command}. Type 'help' for commands."

        # Validate player state
        validation_error = await self._validate_command(player_id, cmd_def)
        if validation_error:
            return validation_error

        # Execute command
        try:
            result = await cmd_def.handler(player_id, parsed.args)
            return result if result else ""
        except Exception as e:
            logger.error(f"Error executing command {parsed.command}: {e}")
            return f"Error executing command: {e}"

    async def _validate_command(self, player_id: EntityId, cmd_def) -> Optional[str]:
        """
        Validate that player can execute this command.

        Returns error message if invalid, None if valid.
        """
        from core.component import get_component_actor

        # Check admin requirement
        if cmd_def.admin_only:
            # Would check player admin flag here
            pass

        # Check position requirement
        # For now, simplified check
        player_actor = get_component_actor("Player")
        player = await player_actor.get.remote(player_id)
        if player:
            position = getattr(player, "position", Position.STANDING)
            if isinstance(position, str):
                position = Position.from_string(position)
            if not Position.allows(position, cmd_def.min_position):
                return f"You can't do that while {position.value}."

        # Check combat state
        if not cmd_def.in_combat:
            combat_actor = get_component_actor("Combat")
            combat = await combat_actor.get.remote(player_id)
            if combat and combat.is_in_combat:
                return "You can't do that while in combat!"

        return None


    async def get_help(self, topic: str = "") -> str:
        """Get help text for a command or topic."""
        if not topic:
            # List all command categories
            lines = ["Available commands by category:", ""]
            for category in CommandCategory:
                commands = self._registry.get_by_category(category)
                if commands:
                    cmd_names = [c.name for c in commands]
                    lines.append(f"  {category.value}: {', '.join(cmd_names)}")
            lines.append("")
            lines.append("Type 'help <command>' for details on a specific command.")
            return "\n".join(lines)

        # Look up specific command
        cmd_def = self._registry.get(topic)
        if cmd_def:
            lines = [
                f"Command: {cmd_def.name}",
                f"Usage: {cmd_def.usage}",
                "",
                cmd_def.help_text,
            ]
            if cmd_def.aliases:
                lines.append(f"Aliases: {', '.join(cmd_def.aliases)}")
            return "\n".join(lines)

        return f"No help available for: {topic}"


# ============================================================================
# Handler Actor Management
# ============================================================================

_handler_actor: Optional[ActorHandle] = None


HANDLER_ACTOR_NAME = "command_handler"
HANDLER_NAMESPACE = "llmmud"


def get_command_handler() -> ActorHandle:
    """Get the global command handler actor."""
    global _handler_actor
    if _handler_actor is None:
        _handler_actor = ray.get_actor(HANDLER_ACTOR_NAME, namespace=HANDLER_NAMESPACE)
    return _handler_actor  # type: ignore[return-value]


async def start_command_handler() -> ActorHandle:
    """Start the command handler actor (local registry)."""
    global _handler_actor

    handler: ActorHandle = CommandHandler.options(
        name=HANDLER_ACTOR_NAME, namespace=HANDLER_NAMESPACE, lifetime="detached"
    ).remote()  # type: ignore[assignment]

    _handler_actor = handler
    return handler


@ray.remote
class DistributedCommandHandler:
    """
    Actor that handles player command execution using the distributed registry.

    Commands are looked up from the CommandRegistryActor, then handlers are
    resolved locally via importlib. This enables multi-process deployments
    where commands are registered from different processes.
    """

    def __init__(self):
        self._parser = CommandParser()
        self._registry_actor = None
        self._local_handler_cache: Dict[str, Callable] = {}

    def _get_registry(self) -> ActorHandle:
        """Get command registry actor lazily."""
        if self._registry_actor is None:
            self._registry_actor = get_command_registry_actor()
        return self._registry_actor

    def _resolve_handler(self, cmd_def: DistributedCommandDefinition) -> Callable:
        """Resolve a command definition's handler to a callable."""
        cache_key = f"{cmd_def.handler_module}:{cmd_def.handler_name}"

        if cache_key in self._local_handler_cache:
            return self._local_handler_cache[cache_key]

        handler = resolve_handler(cmd_def.handler_module, cmd_def.handler_name)
        self._local_handler_cache[cache_key] = handler
        return handler

    async def handle_command(self, player_id: EntityId, raw_input: str) -> str:
        """
        Handle a player command using distributed registry.

        Returns the response text to send to the player.
        """
        # Parse the command
        parsed = self._parser.parse(raw_input)

        if not parsed.command:
            return ""

        # Look up command from distributed registry
        cmd_def = await self._get_registry().get.remote(parsed.command)

        if not cmd_def:
            return f"Unknown command: {parsed.command}. Type 'help' for commands."

        # Resolve handler locally
        try:
            handler = self._resolve_handler(cmd_def)
        except (ImportError, AttributeError) as e:
            logger.error(f"Cannot resolve handler for {parsed.command}: {e}")
            return f"Command handler not available: {parsed.command}"

        # Validate player state
        validation_error = await self._validate_command(player_id, cmd_def)
        if validation_error:
            return validation_error

        # Execute command
        try:
            result = await handler(player_id, parsed.args)
            return result if result else ""
        except Exception as e:
            logger.error(f"Error executing command {parsed.command}: {e}")
            return f"Error executing command: {e}"

    async def _validate_command(
        self, player_id: EntityId, cmd_def: DistributedCommandDefinition
    ) -> Optional[str]:
        """
        Validate that player can execute this command.

        Returns error message if invalid, None if valid.
        """
        from core.component import get_component_actor

        # Check admin requirement
        if cmd_def.admin_only:
            # Would check player admin flag here
            pass

        # Check position requirement
        player_actor = get_component_actor("Player")
        player = await player_actor.get.remote(player_id)
        if player:
            position = getattr(player, "position", Position.STANDING)
            if isinstance(position, str):
                position = Position.from_string(position)
            if not Position.allows(position, cmd_def.min_position):
                return f"You can't do that while {position.value}."

        # Check combat state
        if not cmd_def.in_combat:
            combat_actor = get_component_actor("Combat")
            combat = await combat_actor.get.remote(player_id)
            if combat and combat.is_in_combat:
                return "You can't do that while in combat!"

        return None


    async def get_help(self, topic: str = "") -> str:
        """Get help text for a command or topic."""
        registry = self._get_registry()

        if not topic:
            # List all command categories
            lines = ["Available commands by category:", ""]
            for category in DistributedCommandCategory:
                commands = await registry.get_by_category.remote(category)
                if commands:
                    cmd_names = [c.name for c in commands]
                    lines.append(f"  {category.value}: {', '.join(cmd_names)}")
            lines.append("")
            lines.append("Type 'help <command>' for details on a specific command.")
            return "\n".join(lines)

        # Look up specific command
        cmd_def = await registry.get.remote(topic)
        if cmd_def:
            lines = [
                f"Command: {cmd_def.name}",
                f"Usage: {cmd_def.usage}",
                "",
                cmd_def.help_text,
            ]
            if cmd_def.aliases:
                lines.append(f"Aliases: {', '.join(cmd_def.aliases)}")
            return "\n".join(lines)

        return f"No help available for: {topic}"


# ============================================================================
# Distributed Handler Actor Management
# ============================================================================

DISTRIBUTED_HANDLER_ACTOR_NAME = "distributed_command_handler"

_distributed_handler_actor: Optional[ActorHandle] = None


def get_distributed_command_handler() -> ActorHandle:
    """Get the distributed command handler actor."""
    global _distributed_handler_actor
    if _distributed_handler_actor is None:
        _distributed_handler_actor = ray.get_actor(
            DISTRIBUTED_HANDLER_ACTOR_NAME, namespace=HANDLER_NAMESPACE
        )
    return _distributed_handler_actor  # type: ignore[return-value]


async def start_distributed_command_handler() -> ActorHandle:
    """Start the distributed command handler actor."""
    global _distributed_handler_actor

    handler: ActorHandle = DistributedCommandHandler.options(
        name=DISTRIBUTED_HANDLER_ACTOR_NAME, namespace=HANDLER_NAMESPACE, lifetime="detached"
    ).remote()  # type: ignore[assignment]

    _distributed_handler_actor = handler
    return handler
