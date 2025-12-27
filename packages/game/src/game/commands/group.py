"""Group and party commands."""

import uuid
from typing import Optional

from ..commands.registry import command, CommandCategory


@command(
    name="group",
    aliases=["party", "grp"],
    category=CommandCategory.SOCIAL,
    help_text="Manage your group - invite players, check status, or leave.",
)
async def cmd_group(player_id: str, args: str, game_state) -> str:
    """Group management command."""
    from ..components.group import (
        GroupData,
        GroupMembershipData,
        GroupMember,
        GroupRole,
        GroupInvite,
        LootRule,
        ExpShareMode,
    )
    from ..components.identity import IdentityData

    membership = await game_state.get_component(player_id, "GroupMembershipData")
    if not membership:
        membership = GroupMembershipData()
        await game_state.set_component(player_id, "GroupMembershipData", membership)

    parts = args.lower().split() if args else []
    subcommand = parts[0] if parts else "status"

    # Get player name
    identity = await game_state.get_component(player_id, "IdentityData")
    player_name = identity.name if identity else "Unknown"

    if subcommand == "status" or subcommand == "":
        return await _group_status(player_id, membership, game_state)

    elif subcommand == "create":
        if membership.is_in_group:
            return "You are already in a group. Leave first with 'group leave'."

        group_name = " ".join(parts[1:]) if len(parts) > 1 else f"{player_name}'s Group"
        return await _create_group(player_id, player_name, group_name, game_state)

    elif subcommand == "invite":
        if len(parts) < 2:
            return "Usage: group invite <player>"

        target_name = parts[1]
        return await _invite_to_group(player_id, player_name, target_name, membership, game_state)

    elif subcommand == "accept":
        return await _accept_invite(player_id, player_name, membership, game_state)

    elif subcommand == "decline":
        return await _decline_invite(player_id, membership, game_state)

    elif subcommand == "leave" or subcommand == "quit":
        return await _leave_group(player_id, membership, game_state)

    elif subcommand == "kick":
        if len(parts) < 2:
            return "Usage: group kick <player>"
        return await _kick_from_group(player_id, parts[1], membership, game_state)

    elif subcommand == "promote":
        if len(parts) < 2:
            return "Usage: group promote <player>"
        return await _promote_member(player_id, parts[1], membership, game_state)

    elif subcommand == "demote":
        if len(parts) < 2:
            return "Usage: group demote <player>"
        return await _demote_member(player_id, parts[1], membership, game_state)

    elif subcommand == "leader":
        if len(parts) < 2:
            return "Usage: group leader <player>"
        return await _transfer_leadership(player_id, parts[1], membership, game_state)

    elif subcommand == "loot":
        if len(parts) < 2:
            return "Usage: group loot <freeforall|roundrobin|leader|needgreed>"
        return await _set_loot_rule(player_id, parts[1], membership, game_state)

    elif subcommand == "exp":
        if len(parts) < 2:
            return "Usage: group exp <equal|killer|level>"
        return await _set_exp_mode(player_id, parts[1], membership, game_state)

    elif subcommand == "disband":
        return await _disband_group(player_id, membership, game_state)

    else:
        # Assume it's a player name to invite
        return await _invite_to_group(player_id, player_name, subcommand, membership, game_state)


