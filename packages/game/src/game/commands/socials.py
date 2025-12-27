"""Social commands - emotes, profiles, and social features."""

from typing import Optional

from ..commands.registry import command, CommandCategory
from ..components.group import SOCIAL_EMOTES, get_social_emote


@command(
    name="socials",
    aliases=["emotes"],
    category=CommandCategory.SOCIAL,
    help_text="List available social commands/emotes.",
)
async def cmd_socials(player_id: str, args: str, game_state) -> str:
    """List all available social emotes."""
    emote_names = sorted(SOCIAL_EMOTES.keys())

    lines = [
        "=== Available Socials ===",
        "",
        "Use these commands alone or with a target: <social> [target]",
        "",
    ]

    # Display in columns
    per_row = 5
    for i in range(0, len(emote_names), per_row):
        row = emote_names[i:i + per_row]
        lines.append("  " + "  ".join(f"{e:12}" for e in row))

    lines.append("")
    lines.append(f"Total: {len(emote_names)} socials available.")

    return "\n".join(lines)


# Register all standard social emotes as commands
async def _handle_social(
    social_name: str,
    player_id: str,
    args: str,
    game_state
) -> str:
    """Generic handler for social emotes."""
    from ..components.identity import IdentityData
    from ..components.spatial import LocationData
    from ..components.group import SocialData

    # Get player name
    identity = await game_state.get_component(player_id, "IdentityData")
    actor_name = identity.name if identity else "Someone"

    # Get location for broadcasting
    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    target_id = None
    target_name = None
    is_self = False

    if args:
        target_keyword = args.split()[0].lower()

        # Check for self-targeting
        if target_keyword in ["self", "me", "myself"]:
            is_self = True
            target_name = actor_name
        else:
            # Find target in room
            target_id = await game_state.find_entity_in_room(location.room_id, target_keyword)
            if target_id:
                if target_id == player_id:
                    is_self = True
                    target_name = actor_name
                else:
                    target_identity = await game_state.get_component(target_id, "IdentityData")
                    target_name = target_identity.name if target_identity else "someone"
            else:
                return f"You don't see '{target_keyword}' here."

    # Get the social messages
    messages = get_social_emote(social_name, actor_name, target_name, is_self)

    if not messages:
        return f"Unknown social: {social_name}"

    # Update social stats
    social_data = await game_state.get_component(player_id, "SocialData")
    if social_data:
        social_data.emotes_used += 1
        await game_state.set_component(player_id, "SocialData", social_data)

    # Send to target if applicable
    if target_id and target_id != player_id and "target_msg" in messages:
        await game_state.send_message(target_id, messages["target_msg"])

    # Broadcast to room (excluding actor and target)
    if "others_msg" in messages:
        await game_state.broadcast_to_room(
            location.room_id,
            messages["others_msg"],
            exclude=[player_id, target_id] if target_id else [player_id]
        )

    return messages.get("actor_msg", "")


# Register each social emote as a command
for social_name in SOCIAL_EMOTES.keys():
    # Create a closure to capture social_name properly
    def make_handler(name):
        async def handler(player_id: str, args: str, game_state) -> str:
            return await _handle_social(name, player_id, args, game_state)
        return handler

    command(
        name=social_name,
        category=CommandCategory.SOCIAL,
        help_text=f"Social emote: {social_name}",
    )(make_handler(social_name))


