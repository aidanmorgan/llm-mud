"""
Item Manipulation Commands

Commands for picking up, dropping, and managing items.
"""

from typing import List, Optional, Tuple

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.position import Position


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_ordinal(keyword: str) -> Tuple[int, str]:
    """
    Parse ordinal prefix from keyword.

    Examples:
        "sword" -> (1, "sword")
        "2.sword" -> (2, "sword")
        "3.red" -> (3, "red")

    Returns:
        Tuple of (ordinal, keyword)
    """
    if "." in keyword:
        parts = keyword.split(".", 1)
        if parts[0].isdigit():
            return (int(parts[0]), parts[1])
    return (1, keyword)


def _matches_keyword(identity, keyword: str) -> bool:
    """Check if identity matches keyword."""
    keyword = keyword.lower()
    if keyword in identity.name.lower():
        return True
    for kw in identity.keywords:
        if keyword in kw.lower():
            return True
    return False


async def _find_item_in_room(
    room_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> Optional[EntityId]:
    """
    Find an item in the room by keyword.

    Args:
        room_id: The room to search in
        keyword: Item keyword to match
        ordinal: Which match to return (1 = first, 2 = second, etc.)

    Returns:
        EntityId of matching item or None
    """
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")
    item_actor = get_component_actor("Item")

    all_locations = await location_actor.get_all.remote()

    matches = 0
    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue

        # Check if this entity is an item
        item_data = await item_actor.get.remote(entity_id)
        if not item_data:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        if _matches_keyword(identity, keyword):
            matches += 1
            if matches == ordinal:
                return entity_id

    return None


async def _find_item_in_inventory(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> Optional[EntityId]:
    """
    Find an item in the player's inventory by keyword.

    Args:
        player_id: The player whose inventory to search
        keyword: Item keyword to match
        ordinal: Which match to return (1 = first, 2 = second, etc.)

    Returns:
        EntityId of matching item or None
    """
    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")

    container = await container_actor.get.remote(player_id)
    if not container or not container.contents:
        return None

    matches = 0
    for item_id in container.contents:
        identity = await identity_actor.get.remote(item_id)
        if not identity:
            continue

        if _matches_keyword(identity, keyword):
            matches += 1
            if matches == ordinal:
                return item_id

    return None


async def _find_player_in_room(
    room_id: EntityId,
    keyword: str,
    exclude_id: EntityId,
) -> Optional[EntityId]:
    """Find a player in the room by keyword."""
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")
    player_actor = get_component_actor("Player")

    all_locations = await location_actor.get_all.remote()

    ordinal, keyword = _parse_ordinal(keyword)
    matches = 0

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if entity_id == exclude_id:
            continue

        # Check if this entity is a player
        player_data = await player_actor.get.remote(entity_id)
        if not player_data:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        if _matches_keyword(identity, keyword):
            matches += 1
            if matches == ordinal:
                return entity_id

    return None


async def _get_all_items_in_room(room_id: EntityId) -> List[EntityId]:
    """Get all item entities in a room."""
    location_actor = get_component_actor("Location")
    item_actor = get_component_actor("Item")

    all_locations = await location_actor.get_all.remote()
    items = []

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue

        item_data = await item_actor.get.remote(entity_id)
        if item_data:
            items.append(entity_id)

    return items


async def _send_to_room(room_id: EntityId, message: str, exclude_id: EntityId = None) -> None:
    """Send a message to all players in a room."""
    try:
        import ray
        from network.protocol import create_text

        gateway = ray.get_actor("gateway", namespace="llmmud")
        location_actor = get_component_actor("Location")
        player_actor = get_component_actor("Player")

        all_locations = await location_actor.get_all.remote()

        for entity_id, location in all_locations.items():
            if location.room_id != room_id:
                continue
            if entity_id == exclude_id:
                continue

            # Check if this is a player
            player = await player_actor.get.remote(entity_id)
            if player:
                await gateway.send_to_player.remote(entity_id, create_text(message))
    except Exception:
        pass


# =============================================================================
# Get Command
# =============================================================================


@command(
    name="get",
    aliases=["take", "pick"],
    category=CommandCategory.OBJECT,
    help_text="Pick up an item from the room or from a container.",
    usage="get <item> [from <container>] | get all",
    min_position=Position.RESTING,
)
async def cmd_get(player_id: EntityId, args: List[str]) -> str:
    """Pick up items from the room or a container."""
    if not args:
        return "Get what?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    room_id = player_location.room_id

    # Handle "get all"
    if args[0].lower() == "all":
        return await _get_all(player_id, room_id)

    # Handle "get <item> from <container>"
    if len(args) >= 3 and args[1].lower() in ("from", "in"):
        return await _get_from_container(player_id, args[0], args[2])

    # Standard "get <item>"
    ordinal, keyword = _parse_ordinal(args[0])
    return await _get_item(player_id, room_id, keyword, ordinal)


async def _get_item(
    player_id: EntityId,
    room_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> str:
    """Pick up a single item from the room."""
    item_id = await _find_item_in_room(room_id, keyword, ordinal)

    if not item_id:
        return f"You don't see '{keyword}' here."

    # Get item details
    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    if not item_data:
        return "You can't pick that up."

    # Check if bound
    if item_data.is_bound:
        return "You can't pick up that item."

    # Check player's inventory capacity
    container_actor = get_component_actor("Container")
    player_container = await container_actor.get.remote(player_id)

    if not player_container:
        return "You can't carry anything."

    if not player_container.can_add_item(item_data.weight):
        if player_container.is_full:
            return "You can't carry any more items."
        else:
            return "That's too heavy for you to carry."

    # Get item name for message
    identity_actor = get_component_actor("Identity")
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Move item from room to inventory
    location_actor = get_component_actor("Location")

    # Remove item's location (it's now in inventory, not a room)
    def clear_location(loc):
        loc.room_id = None

    await location_actor.mutate.remote(item_id, clear_location)

    # Add to player's container
    def add_to_inventory(container):
        container.add_item(item_id, item_data.weight)

    await container_actor.mutate.remote(player_id, add_to_inventory)

    # Notify room
    player_identity = await identity_actor.get.remote(player_id)
    player_name = player_identity.name if player_identity else "Someone"
    await _send_to_room(room_id, f"{player_name} picks up {item_name}.", player_id)

    return f"You pick up {item_name}."


async def _get_all(player_id: EntityId, room_id: EntityId) -> str:
    """Pick up all items from the room."""
    items = await _get_all_items_in_room(room_id)

    if not items:
        return "There is nothing here to pick up."

    container_actor = get_component_actor("Container")
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")
    location_actor = get_component_actor("Location")

    player_container = await container_actor.get.remote(player_id)
    if not player_container:
        return "You can't carry anything."

    picked_up = []
    skipped = []

    for item_id in items:
        item_data = await item_actor.get.remote(item_id)
        if not item_data:
            continue

        item_identity = await identity_actor.get.remote(item_id)
        item_name = item_identity.name if item_identity else "something"

        # Check if bound
        if item_data.is_bound:
            skipped.append(item_name)
            continue

        # Check capacity
        if not player_container.can_add_item(item_data.weight):
            skipped.append(item_name)
            continue

        # Move item
        def clear_location(loc):
            loc.room_id = None

        await location_actor.mutate.remote(item_id, clear_location)

        def add_to_inventory(container):
            container.add_item(item_id, item_data.weight)

        await container_actor.mutate.remote(player_id, add_to_inventory)

        # Update local container state for capacity checks
        player_container.add_item(item_id, item_data.weight)

        picked_up.append(item_name)

    if not picked_up:
        if skipped:
            return "You couldn't pick up any of the items."
        return "There is nothing here to pick up."

    result = f"You pick up: {', '.join(picked_up)}"
    if skipped:
        result += f"\nYou couldn't pick up: {', '.join(skipped)}"

    return result


async def _get_from_container(
    player_id: EntityId,
    item_keyword: str,
    container_keyword: str,
) -> str:
    """Get an item from a container."""
    # Find container in inventory or room
    ordinal, container_kw = _parse_ordinal(container_keyword)

    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")
    item_actor = get_component_actor("Item")
    location_actor = get_component_actor("Location")

    player_location = await location_actor.get.remote(player_id)
    room_id = player_location.room_id if player_location else None

    # Try inventory first
    container_id = await _find_item_in_inventory(player_id, container_kw, ordinal)

    # Try room if not in inventory
    if not container_id and room_id:
        container_id = await _find_item_in_room(room_id, container_kw, ordinal)

    if not container_id:
        return f"You don't see '{container_keyword}' here."

    # Check if it's actually a container
    container_data = await container_actor.get.remote(container_id)
    if not container_data:
        container_identity = await identity_actor.get.remote(container_id)
        name = container_identity.name if container_identity else "That"
        return f"{name} is not a container."

    # Check if closed/locked
    if container_data.is_closed:
        return "It's closed."
    if container_data.is_locked:
        return "It's locked."

    if not container_data.contents:
        return "It's empty."

    # Find item in container
    ordinal, item_kw = _parse_ordinal(item_keyword)
    matches = 0
    target_item = None

    for item_id in container_data.contents:
        identity = await identity_actor.get.remote(item_id)
        if identity and _matches_keyword(identity, item_kw):
            matches += 1
            if matches == ordinal:
                target_item = item_id
                break

    if not target_item:
        return f"You don't see '{item_keyword}' in there."

    # Get item details
    item_data = await item_actor.get.remote(target_item)
    item_identity = await identity_actor.get.remote(target_item)
    item_name = item_identity.name if item_identity else "something"

    # Check player's inventory capacity
    player_container = await container_actor.get.remote(player_id)
    if not player_container:
        return "You can't carry anything."

    weight = item_data.weight if item_data else 0
    if not player_container.can_add_item(weight):
        return "You can't carry any more."

    # Move item from container to inventory
    def remove_from_container(c):
        c.remove_item(target_item, weight)

    await container_actor.mutate.remote(container_id, remove_from_container)

    def add_to_inventory(c):
        c.add_item(target_item, weight)

    await container_actor.mutate.remote(player_id, add_to_inventory)

    container_identity = await identity_actor.get.remote(container_id)
    container_name = container_identity.name if container_identity else "it"

    return f"You get {item_name} from {container_name}."


# =============================================================================
# Drop Command
# =============================================================================


@command(
    name="drop",
    category=CommandCategory.OBJECT,
    help_text="Drop an item from your inventory.",
    usage="drop <item> | drop all",
    min_position=Position.RESTING,
)
async def cmd_drop(player_id: EntityId, args: List[str]) -> str:
    """Drop items from inventory to the room."""
    if not args:
        return "Drop what?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    room_id = player_location.room_id

    # Handle "drop all"
    if args[0].lower() == "all":
        return await _drop_all(player_id, room_id)

    # Standard "drop <item>"
    ordinal, keyword = _parse_ordinal(args[0])
    return await _drop_item(player_id, room_id, keyword, ordinal)


async def _drop_item(
    player_id: EntityId,
    room_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> str:
    """Drop a single item from inventory."""
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    # Check if bound
    if item_data and item_data.is_bound:
        return "You can't drop that item."

    # Check if quest item
    if item_data and item_data.is_quest_item:
        return "You can't drop quest items."

    # Get item name
    identity_actor = get_component_actor("Identity")
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Remove from inventory
    container_actor = get_component_actor("Container")
    weight = item_data.weight if item_data else 0

    def remove_from_inventory(container):
        container.remove_item(item_id, weight)

    await container_actor.mutate.remote(player_id, remove_from_inventory)

    # Set item's location to the room
    location_actor = get_component_actor("Location")

    def set_location(loc):
        loc.room_id = room_id

    await location_actor.mutate.remote(item_id, set_location)

    # Notify room
    player_identity = await identity_actor.get.remote(player_id)
    player_name = player_identity.name if player_identity else "Someone"
    await _send_to_room(room_id, f"{player_name} drops {item_name}.", player_id)

    return f"You drop {item_name}."


async def _drop_all(player_id: EntityId, room_id: EntityId) -> str:
    """Drop all items from inventory."""
    container_actor = get_component_actor("Container")
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")
    location_actor = get_component_actor("Location")

    player_container = await container_actor.get.remote(player_id)
    if not player_container or not player_container.contents:
        return "You aren't carrying anything."

    dropped = []
    skipped = []

    # Copy the list since we'll be modifying it
    items_to_drop = list(player_container.contents)

    for item_id in items_to_drop:
        item_data = await item_actor.get.remote(item_id)
        item_identity = await identity_actor.get.remote(item_id)
        item_name = item_identity.name if item_identity else "something"

        # Check if bound or quest item
        if item_data and (item_data.is_bound or item_data.is_quest_item):
            skipped.append(item_name)
            continue

        # Remove from inventory
        weight = item_data.weight if item_data else 0

        def remove_from_inventory(container):
            container.remove_item(item_id, weight)

        await container_actor.mutate.remote(player_id, remove_from_inventory)

        # Set item's location to the room
        def set_location(loc):
            loc.room_id = room_id

        await location_actor.mutate.remote(item_id, set_location)

        dropped.append(item_name)

    if not dropped:
        if skipped:
            return "You can't drop any of your items."
        return "You aren't carrying anything."

    result = f"You drop: {', '.join(dropped)}"
    if skipped:
        result += f"\nYou couldn't drop: {', '.join(skipped)}"

    return result


# =============================================================================
# Put Command
# =============================================================================


@command(
    name="put",
    category=CommandCategory.OBJECT,
    help_text="Put an item into a container.",
    usage="put <item> in <container>",
    min_position=Position.RESTING,
)
async def cmd_put(player_id: EntityId, args: List[str]) -> str:
    """Put an item into a container."""
    if len(args) < 3:
        return "Put what in what? (put <item> in <container>)"

    # Parse "put <item> in <container>"
    try:
        in_index = next(i for i, a in enumerate(args) if a.lower() in ("in", "into"))
    except StopIteration:
        return "Put what in what? (put <item> in <container>)"

    item_keyword = " ".join(args[:in_index])
    container_keyword = " ".join(args[in_index + 1:])

    if not item_keyword or not container_keyword:
        return "Put what in what? (put <item> in <container>)"

    ordinal, item_kw = _parse_ordinal(item_keyword)
    container_ordinal, container_kw = _parse_ordinal(container_keyword)

    # Find item in inventory
    item_id = await _find_item_in_inventory(player_id, item_kw, ordinal)
    if not item_id:
        return f"You don't have '{item_keyword}'."

    # Find container in inventory or room
    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")
    item_actor = get_component_actor("Item")
    location_actor = get_component_actor("Location")

    player_location = await location_actor.get.remote(player_id)
    room_id = player_location.room_id if player_location else None

    # Try inventory first
    container_id = await _find_item_in_inventory(player_id, container_kw, container_ordinal)

    # Try room if not in inventory
    if not container_id and room_id:
        container_id = await _find_item_in_room(room_id, container_kw, container_ordinal)

    if not container_id:
        return f"You don't see '{container_keyword}' here."

    if container_id == item_id:
        return "You can't put something inside itself."

    # Check if it's actually a container
    container_data = await container_actor.get.remote(container_id)
    if not container_data:
        container_identity = await identity_actor.get.remote(container_id)
        name = container_identity.name if container_identity else "That"
        return f"{name} is not a container."

    # Check if closed/locked
    if container_data.is_closed:
        return "It's closed."
    if container_data.is_locked:
        return "It's locked."

    # Get item details
    item_data = await item_actor.get.remote(item_id)
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Check container capacity
    weight = item_data.weight if item_data else 0
    if not container_data.can_add_item(weight):
        return "It won't fit."

    # Remove from inventory
    def remove_from_inventory(c):
        c.remove_item(item_id, weight)

    await container_actor.mutate.remote(player_id, remove_from_inventory)

    # Add to container
    def add_to_container(c):
        c.add_item(item_id, weight)

    await container_actor.mutate.remote(container_id, add_to_container)

    container_identity = await identity_actor.get.remote(container_id)
    container_name = container_identity.name if container_identity else "it"

    return f"You put {item_name} in {container_name}."


# =============================================================================
# Give Command
# =============================================================================


@command(
    name="give",
    category=CommandCategory.OBJECT,
    help_text="Give an item to another player.",
    usage="give <item> to <player>",
    min_position=Position.RESTING,
)
async def cmd_give(player_id: EntityId, args: List[str]) -> str:
    """Give an item to another player."""
    if len(args) < 3:
        return "Give what to whom? (give <item> to <player>)"

    # Parse "give <item> to <player>"
    try:
        to_index = next(i for i, a in enumerate(args) if a.lower() == "to")
    except StopIteration:
        return "Give what to whom? (give <item> to <player>)"

    item_keyword = " ".join(args[:to_index])
    target_keyword = " ".join(args[to_index + 1:])

    if not item_keyword or not target_keyword:
        return "Give what to whom? (give <item> to <player>)"

    ordinal, item_kw = _parse_ordinal(item_keyword)

    # Find item in inventory
    item_id = await _find_item_in_inventory(player_id, item_kw, ordinal)
    if not item_id:
        return f"You don't have '{item_keyword}'."

    # Get item details
    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    # Check if bound
    if item_data and item_data.is_bound:
        return "You can't give that item away."

    # Find target player in room
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    target_id = await _find_player_in_room(
        player_location.room_id,
        target_keyword,
        player_id,
    )

    if not target_id:
        return f"You don't see '{target_keyword}' here."

    # Check target's inventory capacity
    container_actor = get_component_actor("Container")
    target_container = await container_actor.get.remote(target_id)

    if not target_container:
        return "They can't carry anything."

    weight = item_data.weight if item_data else 0
    if not target_container.can_add_item(weight):
        return "They can't carry any more."

    # Get names for messages
    identity_actor = get_component_actor("Identity")
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    target_identity = await identity_actor.get.remote(target_id)
    target_name = target_identity.name if target_identity else "someone"

    player_identity = await identity_actor.get.remote(player_id)
    player_name = player_identity.name if player_identity else "Someone"

    # Remove from giver's inventory
    def remove_from_giver(c):
        c.remove_item(item_id, weight)

    await container_actor.mutate.remote(player_id, remove_from_giver)

    # Add to receiver's inventory
    def add_to_receiver(c):
        c.add_item(item_id, weight)

    await container_actor.mutate.remote(target_id, add_to_receiver)

    # Notify target
    try:
        import ray
        from network.protocol import create_text

        gateway = ray.get_actor("gateway", namespace="llmmud")
        await gateway.send_to_player.remote(
            target_id,
            create_text(f"{player_name} gives you {item_name}."),
        )
    except Exception:
        pass

    # Notify room
    await _send_to_room(
        player_location.room_id,
        f"{player_name} gives {item_name} to {target_name}.",
        player_id,
    )

    return f"You give {item_name} to {target_name}."


# =============================================================================
# Examine Command
# =============================================================================


@command(
    name="examine",
    aliases=["exa", "ex"],
    category=CommandCategory.OBJECT,
    help_text="Examine an item closely.",
    usage="examine <item>",
    min_position=Position.RESTING,
)
async def cmd_examine(player_id: EntityId, args: List[str]) -> str:
    """Examine an item for details."""
    if not args:
        return "Examine what?"

    ordinal, keyword = _parse_ordinal(args[0])

    # Try inventory first
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    # Try room if not in inventory
    if not item_id:
        location_actor = get_component_actor("Location")
        player_location = await location_actor.get.remote(player_id)

        if player_location and player_location.room_id:
            item_id = await _find_item_in_room(
                player_location.room_id,
                keyword,
                ordinal,
            )

    if not item_id:
        return f"You don't see '{keyword}' here."

    # Get item details
    identity_actor = get_component_actor("Identity")
    item_actor = get_component_actor("Item")
    weapon_actor = get_component_actor("Weapon")
    armor_actor = get_component_actor("Armor")

    identity = await identity_actor.get.remote(item_id)
    item_data = await item_actor.get.remote(item_id)
    weapon_data = await weapon_actor.get.remote(item_id)
    armor_data = await armor_actor.get.remote(item_id)

    if not identity:
        return "You can't examine that."

    lines = []

    # Name and description
    lines.append(identity.name)
    lines.append("-" * len(identity.name))

    if identity.long_description:
        lines.append(identity.long_description)
    elif identity.short_description:
        lines.append(identity.short_description)
    else:
        lines.append("You see nothing special about it.")

    if item_data:
        lines.append("")

        # Item type and rarity
        lines.append(f"Type: {item_data.item_type.value.title()}")
        lines.append(f"Rarity: {item_data.rarity.value.title()}")

        # Weight and value
        lines.append(f"Weight: {item_data.weight:.1f} lbs")
        lines.append(f"Value: {item_data.value} gold")

        # Level requirement
        if item_data.level_requirement > 0:
            lines.append(f"Level Required: {item_data.level_requirement}")

        # Durability
        if item_data.max_durability > 0:
            condition = (item_data.current_durability / item_data.max_durability) * 100
            if condition <= 25:
                cond_str = "badly damaged"
            elif condition <= 50:
                cond_str = "worn"
            elif condition <= 75:
                cond_str = "good"
            else:
                cond_str = "excellent"
            lines.append(f"Condition: {cond_str}")

        # Flags
        flags = []
        if item_data.is_cursed:
            flags.append("cursed")
        if item_data.is_bound:
            flags.append("bound")
        if item_data.is_quest_item:
            flags.append("quest item")
        if flags:
            lines.append(f"Flags: {', '.join(flags)}")

    # Weapon stats
    if weapon_data:
        lines.append("")
        lines.append("=== Weapon Stats ===")
        lines.append(f"Damage: {weapon_data.damage_dice} {weapon_data.damage_type}")
        lines.append(f"Type: {weapon_data.weapon_type.title()}")
        if weapon_data.hit_bonus:
            lines.append(f"Hit Bonus: +{weapon_data.hit_bonus}")
        if weapon_data.damage_bonus:
            lines.append(f"Damage Bonus: +{weapon_data.damage_bonus}")
        if weapon_data.two_handed:
            lines.append("(Two-Handed)")
        if weapon_data.special_effects:
            lines.append(f"Effects: {', '.join(weapon_data.special_effects)}")

    # Armor stats
    if armor_data:
        lines.append("")
        lines.append("=== Armor Stats ===")
        lines.append(f"Armor: +{armor_data.armor_bonus}")
        lines.append(f"Type: {armor_data.armor_type.title()}")
        lines.append(f"Slot: {armor_data.slot.value.replace('_', ' ').title()}")
        if armor_data.resistances:
            res_strs = [f"{k}: {v}%" for k, v in armor_data.resistances.items()]
            lines.append(f"Resistances: {', '.join(res_strs)}")
        if armor_data.speed_penalty:
            lines.append(f"Speed Penalty: -{armor_data.speed_penalty}%")
        if armor_data.spell_failure:
            lines.append(f"Spell Failure: {armor_data.spell_failure}%")

    return "\n".join(lines)


# =============================================================================
# Equipment Commands
# =============================================================================


async def _get_slot_for_armor(armor_data) -> Optional[str]:
    """Get the equipment slot for an armor piece."""
    if armor_data and hasattr(armor_data, "slot"):
        return armor_data.slot.value
    return None


async def _equip_item(
    player_id: EntityId,
    item_id: EntityId,
    slot: str,
) -> Tuple[bool, str, Optional[EntityId]]:
    """
    Equip an item in a slot.

    Returns:
        Tuple of (success, message, previous_item_id)
    """
    equipment_actor = get_component_actor("Equipment")
    identity_actor = get_component_actor("Identity")

    equipment = await equipment_actor.get.remote(player_id)
    if not equipment:
        return (False, "You can't wear equipment.", None)

    # Get item name for messages
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Check what's currently in that slot
    previous_item = equipment.slots.get(slot)

    # Equip the item
    def do_equip(eq):
        eq.slots[slot] = item_id

    await equipment_actor.mutate.remote(player_id, do_equip)

    return (True, item_name, previous_item)


async def _unequip_item(
    player_id: EntityId,
    slot: str,
) -> Tuple[bool, str, Optional[EntityId]]:
    """
    Unequip an item from a slot.

    Returns:
        Tuple of (success, message, item_id)
    """
    equipment_actor = get_component_actor("Equipment")
    identity_actor = get_component_actor("Identity")

    equipment = await equipment_actor.get.remote(player_id)
    if not equipment:
        return (False, "You have no equipment.", None)

    item_id = equipment.slots.get(slot)
    if not item_id:
        return (False, None, None)

    # Get item name for messages
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Unequip the item
    def do_unequip(eq):
        eq.slots[slot] = None

    await equipment_actor.mutate.remote(player_id, do_unequip)

    return (True, item_name, item_id)


@command(
    name="wear",
    aliases=["equip", "don"],
    category=CommandCategory.OBJECT,
    help_text="Wear an item from your inventory.",
    usage="wear <item> | wear all",
    min_position=Position.RESTING,
)
async def cmd_wear(player_id: EntityId, args: List[str]) -> str:
    """Wear armor or equipment from inventory."""
    if not args:
        return "Wear what?"

    # Handle "wear all"
    if args[0].lower() == "all":
        return await _wear_all(player_id)

    ordinal, keyword = _parse_ordinal(args[0])
    return await _wear_item(player_id, keyword, ordinal)


async def _wear_item(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> str:
    """Wear a single item from inventory."""
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    # Check if it's armor that can be worn
    armor_actor = get_component_actor("Armor")
    armor_data = await armor_actor.get.remote(item_id)

    if not armor_data:
        # Check if it's a weapon - should use wield
        weapon_actor = get_component_actor("Weapon")
        weapon_data = await weapon_actor.get.remote(item_id)
        if weapon_data:
            return "Use 'wield' to equip weapons."
        return "You can't wear that."

    slot = armor_data.slot.value

    # Check level requirement
    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    if item_data and item_data.level_requirement > 0:
        stats_actor = get_component_actor("Stats")
        player_stats = await stats_actor.get.remote(player_id)
        player_level = getattr(player_stats, "level", 1) if player_stats else 1
        if player_level < item_data.level_requirement:
            return f"You must be level {item_data.level_requirement} to wear that."

    # Remove item from inventory
    container_actor = get_component_actor("Container")
    weight = item_data.weight if item_data else 0

    def remove_from_inv(c):
        c.remove_item(item_id, weight)

    await container_actor.mutate.remote(player_id, remove_from_inv)

    # Equip the item
    success, item_name, previous_item = await _equip_item(player_id, item_id, slot)

    if not success:
        # Put item back in inventory
        def add_back(c):
            c.add_item(item_id, weight)

        await container_actor.mutate.remote(player_id, add_back)
        return item_name  # Error message

    result = f"You wear {item_name}."

    # If there was a previous item, add it to inventory
    if previous_item:
        identity_actor = get_component_actor("Identity")
        prev_identity = await identity_actor.get.remote(previous_item)
        prev_name = prev_identity.name if prev_identity else "something"

        prev_item_data = await item_actor.get.remote(previous_item)
        prev_weight = prev_item_data.weight if prev_item_data else 0

        def add_previous(c):
            c.add_item(previous_item, prev_weight)

        await container_actor.mutate.remote(player_id, add_previous)
        result += f" (removed {prev_name})"

    return result


async def _wear_all(player_id: EntityId) -> str:
    """Wear all wearable items from inventory."""
    container_actor = get_component_actor("Container")
    armor_actor = get_component_actor("Armor")
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")
    equipment_actor = get_component_actor("Equipment")

    player_container = await container_actor.get.remote(player_id)
    if not player_container or not player_container.contents:
        return "You aren't carrying anything."

    equipment = await equipment_actor.get.remote(player_id)
    if not equipment:
        return "You can't wear equipment."

    equipped = []
    skipped = []

    # Copy the list since we'll be modifying it
    items_to_check = list(player_container.contents)

    for item_id in items_to_check:
        armor_data = await armor_actor.get.remote(item_id)
        if not armor_data:
            continue

        slot = armor_data.slot.value
        item_identity = await identity_actor.get.remote(item_id)
        item_name = item_identity.name if item_identity else "something"

        # Check if slot is already occupied
        if equipment.slots.get(slot):
            skipped.append(item_name)
            continue

        # Check level requirement
        item_data = await item_actor.get.remote(item_id)
        if item_data and item_data.level_requirement > 0:
            stats_actor = get_component_actor("Stats")
            player_stats = await stats_actor.get.remote(player_id)
            player_level = getattr(player_stats, "level", 1) if player_stats else 1
            if player_level < item_data.level_requirement:
                skipped.append(item_name)
                continue

        # Remove from inventory
        weight = item_data.weight if item_data else 0

        def remove_from_inv(c):
            c.remove_item(item_id, weight)

        await container_actor.mutate.remote(player_id, remove_from_inv)

        # Equip the item
        success, _, _ = await _equip_item(player_id, item_id, slot)

        if success:
            equipped.append(item_name)
            # Update local equipment state
            equipment.slots[slot] = item_id
        else:
            # Put item back in inventory
            def add_back(c):
                c.add_item(item_id, weight)

            await container_actor.mutate.remote(player_id, add_back)
            skipped.append(item_name)

    if not equipped:
        if skipped:
            return "You couldn't wear any of those items."
        return "You aren't carrying anything you can wear."

    result = f"You wear: {', '.join(equipped)}"
    return result


@command(
    name="remove",
    aliases=["rem", "unequip"],
    category=CommandCategory.OBJECT,
    help_text="Remove an equipped item.",
    usage="remove <item> | remove all",
    min_position=Position.RESTING,
)
async def cmd_remove(player_id: EntityId, args: List[str]) -> str:
    """Remove equipped items."""
    if not args:
        return "Remove what?"

    # Handle "remove all"
    if args[0].lower() == "all":
        return await _remove_all(player_id)

    ordinal, keyword = _parse_ordinal(args[0])
    return await _remove_item(player_id, keyword, ordinal)


async def _find_equipped_item(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> Tuple[Optional[EntityId], Optional[str]]:
    """
    Find an equipped item by keyword.

    Returns:
        Tuple of (item_id, slot_name) or (None, None)
    """
    equipment_actor = get_component_actor("Equipment")
    identity_actor = get_component_actor("Identity")

    equipment = await equipment_actor.get.remote(player_id)
    if not equipment:
        return (None, None)

    matches = 0
    for slot_name, item_id in equipment.slots.items():
        if not item_id:
            continue

        identity = await identity_actor.get.remote(item_id)
        if identity and _matches_keyword(identity, keyword):
            matches += 1
            if matches == ordinal:
                return (item_id, slot_name)

    return (None, None)


async def _remove_item(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> str:
    """Remove a single equipped item."""
    item_id, slot = await _find_equipped_item(player_id, keyword, ordinal)

    if not item_id:
        return f"You aren't wearing '{keyword}'."

    # Check if item is cursed
    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    if item_data and item_data.is_cursed:
        return "You can't remove that item - it's cursed!"

    # Check inventory capacity
    container_actor = get_component_actor("Container")
    player_container = await container_actor.get.remote(player_id)

    if not player_container:
        return "You have no inventory."

    weight = item_data.weight if item_data else 0
    if not player_container.can_add_item(weight):
        return "You can't carry any more."

    # Unequip the item
    success, item_name, _ = await _unequip_item(player_id, slot)

    if not success:
        return "You can't remove that."

    # Add to inventory
    def add_to_inv(c):
        c.add_item(item_id, weight)

    await container_actor.mutate.remote(player_id, add_to_inv)

    return f"You remove {item_name}."


async def _remove_all(player_id: EntityId) -> str:
    """Remove all equipped items."""
    equipment_actor = get_component_actor("Equipment")
    container_actor = get_component_actor("Container")
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")

    equipment = await equipment_actor.get.remote(player_id)
    if not equipment:
        return "You aren't wearing anything."

    player_container = await container_actor.get.remote(player_id)
    if not player_container:
        return "You have no inventory."

    removed = []
    skipped = []

    for slot_name, item_id in list(equipment.slots.items()):
        if not item_id:
            continue

        item_data = await item_actor.get.remote(item_id)
        item_identity = await identity_actor.get.remote(item_id)
        item_name = item_identity.name if item_identity else "something"

        # Check if cursed
        if item_data and item_data.is_cursed:
            skipped.append(item_name)
            continue

        # Check capacity
        weight = item_data.weight if item_data else 0
        if not player_container.can_add_item(weight):
            skipped.append(item_name)
            continue

        # Unequip
        success, _, _ = await _unequip_item(player_id, slot_name)
        if not success:
            skipped.append(item_name)
            continue

        # Add to inventory
        def add_to_inv(c):
            c.add_item(item_id, weight)

        await container_actor.mutate.remote(player_id, add_to_inv)

        # Update local container state
        player_container.add_item(item_id, weight)

        removed.append(item_name)

    if not removed:
        if skipped:
            return "You couldn't remove any of your equipment."
        return "You aren't wearing anything."

    result = f"You remove: {', '.join(removed)}"
    if skipped:
        result += f"\nCouldn't remove: {', '.join(skipped)}"

    return result


@command(
    name="wield",
    category=CommandCategory.OBJECT,
    help_text="Wield a weapon in your main hand.",
    usage="wield <weapon>",
    min_position=Position.RESTING,
)
async def cmd_wield(player_id: EntityId, args: List[str]) -> str:
    """Wield a weapon from inventory."""
    if not args:
        return "Wield what?"

    ordinal, keyword = _parse_ordinal(args[0])
    return await _wield_item(player_id, keyword, ordinal)


async def _wield_item(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> str:
    """Wield a weapon from inventory."""
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    # Check if it's a weapon
    weapon_actor = get_component_actor("Weapon")
    weapon_data = await weapon_actor.get.remote(item_id)

    if not weapon_data:
        return "That's not a weapon."

    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    # Check level requirement
    if item_data and item_data.level_requirement > 0:
        stats_actor = get_component_actor("Stats")
        player_stats = await stats_actor.get.remote(player_id)
        player_level = getattr(player_stats, "level", 1) if player_stats else 1
        if player_level < item_data.level_requirement:
            return f"You must be level {item_data.level_requirement} to wield that."

    # Handle two-handed weapons
    equipment_actor = get_component_actor("Equipment")
    equipment = await equipment_actor.get.remote(player_id)

    if not equipment:
        return "You can't wield weapons."

    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")

    weight = item_data.weight if item_data else 0
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Remove from inventory first
    def remove_from_inv(c):
        c.remove_item(item_id, weight)

    await container_actor.mutate.remote(player_id, remove_from_inv)

    removed_items = []

    # Check for two-handed weapon
    if weapon_data.two_handed:
        # Need to clear both main_hand and off_hand
        if equipment.slots.get("main_hand"):
            prev_item = equipment.slots["main_hand"]
            prev_identity = await identity_actor.get.remote(prev_item)
            prev_name = prev_identity.name if prev_identity else "something"
            prev_data = await item_actor.get.remote(prev_item)
            prev_weight = prev_data.weight if prev_data else 0

            def add_prev_main(c):
                c.add_item(prev_item, prev_weight)

            await container_actor.mutate.remote(player_id, add_prev_main)
            removed_items.append(prev_name)

        if equipment.slots.get("off_hand"):
            prev_item = equipment.slots["off_hand"]
            prev_identity = await identity_actor.get.remote(prev_item)
            prev_name = prev_identity.name if prev_identity else "something"
            prev_data = await item_actor.get.remote(prev_item)
            prev_weight = prev_data.weight if prev_data else 0

            def add_prev_off(c):
                c.add_item(prev_item, prev_weight)

            await container_actor.mutate.remote(player_id, add_prev_off)
            removed_items.append(prev_name)

        # Equip in both slots
        def equip_two_handed(eq):
            eq.slots["main_hand"] = item_id
            eq.slots["off_hand"] = item_id  # Same ID in both for two-handed

        await equipment_actor.mutate.remote(player_id, equip_two_handed)

    else:
        # One-handed weapon - check main_hand
        if equipment.slots.get("main_hand"):
            prev_item = equipment.slots["main_hand"]
            prev_identity = await identity_actor.get.remote(prev_item)
            prev_name = prev_identity.name if prev_identity else "something"
            prev_data = await item_actor.get.remote(prev_item)
            prev_weight = prev_data.weight if prev_data else 0

            # Check if it was two-handed (occupying both slots)
            if equipment.slots.get("off_hand") == prev_item:
                def clear_off(eq):
                    eq.slots["off_hand"] = None

                await equipment_actor.mutate.remote(player_id, clear_off)

            def add_prev(c):
                c.add_item(prev_item, prev_weight)

            await container_actor.mutate.remote(player_id, add_prev)
            removed_items.append(prev_name)

        # Equip in main hand
        def equip_main(eq):
            eq.slots["main_hand"] = item_id

        await equipment_actor.mutate.remote(player_id, equip_main)

    result = f"You wield {item_name}."
    if removed_items:
        result += f" (removed {', '.join(removed_items)})"

    return result


@command(
    name="hold",
    category=CommandCategory.OBJECT,
    help_text="Hold an item in your off-hand.",
    usage="hold <item>",
    min_position=Position.RESTING,
)
async def cmd_hold(player_id: EntityId, args: List[str]) -> str:
    """Hold an item in the off-hand."""
    if not args:
        return "Hold what?"

    ordinal, keyword = _parse_ordinal(args[0])
    return await _hold_item(player_id, keyword, ordinal)


async def _hold_item(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> str:
    """Hold an item in the off-hand."""
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    # Check if it's a two-handed weapon (can't hold in off-hand)
    weapon_actor = get_component_actor("Weapon")
    weapon_data = await weapon_actor.get.remote(item_id)

    if weapon_data and weapon_data.two_handed:
        return "That weapon requires two hands. Use 'wield' instead."

    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    # Check level requirement
    if item_data and item_data.level_requirement > 0:
        stats_actor = get_component_actor("Stats")
        player_stats = await stats_actor.get.remote(player_id)
        player_level = getattr(player_stats, "level", 1) if player_stats else 1
        if player_level < item_data.level_requirement:
            return f"You must be level {item_data.level_requirement} to hold that."

    equipment_actor = get_component_actor("Equipment")
    equipment = await equipment_actor.get.remote(player_id)

    if not equipment:
        return "You can't hold items."

    # Check if main hand has a two-handed weapon
    main_item = equipment.slots.get("main_hand")
    if main_item and equipment.slots.get("off_hand") == main_item:
        return "You're wielding a two-handed weapon. Remove it first."

    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")

    weight = item_data.weight if item_data else 0
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Remove from inventory
    def remove_from_inv(c):
        c.remove_item(item_id, weight)

    await container_actor.mutate.remote(player_id, remove_from_inv)

    removed_item_name = None

    # Check if there's something in off-hand already
    if equipment.slots.get("off_hand"):
        prev_item = equipment.slots["off_hand"]
        prev_identity = await identity_actor.get.remote(prev_item)
        removed_item_name = prev_identity.name if prev_identity else "something"
        prev_data = await item_actor.get.remote(prev_item)
        prev_weight = prev_data.weight if prev_data else 0

        def add_prev(c):
            c.add_item(prev_item, prev_weight)

        await container_actor.mutate.remote(player_id, add_prev)

    # Equip in off-hand
    def equip_off(eq):
        eq.slots["off_hand"] = item_id

    await equipment_actor.mutate.remote(player_id, equip_off)

    result = f"You hold {item_name}."
    if removed_item_name:
        result += f" (removed {removed_item_name})"

    return result
