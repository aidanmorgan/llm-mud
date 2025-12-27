"""
Chat Channel Commands

Commands for multi-channel communication system.
Supports global channels (OOC, Trade, Newbie) and custom channels.
"""

from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field
from datetime import datetime

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.position import Position


# =============================================================================
# Channel Data Structures
# =============================================================================


@dataclass
class ChannelMessage:
    """A message in a channel."""

    sender_id: EntityId
    sender_name: str
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Channel:
    """A chat channel."""

    name: str
    description: str
    color: str = "white"
    admin_only: bool = False
    history: List[ChannelMessage] = field(default_factory=list)
    max_history: int = 50

    def add_message(self, sender_id: EntityId, sender_name: str, content: str) -> None:
        """Add a message to the channel."""
        msg = ChannelMessage(sender_id, sender_name, content)
        self.history.append(msg)
        if len(self.history) > self.max_history:
            self.history.pop(0)


# In-memory channel storage (would be in Redis in production)
_channels: Dict[str, Channel] = {}
_player_channels: Dict[str, Set[str]] = {}  # player_id -> set of channel names
_player_mutes: Dict[str, Set[str]] = {}  # player_id -> set of muted player_ids


def _init_default_channels() -> None:
    """Initialize default channels."""
    if _channels:
        return

    _channels["ooc"] = Channel(
        name="ooc",
        description="Out-of-character chat for general discussion",
        color="cyan",
    )
    _channels["trade"] = Channel(
        name="trade",
        description="Trading and commerce channel",
        color="yellow",
    )
    _channels["newbie"] = Channel(
        name="newbie",
        description="Help channel for new players",
        color="green",
    )
    _channels["announce"] = Channel(
        name="announce",
        description="Server announcements (admin only to send)",
        color="magenta",
        admin_only=True,
    )


def get_channel(name: str) -> Optional[Channel]:
    """Get a channel by name."""
    _init_default_channels()
    return _channels.get(name.lower())


def get_player_channels(player_id: EntityId) -> Set[str]:
    """Get channels a player is subscribed to."""
    key = str(player_id)
    if key not in _player_channels:
        # Default channels for new players
        _player_channels[key] = {"ooc", "newbie"}
    return _player_channels[key]


def add_player_to_channel(player_id: EntityId, channel_name: str) -> bool:
    """Add player to a channel."""
    channel = get_channel(channel_name)
    if not channel:
        return False
    get_player_channels(player_id).add(channel_name.lower())
    return True


def remove_player_from_channel(player_id: EntityId, channel_name: str) -> bool:
    """Remove player from a channel."""
    channels = get_player_channels(player_id)
    name = channel_name.lower()
    if name in channels:
        channels.remove(name)
        return True
    return False


def is_player_muted(player_id: EntityId, target_id: EntityId) -> bool:
    """Check if player has muted another player."""
    key = str(player_id)
    if key not in _player_mutes:
        return False
    return str(target_id) in _player_mutes[key]


def mute_player(player_id: EntityId, target_id: EntityId) -> None:
    """Mute a player."""
    key = str(player_id)
    if key not in _player_mutes:
        _player_mutes[key] = set()
    _player_mutes[key].add(str(target_id))


def unmute_player(player_id: EntityId, target_id: EntityId) -> None:
    """Unmute a player."""
    key = str(player_id)
    if key in _player_mutes:
        _player_mutes[key].discard(str(target_id))


# =============================================================================
# Channel Commands
# =============================================================================


@command(
    name="channels",
    aliases=["channel", "chan"],
    category=CommandCategory.COMMUNICATION,
    help_text="List available channels or manage subscriptions.",
    usage="channels [list|join|leave] [channel_name]",
    min_position=Position.DEAD,
)
async def cmd_channels(player_id: EntityId, args: List[str]) -> str:
    """Manage channel subscriptions."""
    _init_default_channels()

    if not args:
        return await _list_channels(player_id)

    subcommand = args[0].lower()

    if subcommand == "list":
        return await _list_channels(player_id)
    elif subcommand == "join":
        if len(args) < 2:
            return "Join which channel?"
        return await _join_channel(player_id, args[1])
    elif subcommand == "leave":
        if len(args) < 2:
            return "Leave which channel?"
        return await _leave_channel(player_id, args[1])
    else:
        # Treat as channel name to send message
        return await _send_to_channel(player_id, subcommand, " ".join(args[1:]) if len(args) > 1 else "")


