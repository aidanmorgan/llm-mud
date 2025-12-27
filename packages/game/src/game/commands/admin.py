"""
Admin Commands

Commands for administrators and immortals to manage the game world.
All commands in this file require admin privileges.
"""

from typing import List, Optional
from datetime import datetime

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.position import Position


# =============================================================================
# Teleportation Commands
# =============================================================================


@command(
    name="goto",
    aliases=["go"],
    category=CommandCategory.ADMIN,
    help_text="Teleport to a room or player.",
    usage="goto <room_id | player_name>",
    admin_only=True,
    min_position=Position.DEAD,
)
async def cmd_goto(player_id: EntityId, args: List[str]) -> str:
    """Teleport to a room or player location."""
    if not args:
        return "Goto where? Specify a room ID or player name."

    target = args[0]

    # Check if it's a room ID
    room_actor = get_component_actor("Room")
    room_id = EntityId("room", target)
    room = await room_actor.get.remote(room_id)

    if room:
        return await _teleport_to_room(player_id, room_id)

    # Try to find a player
    target_id = await _find_player_by_name(target)
    if target_id:
        location_actor = get_component_actor("Location")
        target_location = await location_actor.get.remote(target_id)
        if target_location and target_location.room_id:
            return await _teleport_to_room(player_id, target_location.room_id)
        return f"Player {target} has no location."

    return f"Cannot find room or player: {target}"


@command(
    name="transfer",
    aliases=["trans"],
    category=CommandCategory.ADMIN,
    help_text="Bring a player to your location.",
    usage="transfer <player_name>",
    admin_only=True,
)
async def cmd_transfer(player_id: EntityId, args: List[str]) -> str:
    """Bring a player to your current location."""
    if not args:
        return "Transfer who?"

    target_name = args[0]
    target_id = await _find_player_by_name(target_name)

    if not target_id:
        return f"Player '{target_name}' not found."

    if target_id == player_id:
        return "You're already here."

    # Get admin's location
    location_actor = get_component_actor("Location")
    admin_location = await location_actor.get.remote(player_id)

    if not admin_location or not admin_location.room_id:
        return "You have no location to transfer to."

    # Teleport target to admin's room
    return await _teleport_to_room(target_id, admin_location.room_id, notify=True)


@command(
    name="at",
    category=CommandCategory.ADMIN,
    help_text="Execute a command at a remote location.",
    usage="at <room_id> <command>",
    admin_only=True,
)
async def cmd_at(player_id: EntityId, args: List[str]) -> str:
    """Execute a command at a remote location."""
    if len(args) < 2:
        return "Usage: at <room_id> <command>"

    room_id_str = args[0]
    command_str = " ".join(args[1:])

    # Save current location
    location_actor = get_component_actor("Location")
    original_location = await location_actor.get.remote(player_id)

    if not original_location:
        return "You have no location."

    # Temporarily move to target room
    room_id = EntityId("room", room_id_str)

    def set_temp_location(loc):
        loc.room_id = room_id

    await location_actor.mutate.remote(player_id, set_temp_location)

    # Execute command (would need CommandHandler access)
    result = f"[At {room_id_str}] Command would execute: {command_str}"

    # Restore original location
    def restore_location(loc):
        loc.room_id = original_location.room_id

    await location_actor.mutate.remote(player_id, restore_location)

    return result


# =============================================================================
# Entity Management Commands
# =============================================================================


@command(
    name="slay",
    category=CommandCategory.ADMIN,
    help_text="Instantly kill a target.",
    usage="slay <target>",
    admin_only=True,
)
async def cmd_slay(player_id: EntityId, args: List[str]) -> str:
    """Instantly kill a target."""
    if not args:
        return "Slay who?"

    target_keyword = args[0].lower()

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    target_id = await _find_entity_in_room(player_location.room_id, target_keyword, player_id)

    if not target_id:
        return f"You don't see '{target_keyword}' here."

    # Get target name
    identity_actor = get_component_actor("Identity")
    target_identity = await identity_actor.get.remote(target_id)
    target_name = target_identity.name if target_identity else "It"

    # Kill the target
    stats_actor = get_component_actor("Stats")

    def kill_entity(stats):
        stats.current_hp = 0
        stats.is_alive = False

    await stats_actor.mutate.remote(target_id, kill_entity)

    return f"You slay {target_name} with divine power!"


