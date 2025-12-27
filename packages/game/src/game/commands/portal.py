"""
Portal Commands

Commands for interacting with portals to dynamic content.
"""

from typing import List

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory


@command(
    name="enter",
    aliases=["portal"],
    category=CommandCategory.MOVEMENT,
    help_text="Enter a portal to a dynamic dungeon.",
    usage="enter [portal]",
)
async def cmd_enter(player_id: EntityId, args: List[str]) -> str:
    """Enter a portal to begin a dynamic dungeon instance."""
    # Get player's current room
    location = await _get_player_location(player_id)
    if not location:
        return "You don't seem to be anywhere."

    # Find portal in room
    portal = await _find_portal_in_room(location, args)
    if not portal:
        if args:
            return f"You don't see a portal called '{' '.join(args)}' here."
        return "You don't see any portals here."

    # Check requirements
    requirement_error = await _check_portal_requirements(player_id, portal)
    if requirement_error:
        return requirement_error

    # Create instance and enter
    result = await _enter_portal(player_id, portal)
    return result


@command(
    name="leave",
    aliases=["exit", "escape"],
    category=CommandCategory.MOVEMENT,
    help_text="Leave the current dungeon instance.",
    usage="leave",
)
async def cmd_leave(player_id: EntityId, args: List[str]) -> str:
    """Leave the current dungeon instance and return to the static world."""
    from generation.instance import get_instance_manager, instance_manager_exists

    if not instance_manager_exists():
        return "The instance system is not available."

    manager = get_instance_manager()

    # Check if player is in an instance
    instance_id = await manager.get_player_instance.remote(player_id)
    if not instance_id:
        return "You are not in a dungeon instance."

    # Get instance info
    info = await manager.get_instance_info.remote(instance_id)
    if not info:
        return "Error: Instance not found."

    # Leave the instance
    await manager.player_leave.remote(instance_id, player_id)

    # TODO: Teleport player back to portal location

    return (
        "You feel a strange sensation as reality shifts around you.\n"
        "You find yourself back at the portal entrance."
    )


@command(
    name="instance",
    aliases=["dungeon"],
    category=CommandCategory.INFORMATION,
    help_text="Show information about the current dungeon instance.",
    usage="instance",
)
async def cmd_instance(player_id: EntityId, args: List[str]) -> str:
    """Show information about the current dungeon instance."""
    from generation.instance import get_instance_manager, instance_manager_exists

    if not instance_manager_exists():
        return "The instance system is not available."

    manager = get_instance_manager()

    # Check if player is in an instance
    instance_id = await manager.get_player_instance.remote(player_id)
    if not instance_id:
        return "You are not in a dungeon instance."

    # Get instance info
    info = await manager.get_instance_info.remote(instance_id)
    if not info:
        return "Error: Instance not found."

    lines = [
        "=== Dungeon Instance ===",
        f"Theme: {info['theme_id']}",
        f"Difficulty: {info['difficulty']}",
        f"Rooms explored: {info['rooms_generated']}/{info['max_rooms']}",
        f"Players: {info['player_count']}",
    ]

    return "\n".join(lines)


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_player_location(player_id: EntityId) -> str | None:
    """Get the player's current room ID."""
    try:
        location_actor = get_component_actor("Location")
        location = await location_actor.get.remote(player_id)
        if location:
            return location.get("room_id")
    except Exception:
        pass
    return None


async def _find_portal_in_room(room_id: str, keywords: List[str]) -> dict | None:
    """Find a portal in the given room."""
    # TODO: Query room for portal entities
    # For now, return None - portals need to be implemented as entities
    return None


async def _check_portal_requirements(player_id: EntityId, portal: dict) -> str | None:
    """Check if player meets portal requirements. Returns error message if not."""
    # Check level requirement
    min_level = portal.get("min_level", 1)

    try:
        stats_actor = get_component_actor("PlayerStats")
        stats = await stats_actor.get.remote(player_id)
        if stats:
            player_level = stats.get("level", 1)
            if player_level < min_level:
                return f"You must be at least level {min_level} to enter this portal."
    except Exception:
        pass

    # Check required items
    required_items = portal.get("required_items", [])
    if required_items:
        # TODO: Check player inventory for required items
        pass

    # Check cooldown
    # TODO: Implement portal cooldown tracking

    return None


async def _enter_portal(player_id: EntityId, portal: dict) -> str:
    """Create an instance and enter the player into it."""
    from generation.instance import (
        get_instance_manager,
        start_instance_manager,
        instance_manager_exists,
    )

    # Ensure instance manager is running
    if not instance_manager_exists():
        start_instance_manager()

    manager = get_instance_manager()

    # Calculate difficulty based on player level
    difficulty = 10  # Default
    try:
        stats_actor = get_component_actor("PlayerStats")
        stats = await stats_actor.get.remote(player_id)
        if stats:
            difficulty = stats.get("level", 10)
    except Exception:
        pass

    # Clamp to portal's difficulty range
    difficulty = max(
        portal.get("difficulty_min", 1),
        min(difficulty, portal.get("difficulty_max", 100)),
    )

    # Create instance
    instance_id = await manager.create_instance.remote(
        portal_template_id=portal.get("template_id", "unknown"),
        theme_id=portal.get("theme_id", "dark_cave"),
        difficulty=difficulty,
        player_id=player_id,
        max_rooms=portal.get("max_rooms", 15),
    )

    if not instance_id:
        return "The portal flickers but refuses to open. Try again later."

    # Get entrance room info
    entrance = await manager.get_entrance_room.remote(instance_id)
    if not entrance:
        return "You step through the portal into darkness..."

    # Build entrance description
    room = entrance.generated
    lines = [
        "You step through the shimmering portal...",
        "",
        f"=== {room.name} ===",
        room.long_description,
        "",
    ]

    # Add exits
    if room.exits:
        exit_strs = [e.direction.value for e in room.exits]
        lines.append(f"Exits: {', '.join(exit_strs)}")

    return "\n".join(lines)
