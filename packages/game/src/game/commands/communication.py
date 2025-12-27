"""
Communication Commands

Commands for player communication - say, shout, tell, etc.
"""

from typing import List, Optional

from core import EntityId
from .registry import command, CommandCategory
from ..components.position import Position


@command(
    name="say",
    aliases=["'"],
    category=CommandCategory.COMMUNICATION,
    help_text="Say something to the room.",
    usage="say <message>",
    min_position=Position.RESTING,
)
async def cmd_say(player_id: EntityId, args: List[str]) -> str:
    """Say something to everyone in the room."""
    if not args:
        return "Say what?"

    message = " ".join(args)

    from core.component import get_component_actor

    # Get player name
    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    name = identity.name if identity else "Someone"

    # Get player's room
    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    # Send message to all players in room
    await _broadcast_to_room(location.room_id, f"{name} says '{message}'", exclude=player_id)

    return f"You say '{message}'"


@command(
    name="emote",
    aliases=[":", ";"],
    category=CommandCategory.COMMUNICATION,
    help_text="Perform an emote action.",
    usage="emote <action>",
    min_position=Position.RESTING,
)
async def cmd_emote(player_id: EntityId, args: List[str]) -> str:
    """Perform an emote visible to the room."""
    if not args:
        return "Emote what?"

    action = " ".join(args)

    from core.component import get_component_actor

    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    name = identity.name if identity else "Someone"

    location_actor = get_component_actor("Location")
    location = await location_actor.get.remote(player_id)

    if not location or not location.room_id:
        return "You are nowhere."

    emote_msg = f"{name} {action}"

    await _broadcast_to_room(location.room_id, emote_msg)

    return emote_msg


@command(
    name="shout",
    aliases=["sh"],
    category=CommandCategory.COMMUNICATION,
    help_text="Shout a message to the entire area.",
    usage="shout <message>",
    min_position=Position.RESTING,
)
async def cmd_shout(player_id: EntityId, args: List[str]) -> str:
    """Shout a message to everyone in the area."""
    if not args:
        return "Shout what?"

    message = " ".join(args)

    from core.component import get_component_actor

    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    name = identity.name if identity else "Someone"

    # Broadcast to all players
    await _broadcast_global(f"{name} shouts '{message}'", exclude=player_id)

    return f"You shout '{message}'"


@command(
    name="tell",
    aliases=["t", "whisper"],
    category=CommandCategory.COMMUNICATION,
    help_text="Send a private message to a player.",
    usage="tell <player> <message>",
)
async def cmd_tell(player_id: EntityId, args: List[str]) -> str:
    """Send a private message to another player."""
    if len(args) < 2:
        return "Tell who what?"

    target_name = args[0]
    message = " ".join(args[1:])

    from core.component import get_component_actor

    identity_actor = get_component_actor("Identity")
    sender_identity = await identity_actor.get.remote(player_id)
    sender_name = sender_identity.name if sender_identity else "Someone"

    # Find target player
    target_id = await _find_player_by_name(target_name)

    if not target_id:
        return f"Player '{target_name}' not found."

    if target_id == player_id:
        return "Talking to yourself again?"

    target_identity = await identity_actor.get.remote(target_id)
    target_display_name = target_identity.name if target_identity else target_name

    # Send message to target
    await _send_to_player(target_id, f"{sender_name} tells you '{message}'")

    return f"You tell {target_display_name} '{message}'"


@command(
    name="reply",
    aliases=["r"],
    category=CommandCategory.COMMUNICATION,
    help_text="Reply to the last person who sent you a tell.",
    usage="reply <message>",
)
async def cmd_reply(player_id: EntityId, args: List[str]) -> str:
    """Reply to the last tell received."""
    if not args:
        return "Reply with what?"

    # Would need to track last tell sender in session/component
    return "You haven't received any tells."


@command(
    name="ooc",
    category=CommandCategory.COMMUNICATION,
    help_text="Send an out-of-character message.",
    usage="ooc <message>",
    min_position=Position.DEAD,
)
async def cmd_ooc(player_id: EntityId, args: List[str]) -> str:
    """Send an out-of-character message to all players."""
    if not args:
        return "OOC what?"

    message = " ".join(args)

    from core.component import get_component_actor

    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    name = identity.name if identity else "Someone"

    await _broadcast_global(f"[OOC] {name}: {message}", exclude=player_id)

    return f"[OOC] You: {message}"


# ============================================================================
# Helper Functions
# ============================================================================


async def _broadcast_to_room(room_id: EntityId, message: str, exclude: EntityId = None) -> None:
    """Send a message to all players in a room."""
    from core.component import get_component_actor

    location_actor = get_component_actor("Location")
    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if entity_id.entity_type != "player":
            continue
        if exclude and entity_id == exclude:
            continue

        await _send_to_player(entity_id, message)


async def _broadcast_global(message: str, exclude: EntityId = None) -> None:
    """Send a message to all online players."""
    from core.component import get_component_actor

    connection_actor = get_component_actor("Connection")
    all_connections = await connection_actor.get_all.remote()

    for entity_id, connection in all_connections.items():
        if not connection.is_connected:
            continue
        if exclude and entity_id == exclude:
            continue

        await _send_to_player(entity_id, message)


async def _send_to_player(player_id: EntityId, message: str) -> None:
    """Send a message to a specific player."""
    try:
        import ray

        gateway = ray.get_actor("gateway", namespace="llmmud")
        from network.protocol import create_text

        await gateway.send_to_player.remote(player_id, create_text(message, "tell"))
    except Exception:
        # Gateway not available, silently ignore
        pass


async def _find_player_by_name(name: str) -> Optional[EntityId]:
    """Find an online player by name."""
    from core.component import get_component_actor

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