@command(
    name="restore",
    aliases=["heal"],
    category=CommandCategory.ADMIN,
    help_text="Restore a target to full health and mana.",
    usage="restore [target]",
    admin_only=True,
)
async def cmd_restore(player_id: EntityId, args: List[str]) -> str:
    """Restore a target to full health and mana."""
    target_id = player_id
    target_name = "yourself"

    if args:
        target_keyword = args[0].lower()

        location_actor = get_component_actor("Location")
        player_location = await location_actor.get.remote(player_id)

        if player_location and player_location.room_id:
            found_id = await _find_entity_in_room(
                player_location.room_id, target_keyword, None
            )
            if found_id:
                target_id = found_id
                identity_actor = get_component_actor("Identity")
                identity = await identity_actor.get.remote(target_id)
                target_name = identity.name if identity else target_keyword

    # Restore stats
    stats_actor = get_component_actor("Stats")

    def restore_stats(stats):
        stats.current_hp = stats.max_hp
        stats.current_mana = stats.max_mana
        stats.current_stamina = stats.max_stamina
        stats.is_alive = True

    await stats_actor.mutate.remote(target_id, restore_stats)

    return f"You restore {target_name} to full health!"


@command(
    name="peace",
    category=CommandCategory.ADMIN,
    help_text="Stop all combat in the current room.",
    usage="peace",
    admin_only=True,
)
async def cmd_peace(player_id: EntityId, args: List[str]) -> str:
    """Stop all combat in the current room."""
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    room_id = player_location.room_id

    # Find all entities in room
    all_locations = await location_actor.get_all.remote()
    combat_actor = get_component_actor("Combat")

    stopped = 0
    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue

        combat = await combat_actor.get.remote(entity_id)
        if combat and combat.is_in_combat:

            def clear_combat(c):
                c.clear_target()
                c.targeted_by = []

            await combat_actor.mutate.remote(entity_id, clear_combat)
            stopped += 1

    if stopped == 0:
        return "There is no fighting here."

    return f"Peace descends upon the room. ({stopped} combatants stopped)"


@command(
    name="purge",
    category=CommandCategory.ADMIN,
    help_text="Remove all non-player entities from the room.",
    usage="purge",
    admin_only=True,
)
async def cmd_purge(player_id: EntityId, args: List[str]) -> str:
    """Remove all non-player entities from the room."""
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    room_id = player_location.room_id

    # Find all non-player entities in room
    all_locations = await location_actor.get_all.remote()

    purged = 0
    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if entity_id.entity_type == "player":
            continue

        # Remove entity by clearing its location
        def clear_location(loc):
            loc.room_id = None

        await location_actor.mutate.remote(entity_id, clear_location)
        purged += 1

    if purged == 0:
        return "There is nothing to purge here."

    return f"The room is purged of {purged} entities."


# =============================================================================
# Information Commands
# =============================================================================


@command(
    name="stat",
    aliases=["mstat"],
    category=CommandCategory.ADMIN,
    help_text="Show detailed statistics for an entity.",
    usage="stat <target>",
    admin_only=True,
)
async def cmd_stat(player_id: EntityId, args: List[str]) -> str:
    """Show detailed entity statistics."""
    if not args:
        return "Stat who?"

    target_keyword = args[0].lower()

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    target_id = await _find_entity_in_room(
        player_location.room_id, target_keyword, None
    )

    if not target_id:
        return f"You don't see '{target_keyword}' here."

    # Gather all component data
    lines = [f"=== Entity Stats: {target_id} ==="]

    # Identity
    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(target_id)
    if identity:
        lines.append(f"Name: {identity.name}")
        lines.append(f"Keywords: {', '.join(identity.keywords)}")

    # Stats
    stats_actor = get_component_actor("Stats")
    stats = await stats_actor.get.remote(target_id)
    if stats:
        lines.append(f"HP: {stats.current_hp}/{stats.max_hp}")
        lines.append(f"Mana: {stats.current_mana}/{stats.max_mana}")
        lines.append(f"Alive: {stats.is_alive}")
        if hasattr(stats, "level"):
            lines.append(f"Level: {stats.level}")
        if hasattr(stats, "challenge_rating"):
            lines.append(f"CR: {stats.challenge_rating}")

    # Combat
    combat_actor = get_component_actor("Combat")
    combat = await combat_actor.get.remote(target_id)
    if combat:
        lines.append(f"In Combat: {combat.is_in_combat}")
        lines.append(f"Target: {combat.target}")

    # AI
    ai_actor = get_component_actor("AI")
    ai = await ai_actor.get.remote(target_id)
    if ai:
        lines.append(f"AI Behavior: {ai.get('behavior_type', 'none')}")

    # Dynamic AI
    dynamic_ai_actor = get_component_actor("DynamicAI")
    dynamic_ai = await dynamic_ai_actor.get.remote(target_id)
    if dynamic_ai:
        personality = dynamic_ai.get("personality", {})
        lines.append(f"Personality Traits: {personality.get('traits', [])}")
        lines.append(f"Combat Style: {personality.get('combat_style', 'unknown')}")

    return "\n".join(lines)