@command(
    name="finger",
    aliases=["whois", "profile"],
    category=CommandCategory.INFO,
    help_text="View information about a player.",
)
async def cmd_finger(player_id: str, args: str, game_state) -> str:
    """View player profile information."""
    from ..components.identity import IdentityData
    from ..components.stats import PlayerStatsData
    from ..components.player import PlayerProgressData, PlayerConnectionData
    from ..components.group import SocialData, GroupMembershipData
    from ..components.character import ClassData, RaceData

    if not args:
        # Show own profile
        target_id = player_id
    else:
        target_name = args.split()[0]
        target_id = await game_state.find_player_by_name(target_name)
        if not target_id:
            return f"No player named '{target_name}' found."

    # Gather info
    identity = await game_state.get_component(target_id, "IdentityData")
    stats = await game_state.get_component(target_id, "PlayerStatsData")
    progress = await game_state.get_component(target_id, "PlayerProgressData")
    connection = await game_state.get_component(target_id, "PlayerConnectionData")
    social = await game_state.get_component(target_id, "SocialData")
    membership = await game_state.get_component(target_id, "GroupMembershipData")
    class_data = await game_state.get_component(target_id, "ClassData")
    race_data = await game_state.get_component(target_id, "RaceData")

    if not identity:
        return "Cannot find information about that player."

    # Check if hidden
    if social and social.hidden and target_id != player_id:
        return f"{identity.name} prefers to keep a low profile."

    # Build display
    name = identity.name
    if social:
        name = social.get_display_name(identity.name)

    lines = [
        f"=== {name} ===",
        "",
    ]

    # Basic info
    if race_data and class_data:
        lines.append(f"A level {stats.level if stats else 1} {race_data.race_id} {class_data.class_id}")

    # Title/bio
    if social:
        if social.title:
            lines.append(f"Title: {social.title}")
        if social.bio:
            lines.append("")
            lines.append(social.bio)
            lines.append("")

    # Stats (if visible)
    if progress:
        lines.extend([
            f"Kills: {progress.total_kills}  Deaths: {progress.total_deaths}",
            f"Areas Explored: {len(progress.discovered_areas)}",
            f"Achievements: {len(progress.achievements)} ({progress.achievement_points} points)",
        ])

    # Play time
    if progress:
        lines.append(f"Play Time: {progress.get_play_time_formatted()}")

    # Online status
    if connection:
        if connection.is_connected:
            if social and social.is_afk:
                lines.append(f"Status: AFK - {social.afk_message}")
            else:
                idle_mins = int(connection.idle_seconds / 60)
                if idle_mins > 0:
                    lines.append(f"Status: Online (idle {idle_mins}m)")
                else:
                    lines.append("Status: Online")
        elif connection.is_linkdead:
            lines.append("Status: Link-dead")
        else:
            lines.append("Status: Offline")

    # Group
    if membership and membership.is_in_group:
        group = await game_state.get_component(membership.group_entity_id, "GroupData")
        if group:
            lines.append(f"Group: {group.name or 'Unnamed'}")

    return "\n".join(lines)


@command(
    name="bio",
    aliases=["biography", "describe"],
    category=CommandCategory.SOCIAL,
    help_text="Set your character biography/description.",
)
async def cmd_bio(player_id: str, args: str, game_state) -> str:
    """Set character biography."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    if not args:
        if social.bio:
            return f"Your current bio:\n{social.bio}\n\nUse 'bio clear' to remove or 'bio <text>' to set."
        return "You haven't set a bio. Use 'bio <text>' to set one."

    if args.lower() == "clear":
        social.bio = ""
        await game_state.set_component(player_id, "SocialData", social)
        return "Your bio has been cleared."

    # Limit bio length
    if len(args) > 500:
        return "Your bio is too long. Maximum 500 characters."

    social.bio = args
    await game_state.set_component(player_id, "SocialData", social)

    return "Your bio has been updated."


@command(
    name="title",
    aliases=["settitle"],
    category=CommandCategory.SOCIAL,
    help_text="Set your character title (shown after name).",
)
async def cmd_title(player_id: str, args: str, game_state) -> str:
    """Set character title."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    if not args:
        if social.title:
            return f"Your current title: {social.title}\nUse 'title clear' to remove."
        return "You haven't set a title. Use 'title <text>' to set one."

    if args.lower() == "clear":
        social.title = ""
        await game_state.set_component(player_id, "SocialData", social)
        return "Your title has been cleared."

    # Limit title length
    if len(args) > 50:
        return "Your title is too long. Maximum 50 characters."

    social.title = args
    await game_state.set_component(player_id, "SocialData", social)

    identity = await game_state.get_component(player_id, "IdentityData")
    name = identity.name if identity else "You"

    return f"Your title is now: {name} {args}"