async def _group_status(player_id: str, membership, game_state) -> str:
    """Show current group status."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        if membership.pending_invites:
            invite = membership.get_latest_invite()
            if invite:
                return (
                    f"You are not in a group.\n"
                    f"You have a pending invite from {invite.from_name}.\n"
                    f"Use 'group accept' to join or 'group decline' to refuse."
                )
        return "You are not in a group. Use 'group create' or 'group <player>' to start one."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group:
        membership.leave_group()
        return "Your group no longer exists."

    lines = [
        f"=== {group.name or 'Your Group'} ===",
        f"Members: {group.member_count}/{group.max_members}",
        f"Loot: {group.loot_rule.value.replace('_', ' ').title()}",
        f"Exp: {group.exp_share_mode.value.replace('_', ' ').title()}",
        "",
        "Members:",
    ]

    for member in group.members.values():
        role_str = f" [{member.role.value}]" if member.role.value != "member" else ""
        lines.append(f"  {member.name}{role_str}")

    if group.total_kills > 0:
        lines.extend([
            "",
            f"Group Stats: {group.total_kills} kills, {group.total_exp_earned} exp earned",
        ])

    return "\n".join(lines)


async def _create_group(player_id: str, player_name: str, group_name: str, game_state) -> str:
    """Create a new group."""
    from ..components.group import GroupData, GroupMember, GroupRole, GroupMembershipData

    group_id = str(uuid.uuid4())[:8]
    group_entity_id = f"group_{group_id}"

    # Create group data
    group = GroupData(
        group_id=group_id,
        name=group_name,
        leader_id=player_id,
    )
    group.add_member(player_id, player_name, GroupRole.LEADER)

    await game_state.set_component(group_entity_id, "GroupData", group)

    # Update player membership
    membership = await game_state.get_component(player_id, "GroupMembershipData")
    if not membership:
        membership = GroupMembershipData()
    membership.join_group(group_id, group_entity_id)
    membership.groups_led += 1
    await game_state.set_component(player_id, "GroupMembershipData", membership)

    return f"You have created the group '{group_name}'."


async def _invite_to_group(
    player_id: str, player_name: str, target_name: str, membership, game_state
) -> str:
    """Invite a player to join your group."""
    from ..components.group import GroupData, GroupInvite, GroupMembershipData

    # Find target player
    target_id = await game_state.find_player_by_name(target_name)
    if not target_id:
        return f"Cannot find player '{target_name}'."

    if target_id == player_id:
        return "You cannot invite yourself."

    # Check if we have a group
    if not membership.is_in_group:
        # Create a new group
        group_id = str(uuid.uuid4())[:8]
        group_entity_id = f"group_{group_id}"

        from ..components.group import GroupData, GroupMember, GroupRole
        group = GroupData(
            group_id=group_id,
            name=f"{player_name}'s Group",
            leader_id=player_id,
        )
        group.add_member(player_id, player_name, GroupRole.LEADER)
        await game_state.set_component(group_entity_id, "GroupData", group)

        membership.join_group(group_id, group_entity_id)
        membership.groups_led += 1
        await game_state.set_component(player_id, "GroupMembershipData", membership)
    else:
        group = await game_state.get_component(membership.group_entity_id, "GroupData")
        if not group:
            return "Your group no longer exists."

        if not group.is_officer(player_id):
            return "Only the leader or officers can invite players."

        if group.is_full:
            return "Your group is full."

    # Check target's membership
    target_membership = await game_state.get_component(target_id, "GroupMembershipData")
    if not target_membership:
        target_membership = GroupMembershipData()

    if target_membership.is_in_group:
        return f"{target_name} is already in a group."

    if not target_membership.accept_invites:
        return f"{target_name} is not accepting group invitations."

    # Send invite
    invite = GroupInvite(
        from_entity_id=player_id,
        from_name=player_name,
        group_id=membership.group_id,
    )
    target_membership.add_invite(invite)
    await game_state.set_component(target_id, "GroupMembershipData", target_membership)

    # Notify target (would use event system)
    await game_state.send_message(
        target_id,
        f"{player_name} has invited you to join their group. Use 'group accept' or 'group decline'."
    )

    return f"You have invited {target_name} to join your group."


async def _accept_invite(player_id: str, player_name: str, membership, game_state) -> str:
    """Accept a group invitation."""
    from ..components.group import GroupData, GroupMember, GroupRole

    invite = membership.get_latest_invite()
    if not invite:
        return "You have no pending group invitations."

    # Find the group
    group_entity_id = f"group_{invite.group_id}"
    group = await game_state.get_component(group_entity_id, "GroupData")

    if not group:
        membership.remove_invite(invite.group_id)
        await game_state.set_component(player_id, "GroupMembershipData", membership)
        return "That group no longer exists."

    if group.is_full:
        membership.remove_invite(invite.group_id)
        await game_state.set_component(player_id, "GroupMembershipData", membership)
        return "That group is now full."

    # Join the group
    group.add_member(player_id, player_name, GroupRole.MEMBER)
    await game_state.set_component(group_entity_id, "GroupData", group)

    membership.join_group(invite.group_id, group_entity_id)
    await game_state.set_component(player_id, "GroupMembershipData", membership)

    # Notify group members
    for member_id in group.member_ids:
        if member_id != player_id:
            await game_state.send_message(member_id, f"{player_name} has joined the group.")

    return f"You have joined {invite.from_name}'s group."


async def _decline_invite(player_id: str, membership, game_state) -> str:
    """Decline a group invitation."""
    invite = membership.get_latest_invite()
    if not invite:
        return "You have no pending group invitations."

    membership.remove_invite(invite.group_id)
    await game_state.set_component(player_id, "GroupMembershipData", membership)

    # Notify inviter
    await game_state.send_message(
        invite.from_entity_id,
        f"Your group invitation was declined."
    )

    return "You have declined the group invitation."


async def _leave_group(player_id: str, membership, game_state) -> str:
    """Leave the current group."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group:
        membership.leave_group()
        await game_state.set_component(player_id, "GroupMembershipData", membership)
        return "You have left the group."

    # Get player name for notifications
    identity = await game_state.get_component(player_id, "IdentityData")
    player_name = identity.name if identity else "Someone"

    # Remove from group
    was_leader = group.is_leader(player_id)
    group.remove_member(player_id)

    # If group is empty, delete it
    if group.member_count == 0:
        await game_state.remove_component(membership.group_entity_id, "GroupData")
    else:
        await game_state.set_component(membership.group_entity_id, "GroupData", group)
        # Notify remaining members
        for member_id in group.member_ids:
            msg = f"{player_name} has left the group."
            if was_leader:
                new_leader = group.members.get(group.leader_id)
                if new_leader:
                    msg += f" {new_leader.name} is now the leader."
            await game_state.send_message(member_id, msg)

    membership.leave_group()
    await game_state.set_component(player_id, "GroupMembershipData", membership)

    return "You have left the group."


