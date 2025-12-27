"""
Movement Commands

Commands for moving around the world, including support for dynamic regions
that are generated on-demand as players explore.
"""

from typing import List, Optional
import logging

from core import EntityId
from ..components import Direction, WorldCoordinate
from .registry import command, CommandCategory

logger = logging.getLogger(__name__)


@command(
    name="north",
    aliases=["n"],
    category=CommandCategory.MOVEMENT,
    help_text="Move north.",
    usage="north",
)
async def cmd_north(player_id: EntityId, args: List[str]) -> str:
    """Move to the north."""
    return await _do_move(player_id, "north")


@command(
    name="south",
    aliases=["s"],
    category=CommandCategory.MOVEMENT,
    help_text="Move south.",
    usage="south",
)
async def cmd_south(player_id: EntityId, args: List[str]) -> str:
    """Move to the south."""
    return await _do_move(player_id, "south")


@command(
    name="east",
    aliases=["e"],
    category=CommandCategory.MOVEMENT,
    help_text="Move east.",
    usage="east",
)
async def cmd_east(player_id: EntityId, args: List[str]) -> str:
    """Move to the east."""
    return await _do_move(player_id, "east")


@command(
    name="west",
    aliases=["w"],
    category=CommandCategory.MOVEMENT,
    help_text="Move west.",
    usage="west",
)
async def cmd_west(player_id: EntityId, args: List[str]) -> str:
    """Move to the west."""
    return await _do_move(player_id, "west")


@command(
    name="up",
    aliases=["u"],
    category=CommandCategory.MOVEMENT,
    help_text="Move up.",
    usage="up",
)
async def cmd_up(player_id: EntityId, args: List[str]) -> str:
    """Move up."""
    return await _do_move(player_id, "up")


@command(
    name="down",
    aliases=["d"],
    category=CommandCategory.MOVEMENT,
    help_text="Move down.",
    usage="down",
)
async def cmd_down(player_id: EntityId, args: List[str]) -> str:
    """Move down."""
    return await _do_move(player_id, "down")


@command(
    name="northeast",
    aliases=["ne"],
    category=CommandCategory.MOVEMENT,
    help_text="Move northeast.",
    usage="northeast",
)
async def cmd_northeast(player_id: EntityId, args: List[str]) -> str:
    """Move northeast."""
    return await _do_move(player_id, "northeast")


@command(
    name="northwest",
    aliases=["nw"],
    category=CommandCategory.MOVEMENT,
    help_text="Move northwest.",
    usage="northwest",
)
async def cmd_northwest(player_id: EntityId, args: List[str]) -> str:
    """Move northwest."""
    return await _do_move(player_id, "northwest")


@command(
    name="southeast",
    aliases=["se"],
    category=CommandCategory.MOVEMENT,
    help_text="Move southeast.",
    usage="southeast",
)
async def cmd_southeast(player_id: EntityId, args: List[str]) -> str:
    """Move southeast."""
    return await _do_move(player_id, "southeast")


@command(
    name="southwest",
    aliases=["sw"],
    category=CommandCategory.MOVEMENT,
    help_text="Move southwest.",
    usage="southwest",
)
async def cmd_southwest(player_id: EntityId, args: List[str]) -> str:
    """Move southwest."""
    return await _do_move(player_id, "southwest")


async def _do_move(player_id: EntityId, direction: str) -> str:
    """
    Execute a movement command.

    Handles three types of exits:
    1. Normal exits with destination_id -> direct room transition
    2. Exits leading to dynamic regions -> generate room on-demand
    3. Exits from dynamic regions to static rooms

    This creates a MovementRequest component that will be processed
    by the MovementSystem on the next tick.
    """
    from datetime import datetime
    from core.component import get_component_actor

    # Get player's current location
    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    # Get current room to check exits
    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(location.room_id)

    if not room:
        return "You are in a featureless void."

    # Check for exit in that direction
    exit_data = room.get_exit(direction)
    if not exit_data:
        return f"You can't go {direction}."

    # Check if door is locked
    if exit_data.is_locked:
        return "The door is locked."

    # Check combat state
    combat_actor = get_component_actor("Combat")
    combat = await combat_actor.get.remote(player_id)
    if combat and combat.is_in_combat:
        return "You can't leave while in combat! Try to flee instead."

    # Determine destination based on exit type
    destination_id = None
    destination_room = None
    entering_region = None
    exiting_region = None
    entry_coordinate = None

    if exit_data.destination_id:
        # Type 1: Normal exit with direct destination
        destination_id = exit_data.destination_id

    elif exit_data.leads_to_region and exit_data.target_coordinate:
        # Type 2: Exit leads into a dynamic region
        destination_id, destination_room, entering_region, entry_coordinate = (
            await _handle_region_entry(
                player_id,
                exit_data.leads_to_region,
                exit_data.target_coordinate,
                direction,
            )
        )
        if not destination_id:
            return "The path ahead is shrouded in an impenetrable mist."

    elif exit_data.target_static_room:
        # Type 3: Exit from dynamic region to static room
        destination_id, exiting_region = await _handle_region_exit(
            player_id,
            room,
            exit_data.target_static_room,
        )
        if not destination_id:
            return "You cannot find the way back."

    else:
        return f"The exit {direction} leads nowhere."

    # Track region transitions
    if entering_region:
        await _track_region_entry(player_id, entering_region, entry_coordinate)

    if exiting_region:
        current_coord = getattr(room, "coordinate", None)
        await _track_region_exit(player_id, exiting_region, current_coord)

    # Perform the movement
    def update_location(loc):
        loc.last_room_id = loc.room_id
        loc.room_id = destination_id
        loc.entered_at = datetime.utcnow()

    await location_actor.mutate.remote(player_id, update_location)

    # Get destination room description
    dest_room = destination_room
    if not dest_room:
        dest_room = await room_actor.get.remote(destination_id)

    identity_actor = get_component_actor("Identity")
    dest_identity = await identity_actor.get.remote(destination_id)

    room_name = dest_identity.name if dest_identity else dest_room.short_description if dest_room else "A Room"
    room_desc = dest_room.long_description if dest_room else "You see nothing special."

    # Get exits
    exits = dest_room.get_available_exits() if dest_room else []
    exits_str = ", ".join(exits) if exits else "none"

    # Get entities in room
    all_locations = await location_actor.get_all.remote()
    entities_here = []
    for eid, loc in all_locations.items():
        if loc.room_id == destination_id and eid != player_id:
            entity_identity = await identity_actor.get.remote(eid)
            if entity_identity:
                entities_here.append(entity_identity.short_description)

    # Build output
    lines = [
        room_name,
        "",
        room_desc,
    ]

    if entities_here:
        lines.append("")
        for desc in entities_here:
            lines.append(desc)

    lines.append("")
    lines.append(f"[Exits: {exits_str}]")

    return "\n".join(lines)