@command(
    name="rstat",
    category=CommandCategory.ADMIN,
    help_text="Show detailed statistics for the current room.",
    usage="rstat",
    admin_only=True,
)
async def cmd_rstat(player_id: EntityId, args: List[str]) -> str:
    """Show detailed room statistics."""
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    room_id = player_location.room_id
    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(room_id)

    if not room:
        return f"Room {room_id} not found."

    lines = [f"=== Room Stats: {room_id} ==="]
    lines.append(f"Name: {room.name}")
    lines.append(f"Zone: {getattr(room, 'zone_id', 'unknown')}")
    lines.append(f"Sector: {getattr(room, 'sector_type', 'unknown')}")
    lines.append(f"Safe: {getattr(room, 'is_safe', False)}")

    # Exits
    exits = room.get_available_exits() if hasattr(room, "get_available_exits") else []
    lines.append(f"Exits: {', '.join(exits) if exits else 'none'}")

    # Count entities in room
    all_locations = await location_actor.get_all.remote()
    entity_count = sum(1 for loc in all_locations.values() if loc.room_id == room_id)
    lines.append(f"Entities: {entity_count}")

    return "\n".join(lines)


# =============================================================================
# Entity Modification Commands
# =============================================================================


@command(
    name="set",
    category=CommandCategory.ADMIN,
    help_text="Set a property on an entity.",
    usage="set <target> <property> <value>",
    admin_only=True,
)
async def cmd_set(player_id: EntityId, args: List[str]) -> str:
    """Set a property on an entity."""
    if len(args) < 3:
        return "Usage: set <target> <property> <value>"

    target_keyword = args[0].lower()
    prop = args[1].lower()
    value = " ".join(args[2:])

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    target_id = await _find_entity_in_room(
        player_location.room_id, target_keyword, None
    )

    if not target_id:
        return f"You don't see '{target_keyword}' here."

    # Handle common properties
    if prop in ("hp", "health"):
        try:
            hp_value = int(value)
            stats_actor = get_component_actor("Stats")

            def set_hp(stats):
                stats.current_hp = hp_value

            await stats_actor.mutate.remote(target_id, set_hp)
            return f"Set HP to {hp_value}."
        except ValueError:
            return "HP must be a number."

    elif prop in ("mana", "mp"):
        try:
            mana_value = int(value)
            stats_actor = get_component_actor("Stats")

            def set_mana(stats):
                stats.current_mana = mana_value

            await stats_actor.mutate.remote(target_id, set_mana)
            return f"Set mana to {mana_value}."
        except ValueError:
            return "Mana must be a number."

    elif prop == "level":
        try:
            level_value = int(value)
            stats_actor = get_component_actor("Stats")

            def set_level(stats):
                stats.level = level_value

            await stats_actor.mutate.remote(target_id, set_level)
            return f"Set level to {level_value}."
        except ValueError:
            return "Level must be a number."

    elif prop == "name":
        identity_actor = get_component_actor("Identity")

        def set_name(identity):
            identity.name = value

        await identity_actor.mutate.remote(target_id, set_name)
        return f"Set name to '{value}'."

    else:
        return f"Unknown property: {prop}. Try: hp, mana, level, name"


# =============================================================================
# Server Commands
# =============================================================================


@command(
    name="shutdown",
    category=CommandCategory.ADMIN,
    help_text="Shut down the server.",
    usage="shutdown [delay_seconds]",
    admin_only=True,
    min_position=Position.DEAD,
)
async def cmd_shutdown(player_id: EntityId, args: List[str]) -> str:
    """Initiate server shutdown."""
    delay = 0
    if args:
        try:
            delay = int(args[0])
        except ValueError:
            return "Delay must be a number of seconds."

    if delay > 0:
        return f"Server shutdown initiated in {delay} seconds. (Not implemented)"
    else:
        return "Immediate server shutdown requested. (Not implemented)"


@command(
    name="reboot",
    category=CommandCategory.ADMIN,
    help_text="Reboot the server.",
    usage="reboot [delay_seconds]",
    admin_only=True,
    min_position=Position.DEAD,
)
async def cmd_reboot(player_id: EntityId, args: List[str]) -> str:
    """Initiate server reboot."""
    delay = 0
    if args:
        try:
            delay = int(args[0])
        except ValueError:
            return "Delay must be a number of seconds."

    if delay > 0:
        return f"Server reboot initiated in {delay} seconds. (Not implemented)"
    else:
        return "Immediate server reboot requested. (Not implemented)"