async def _kick_from_group(player_id: str, target_name: str, membership, game_state) -> str:
    """Kick a player from the group."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group:
        return "Your group no longer exists."

    if not group.is_officer(player_id):
        return "Only the leader or officers can kick players."

    # Find target in group
    target_id = None
    for mid, member in group.members.items():
        if member.name.lower() == target_name.lower():
            target_id = mid
            break

    if not target_id:
        return f"{target_name} is not in your group."

    if target_id == player_id:
        return "You cannot kick yourself. Use 'group leave' instead."

    if group.is_leader(target_id):
        return "You cannot kick the leader."

    # Kick them
    kicked_name = group.members[target_id].name
    group.remove_member(target_id)
    await game_state.set_component(membership.group_entity_id, "GroupData", group)

    # Update target's membership
    target_membership = await game_state.get_component(target_id, "GroupMembershipData")
    if target_membership:
        target_membership.leave_group()
        await game_state.set_component(target_id, "GroupMembershipData", target_membership)

    # Notify
    await game_state.send_message(target_id, "You have been kicked from the group.")
    for member_id in group.member_ids:
        await game_state.send_message(member_id, f"{kicked_name} has been kicked from the group.")

    return f"You have kicked {kicked_name} from the group."


async def _promote_member(player_id: str, target_name: str, membership, game_state) -> str:
    """Promote a member to officer."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or not group.is_leader(player_id):
        return "Only the leader can promote members."

    # Find target
    target_id = None
    for mid, member in group.members.items():
        if member.name.lower() == target_name.lower():
            target_id = mid
            break

    if not target_id:
        return f"{target_name} is not in your group."

    if group.promote(target_id):
        await game_state.set_component(membership.group_entity_id, "GroupData", group)
        return f"{target_name} has been promoted to officer."
    return f"{target_name} cannot be promoted."


async def _demote_member(player_id: str, target_name: str, membership, game_state) -> str:
    """Demote an officer to member."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or not group.is_leader(player_id):
        return "Only the leader can demote officers."

    # Find target
    target_id = None
    for mid, member in group.members.items():
        if member.name.lower() == target_name.lower():
            target_id = mid
            break

    if not target_id:
        return f"{target_name} is not in your group."

    if group.demote(target_id):
        await game_state.set_component(membership.group_entity_id, "GroupData", group)
        return f"{target_name} has been demoted to member."
    return f"{target_name} cannot be demoted."


async def _transfer_leadership(player_id: str, target_name: str, membership, game_state) -> str:
    """Transfer leadership to another member."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or not group.is_leader(player_id):
        return "Only the leader can transfer leadership."

    # Find target
    target_id = None
    for mid, member in group.members.items():
        if member.name.lower() == target_name.lower():
            target_id = mid
            break

    if not target_id:
        return f"{target_name} is not in your group."

    if group.transfer_leadership(target_id):
        await game_state.set_component(membership.group_entity_id, "GroupData", group)

        # Notify group
        for member_id in group.member_ids:
            await game_state.send_message(
                member_id, f"{target_name} is now the group leader."
            )

        return f"You have transferred leadership to {target_name}."
    return f"Cannot transfer leadership to {target_name}."


