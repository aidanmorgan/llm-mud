"""
OLC (Online Creation) Commands

Commands for building and editing the game world online.
These commands allow administrators to create and modify rooms,
mobs, items, and zones without restarting the server.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory


# =============================================================================
# OLC Session State
# =============================================================================

# In-memory OLC sessions per player
# In production, this would be stored in a component or Redis
_olc_sessions: Dict[str, "OLCSession"] = {}


@dataclass
class OLCSession:
    """Tracks a player's OLC editing session."""

    player_id: EntityId
    mode: str  # 'room', 'mob', 'item', 'zone'
    target_id: Optional[EntityId] = None
    is_new: bool = False
    changes: Dict[str, Any] = field(default_factory=dict)


def get_session(player_id: EntityId) -> Optional[OLCSession]:
    """Get a player's OLC session."""
    return _olc_sessions.get(str(player_id))


def set_session(player_id: EntityId, session: OLCSession) -> None:
    """Set a player's OLC session."""
    _olc_sessions[str(player_id)] = session


def clear_session(player_id: EntityId) -> None:
    """Clear a player's OLC session."""
    _olc_sessions.pop(str(player_id), None)


# =============================================================================
# Room Editing (redit)
# =============================================================================


@command(
    name="redit",
    category=CommandCategory.ADMIN,
    help_text="Edit the current room or create a new one.",
    usage="redit [create|done|show|<property> <value>]",
    admin_only=True,
)
async def cmd_redit(player_id: EntityId, args: List[str]) -> str:
    """Room editor command."""
    if not args:
        return _redit_help()

    subcommand = args[0].lower()

    if subcommand == "create":
        return await _redit_create(player_id)
    elif subcommand == "done":
        return await _redit_done(player_id)
    elif subcommand == "show":
        return await _redit_show(player_id)
    elif subcommand == "cancel":
        return _redit_cancel(player_id)
    else:
        # Property setting
        if len(args) < 2:
            return f"Usage: redit {subcommand} <value>"
        return await _redit_set(player_id, subcommand, " ".join(args[1:]))


def _redit_help() -> str:
    """Return redit help text."""
    return """Room Editor (redit) Commands:
  redit create          - Start creating a new room
  redit show            - Show current room properties
  redit done            - Save changes and exit editor
  redit cancel          - Discard changes and exit editor

Properties:
  redit name <name>           - Set room name
  redit desc <description>    - Set long description
  redit sector <type>         - Set sector type (inside, city, forest, etc.)
  redit safe <true/false>     - Set safe room flag
  redit exit <dir> <room_id>  - Add/modify an exit
  redit rmexit <direction>    - Remove an exit"""


async def _redit_create(player_id: EntityId) -> str:
    """Start creating a new room."""
    session = OLCSession(
        player_id=player_id,
        mode="room",
        is_new=True,
        changes={
            "name": "A New Room",
            "description": "This room has not been described yet.",
            "sector_type": "inside",
            "is_safe": False,
            "exits": {},
        },
    )
    set_session(player_id, session)
    return "Room creation started. Use 'redit show' to see properties, 'redit done' to save."


async def _redit_show(player_id: EntityId) -> str:
    """Show current room or session properties."""
    session = get_session(player_id)

    if session and session.mode == "room":
        # Show session changes
        lines = ["=== Room Editor ==="]
        lines.append(f"Status: {'New Room' if session.is_new else 'Editing'}")
        for key, value in session.changes.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)

    # Show current room
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    room_actor = get_component_actor("Room")
    room = await room_actor.get.remote(player_location.room_id)

    if not room:
        return "Current room not found."

    lines = [f"=== Room: {player_location.room_id} ==="]
    lines.append(f"Name: {room.name}")
    lines.append(f"Description: {room.description[:100]}...")
    lines.append(f"Sector: {getattr(room, 'sector_type', 'unknown')}")
    lines.append(f"Safe: {getattr(room, 'is_safe', False)}")

    exits = room.get_available_exits() if hasattr(room, "get_available_exits") else []
    lines.append(f"Exits: {', '.join(exits) if exits else 'none'}")

    lines.append("\nUse 'redit <property> <value>' to modify.")
    return "\n".join(lines)