async def _list_channels(player_id: EntityId) -> str:
    """List available channels and subscriptions."""
    subscribed = get_player_channels(player_id)

    lines = ["=== Chat Channels ===", ""]

    for name, channel in _channels.items():
        status = "[+]" if name in subscribed else "[ ]"
        admin_tag = " (admin)" if channel.admin_only else ""
        lines.append(f"  {status} {name}: {channel.description}{admin_tag}")

    lines.append("")
    lines.append("Commands:")
    lines.append("  channels join <name>  - Subscribe to a channel")
    lines.append("  channels leave <name> - Unsubscribe from a channel")
    lines.append("  <channel> <message>   - Send message (e.g., 'ooc hello')")

    return "\n".join(lines)


async def _join_channel(player_id: EntityId, channel_name: str) -> str:
    """Join a channel."""
    channel = get_channel(channel_name)
    if not channel:
        return f"Channel '{channel_name}' does not exist."

    if channel_name.lower() in get_player_channels(player_id):
        return f"You are already subscribed to [{channel_name}]."

    add_player_to_channel(player_id, channel_name)
    return f"You have joined [{channel_name}]."


async def _leave_channel(player_id: EntityId, channel_name: str) -> str:
    """Leave a channel."""
    if channel_name.lower() not in get_player_channels(player_id):
        return f"You are not subscribed to [{channel_name}]."

    remove_player_from_channel(player_id, channel_name)
    return f"You have left [{channel_name}]."


async def _send_to_channel(player_id: EntityId, channel_name: str, message: str) -> str:
    """Send a message to a channel."""
    if not message:
        # Show channel history instead
        return await _show_channel_history(player_id, channel_name)

    channel = get_channel(channel_name)
    if not channel:
        return f"Channel '{channel_name}' does not exist."

    if channel_name.lower() not in get_player_channels(player_id):
        return f"You are not subscribed to [{channel_name}]. Use 'channels join {channel_name}' first."

    # Check admin-only channels
    if channel.admin_only:
        # Would check player admin flag here
        pass

    # Get sender name
    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(player_id)
    sender_name = identity.name if identity else "Unknown"

    # Add to channel history
    channel.add_message(player_id, sender_name, message)

    # Broadcast to all subscribed players
    await _broadcast_channel_message(channel_name, player_id, sender_name, message)

    return f"[{channel_name}] You: {message}"


async def _show_channel_history(player_id: EntityId, channel_name: str) -> str:
    """Show recent messages from a channel."""
    channel = get_channel(channel_name)
    if not channel:
        return f"Channel '{channel_name}' does not exist."

    if channel_name.lower() not in get_player_channels(player_id):
        return f"You are not subscribed to [{channel_name}]."

    if not channel.history:
        return f"No recent messages in [{channel_name}]."

    lines = [f"=== [{channel_name}] Recent Messages ==="]
    for msg in channel.history[-10:]:  # Last 10 messages
        timestamp = msg.timestamp.strftime("%H:%M")
        lines.append(f"[{timestamp}] {msg.sender_name}: {msg.content}")

    return "\n".join(lines)


async def _broadcast_channel_message(
    channel_name: str, sender_id: EntityId, sender_name: str, message: str
) -> None:
    """Broadcast a message to all channel subscribers."""
    connection_actor = get_component_actor("Connection")
    all_connections = await connection_actor.get_all.remote()

    formatted = f"[{channel_name}] {sender_name}: {message}"

    for entity_id, connection in all_connections.items():
        if not connection.is_connected:
            continue
        if entity_id == sender_id:
            continue  # Sender already got confirmation

        # Check if subscribed
        if channel_name.lower() not in get_player_channels(entity_id):
            continue

        # Check if sender is muted
        if is_player_muted(entity_id, sender_id):
            continue

        await _send_to_player(entity_id, formatted)