async def _set_loot_rule(player_id: str, rule_str: str, membership, game_state) -> str:
    """Set the group's loot distribution rule."""
    from ..components.group import GroupData, LootRule

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or not group.is_leader(player_id):
        return "Only the leader can change loot rules."

    rule_map = {
        "freeforall": LootRule.FREE_FOR_ALL,
        "free": LootRule.FREE_FOR_ALL,
        "roundrobin": LootRule.ROUND_ROBIN,
        "robin": LootRule.ROUND_ROBIN,
        "leader": LootRule.LEADER_ASSIGNS,
        "assign": LootRule.LEADER_ASSIGNS,
        "needgreed": LootRule.NEED_GREED,
        "need": LootRule.NEED_GREED,
    }

    rule = rule_map.get(rule_str.lower())
    if not rule:
        return "Valid loot rules: freeforall, roundrobin, leader, needgreed"

    group.loot_rule = rule
    await game_state.set_component(membership.group_entity_id, "GroupData", group)

    return f"Loot rule set to: {rule.value.replace('_', ' ').title()}"


async def _set_exp_mode(player_id: str, mode_str: str, membership, game_state) -> str:
    """Set the group's experience sharing mode."""
    from ..components.group import GroupData, ExpShareMode

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or not group.is_leader(player_id):
        return "Only the leader can change exp sharing."

    mode_map = {
        "equal": ExpShareMode.EQUAL,
        "split": ExpShareMode.EQUAL,
        "killer": ExpShareMode.KILLER_BONUS,
        "bonus": ExpShareMode.KILLER_BONUS,
        "level": ExpShareMode.LEVEL_WEIGHTED,
        "weighted": ExpShareMode.LEVEL_WEIGHTED,
    }

    mode = mode_map.get(mode_str.lower())
    if not mode:
        return "Valid exp modes: equal, killer, level"

    group.exp_share_mode = mode
    await game_state.set_component(membership.group_entity_id, "GroupData", group)

    return f"Exp sharing set to: {mode.value.replace('_', ' ').title()}"


async def _disband_group(player_id: str, membership, game_state) -> str:
    """Disband the entire group."""
    from ..components.group import GroupData

    if not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or not group.is_leader(player_id):
        return "Only the leader can disband the group."

    # Notify and update all members
    for member_id in group.member_ids:
        member_membership = await game_state.get_component(member_id, "GroupMembershipData")
        if member_membership:
            member_membership.leave_group()
            await game_state.set_component(member_id, "GroupMembershipData", member_membership)
        await game_state.send_message(member_id, "Your group has been disbanded.")

    # Delete group
    await game_state.remove_component(membership.group_entity_id, "GroupData")

    return "You have disbanded the group."


@command(
    name="follow",
    aliases=["fol"],
    category=CommandCategory.MOVEMENT,
    help_text="Start following another player.",
)
async def cmd_follow(player_id: str, args: str, game_state) -> str:
    """Follow another player."""
    from ..components.group import GroupMembershipData
    from ..components.spatial import LocationData

    if not args:
        return "Follow whom? Usage: follow <player>"

    target_name = args.split()[0]

    # Find target in same room
    location = await game_state.get_component(player_id, "LocationData")
    if not location:
        return "You don't seem to be anywhere."

    target_id = await game_state.find_entity_in_room(location.room_id, target_name)
    if not target_id:
        return f"You don't see '{target_name}' here."

    if target_id == player_id:
        return "You cannot follow yourself."

    # Check if target accepts followers
    target_membership = await game_state.get_component(target_id, "GroupMembershipData")
    if target_membership and not target_membership.accept_followers:
        return "That player is not accepting followers."

    # Update our membership
    membership = await game_state.get_component(player_id, "GroupMembershipData")
    if not membership:
        membership = GroupMembershipData()

    # Stop following old target
    if membership.is_following:
        old_target_membership = await game_state.get_component(
            membership.following_id, "GroupMembershipData"
        )
        if old_target_membership:
            old_target_membership.remove_follower(player_id)
            await game_state.set_component(
                membership.following_id, "GroupMembershipData", old_target_membership
            )

    # Start following new target
    membership.start_following(target_id)
    await game_state.set_component(player_id, "GroupMembershipData", membership)

    # Add us to target's followers
    if not target_membership:
        target_membership = GroupMembershipData()
    target_membership.add_follower(player_id)
    await game_state.set_component(target_id, "GroupMembershipData", target_membership)

    # Get names
    target_identity = await game_state.get_component(target_id, "IdentityData")
    target_display = target_identity.name if target_identity else "them"

    player_identity = await game_state.get_component(player_id, "IdentityData")
    player_display = player_identity.name if player_identity else "Someone"

    # Notify target
    await game_state.send_message(target_id, f"{player_display} is now following you.")

    return f"You are now following {target_display}."


