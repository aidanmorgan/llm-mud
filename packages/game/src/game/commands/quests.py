"""Quest commands - viewing, accepting, abandoning quests."""

from typing import Optional

from ..commands.registry import command, CommandCategory


@command(
    name="quests",
    aliases=["quest", "journal", "log"],
    category=CommandCategory.INFO,
    help_text="View your active quests and quest log.",
)
async def cmd_quests(player_id: str, args: str, game_state) -> str:
    """View quest log."""
    from ..components.quests import (
        QuestLogData,
        QuestState,
        get_quest_definition,
    )

    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log:
        quest_log = QuestLogData()
        await game_state.set_component(player_id, "QuestLogData", quest_log)

    if not args:
        # Show summary of all active quests
        if not quest_log.active_quests:
            return "You have no active quests. Talk to NPCs with a '!' to find quests."

        lines = [
            "=== Quest Log ===",
            "",
        ]

        for quest_id, active in quest_log.active_quests.items():
            definition = get_quest_definition(quest_id)
            name = definition.name if definition else quest_id

            if active.state == QuestState.COMPLETED:
                status = "(Ready to turn in)"
            elif active.is_expired:
                status = "(EXPIRED)"
            else:
                completed = sum(1 for o in active.objectives if o.is_complete)
                total = len(active.objectives)
                status = f"({completed}/{total} objectives)"

            lines.append(f"  {name} {status}")

        lines.append("")
        lines.append(f"({quest_log.active_count}/{quest_log.max_active_quests} quests)")
        lines.append("")
        lines.append("Use 'quest <name>' for details on a specific quest.")

        return "\n".join(lines)

    # Show specific quest details
    search = args.lower()

    # Find matching quest
    found_quest = None
    found_id = None

    for quest_id, active in quest_log.active_quests.items():
        definition = get_quest_definition(quest_id)
        if not definition:
            continue

        if (search in definition.name.lower() or
            search in quest_id.lower()):
            found_quest = active
            found_id = quest_id
            break

    if not found_quest:
        return f"No active quest matching '{args}'."

    definition = get_quest_definition(found_id)
    if not definition:
        return "Quest data not found."

    lines = [
        f"=== {definition.name} ===",
        f"[{definition.rarity.value.title()}]",
        "",
        definition.description,
        "",
        "Objectives:",
    ]

    for obj in found_quest.objectives:
        check = "[x]" if obj.is_complete else "[ ]"
        lines.append(f"  {check} {obj.description} ({obj.progress_text})")

    lines.append("")

    if found_quest.state == QuestState.COMPLETED:
        turn_in = definition.turn_in_id or definition.giver_id
        lines.append(f"Quest complete! Return to {turn_in} to turn in.")
    elif found_quest.is_expired:
        lines.append("This quest has EXPIRED and will be removed.")
    elif found_quest.expires_at:
        remaining = found_quest.expires_at - datetime.utcnow()
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        lines.append(f"Time remaining: {hours}h {minutes}m")

    # Show rewards
    rewards = definition.rewards
    if rewards.experience or rewards.gold or rewards.items:
        lines.append("")
        lines.append("Rewards:")
        if rewards.experience:
            lines.append(f"  Experience: {rewards.experience}")
        if rewards.gold:
            lines.append(f"  Gold: {rewards.gold}")
        if rewards.items:
            lines.append(f"  Items: {len(rewards.items)}")

    return "\n".join(lines)


@command(
    name="accept",
    aliases=["acceptquest"],
    category=CommandCategory.SOCIAL,
    help_text="Accept a quest from an NPC.",
)
async def cmd_accept(player_id: str, args: str, game_state) -> str:
    """Accept a quest."""
    from ..systems.quests import accept_quest
    from ..components.quests import get_quest_definition

    if not args:
        return "Accept which quest? Usage: accept <quest name or number>"

    # Get available quests from context (would be set by talking to NPC)
    # For now, try to find by quest ID or name
    from ..components.quests import get_all_quest_definitions

    all_quests = get_all_quest_definitions()
    search = args.lower()

    found_id = None
    for quest_id, definition in all_quests.items():
        if (search in definition.name.lower() or
            search == quest_id.lower()):
            found_id = quest_id
            break

    if not found_id:
        return f"No quest found matching '{args}'."

    success, message = await accept_quest(player_id, found_id, game_state)
    return message


