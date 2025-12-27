"""
Distributed Command Registry Actor

A Ray actor that provides distributed storage for command definitions.
This replaces the process-local CommandRegistry singleton, enabling
multiple Python processes to register and share commands via the Ray cluster.

Key Design Decision:
    Commands store handler references (module + function name) instead of
    actual callables. The CommandHandler resolves these to real functions
    via importlib at runtime. This solves the pickle serialization problem.
"""

import ray
from ray.actor import ActorHandle
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import logging

from ..components.position import Position

logger = logging.getLogger(__name__)

ACTOR_NAME = "command_registry"
ACTOR_NAMESPACE = "llmmud"


class CommandCategory(str, Enum):
    """Categories of commands for help organization."""

    MOVEMENT = "movement"
    COMBAT = "combat"
    OBJECT = "object"
    COMMUNICATION = "communication"
    SOCIAL = "social"
    INFORMATION = "information"
    CONFIGURATION = "configuration"
    ADMIN = "admin"


@dataclass
class DistributedCommandDefinition:
    """
    Definition of a game command for distributed storage.

    Unlike CommandDefinition, this stores handler references (module + name)
    instead of actual callables, making it safe to serialize via Ray.
    """

    name: str
    handler_module: str  # e.g., "game.commands.movement"
    handler_name: str  # e.g., "cmd_north"
    aliases: List[str] = field(default_factory=list)
    category: CommandCategory = CommandCategory.INFORMATION
    min_position: Position = Position.STANDING
    help_text: str = ""
    usage: str = ""
    admin_only: bool = False
    in_combat: bool = True  # Can be used while in combat
    hidden: bool = False  # Hidden from help listing


@ray.remote
class CommandRegistryActor:
    """
    Distributed registry for game commands.

    This actor is the single source of truth for command definitions
    across all processes connected to the Ray cluster.
    """

    def __init__(self):
        self._commands: Dict[str, DistributedCommandDefinition] = {}
        self._aliases: Dict[str, str] = {}  # alias -> command_name
        self._by_category: Dict[str, List[str]] = {cat.value: [] for cat in CommandCategory}
        self._version: int = 0

        logger.info("CommandRegistryActor initialized")

    def _increment_version(self) -> None:
        """Increment version after any mutation."""
        self._version += 1

    # =========================================================================
    # Version / Cache Support
    # =========================================================================

    def get_version(self) -> int:
        """Get current registry version for cache invalidation."""
        return self._version

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "commands": len(self._commands),
            "aliases": len(self._aliases),
            "version": self._version,
        }

    # =========================================================================
    # Command Registration
    # =========================================================================

    def register(self, definition: DistributedCommandDefinition) -> None:
        """Register a command definition."""
        name = definition.name.lower()
        self._commands[name] = definition
        self._by_category[definition.category.value].append(name)

        # Register aliases
        for alias in definition.aliases:
            self._aliases[alias.lower()] = name

        self._increment_version()
        logger.debug(f"Registered command: {name}")

    def register_batch(self, definitions: List[DistributedCommandDefinition]) -> int:
        """Register multiple command definitions at once. Returns count."""
        for definition in definitions:
            name = definition.name.lower()
            self._commands[name] = definition
            self._by_category[definition.category.value].append(name)

            for alias in definition.aliases:
                self._aliases[alias.lower()] = name

        self._increment_version()
        logger.info(f"Registered {len(definitions)} commands (batch)")
        return len(definitions)

    def unregister(self, command_name: str) -> bool:
        """Remove a command. Returns True if found."""
        name = command_name.lower()
        if name not in self._commands:
            return False

        definition = self._commands.pop(name)

        # Remove from category
        if name in self._by_category[definition.category.value]:
            self._by_category[definition.category.value].remove(name)

        # Remove aliases
        for alias in definition.aliases:
            if alias.lower() in self._aliases:
                del self._aliases[alias.lower()]

        self._increment_version()
        return True

    # =========================================================================
    # Command Lookup
    # =========================================================================

    def get(self, command_name: str) -> Optional[DistributedCommandDefinition]:
        """Get a command by name or alias."""
        name = command_name.lower()

        # Check direct command
        if name in self._commands:
            return self._commands[name]

        # Check aliases
        if name in self._aliases:
            return self._commands[self._aliases[name]]

        return None

    def get_all(self) -> Dict[str, DistributedCommandDefinition]:
        """Get all registered commands."""
        return self._commands.copy()

    def get_by_category(self, category: CommandCategory) -> List[DistributedCommandDefinition]:
        """Get commands in a category."""
        return [
            self._commands[name]
            for name in self._by_category.get(category.value, [])
            if not self._commands[name].hidden
        ]

    def get_visible_commands(self) -> List[DistributedCommandDefinition]:
        """Get all non-hidden commands."""
        return [cmd for cmd in self._commands.values() if not cmd.hidden]

    def get_aliases(self) -> Dict[str, str]:
        """Get all alias mappings."""
        return self._aliases.copy()

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def clear_all(self) -> None:
        """Remove all commands."""
        self._commands.clear()
        self._aliases.clear()
        for cat in self._by_category:
            self._by_category[cat].clear()
        self._increment_version()
        logger.info("Cleared all commands")


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_command_registry() -> ActorHandle:
    """
    Start the command registry actor.

    Should be called once during server initialization.
    Returns the actor handle.
    """
    actor: ActorHandle = CommandRegistryActor.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote()  # type: ignore[assignment]
    logger.info(f"Started CommandRegistryActor as {ACTOR_NAMESPACE}/{ACTOR_NAME}")
    return actor


def get_command_registry_actor() -> ActorHandle:
    """
    Get the command registry actor.

    Returns the existing actor handle from the Ray cluster.
    Raises ValueError if the actor doesn't exist.
    """
    try:
        return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
    except ValueError:
        raise ValueError(
            "CommandRegistryActor not found. " "Ensure start_command_registry() was called first."
        )


def command_registry_exists() -> bool:
    """Check if the command registry actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_command_registry() -> bool:
    """
    Stop and kill the command registry actor.

    Returns True if successfully killed, False if actor wasn't found.
    """
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info(f"Stopped CommandRegistryActor {ACTOR_NAMESPACE}/{ACTOR_NAME}")
        return True
    except ValueError:
        logger.warning("CommandRegistryActor not found, nothing to stop")
        return False
    except Exception as e:
        logger.error(f"Error stopping CommandRegistryActor: {e}")
        return False


# =============================================================================
# Helper for Converting Local Definitions
# =============================================================================


def to_distributed_definition(
    name: str,
    handler_module: str,
    handler_name: str,
    aliases: Optional[List[str]] = None,
    category: CommandCategory = CommandCategory.INFORMATION,
    min_position: Position = Position.STANDING,
    help_text: str = "",
    usage: str = "",
    admin_only: bool = False,
    in_combat: bool = True,
    hidden: bool = False,
) -> DistributedCommandDefinition:
    """
    Create a DistributedCommandDefinition.

    Helper function for creating command definitions with proper defaults.
    """
    return DistributedCommandDefinition(
        name=name,
        handler_module=handler_module,
        handler_name=handler_name,
        aliases=aliases or [],
        category=category,
        min_position=min_position,
        help_text=help_text,
        usage=usage or f"{name} [arguments]",
        admin_only=admin_only,
        in_combat=in_combat,
        hidden=hidden,
    )