@command(
    name="unfollow",
    aliases=["nofollow", "stopfollow"],
    category=CommandCategory.MOVEMENT,
    help_text="Stop following another player.",
)
async def cmd_unfollow(player_id: str, args: str, game_state) -> str:
    """Stop following."""
    from ..components.group import GroupMembershipData

    membership = await game_state.get_component(player_id, "GroupMembershipData")
    if not membership or not membership.is_following:
        return "You are not following anyone."

    # Get target info for message
    target_identity = await game_state.get_component(membership.following_id, "IdentityData")
    target_name = target_identity.name if target_identity else "them"

    # Remove from target's followers
    target_membership = await game_state.get_component(
        membership.following_id, "GroupMembershipData"
    )
    if target_membership:
        target_membership.remove_follower(player_id)
        await game_state.set_component(
            membership.following_id, "GroupMembershipData", target_membership
        )

    # Stop following
    membership.stop_following()
    await game_state.set_component(player_id, "GroupMembershipData", membership)

    return f"You stop following {target_name}."


@command(
    name="gtell",
    aliases=["gt", "groupsay"],
    category=CommandCategory.COMMUNICATION,
    help_text="Send a message to your group.",
)
async def cmd_gtell(player_id: str, args: str, game_state) -> str:
    """Send a message to the group."""
    from ..components.group import GroupMembershipData, GroupData

    if not args:
        return "What do you want to tell your group?"

    membership = await game_state.get_component(player_id, "GroupMembershipData")
    if not membership or not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group:
        return "Your group no longer exists."

    # Get sender name
    identity = await game_state.get_component(player_id, "IdentityData")
    sender_name = identity.name if identity else "Someone"

    # Send to all group members
    for member_id in group.member_ids:
        if member_id == player_id:
            await game_state.send_message(player_id, f"[Group] You: {args}")
        else:
            await game_state.send_message(member_id, f"[Group] {sender_name}: {args}")

    return ""  # Message already sent


@command(
    name="split",
    aliases=["divide"],
    category=CommandCategory.OBJECT,
    help_text="Split gold with your group.",
)
async def cmd_split(player_id: str, args: str, game_state) -> str:
    """Split gold with group members."""
    from ..components.group import GroupMembershipData, GroupData
    from ..components.inventory import ContainerData

    if not args:
        return "Split how much gold? Usage: split <amount>"

    try:
        amount = int(args.split()[0])
    except ValueError:
        return "That's not a valid amount."

    if amount <= 0:
        return "You must split a positive amount."

    membership = await game_state.get_component(player_id, "GroupMembershipData")
    if not membership or not membership.is_in_group:
        return "You are not in a group."

    group = await game_state.get_component(membership.group_entity_id, "GroupData")
    if not group or group.member_count < 2:
        return "You need at least 2 group members to split gold."

    # Check if player has enough gold
    inventory = await game_state.get_component(player_id, "ContainerData")
    if not inventory or inventory.gold < amount:
        return "You don't have that much gold."

    # Calculate split
    per_member = amount // group.member_count
    if per_member <= 0:
        return "That's not enough gold to split meaningfully."

    remainder = amount - (per_member * group.member_count)

    # Deduct from splitter
    inventory.gold -= amount
    # Splitter gets their share plus remainder
    inventory.gold += per_member + remainder
    await game_state.set_component(player_id, "ContainerData", inventory)

    # Get splitter name
    identity = await game_state.get_component(player_id, "IdentityData")
    splitter_name = identity.name if identity else "Someone"

    # Give to each member
    for member_id in group.member_ids:
        if member_id == player_id:
            continue

        member_inv = await game_state.get_component(member_id, "ContainerData")
        if not member_inv:
            from ..components.inventory import ContainerData
            member_inv = ContainerData()

        member_inv.gold += per_member
        await game_state.set_component(member_id, "ContainerData", member_inv)
        await game_state.send_message(
            member_id,
            f"{splitter_name} splits {amount} gold. You receive {per_member} gold."
        )

    group.total_gold_earned += amount
    await game_state.set_component(membership.group_entity_id, "GroupData", group)

    return f"You split {amount} gold. Each member receives {per_member} gold."
