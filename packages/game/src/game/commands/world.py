"""World commands - time, weather, navigation, zones."""

from typing import Optional, List, Dict

from ..commands.registry import command, CommandCategory


@command(
    name="time",
    aliases=["date", "clock"],
    category=CommandCategory.INFO,
    help_text="Check the current game time and date.",
)
async def cmd_time(player_id: str, args: str, game_state) -> str:
    """Display current game time."""
    from ..components.world import WorldStateData

    world = await game_state.get_component("world", "WorldStateData")
    if not world:
        return "The flow of time seems uncertain here."

    gt = world.game_time
    lines = [
        f"=== Time ===",
        "",
        f"Time: {gt.format_time()}",
        f"Date: {gt.format_date()}",
        "",
        f"It is currently {gt.time_of_day.value}.",
        gt.time_of_day.description,
        "",
        f"Season: {gt.season.value.title()}",
        gt.season.description,
        "",
        f"Moon: {gt.moon_phase.value.replace('_', ' ').title()}",
        gt.moon_phase.description,
    ]

    return "\n".join(lines)


@command(
    name="where",
    aliases=["nearby"],
    category=CommandCategory.INFO,
    help_text="Show nearby players and points of interest.",
)
async def cmd_where(player_id: str, args: str, game_state) -> str:
    """Show nearby players and locations."""
    from ..components.spatial import LocationData, RoomData
    from ..components.identity import IdentityData

    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    # Get current room info
    room = await game_state.get_component(location.room_id, "RoomData")
    room_name = room.name if room else "Unknown Location"
    zone_id = room.zone_id if room else "unknown"

    lines = [
        f"=== Where: {room_name} ===",
        f"Zone: {zone_id.replace('_', ' ').title()}",
        "",
    ]

    # Get players in same zone
    zone_players = await game_state.get_players_in_zone(zone_id)
    if zone_players:
        lines.append("Players in this area:")
        for pid, room_id in zone_players.items():
            if pid == player_id:
                continue
            p_identity = await game_state.get_component(pid, "IdentityData")
            p_room = await game_state.get_component(room_id, "RoomData")
            p_name = p_identity.name if p_identity else "Someone"
            p_location = p_room.name if p_room else "somewhere"

            if room_id == location.room_id:
                lines.append(f"  {p_name} - here")
            else:
                lines.append(f"  {p_name} - {p_location}")
    else:
        lines.append("You don't sense any other adventurers nearby.")

    # Points of interest (shops, trainers, etc.)
    poi = await game_state.get_points_of_interest(zone_id)
    if poi:
        lines.append("")
        lines.append("Points of Interest:")
        for name, room_name in poi.items():
            lines.append(f"  {name} - {room_name}")

    return "\n".join(lines)


@command(
    name="scan",
    aliases=["look around", "peer"],
    category=CommandCategory.INFO,
    help_text="Look into adjacent rooms to see what's there.",
)
async def cmd_scan(player_id: str, args: str, game_state) -> str:
    """Scan adjacent rooms."""
    from ..components.spatial import LocationData, RoomData, Direction
    from ..components.identity import IdentityData
    from ..components.world import WorldStateData, RoomVisibilityData

    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    room = await game_state.get_component(location.room_id, "RoomData")
    if not room:
        return "You can't make out your surroundings."

    # Check visibility
    world = await game_state.get_component("world", "WorldStateData")
    visibility = await game_state.get_component(location.room_id, "RoomVisibilityData")

    lines = ["=== Scanning ===", ""]

    for direction, exit_data in room.exits.items():
        if not exit_data or not exit_data.destination:
            continue

        dir_name = direction.value if hasattr(direction, 'value') else direction
        dest_room = await game_state.get_component(exit_data.destination, "RoomData")

        if not dest_room:
            lines.append(f"{dir_name.title()}: You can't see what lies that way.")
            continue

        # Get entities in that room
        entities = await game_state.get_entities_in_room(exit_data.destination)

        entity_names = []
        for eid in entities:
            e_identity = await game_state.get_component(eid, "IdentityData")
            if e_identity:
                entity_names.append(e_identity.name)

        if entity_names:
            entity_str = ", ".join(entity_names[:5])
            if len(entity_names) > 5:
                entity_str += f" and {len(entity_names) - 5} more"
            lines.append(f"{dir_name.title()}: {dest_room.name}")
            lines.append(f"    You see: {entity_str}")
        else:
            lines.append(f"{dir_name.title()}: {dest_room.name} (empty)")

    if len(lines) == 2:
        return "You scan your surroundings but see no exits."

    return "\n".join(lines)


