"""
Guild Access System

Enforces class-based room restrictions for guild halls.
Players can only enter their own class's guild.

This system doesn't run every tick like other systems.
Instead, it provides validation methods called by the movement system.
"""

import logging
from typing import Optional, Tuple

import ray
from ray.actor import ActorHandle

from core import EntityId

logger = logging.getLogger(__name__)


# =============================================================================
# Guild Access Validation
# =============================================================================


@ray.remote
class GuildAccessSystem:
    """
    Validates guild room access based on player class.

    This is a utility actor, not a tick-based system.
    Called by MovementSystem before allowing entry to guild rooms.

    Features:
    - Check if a room is a guild room
    - Validate player class matches guild class
    - Provide appropriate rejection messages
    """

    def __init__(self):
        self._class_registry = None

    def _get_class_registry(self) -> ActorHandle:
        """Get the class registry actor lazily."""
        if self._class_registry is None:
            from ..world.class_registry import get_class_registry
            self._class_registry = get_class_registry()
        return self._class_registry

    async def validate_entry(
        self,
        room_id: EntityId,
        player_class: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if a player can enter a room.

        Args:
            room_id: The room the player wants to enter
            player_class: The player's class ID

        Returns:
            (allowed, message) tuple:
            - allowed: True if player can enter
            - message: Rejection message if not allowed, entrance message if allowed
        """
        registry = self._get_class_registry()

        # Check if this is a guild room
        guild_class = await registry.get_guild_class.remote(room_id)

        if guild_class is None:
            # Not a guild room - allow entry
            return (True, None)

        # Check if player's class matches
        if guild_class == player_class:
            # Get entrance message
            entrance_msg = await registry.get_guild_entrance_message.remote(room_id)
            return (True, entrance_msg)

        # Player can't enter - get rejection message
        rejection_msg = await registry.get_guild_rejection_message.remote(room_id)
        if not rejection_msg:
            rejection_msg = "Only members of this guild may enter."

        return (False, rejection_msg)

    async def get_guild_info(
        self,
        room_id: EntityId,
    ) -> Optional[dict]:
        """
        Get guild information for a room.

        Returns None if not a guild room.
        """
        registry = self._get_class_registry()
        guild_class = await registry.get_guild_class.remote(room_id)

        if guild_class is None:
            return None

        class_def = await registry.get_class.remote(guild_class)
        if not class_def:
            return {"class_id": guild_class}

        return {
            "class_id": guild_class,
            "class_name": class_def.name,
            "guild_name": class_def.guild.guild_name,
            "guild_master_id": class_def.guild.guild_master_id,
        }

    async def is_guild_room(self, room_id: EntityId) -> bool:
        """Check if a room is a guild room."""
        registry = self._get_class_registry()
        guild_class = await registry.get_guild_class.remote(room_id)
        return guild_class is not None

    async def get_player_guild_location(self, player_class: str) -> Optional[str]:
        """Get the guild location for a player's class."""
        registry = self._get_class_registry()
        guild_config = await registry.get_guild_for_class.remote(player_class)

        if guild_config:
            return guild_config.location_id
        return None


# =============================================================================
# Actor Management
# =============================================================================

ACTOR_NAME = "guild_access_system"
ACTOR_NAMESPACE = "llmmud"

_guild_access_system: Optional[ActorHandle] = None


def get_guild_access_system() -> ActorHandle:
    """Get the guild access system actor."""
    global _guild_access_system
    if _guild_access_system is None:
        _guild_access_system = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
    return _guild_access_system


async def start_guild_access_system() -> ActorHandle:
    """Start the guild access system actor."""
    global _guild_access_system

    system: ActorHandle = GuildAccessSystem.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote()

    _guild_access_system = system
    logger.info("Started GuildAccessSystem actor")
    return system


def guild_access_system_exists() -> bool:
    """Check if guild access system actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


# =============================================================================
# Utility Functions
# =============================================================================


async def can_enter_guild_room(
    room_id: EntityId,
    player_class: str,
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to check guild room access.

    Can be called from movement commands without getting the actor.
    """
    if not guild_access_system_exists():
        # If system not running, allow all access
        return (True, None)

    system = get_guild_access_system()
    return await system.validate_entry.remote(room_id, player_class)