# =============================================================================
# Quick Channel Commands
# =============================================================================


@command(
    name="ooc",
    category=CommandCategory.COMMUNICATION,
    help_text="Send a message to the OOC channel.",
    usage="ooc <message>",
    min_position=Position.DEAD,
)
async def cmd_ooc_channel(player_id: EntityId, args: List[str]) -> str:
    """Send to OOC channel (override the basic ooc command)."""
    if not args:
        return await _show_channel_history(player_id, "ooc")
    return await _send_to_channel(player_id, "ooc", " ".join(args))


@command(
    name="trade",
    category=CommandCategory.COMMUNICATION,
    help_text="Send a message to the Trade channel.",
    usage="trade <message>",
    min_position=Position.RESTING,
)
async def cmd_trade(player_id: EntityId, args: List[str]) -> str:
    """Send to Trade channel."""
    if not args:
        return await _show_channel_history(player_id, "trade")
    return await _send_to_channel(player_id, "trade", " ".join(args))


@command(
    name="newbie",
    aliases=["newb"],
    category=CommandCategory.COMMUNICATION,
    help_text="Send a message to the Newbie help channel.",
    usage="newbie <message>",
    min_position=Position.DEAD,
)
async def cmd_newbie(player_id: EntityId, args: List[str]) -> str:
    """Send to Newbie channel."""
    if not args:
        return await _show_channel_history(player_id, "newbie")
    return await _send_to_channel(player_id, "newbie", " ".join(args))


# =============================================================================
# Mute Commands
# =============================================================================


@command(
    name="mute",
    aliases=["ignore"],
    category=CommandCategory.COMMUNICATION,
    help_text="Mute a player so you don't see their messages.",
    usage="mute <player_name>",
    min_position=Position.DEAD,
)
async def cmd_mute(player_id: EntityId, args: List[str]) -> str:
    """Mute a player."""
    if not args:
        # List muted players
        key = str(player_id)
        muted = _player_mutes.get(key, set())
        if not muted:
            return "You have no muted players."
        return f"Muted players: {', '.join(muted)}"

    target_name = args[0]
    target_id = await _find_player_by_name(target_name)

    if not target_id:
        return f"Player '{target_name}' not found."

    if target_id == player_id:
        return "You can't mute yourself."

    mute_player(player_id, target_id)

    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(target_id)
    display_name = identity.name if identity else target_name

    return f"You have muted {display_name}. You will no longer see their messages."


@command(
    name="unmute",
    aliases=["unignore"],
    category=CommandCategory.COMMUNICATION,
    help_text="Unmute a previously muted player.",
    usage="unmute <player_name>",
    min_position=Position.DEAD,
)
async def cmd_unmute(player_id: EntityId, args: List[str]) -> str:
    """Unmute a player."""
    if not args:
        return "Unmute which player?"

    target_name = args[0]
    target_id = await _find_player_by_name(target_name)

    if not target_id:
        return f"Player '{target_name}' not found."

    if not is_player_muted(player_id, target_id):
        return "You haven't muted that player."

    unmute_player(player_id, target_id)

    identity_actor = get_component_actor("Identity")
    identity = await identity_actor.get.remote(target_id)
    display_name = identity.name if identity else target_name

    return f"You have unmuted {display_name}."


# =============================================================================
# Helper Functions
# =============================================================================


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


async def _send_to_player(entity_id: EntityId, message: str) -> None:
    """Send a message to a specific player."""
    try:
        import ray

        gateway = ray.get_actor("gateway", namespace="llmmud")
        from network.protocol import create_text

        await gateway.send_to_player.remote(entity_id, create_text(message, "channel"))
    except Exception:
        pass