async def _handle_region_entry(
    player_id: EntityId,
    region_id: str,
    target_coordinate: WorldCoordinate,
    direction: str,
) -> tuple:
    """
    Handle entering a dynamic region.

    Returns (destination_id, room_data, region_id, coordinate) or (None, None, None, None).
    """
    try:
        from generation import get_region_manager, region_manager_exists

        if not region_manager_exists():
            logger.warning("RegionManager not available")
            return None, None, None, None

        manager = get_region_manager()

        # Parse direction
        dir_enum = Direction.from_string(direction)

        # Get or generate the room at target coordinate
        room_id = await manager.get_or_generate_room.remote(
            region_id=region_id,
            coordinate=target_coordinate,
            entry_direction=dir_enum,
            triggered_by=player_id,
        )

        if not room_id:
            return None, None, None, None

        # Get the room data
        room_data = await manager.get_room_by_id.remote(region_id, room_id)

        return room_id, room_data, region_id, target_coordinate

    except Exception as e:
        logger.error(f"Error handling region entry: {e}")
        return None, None, None, None


async def _handle_region_exit(
    player_id: EntityId,
    current_room,
    target_static_room_id: str,
) -> tuple:
    """
    Handle exiting a dynamic region to a static room.

    Returns (destination_id, region_id) or (None, None).
    """
    try:
        # Get the static room entity ID
        destination_id = EntityId(id=target_static_room_id, entity_type="room")

        # Get region ID from current room if available
        region_id = getattr(current_room, "region_id", None)

        return destination_id, region_id

    except Exception as e:
        logger.error(f"Error handling region exit: {e}")
        return None, None


async def _track_region_entry(
    player_id: EntityId,
    region_id: str,
    coordinate: Optional[WorldCoordinate],
) -> None:
    """Track player entering a region."""
    try:
        from generation import get_region_manager, region_manager_exists

        if region_manager_exists():
            manager = get_region_manager()
            await manager.player_enter_region.remote(
                region_id=region_id,
                player_id=str(player_id.id),
                coordinate=coordinate or WorldCoordinate(0, 0, 0),
            )
    except Exception as e:
        logger.warning(f"Failed to track region entry: {e}")


async def _track_region_exit(
    player_id: EntityId,
    region_id: str,
    coordinate: Optional[WorldCoordinate],
) -> None:
    """Track player exiting a region."""
    try:
        from generation import get_region_manager, region_manager_exists

        if region_manager_exists():
            manager = get_region_manager()
            await manager.player_exit_region.remote(
                region_id=region_id,
                player_id=str(player_id.id),
                coordinate=coordinate or WorldCoordinate(0, 0, 0),
            )
    except Exception as e:
        logger.warning(f"Failed to track region exit: {e}")


@command(
    name="exits",
    aliases=["ex"],
    category=CommandCategory.MOVEMENT,
    help_text="Show available exits from current room.",
    usage="exits",
)
async def cmd_exits(player_id: EntityId, args: List[str]) -> str:
    """Show exits from the current room."""
    from core.component import get_component_actor

    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(location.room_id)

    if not room:
        return "You are in a featureless void."

    exits = []
    for direction, exit_data in room.exits.items():
        if exit_data.is_hidden:
            continue

        status = ""
        if exit_data.is_door:
            status = " (door)"
            if exit_data.is_locked:
                status = " (locked)"

        exits.append(f"  {direction}{status}")

    if not exits:
        return "There are no obvious exits."

    return "Obvious exits:\n" + "\n".join(exits)


@command(
    name="recall",
    aliases=["rec"],
    category=CommandCategory.MOVEMENT,
    help_text="Return to the starting location.",
    usage="recall",
    in_combat=False,
)
async def cmd_recall(player_id: EntityId, args: List[str]) -> str:
    """Recall to the starting location."""
    from core.component import get_component_actor

    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    # Check if room allows recall
    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(location.room_id)

    if room and room.is_no_recall:
        return "Something prevents your recall."

    # Get starting room (first room in template registry)
    from ..world.templates import get_template_registry

    registry = get_template_registry()
    rooms = registry.get_all_rooms()

    if not rooms:
        return "There is nowhere to recall to."

    start_template_id = list(rooms.keys())[0]
    start_room_id = EntityId(id=start_template_id, entity_type="room")

    # Teleport player
    from datetime import datetime

    def teleport(loc):
        loc.last_room_id = loc.room_id
        loc.room_id = start_room_id
        loc.entered_at = datetime.utcnow()

    await location_actor.mutate.remote(player_id, teleport)

    return "You pray to the gods and are transported back to safety."