@command(
    name="abandon",
    aliases=["abandonquest", "dropquest"],
    category=CommandCategory.SOCIAL,
    help_text="Abandon an active quest.",
)
async def cmd_abandon(player_id: str, args: str, game_state) -> str:
    """Abandon a quest."""
    from ..components.quests import QuestLogData, get_quest_definition

    if not args:
        return "Abandon which quest? Usage: abandon <quest name>"

    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log:
        return "You have no quests to abandon."

    search = args.lower()

    # Find matching quest
    found_id = None
    found_name = None

    for quest_id in quest_log.active_quests:
        definition = get_quest_definition(quest_id)
        if not definition:
            continue

        if (search in definition.name.lower() or
            search in quest_id.lower()):
            found_id = quest_id
            found_name = definition.name
            break

    if not found_id:
        return f"No active quest matching '{args}'."

    if quest_log.abandon_quest(found_id):
        await game_state.set_component(player_id, "QuestLogData", quest_log)
        return f"Quest abandoned: {found_name}"

    return "Failed to abandon quest."


@command(
    name="turnin",
    aliases=["complete", "finish"],
    category=CommandCategory.SOCIAL,
    help_text="Turn in a completed quest to receive rewards.",
)
async def cmd_turnin(player_id: str, args: str, game_state) -> str:
    """Turn in a completed quest."""
    from ..systems.quests import turn_in_quest
    from ..components.quests import QuestLogData, QuestState, get_quest_definition

    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log:
        return "You have no quests."

    # Find a completed quest to turn in
    if not args:
        # Try to auto-find a completed quest
        for quest_id, active in quest_log.active_quests.items():
            if active.state == QuestState.COMPLETED or active.is_complete:
                args = quest_id
                break

        if not args:
            return "You have no completed quests to turn in."

    search = args.lower()

    # Find matching quest
    found_id = None

    for quest_id in quest_log.active_quests:
        definition = get_quest_definition(quest_id)
        if not definition:
            if search == quest_id.lower():
                found_id = quest_id
                break
            continue

        if (search in definition.name.lower() or
            search in quest_id.lower()):
            found_id = quest_id
            break

    if not found_id:
        return f"No active quest matching '{args}'."

    success, message, rewards = await turn_in_quest(player_id, found_id, game_state)

    if success and rewards.get("unlocked_quests"):
        message += f"\n\nNew quests available!"

    return message


