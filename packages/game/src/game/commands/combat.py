"""
Combat Commands

Commands for fighting and combat-related actions.
"""

from typing import List, Optional

from core import EntityId
from .registry import command, CommandCategory


@command(
    name="kill",
    aliases=["k", "attack", "hit"],
    category=CommandCategory.COMBAT,
    help_text="Attack a target.",
    usage="kill <target>",
)
async def cmd_kill(player_id: EntityId, args: List[str]) -> str:
    """Initiate combat with a target."""
    if not args:
        return "Kill who?"

    target_keyword = args[0].lower()
    return await _initiate_combat(player_id, target_keyword)


async def _initiate_combat(player_id: EntityId, target_keyword: str) -> str:
    """Find target and start combat."""
    from core.component import get_component_actor

    # Check if already in combat
    combat_actor = get_component_actor("Combat")
    player_combat = await combat_actor.get.remote(player_id)

    if player_combat and player_combat.is_in_combat:
        return "You are already fighting!"

    # Get player location
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    # Check room allows combat
    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(player_location.room_id)

    if room and room.is_safe:
        return "You cannot fight here."

    # Find target in room
    target_id = await _find_target(player_location.room_id, target_keyword, player_id)

    if not target_id:
        return f"You don't see '{target_keyword}' here."

    # Check target can be attacked
    target_combat = await combat_actor.get.remote(target_id)
    if not target_combat:
        return "You can't attack that."

    # Check target is alive
    stats_actor = get_component_actor("Stats")
    target_stats = await stats_actor.get.remote(target_id)
    if not target_stats or not target_stats.is_alive:
        return "It's already dead."

    # Get target name for message
    identity_actor = get_component_actor("Identity")
    target_identity = await identity_actor.get.remote(target_id)
    target_name = target_identity.name if target_identity else "something"

    # Start combat - set targeting
    def set_player_target(c):
        c.set_target(target_id)

    await combat_actor.mutate.remote(player_id, set_player_target)

    def add_player_attacker(c):
        c.add_attacker(player_id)

    await combat_actor.mutate.remote(target_id, add_player_attacker)

    return f"You attack {target_name}!"


async def _find_target(room_id: EntityId, keyword: str, exclude_id: EntityId) -> Optional[EntityId]:
    """Find a target in the room by keyword."""
    from core.component import get_component_actor

    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")

    all_locations = await location_actor.get_all.remote()

    # Parse ordinal (e.g., "2.goblin" for second goblin)
    ordinal = 1
    if "." in keyword:
        parts = keyword.split(".", 1)
        if parts[0].isdigit():
            ordinal = int(parts[0])
            keyword = parts[1]

    matches = 0
    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if entity_id == exclude_id:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        # Check if keyword matches
        if _matches_keyword(identity, keyword):
            matches += 1
            if matches == ordinal:
                return entity_id

    return None


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
    name="flee",
    aliases=["fl"],
    category=CommandCategory.COMBAT,
    help_text="Attempt to flee from combat.",
    usage="flee",
)
async def cmd_flee(player_id: EntityId, args: List[str]) -> str:
    """Attempt to flee from combat."""
    import random
    from core.component import get_component_actor
    from datetime import datetime

    # Check if in combat
    combat_actor = get_component_actor("Combat")
    player_combat = await combat_actor.get.remote(player_id)

    if not player_combat or not player_combat.is_in_combat:
        return "You aren't fighting anyone."

    # Get player stats for flee chance
    stats_actor = get_component_actor("Stats")
    player_stats = await stats_actor.get.remote(player_id)

    # Calculate flee chance
    dex_mod = player_stats.attributes.get_modifier("dexterity") if player_stats else 0
    flee_chance = 50 + (dex_mod * 5)
    flee_chance -= len(player_combat.targeted_by) * 10
    flee_chance = max(10, min(90, flee_chance))

    if random.randint(1, 100) > flee_chance:
        return "PANIC! You couldn't escape!"

    # Get a random exit
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "There's nowhere to flee to!"

    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(player_location.room_id)

    if not room:
        return "There's nowhere to flee to!"

    exits = room.get_available_exits()
    if not exits:
        return "There's nowhere to flee to!"

    flee_direction = random.choice(exits)
    exit_data = room.get_exit(flee_direction)

    if not exit_data or exit_data.is_locked:
        return "PANIC! You couldn't escape!"

    # Exit combat
    target_id = player_combat.target

    def clear_combat(c):
        c.clear_target()

    await combat_actor.mutate.remote(player_id, clear_combat)

    # Remove from target's attacker list
    if target_id:

        def remove_attacker(c):
            c.remove_attacker(player_id)

        await combat_actor.mutate.remote(target_id, remove_attacker)

    # Move to new room
    destination_id = exit_data.destination_id

    def update_location(loc):
        loc.last_room_id = loc.room_id
        loc.room_id = destination_id
        loc.entered_at = datetime.utcnow()

    await location_actor.mutate.remote(player_id, update_location)

    return f"You flee {flee_direction}!"


@command(
    name="consider",
    aliases=["con"],
    category=CommandCategory.COMBAT,
    help_text="Consider how tough a target is.",
    usage="consider <target>",
)
async def cmd_consider(player_id: EntityId, args: List[str]) -> str:
    """Consider a target's difficulty."""
    if not args:
        return "Consider who?"

    target_keyword = args[0].lower()

    from core.component import get_component_actor

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    target_id = await _find_target(player_location.room_id, target_keyword, player_id)

    if not target_id:
        return f"You don't see '{target_keyword}' here."

    # Get player and target stats
    stats_actor = get_component_actor("Stats")
    player_stats = await stats_actor.get.remote(player_id)
    target_stats = await stats_actor.get.remote(target_id)

    if not target_stats:
        return "You can't tell anything about it."

    identity_actor = get_component_actor("Identity")
    target_identity = await identity_actor.get.remote(target_id)
    target_name = target_identity.name if target_identity else "It"

    # Compare levels/power
    player_level = getattr(player_stats, "level", 1)
    target_level = getattr(target_stats, "challenge_rating", 1)

    diff = target_level - player_level

    if diff <= -10:
        assessment = f"{target_name} is barely worth your time."
    elif diff <= -5:
        assessment = f"{target_name} looks like an easy fight."
    elif diff <= -2:
        assessment = f"{target_name} appears weaker than you."
    elif diff <= 2:
        assessment = f"{target_name} looks to be a fair fight."
    elif diff <= 5:
        assessment = f"{target_name} appears stronger than you."
    elif diff <= 10:
        assessment = f"{target_name} looks like a difficult fight."
    else:
        assessment = f"{target_name} would crush you like a bug!"

    return assessment


@command(
    name="wimpy",
    category=CommandCategory.COMBAT,
    help_text="Set your auto-flee threshold.",
    usage="wimpy [percentage]",
)
async def cmd_wimpy(player_id: EntityId, args: List[str]) -> str:
    """Set auto-flee threshold."""
    # This would set a threshold for automatic fleeing
    # when health drops below a certain percentage
    if not args:
        return "Your wimpy threshold is set to 20% health."

    try:
        threshold = int(args[0])
        if threshold < 0 or threshold > 100:
            return "Wimpy must be between 0 and 100."
        return f"Wimpy threshold set to {threshold}% health."
    except ValueError:
        return "Wimpy must be a number between 0 and 100."