@command(
    name="afk",
    aliases=["away"],
    category=CommandCategory.SOCIAL,
    help_text="Mark yourself as away from keyboard.",
)
async def cmd_afk(player_id: str, args: str, game_state) -> str:
    """Toggle AFK status."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    if social.is_afk:
        social.clear_afk()
        await game_state.set_component(player_id, "SocialData", social)
        return "You are no longer AFK."

    message = args if args else "Away from keyboard"
    social.set_afk(message)
    await game_state.set_component(player_id, "SocialData", social)

    return f"You are now AFK: {message}"


@command(
    name="friend",
    aliases=["friends"],
    category=CommandCategory.SOCIAL,
    help_text="Manage your friends list.",
)
async def cmd_friend(player_id: str, args: str, game_state) -> str:
    """Manage friends list."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    parts = args.lower().split() if args else []
    subcommand = parts[0] if parts else "list"

    if subcommand == "list" or not parts:
        if not social.friends:
            return "Your friends list is empty."
        lines = ["=== Friends List ===", ""]
        for friend in sorted(social.friends):
            # Check if online
            friend_id = await game_state.find_player_by_name(friend)
            if friend_id:
                conn = await game_state.get_component(friend_id, "PlayerConnectionData")
                status = "Online" if conn and conn.is_connected else "Offline"
            else:
                status = "Unknown"
            lines.append(f"  {friend.title()} [{status}]")
        return "\n".join(lines)

    elif subcommand == "add":
        if len(parts) < 2:
            return "Usage: friend add <name>"
        name = parts[1]
        if social.add_friend(name):
            await game_state.set_component(player_id, "SocialData", social)
            return f"{name.title()} has been added to your friends list."
        return f"{name.title()} is already on your friends list."

    elif subcommand in ["remove", "del", "delete"]:
        if len(parts) < 2:
            return "Usage: friend remove <name>"
        name = parts[1]
        if social.remove_friend(name):
            await game_state.set_component(player_id, "SocialData", social)
            return f"{name.title()} has been removed from your friends list."
        return f"{name.title()} is not on your friends list."

    else:
        # Assume it's a name to add
        if social.add_friend(subcommand):
            await game_state.set_component(player_id, "SocialData", social)
            return f"{subcommand.title()} has been added to your friends list."
        return f"{subcommand.title()} is already on your friends list."


@command(
    name="ignore",
    aliases=["block"],
    category=CommandCategory.SOCIAL,
    help_text="Ignore a player (block their messages).",
)
async def cmd_ignore(player_id: str, args: str, game_state) -> str:
    """Manage ignore list."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    parts = args.lower().split() if args else []
    subcommand = parts[0] if parts else "list"

    if subcommand == "list" or not parts:
        if not social.ignored:
            return "Your ignore list is empty."
        lines = ["=== Ignored Players ===", ""]
        for name in sorted(social.ignored):
            lines.append(f"  {name.title()}")
        lines.append("")
        lines.append("Use 'unignore <name>' to remove someone from this list.")
        return "\n".join(lines)

    else:
        name = subcommand
        if social.ignore(name):
            await game_state.set_component(player_id, "SocialData", social)
            return f"You are now ignoring {name.title()}."
        return f"You are already ignoring {name.title()}."


@command(
    name="unignore",
    aliases=["unblock"],
    category=CommandCategory.SOCIAL,
    help_text="Stop ignoring a player.",
)
async def cmd_unignore(player_id: str, args: str, game_state) -> str:
    """Remove from ignore list."""
    from ..components.group import SocialData

    if not args:
        return "Unignore whom? Usage: unignore <name>"

    name = args.split()[0].lower()

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        return f"You weren't ignoring {name.title()}."

    if social.unignore(name):
        await game_state.set_component(player_id, "SocialData", social)
        return f"You are no longer ignoring {name.title()}."

    return f"You weren't ignoring {name.title()}."


@command(
    name="notell",
    aliases=["dnd"],
    category=CommandCategory.SOCIAL,
    help_text="Toggle 'do not disturb' mode (block tells from non-friends).",
)
async def cmd_notell(player_id: str, args: str, game_state) -> str:
    """Toggle no-tell mode."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    social.no_tell = not social.no_tell
    await game_state.set_component(player_id, "SocialData", social)

    if social.no_tell:
        return "You are now only accepting tells from friends."
    return "You are now accepting tells from everyone."


@command(
    name="hide",
    aliases=["hidden"],
    category=CommandCategory.SOCIAL,
    help_text="Toggle hidden mode (don't appear on 'who' list).",
)
async def cmd_hide(player_id: str, args: str, game_state) -> str:
    """Toggle hidden mode."""
    from ..components.group import SocialData

    social = await game_state.get_component(player_id, "SocialData")
    if not social:
        social = SocialData()

    social.hidden = not social.hidden
    await game_state.set_component(player_id, "SocialData", social)

    if social.hidden:
        return "You are now hidden from the 'who' list."
    return "You are now visible on the 'who' list."