@command(
    name="echo",
    category=CommandCategory.ADMIN,
    help_text="Send a message to all players in the room.",
    usage="echo <message>",
    admin_only=True,
)
async def cmd_echo(player_id: EntityId, args: List[str]) -> str:
    """Send a message to all players in the room."""
    if not args:
        return "Echo what?"

    message = " ".join(args)

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    await _broadcast_to_room(player_location.room_id, message)

    return f"Echoed: {message}"


@command(
    name="gecho",
    category=CommandCategory.ADMIN,
    help_text="Send a message to all players globally.",
    usage="gecho <message>",
    admin_only=True,
)
async def cmd_gecho(player_id: EntityId, args: List[str]) -> str:
    """Send a message to all online players."""
    if not args:
        return "Global echo what?"

    message = " ".join(args)

    await _broadcast_global(message)

    return f"Global echo: {message}"


# =============================================================================
# Save Commands
# =============================================================================


@command(
    name="saveall",
    category=CommandCategory.ADMIN,
    help_text="Save all online players.",
    usage="saveall",
    admin_only=True,
    min_position=Position.DEAD,
)
async def cmd_saveall(player_id: EntityId, args: List[str]) -> str:
    """Save all online players."""
    from ..persistence import get_autosave_manager, autosave_manager_exists

    if not autosave_manager_exists():
        return "Auto-save system is not running."

    manager = get_autosave_manager()
    saved = await manager.save_all_players.remote()

    return f"Saved {saved} players."


@command(
    name="forcesave",
    category=CommandCategory.ADMIN,
    help_text="Force save a specific player.",
    usage="forcesave <player_name>",
    admin_only=True,
    min_position=Position.DEAD,
)
async def cmd_forcesave(player_id: EntityId, args: List[str]) -> str:
    """Force save a specific player."""
    if not args:
        return "Save which player?"

    target_name = args[0]
    target_id = await _find_player_by_name(target_name)

    if not target_id:
        return f"Player '{target_name}' not found."

    from ..persistence import save_player

    if await save_player(target_id):
        identity_actor = get_component_actor("Identity")
        identity = await identity_actor.get.remote(target_id)
        name = identity.name if identity else target_name
        return f"Saved player: {name}"
    else:
        return "Failed to save player."


# =============================================================================
# Helper Functions
# =============================================================================


async def _teleport_to_room(
    entity_id: EntityId, room_id: EntityId, notify: bool = False
) -> str:
    """Teleport an entity to a room."""
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")

    identity = await identity_actor.get.remote(entity_id)
    name = identity.name if identity else "Someone"

    def update_location(loc):
        loc.last_room_id = loc.room_id
        loc.room_id = room_id
        loc.entered_at = datetime.utcnow()

    await location_actor.mutate.remote(entity_id, update_location)

    if notify:
        await _send_to_entity(entity_id, "You have been summoned!")

    return f"{name} teleported to {room_id}."


async def _find_player_by_name(name: str) -> Optional[EntityId]:
    """Find a player by name."""
    name_lower = name.lower()
    identity_actor = get_component_actor("Identity")
    connection_actor = get_component_actor("Connection")

    all_connections = await connection_actor.get_all.remote()

    for entity_id, connection in all_connections.items():
        if not connection.is_connected:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if identity and identity.name.lower().startswith(name_lower):
            return entity_id

    return None


async def _find_entity_in_room(
    room_id: EntityId, keyword: str, exclude_id: Optional[EntityId]
) -> Optional[EntityId]:
    """Find an entity in a room by keyword."""
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")

    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if exclude_id and entity_id == exclude_id:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        # Check if keyword matches
        if keyword in identity.name.lower():
            return entity_id
        for kw in identity.keywords:
            if keyword in kw.lower():
                return entity_id

    return None


async def _broadcast_to_room(room_id: EntityId, message: str) -> None:
    """Send a message to all players in a room."""
    location_actor = get_component_actor("Location")
    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if entity_id.entity_type != "player":
            continue

        await _send_to_entity(entity_id, message)


async def _broadcast_global(message: str) -> None:
    """Send a message to all online players."""
    connection_actor = get_component_actor("Connection")
    all_connections = await connection_actor.get_all.remote()

    for entity_id, connection in all_connections.items():
        if not connection.is_connected:
            continue

        await _send_to_entity(entity_id, message)


async def _send_to_entity(entity_id: EntityId, message: str) -> None:
    """Send a message to a specific entity."""
    try:
        import ray

        gateway = ray.get_actor("gateway", namespace="llmmud")
        from network.protocol import create_text

        await gateway.send_to_player.remote(entity_id, create_text(message, "admin"))
    except Exception:
        pass