async def _redit_set(player_id: EntityId, prop: str, value: str) -> str:
    """Set a room property."""
    session = get_session(player_id)

    # Start editing current room if no session
    if not session or session.mode != "room":
        location_actor = get_component_actor("Location")
        player_location = await location_actor.get.remote(player_id)

        if not player_location or not player_location.room_id:
            return "You are nowhere. Use 'redit create' to make a new room."

        session = OLCSession(
            player_id=player_id,
            mode="room",
            target_id=player_location.room_id,
            is_new=False,
            changes={},
        )
        set_session(player_id, session)

    # Handle different properties
    if prop == "name":
        session.changes["name"] = value
        return f"Room name set to: {value}"

    elif prop in ("desc", "description"):
        session.changes["description"] = value
        return "Room description set."

    elif prop == "sector":
        valid_sectors = ["inside", "city", "field", "forest", "hills", "mountain", "cave", "desert"]
        if value.lower() not in valid_sectors:
            return f"Invalid sector. Choose from: {', '.join(valid_sectors)}"
        session.changes["sector_type"] = value.lower()
        return f"Sector type set to: {value}"

    elif prop == "safe":
        session.changes["is_safe"] = value.lower() in ("true", "yes", "1")
        return f"Safe flag set to: {session.changes['is_safe']}"

    elif prop == "exit":
        parts = value.split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: redit exit <direction> <room_id>"
        direction, room_id = parts[0].lower(), parts[1]
        if "exits" not in session.changes:
            session.changes["exits"] = {}
        session.changes["exits"][direction] = room_id
        return f"Exit {direction} -> {room_id} added."

    elif prop == "rmexit":
        direction = value.lower()
        if "exits" not in session.changes:
            session.changes["exits"] = {}
        session.changes["exits"][direction] = None  # Mark for deletion
        return f"Exit {direction} marked for removal."

    else:
        return f"Unknown property: {prop}. Use 'redit' for help."


async def _redit_done(player_id: EntityId) -> str:
    """Save room changes."""
    session = get_session(player_id)

    if not session or session.mode != "room":
        return "You are not editing a room."

    if session.is_new:
        # Create new room (would integrate with world factory)
        clear_session(player_id)
        return "New room created. (Room creation not fully implemented)"

    # Update existing room
    if session.target_id:
        room_actor = get_component_actor("Room")

        def apply_changes(room):
            for key, value in session.changes.items():
                if key == "exits":
                    # Handle exit changes specially
                    pass
                else:
                    setattr(room, key, value)

        await room_actor.mutate.remote(session.target_id, apply_changes)

    clear_session(player_id)
    return "Room changes saved."


def _redit_cancel(player_id: EntityId) -> str:
    """Cancel room editing."""
    session = get_session(player_id)
    if not session or session.mode != "room":
        return "You are not editing a room."

    clear_session(player_id)
    return "Room editing cancelled. Changes discarded."


# =============================================================================
# Mob Editing (medit)
# =============================================================================


@command(
    name="medit",
    category=CommandCategory.ADMIN,
    help_text="Edit a mob template or create a new one.",
    usage="medit [create|done|show|<property> <value>]",
    admin_only=True,
)
async def cmd_medit(player_id: EntityId, args: List[str]) -> str:
    """Mob editor command."""
    if not args:
        return _medit_help()

    subcommand = args[0].lower()

    if subcommand == "create":
        return await _medit_create(player_id)
    elif subcommand == "done":
        return await _medit_done(player_id)
    elif subcommand == "show":
        return await _medit_show(player_id)
    elif subcommand == "cancel":
        return _medit_cancel(player_id)
    elif subcommand == "load":
        if len(args) < 2:
            return "Usage: medit load <mob_keyword>"
        return await _medit_load(player_id, args[1])
    else:
        if len(args) < 2:
            return f"Usage: medit {subcommand} <value>"
        return await _medit_set(player_id, subcommand, " ".join(args[1:]))


def _medit_help() -> str:
    """Return medit help text."""
    return """Mob Editor (medit) Commands:
  medit create          - Start creating a new mob
  medit load <keyword>  - Load an existing mob for editing
  medit show            - Show current mob properties
  medit done            - Save changes and exit editor
  medit cancel          - Discard changes and exit editor

Properties:
  medit name <name>           - Set mob name
  medit keywords <kw1 kw2>    - Set targeting keywords
  medit short <desc>          - Set short description (in room)
  medit long <desc>           - Set long description (when looked at)
  medit level <number>        - Set level/challenge rating
  medit hp <number>           - Set max hit points
  medit behavior <type>       - Set AI behavior (passive, aggressive, etc.)"""