@command(
    name="questgiver",
    aliases=["questgivers", "!"],
    category=CommandCategory.INFO,
    help_text="Check if nearby NPCs have quests for you.",
)
async def cmd_questgiver(player_id: str, args: str, game_state) -> str:
    """Find quest givers in the current room."""
    from ..components.spatial import LocationData
    from ..components.ai import DialogueData
    from ..components.identity import IdentityData
    from ..systems.quests import get_available_quests

    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    # Get entities in room
    room_entities = await game_state.get_entities_in_room(location.room_id)

    quest_givers = []

    for entity_id in room_entities:
        dialogue = await game_state.get_component(entity_id, "DialogueData")
        if not dialogue or not getattr(dialogue, "is_quest_giver", False):
            continue

        identity = await game_state.get_component(entity_id, "IdentityData")
        name = identity.name if identity else entity_id

        # Get available static quests from this NPC
        available = await get_available_quests(player_id, entity_id, game_state)

        # Also check for dynamic quest generation
        can_generate = getattr(dialogue, "can_generate_quests", False)
        generated_quests = []

        if can_generate:
            try:
                from ..systems.quest_generation import get_generated_quests_for_player
                # Get zone from location
                zone_id = location.room_id.split("_")[0] if "_" in location.room_id else "unknown"
                generated_quests = await get_generated_quests_for_player(
                    player_id, entity_id, zone_id, game_state, max_quests=1
                )
            except ImportError:
                pass  # Quest generation not available
            except Exception:
                pass  # Generation failed, fall back to static

        # Combine static and generated quests
        all_quests = available + generated_quests

        if all_quests:
            quest_givers.append((name, entity_id, all_quests, can_generate))
        elif can_generate:
            # NPC can generate but none available right now
            quest_givers.append((name, entity_id, [], can_generate))

    if not quest_givers:
        return "There are no quest givers here with quests for you."

    lines = ["=== Quest Givers ===", ""]

    for name, npc_id, quests, can_generate in quest_givers:
        gen_indicator = " [Dynamic]" if can_generate else ""
        lines.append(f"{name}{gen_indicator}:")

        if quests:
            for definition, can_accept, reason in quests:
                status = ""
                if not can_accept:
                    status = f" ({reason})"
                # Mark generated quests
                quest_type = "[Generated]" if definition.quest_id.startswith("gen_") else ""
                lines.append(f"  - {definition.name} [{definition.rarity.value}]{quest_type}{status}")
        else:
            lines.append("  (Talk to request a quest)")

        lines.append("")

    lines.append("Talk to them to accept quests.")

    return "\n".join(lines)


@command(
    name="completed",
    aliases=["questhistory"],
    category=CommandCategory.INFO,
    help_text="View your completed quests.",
)
async def cmd_completed(player_id: str, args: str, game_state) -> str:
    """View completed quests."""
    from ..components.quests import QuestLogData, get_quest_definition

    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log or not quest_log.completed_quests:
        return "You haven't completed any quests yet."

    lines = [
        "=== Completed Quests ===",
        "",
    ]

    # Sort by completion date (most recent first)
    sorted_quests = sorted(
        quest_log.completed_quests.items(),
        key=lambda x: x[1],
        reverse=True
    )

    # Show most recent 20
    for quest_id, completed_at in sorted_quests[:20]:
        definition = get_quest_definition(quest_id)
        name = definition.name if definition else quest_id
        date_str = completed_at.strftime("%Y-%m-%d")
        lines.append(f"  {name} - {date_str}")

    if len(sorted_quests) > 20:
        lines.append(f"  ... and {len(sorted_quests) - 20} more")

    lines.append("")
    lines.append(f"Total completed: {len(quest_log.completed_quests)}")

    return "\n".join(lines)


@command(
    name="track",
    aliases=["trackquest"],
    category=CommandCategory.INFO,
    help_text="Set a quest as your tracked/primary quest.",
)
async def cmd_track_quest(player_id: str, args: str, game_state) -> str:
    """Track a quest for quick reference."""
    from ..components.quests import QuestLogData, get_quest_definition
    from ..components.preferences import PreferencesData

    if not args:
        # Show currently tracked
        prefs = await game_state.get_component(player_id, "PreferencesData")
        tracked = getattr(prefs, "tracked_quest", None) if prefs else None

        if tracked:
            definition = get_quest_definition(tracked)
            name = definition.name if definition else tracked
            return f"Currently tracking: {name}\nUse 'track <quest>' to change."
        return "No quest tracked. Use 'track <quest name>' to track one."

    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log:
        return "You have no quests."

    search = args.lower()

    # Find matching quest
    found_id = None
    found_name = None

    for quest_id in quest_log.active_quests:
        definition = get_quest_definition(quest_id)
        if not definition:
            continue

        if (search in definition.name.lower() or
            search in quest_id.lower()):
            found_id = quest_id
            found_name = definition.name
            break

    if not found_id:
        return f"No active quest matching '{args}'."

    # Save to preferences
    prefs = await game_state.get_component(player_id, "PreferencesData")
    if not prefs:
        prefs = PreferencesData()

    # Add tracked_quest attribute if needed
    prefs.tracked_quest = found_id
    await game_state.set_component(player_id, "PreferencesData", prefs)

    return f"Now tracking: {found_name}"