@command(
    name="track",
    aliases=["hunt", "search"],
    category=CommandCategory.INFO,
    help_text="Try to track a target's direction.",
)
async def cmd_track(player_id: str, args: str, game_state) -> str:
    """Track a target."""
    from ..components.spatial import LocationData
    from ..components.stats import PlayerStatsData

    if not args:
        return "Track whom? Usage: track <name>"

    target_name = args.split()[0]

    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    # Get player stats for tracking ability
    stats = await game_state.get_component(player_id, "PlayerStatsData")
    wisdom = stats.attributes.wisdom if stats and hasattr(stats, 'attributes') else 10

    # Try to find target
    target_id = await game_state.find_player_by_name(target_name)
    if not target_id:
        # Try to find mob
        target_id = await game_state.find_mob_by_name(target_name, location.room_id)

    if not target_id:
        return f"You cannot find any trace of '{target_name}'."

    target_location = await game_state.get_component(target_id, "LocationData")
    if not target_location:
        return f"You cannot find any trace of '{target_name}'."

    # Check if same room
    if target_location.room_id == location.room_id:
        return f"{target_name} is right here!"

    # Calculate direction (simplified - would use pathfinding)
    direction = await game_state.get_direction_to(location.room_id, target_location.room_id)

    if direction:
        # Tracking success based on wisdom
        import random
        if random.randint(1, 20) + (wisdom - 10) // 2 >= 10:
            return f"You sense that {target_name} is somewhere to the {direction}."
        else:
            return "You find some tracks but cannot determine the direction."
    else:
        return f"You cannot find a clear path to {target_name}."


@command(
    name="areas",
    aliases=["zones", "regions"],
    category=CommandCategory.INFO,
    help_text="List available zones and areas.",
)
async def cmd_areas(player_id: str, args: str, game_state) -> str:
    """List all zones."""
    from ..components.world import ZoneStateData

    # Get all registered zones
    zones = await game_state.get_all_zones()

    if not zones:
        return "No areas have been discovered yet."

    lines = [
        "=== Known Areas ===",
        "",
    ]

    # Group by level range
    level_groups: Dict[str, List] = {
        "Beginner (1-10)": [],
        "Intermediate (11-20)": [],
        "Advanced (21-30)": [],
        "Expert (31+)": [],
    }

    for zone_id, zone_info in zones.items():
        min_lvl = zone_info.get("min_level", 1)
        max_lvl = zone_info.get("max_level", 50)
        name = zone_info.get("name", zone_id.replace("_", " ").title())
        players = zone_info.get("player_count", 0)

        entry = f"  {name}"
        if players > 0:
            entry += f" ({players} players)"

        if min_lvl <= 10:
            level_groups["Beginner (1-10)"].append(entry)
        elif min_lvl <= 20:
            level_groups["Intermediate (11-20)"].append(entry)
        elif min_lvl <= 30:
            level_groups["Advanced (21-30)"].append(entry)
        else:
            level_groups["Expert (31+)"].append(entry)

    for group_name, entries in level_groups.items():
        if entries:
            lines.append(group_name + ":")
            lines.extend(entries)
            lines.append("")

    return "\n".join(lines)


@command(
    name="events",
    aliases=["worldevents"],
    category=CommandCategory.INFO,
    help_text="Show active world events.",
)
async def cmd_events(player_id: str, args: str, game_state) -> str:
    """Show active world events."""
    from ..components.world import WorldStateData

    world = await game_state.get_component("world", "WorldStateData")
    if not world or not world.active_events:
        return "There are no special events active at this time."

    lines = [
        "=== Active World Events ===",
        "",
    ]

    for event in world.active_events:
        if not event.is_active:
            continue

        remaining = event.time_remaining
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)

        lines.append(f"** {event.name} **")
        lines.append(f"   {event.description}")
        if hours > 0:
            lines.append(f"   Time remaining: {hours}h {minutes}m")
        else:
            lines.append(f"   Time remaining: {minutes}m")

        if event.multipliers:
            mods = []
            for mult_type, value in event.multipliers.items():
                if value > 1:
                    mods.append(f"{mult_type}: x{value}")
            if mods:
                lines.append(f"   Bonuses: {', '.join(mods)}")

        lines.append("")

    return "\n".join(lines)


@command(
    name="compass",
    aliases=["directions"],
    category=CommandCategory.INFO,
    help_text="Show available exits with a compass display.",
)
async def cmd_compass(player_id: str, args: str, game_state) -> str:
    """Show compass with available exits."""
    from ..components.spatial import LocationData, RoomData

    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    room = await game_state.get_component(location.room_id, "RoomData")
    if not room:
        return "You can't make out your surroundings."

    # Build compass display
    exits = {d.value if hasattr(d, 'value') else d for d in room.exits.keys()}

    n = "N" if "north" in exits else "-"
    s = "S" if "south" in exits else "-"
    e = "E" if "east" in exits else "-"
    w = "W" if "west" in exits else "-"
    u = "U" if "up" in exits else "-"
    d = "D" if "down" in exits else "-"

    compass = f"""
      {n}
    {w}-+-{e}
      {s}
    [{u}/{d}]
    """

    lines = [
        f"=== {room.name} ===",
        compass,
        "Exits: " + ", ".join(sorted(exits)) if exits else "No obvious exits.",
    ]

    return "\n".join(lines)