async def _medit_create(player_id: EntityId) -> str:
    """Start creating a new mob."""
    session = OLCSession(
        player_id=player_id,
        mode="mob",
        is_new=True,
        changes={
            "name": "a new mob",
            "keywords": ["mob", "new"],
            "short_description": "A new mob stands here.",
            "long_description": "This mob has not been described yet.",
            "level": 1,
            "max_hp": 100,
            "behavior_type": "passive",
        },
    )
    set_session(player_id, session)
    return "Mob creation started. Use 'medit show' to see properties, 'medit done' to save."


async def _medit_load(player_id: EntityId, keyword: str) -> str:
    """Load an existing mob for editing."""
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    # Find mob in room
    identity_actor = get_component_actor("Identity")
    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != player_location.room_id:
            continue
        if entity_id.entity_type not in ("mob", "npc"):
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        if keyword.lower() in identity.name.lower() or keyword.lower() in [
            k.lower() for k in identity.keywords
        ]:
            # Load this mob's data into session
            stats_actor = get_component_actor("Stats")
            stats = await stats_actor.get.remote(entity_id)

            ai_actor = get_component_actor("AI")
            ai = await ai_actor.get.remote(entity_id)

            session = OLCSession(
                player_id=player_id,
                mode="mob",
                target_id=entity_id,
                is_new=False,
                changes={
                    "name": identity.name,
                    "keywords": identity.keywords,
                    "short_description": getattr(identity, "short_description", ""),
                    "long_description": getattr(identity, "long_description", ""),
                    "level": getattr(stats, "challenge_rating", 1) if stats else 1,
                    "max_hp": stats.max_hp if stats else 100,
                    "behavior_type": ai.get("behavior_type", "passive") if ai else "passive",
                },
            )
            set_session(player_id, session)
            return f"Loaded mob: {identity.name}. Use 'medit show' to view, 'medit done' to save."

    return f"No mob matching '{keyword}' found in this room."


async def _medit_show(player_id: EntityId) -> str:
    """Show current mob session properties."""
    session = get_session(player_id)

    if not session or session.mode != "mob":
        return "You are not editing a mob. Use 'medit create' or 'medit load <keyword>'."

    lines = ["=== Mob Editor ==="]
    lines.append(f"Status: {'New Mob' if session.is_new else f'Editing {session.target_id}'}")
    for key, value in session.changes.items():
        if isinstance(value, list):
            lines.append(f"  {key}: {', '.join(value)}")
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


async def _medit_set(player_id: EntityId, prop: str, value: str) -> str:
    """Set a mob property."""
    session = get_session(player_id)

    if not session or session.mode != "mob":
        return "You are not editing a mob. Use 'medit create' first."

    if prop == "name":
        session.changes["name"] = value
        return f"Mob name set to: {value}"

    elif prop == "keywords":
        session.changes["keywords"] = value.split()
        return f"Keywords set to: {value}"

    elif prop == "short":
        session.changes["short_description"] = value
        return "Short description set."

    elif prop == "long":
        session.changes["long_description"] = value
        return "Long description set."

    elif prop == "level":
        try:
            session.changes["level"] = int(value)
            return f"Level set to: {value}"
        except ValueError:
            return "Level must be a number."

    elif prop == "hp":
        try:
            session.changes["max_hp"] = int(value)
            return f"Max HP set to: {value}"
        except ValueError:
            return "HP must be a number."

    elif prop == "behavior":
        valid = ["passive", "aggressive", "defensive", "patrol"]
        if value.lower() not in valid:
            return f"Invalid behavior. Choose from: {', '.join(valid)}"
        session.changes["behavior_type"] = value.lower()
        return f"Behavior set to: {value}"

    else:
        return f"Unknown property: {prop}. Use 'medit' for help."


