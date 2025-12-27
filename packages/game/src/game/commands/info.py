"""
Information Commands

Commands for viewing information about yourself and the world.
"""

from typing import List

from core import EntityId
from .registry import command, CommandCategory
from ..components.position import Position


@command(
    name="look",
    aliases=["l"],
    category=CommandCategory.INFORMATION,
    help_text="Look around or at something specific.",
    usage="look [target]",
    min_position=Position.RESTING,
)
async def cmd_look(player_id: EntityId, args: List[str]) -> str:
    """Look at the current room or a specific target."""
    from core.component import get_component_actor

    if args:
        # Look at specific target
        return await _look_at_target(player_id, args[0])

    # Look at room
    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(location.room_id)

    if not room:
        return "You are in a featureless void."

    identity_actor = get_component_actor("Identity")
    room_identity = await identity_actor.get.remote(location.room_id)
    room_name = room_identity.name if room_identity else "A Room"

    # Get entities in room
    all_locations = await location_actor.get_all.remote()
    entities_here = []
    items_here = []

    for entity_id, loc in all_locations.items():
        if loc.room_id == location.room_id and entity_id != player_id:
            entity_identity = await identity_actor.get.remote(entity_id)
            if entity_identity:
                if entity_id.entity_type == "item":
                    items_here.append(entity_identity.short_description)
                else:
                    entities_here.append(entity_identity.short_description)

    # Build output
    lines = [
        room_name,
        "",
        room.long_description,
    ]

    if items_here:
        lines.append("")
        for desc in items_here:
            lines.append(f"  {desc}")

    if entities_here:
        lines.append("")
        for desc in entities_here:
            lines.append(desc)

    exits = room.get_available_exits()
    exits_str = ", ".join(exits) if exits else "none"
    lines.append("")
    lines.append(f"[Exits: {exits_str}]")

    return "\n".join(lines)


async def _look_at_target(player_id: EntityId, target_keyword: str) -> str:
    """Look at a specific target."""
    from core.component import get_component_actor

    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    identity_actor = get_component_actor("Identity")
    all_locations = await location_actor.get_all.remote()

    # Find target in room
    for entity_id, loc in all_locations.items():
        if loc.room_id != location.room_id:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        if _matches_keyword(identity, target_keyword):
            return identity.long_description or identity.short_description

    return f"You don't see '{target_keyword}' here."


def _matches_keyword(identity, keyword: str) -> bool:
    """Check if identity matches keyword."""
    keyword = keyword.lower()
    if keyword in identity.name.lower():
        return True
    for kw in identity.keywords:
        if keyword in kw.lower():
            return True
    return False


@command(
    name="score",
    aliases=["sc", "stats"],
    category=CommandCategory.INFORMATION,
    help_text="View your character's score and statistics.",
    usage="score",
    min_position=Position.DEAD,
)
async def cmd_score(player_id: EntityId, args: List[str]) -> str:
    """View character score and stats."""
    from core.component import get_component_actor

    stats_actor = get_component_actor("Stats")
    stats = await stats_actor.get.remote(player_id)

    if not stats:
        return "You have no stats."

    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    name = identity.name if identity else "Unknown"

    # Build score display
    lines = [
        f"Score for {name}",
        "-" * 40,
        "",
        f"Level: {getattr(stats, 'level', 1)}",
        f"Class: {getattr(stats, 'class_name', 'Unknown')}",
        f"Race: {getattr(stats, 'race_name', 'Unknown')}",
        "",
        f"Health: {stats.current_health}/{stats.max_health}",
        f"Mana:   {stats.current_mana}/{stats.max_mana}",
        f"Stamina: {stats.current_stamina}/{stats.max_stamina}",
        "",
        "Attributes:",
        f"  Strength:     {stats.attributes.strength}",
        f"  Dexterity:    {stats.attributes.dexterity}",
        f"  Constitution: {stats.attributes.constitution}",
        f"  Intelligence: {stats.attributes.intelligence}",
        f"  Wisdom:       {stats.attributes.wisdom}",
        f"  Charisma:     {stats.attributes.charisma}",
        "",
        f"Armor Class: {stats.armor_class}",
    ]

    # Add experience if player
    if hasattr(stats, "experience"):
        lines.append("")
        lines.append(f"Experience: {stats.experience}/{stats.experience_to_level}")
        lines.append(f"Gold: {getattr(stats, 'gold', 0)}")

    return "\n".join(lines)


@command(
    name="inventory",
    aliases=["i", "inv"],
    category=CommandCategory.INFORMATION,
    help_text="View your inventory.",
    usage="inventory",
    min_position=Position.RESTING,
)
async def cmd_inventory(player_id: EntityId, args: List[str]) -> str:
    """View inventory contents."""
    from core.component import get_component_actor

    container_actor = get_component_actor("Container")
    container = await container_actor.get.remote(player_id)

    if not container:
        return "You aren't carrying anything."

    if not container.contents:
        return "You aren't carrying anything."

    identity_actor = get_component_actor("Identity")
    lines = ["You are carrying:"]

    for item_id in container.contents:
        identity = await identity_actor.get.remote(item_id)
        if identity:
            lines.append(f"  {identity.name}")

    lines.append(f"\nWeight: {container.current_weight:.1f}/{container.max_weight:.1f}")

    return "\n".join(lines)