async def _medit_done(player_id: EntityId) -> str:
    """Save mob changes."""
    session = get_session(player_id)

    if not session or session.mode != "mob":
        return "You are not editing a mob."

    if session.is_new:
        clear_session(player_id)
        return "New mob template created. (Full mob creation not implemented)"

    # Update existing mob
    if session.target_id:
        identity_actor = get_component_actor("Identity")
        stats_actor = get_component_actor("Stats")
        ai_actor = get_component_actor("AI")

        # Update identity
        def update_identity(identity):
            if "name" in session.changes:
                identity.name = session.changes["name"]
            if "keywords" in session.changes:
                identity.keywords = session.changes["keywords"]
            if "short_description" in session.changes:
                identity.short_description = session.changes["short_description"]
            if "long_description" in session.changes:
                identity.long_description = session.changes["long_description"]

        await identity_actor.mutate.remote(session.target_id, update_identity)

        # Update stats
        def update_stats(stats):
            if "max_hp" in session.changes:
                stats.max_hp = session.changes["max_hp"]
            if "level" in session.changes:
                stats.challenge_rating = session.changes["level"]

        await stats_actor.mutate.remote(session.target_id, update_stats)

        # Update AI
        def update_ai(ai):
            if "behavior_type" in session.changes:
                ai["behavior_type"] = session.changes["behavior_type"]

        await ai_actor.mutate.remote(session.target_id, update_ai)

    clear_session(player_id)
    return "Mob changes saved."


def _medit_cancel(player_id: EntityId) -> str:
    """Cancel mob editing."""
    session = get_session(player_id)
    if not session or session.mode != "mob":
        return "You are not editing a mob."

    clear_session(player_id)
    return "Mob editing cancelled. Changes discarded."


# =============================================================================
# Object/Item Editing (oedit)
# =============================================================================


@command(
    name="oedit",
    category=CommandCategory.ADMIN,
    help_text="Edit an item template or create a new one.",
    usage="oedit [create|done|show|<property> <value>]",
    admin_only=True,
)
async def cmd_oedit(player_id: EntityId, args: List[str]) -> str:
    """Object/Item editor command."""
    if not args:
        return _oedit_help()

    subcommand = args[0].lower()

    if subcommand == "create":
        return await _oedit_create(player_id)
    elif subcommand == "done":
        return await _oedit_done(player_id)
    elif subcommand == "show":
        return await _oedit_show(player_id)
    elif subcommand == "cancel":
        return _oedit_cancel(player_id)
    else:
        if len(args) < 2:
            return f"Usage: oedit {subcommand} <value>"
        return await _oedit_set(player_id, subcommand, " ".join(args[1:]))


def _oedit_help() -> str:
    """Return oedit help text."""
    return """Object Editor (oedit) Commands:
  oedit create          - Start creating a new item
  oedit show            - Show current item properties
  oedit done            - Save changes and exit editor
  oedit cancel          - Discard changes and exit editor

Properties:
  oedit name <name>           - Set item name
  oedit keywords <kw1 kw2>    - Set targeting keywords
  oedit short <desc>          - Set short description (on ground)
  oedit long <desc>           - Set long description (when examined)
  oedit type <type>           - Set item type (weapon, armor, etc.)
  oedit weight <number>       - Set weight
  oedit value <number>        - Set gold value
  oedit level <number>        - Set level requirement"""


async def _oedit_create(player_id: EntityId) -> str:
    """Start creating a new item."""
    session = OLCSession(
        player_id=player_id,
        mode="item",
        is_new=True,
        changes={
            "name": "a new item",
            "keywords": ["item", "new"],
            "short_description": "A new item lies here.",
            "long_description": "This item has not been described yet.",
            "item_type": "misc",
            "weight": 1.0,
            "value": 0,
            "level_requirement": 0,
        },
    )
    set_session(player_id, session)
    return "Item creation started. Use 'oedit show' to see properties, 'oedit done' to save."


async def _oedit_show(player_id: EntityId) -> str:
    """Show current item session properties."""
    session = get_session(player_id)

    if not session or session.mode != "item":
        return "You are not editing an item. Use 'oedit create' first."

    lines = ["=== Object Editor ==="]
    lines.append(f"Status: {'New Item' if session.is_new else f'Editing {session.target_id}'}")
    for key, value in session.changes.items():
        if isinstance(value, list):
            lines.append(f"  {key}: {', '.join(str(v) for v in value)}")
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


async def _oedit_set(player_id: EntityId, prop: str, value: str) -> str:
    """Set an item property."""
    session = get_session(player_id)

    if not session or session.mode != "item":
        return "You are not editing an item. Use 'oedit create' first."

    if prop == "name":
        session.changes["name"] = value
        return f"Item name set to: {value}"

    elif prop == "keywords":
        session.changes["keywords"] = value.split()
        return f"Keywords set to: {value}"

    elif prop == "short":
        session.changes["short_description"] = value
        return "Short description set."

    elif prop == "long":
        session.changes["long_description"] = value
        return "Long description set."

    elif prop == "type":
        valid = ["weapon", "armor", "consumable", "container", "key", "treasure", "misc", "quest"]
        if value.lower() not in valid:
            return f"Invalid type. Choose from: {', '.join(valid)}"
        session.changes["item_type"] = value.lower()
        return f"Item type set to: {value}"

    elif prop == "weight":
        try:
            session.changes["weight"] = float(value)
            return f"Weight set to: {value}"
        except ValueError:
            return "Weight must be a number."

    elif prop == "value":
        try:
            session.changes["value"] = int(value)
            return f"Value set to: {value} gold"
        except ValueError:
            return "Value must be a number."

    elif prop == "level":
        try:
            session.changes["level_requirement"] = int(value)
            return f"Level requirement set to: {value}"
        except ValueError:
            return "Level must be a number."

    else:
        return f"Unknown property: {prop}. Use 'oedit' for help."


async def _oedit_done(player_id: EntityId) -> str:
    """Save item changes."""
    session = get_session(player_id)

    if not session or session.mode != "item":
        return "You are not editing an item."

    clear_session(player_id)
    return "Item template saved. (Full item creation not implemented)"


def _oedit_cancel(player_id: EntityId) -> str:
    """Cancel item editing."""
    session = get_session(player_id)
    if not session or session.mode != "item":
        return "You are not editing an item."

    clear_session(player_id)
    return "Item editing cancelled. Changes discarded."


# =============================================================================
# Utility Commands
# =============================================================================


@command(
    name="dig",
    category=CommandCategory.ADMIN,
    help_text="Create a new room in a direction and link it.",
    usage="dig <direction> [room_name]",
    admin_only=True,
)
async def cmd_dig(player_id: EntityId, args: List[str]) -> str:
    """Create a new room and link it to the current room."""
    if not args:
        return "Dig in which direction?"

    direction = args[0].lower()
    valid_directions = ["north", "south", "east", "west", "up", "down", "n", "s", "e", "w", "u", "d"]

    if direction not in valid_directions:
        return f"Invalid direction. Use: {', '.join(valid_directions[:6])}"

    # Expand short directions
    dir_map = {"n": "north", "s": "south", "e": "east", "w": "west", "u": "up", "d": "down"}
    direction = dir_map.get(direction, direction)

    room_name = " ".join(args[1:]) if len(args) > 1 else f"A New Room ({direction})"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    # Check if exit already exists
    room_actor = get_component_actor("Room")
    current_room = await room_actor.get.remote(player_location.room_id)

    if current_room:
        existing_exit = current_room.get_exit(direction) if hasattr(current_room, "get_exit") else None
        if existing_exit:
            return f"An exit already exists to the {direction}."

    return f"Room '{room_name}' created to the {direction}. (Full room creation not implemented)"


@command(
    name="mload",
    category=CommandCategory.ADMIN,
    help_text="Load a mob from a template.",
    usage="mload <template_id>",
    admin_only=True,
)
async def cmd_mload(player_id: EntityId, args: List[str]) -> str:
    """Load a mob from a template into the current room."""
    if not args:
        return "Load which mob template?"

    template_id = args[0]

    # Would use EntityFactory to spawn from template
    return f"Mob template '{template_id}' loaded into room. (Template loading not fully implemented)"


@command(
    name="oload",
    category=CommandCategory.ADMIN,
    help_text="Load an item from a template.",
    usage="oload <template_id>",
    admin_only=True,
)
async def cmd_oload(player_id: EntityId, args: List[str]) -> str:
    """Load an item from a template into the current room."""
    if not args:
        return "Load which item template?"

    template_id = args[0]

    # Would use EntityFactory to spawn from template
    return f"Item template '{template_id}' loaded into room. (Template loading not fully implemented)"