@command(
    name="equipment",
    aliases=["eq", "worn"],
    category=CommandCategory.INFORMATION,
    help_text="View your equipped items.",
    usage="equipment",
    min_position=Position.RESTING,
)
async def cmd_equipment(player_id: EntityId, args: List[str]) -> str:
    """View equipped items."""
    from core.component import get_component_actor

    equipment_actor = get_component_actor("Equipment")
    equipment = await equipment_actor.get.remote(player_id)

    if not equipment:
        return "You aren't wearing anything."

    identity_actor = get_component_actor("Identity")

    lines = ["You are wearing:"]

    slot_names = {
        "head": "Head",
        "neck": "Neck",
        "torso": "Torso",
        "body": "Body",
        "arms": "Arms",
        "hands": "Hands",
        "waist": "Waist",
        "legs": "Legs",
        "feet": "Feet",
        "finger1": "Ring",
        "finger2": "Ring",
        "wrist1": "Wrist",
        "wrist2": "Wrist",
        "main_hand": "Main Hand",
        "off_hand": "Off Hand",
        "held": "Held",
    }

    equipped_something = False
    for slot, display_name in slot_names.items():
        item_id = getattr(equipment, slot, None)
        if item_id:
            identity = await identity_actor.get.remote(item_id)
            item_name = identity.name if identity else "something"
            lines.append(f"  <{display_name}> {item_name}")
            equipped_something = True

    if not equipped_something:
        return "You aren't wearing anything."

    return "\n".join(lines)


@command(
    name="who",
    category=CommandCategory.INFORMATION,
    help_text="See who is currently playing.",
    usage="who",
    min_position=Position.DEAD,
)
async def cmd_who(player_id: EntityId, args: List[str]) -> str:
    """List online players."""
    from core.component import get_component_actor

    # Get all player entities with Connection component
    connection_actor = get_component_actor("Connection")
    stats_actor = get_component_actor("Stats")
    identity_actor = get_component_actor("Identity")

    all_connections = await connection_actor.get_all.remote()

    lines = [
        "Players currently online:",
        "-" * 40,
    ]

    count = 0
    for entity_id, connection in all_connections.items():
        if not connection.is_connected:
            continue

        identity = await identity_actor.get.remote(entity_id)
        stats = await stats_actor.get.remote(entity_id)

        name = identity.name if identity else "Unknown"
        level = getattr(stats, "level", 1) if stats else 1
        class_name = getattr(stats, "class_name", "adventurer") if stats else "adventurer"

        lines.append(f"  [{level:2d} {class_name:12s}] {name}")
        count += 1

    lines.append("")
    lines.append(f"{count} player(s) online.")

    return "\n".join(lines)


@command(
    name="help",
    aliases=["?"],
    category=CommandCategory.INFORMATION,
    help_text="Get help on commands.",
    usage="help [topic]",
    min_position=Position.DEAD,
)
async def cmd_help(player_id: EntityId, args: List[str]) -> str:
    """Display help information."""
    from .registry import get_command_registry, CommandCategory

    registry = get_command_registry()

    if not args:
        # List all commands by category
        lines = [
            "Available commands:",
            "-" * 40,
        ]

        for category in CommandCategory:
            commands = registry.get_by_category(category)
            if commands:
                cmd_names = [c.name for c in commands]
                lines.append(f"  {category.value}: {', '.join(cmd_names)}")

        lines.append("")
        lines.append("Type 'help <command>' for details on a specific command.")
        return "\n".join(lines)

    # Look up specific command
    topic = args[0].lower()
    cmd_def = registry.get(topic)

    if cmd_def:
        lines = [
            f"Command: {cmd_def.name}",
            f"Usage: {cmd_def.usage}",
            "",
            cmd_def.help_text or "No help available.",
        ]
        if cmd_def.aliases:
            lines.append("")
            lines.append(f"Aliases: {', '.join(cmd_def.aliases)}")
        return "\n".join(lines)

    return f"No help available for: {topic}"


@command(
    name="time",
    category=CommandCategory.INFORMATION,
    help_text="Show the current game time.",
    usage="time",
    min_position=Position.DEAD,
)
async def cmd_time(player_id: EntityId, args: List[str]) -> str:
    """Show current game time."""
    from datetime import datetime

    now = datetime.utcnow()
    return f"The current time is {now.strftime('%H:%M:%S')} (server time)."


@command(
    name="quit",
    aliases=["exit"],
    category=CommandCategory.INFORMATION,
    help_text="Save and quit the game.",
    usage="quit",
    min_position=Position.DEAD,
    in_combat=False,
)
async def cmd_quit(player_id: EntityId, args: List[str]) -> str:
    """Quit the game."""
    # Save before quitting
    from ..persistence import save_player

    await save_player(player_id)

    # The actual quit is handled by the Gateway
    return "Goodbye! Your character has been saved."


@command(
    name="save",
    category=CommandCategory.INFORMATION,
    help_text="Save your character.",
    usage="save",
    min_position=Position.DEAD,
)
async def cmd_save(player_id: EntityId, args: List[str]) -> str:
    """Save your character."""
    from ..persistence import save_player, get_autosave_manager, autosave_manager_exists

    if await save_player(player_id):
        # Record save time with manager if available
        if autosave_manager_exists():
            manager = get_autosave_manager()
            last_save = await manager.get_last_save.remote(player_id)
            if last_save:
                return f"Your character has been saved. (Last auto-save: {last_save})"
        return "Your character has been saved."
    else:
        return "Failed to save character. Please try again."
