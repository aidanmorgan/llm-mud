"""Group systems - experience sharing, following, and combat assist."""

from typing import Dict, List, Optional, Set

from core.system import System


class GroupExpShareSystem(System):
    """
    Handles experience distribution when a group member kills a mob.

    When a mob dies:
    1. Check if killer is in a group
    2. Get all group members in the same room or nearby
    3. Distribute experience according to group settings
    """

    priority = 45  # After death system (40), before respawn

    required_components = ["GroupMembershipData"]

    async def distribute_experience(
        self,
        killer_id: str,
        base_exp: int,
        room_id: str,
        game_state,
    ) -> Dict[str, int]:
        """
        Distribute experience to group members.

        Returns dict of entity_id -> exp_gained.
        """
        from ..components.group import GroupMembershipData, GroupData

        # Check if killer is in a group
        membership = await game_state.get_component(killer_id, "GroupMembershipData")
        if not membership or not membership.is_in_group:
            # Solo kill, full exp to killer
            return {killer_id: base_exp}

        # Get group data
        group = await game_state.get_component(membership.group_entity_id, "GroupData")
        if not group:
            return {killer_id: base_exp}

        # Get members in same room (or nearby for larger groups)
        eligible_members = []
        for member_id in group.member_ids:
            member_location = await game_state.get_component(member_id, "LocationData")
            if member_location and member_location.room_id == room_id:
                eligible_members.append(member_id)

        if len(eligible_members) <= 1:
            # Only killer in room, full exp
            return {killer_id: base_exp}

        # Apply group bonus (5% per extra member)
        group_bonus = 1.0 + (len(eligible_members) - 1) * 0.05
        total_exp = int(base_exp * group_bonus)

        # Calculate shares
        if hasattr(group, 'calculate_exp_shares'):
            shares = group.calculate_exp_shares(total_exp, killer_id)
        else:
            # Equal split fallback
            per_member = total_exp // len(eligible_members)
            shares = {mid: per_member for mid in eligible_members}

        # Filter to only eligible members
        shares = {mid: exp for mid, exp in shares.items() if mid in eligible_members}

        # Record group stats
        group.total_exp_earned += sum(shares.values())
        group.record_kill(killer_id)
        await game_state.set_component(membership.group_entity_id, "GroupData", group)

        # Update individual member stats
        for member_id, exp in shares.items():
            member = group.members.get(member_id)
            if member:
                member.exp_earned += exp

        return shares


class FollowSystem(System):
    """
    Handles automatic following when group leaders move.

    When a player moves:
    1. Check if they have followers
    2. Move all followers to the same room
    3. Notify followers of the movement
    """

    priority = 15  # After movement system (10)

    required_components = ["GroupMembershipData", "LocationData"]

    async def process_follow(
        self,
        leader_id: str,
        from_room: str,
        to_room: str,
        direction: str,
        game_state,
    ) -> List[str]:
        """
        Move followers along with leader.

        Returns list of follower IDs that moved.
        """
        from ..components.group import GroupMembershipData
        from ..components.spatial import LocationData
        from ..components.identity import IdentityData

        # Get leader's followers
        membership = await game_state.get_component(leader_id, "GroupMembershipData")
        if not membership or not membership.has_followers:
            return []

        leader_identity = await game_state.get_component(leader_id, "IdentityData")
        leader_name = leader_identity.name if leader_identity else "Someone"

        moved_followers = []

        for follower_id in list(membership.followers):
            # Verify follower is in the same room
            follower_loc = await game_state.get_component(follower_id, "LocationData")
            if not follower_loc or follower_loc.room_id != from_room:
                continue

            # Check follower is still following
            follower_membership = await game_state.get_component(
                follower_id, "GroupMembershipData"
            )
            if not follower_membership or follower_membership.following_id != leader_id:
                # Remove stale follower
                membership.remove_follower(follower_id)
                continue

            # Move follower
            follower_loc.room_id = to_room
            await game_state.set_component(follower_id, "LocationData", follower_loc)

            # Notify follower
            await game_state.send_message(
                follower_id,
                f"You follow {leader_name} {direction}."
            )

            moved_followers.append(follower_id)

        # Update leader's follower list if any were removed
        await game_state.set_component(leader_id, "GroupMembershipData", membership)

        return moved_followers


class GroupCombatSystem(System):
    """
    Handles group combat mechanics - assist and auto-attack.

    When a group member is attacked:
    1. Check if attacker is hostile
    2. Find group members in same room
    3. If assist is enabled, start combat for group members
    """

    priority = 22  # After combat initiation (20)

    required_components = ["GroupMembershipData", "CombatData"]

    async def check_assist(
        self,
        attacked_id: str,
        attacker_id: str,
        game_state,
    ) -> List[str]:
        """
        Check if group members should assist.

        Returns list of member IDs that started combat.
        """
        from ..components.group import GroupMembershipData, GroupData
        from ..components.spatial import LocationData
        from ..components.combat import CombatData

        # Check if victim is in a group
        membership = await game_state.get_component(attacked_id, "GroupMembershipData")
        if not membership or not membership.is_in_group:
            return []

        group = await game_state.get_component(membership.group_entity_id, "GroupData")
        if not group:
            return []

        # Get victim's location
        victim_loc = await game_state.get_component(attacked_id, "LocationData")
        if not victim_loc:
            return []

        assisted = []

        for member_id in group.member_ids:
            if member_id == attacked_id:
                continue

            # Check if in same room
            member_loc = await game_state.get_component(member_id, "LocationData")
            if not member_loc or member_loc.room_id != victim_loc.room_id:
                continue

            # Check if already in combat
            member_combat = await game_state.get_component(member_id, "CombatData")
            if member_combat and member_combat.target_id:
                continue

            # Start combat with attacker
            if not member_combat:
                member_combat = CombatData()

            member_combat.target_id = attacker_id
            member_combat.is_in_combat = True
            await game_state.set_component(member_id, "CombatData", member_combat)

            # Notify
            await game_state.send_message(
                member_id,
                "You rush to assist your group member!"
            )

            assisted.append(member_id)

        return assisted


class GroupInviteCleanupSystem(System):
    """
    Cleans up expired group invites.
    """

    priority = 99  # Run late

    required_components = ["GroupMembershipData"]

    async def process(self, entity_id: str, components: Dict) -> None:
        """Clean up expired invites."""
        from ..components.group import GroupMembershipData

        membership: GroupMembershipData = components["GroupMembershipData"]

        # Remove expired invites
        before = len(membership.pending_invites)
        membership.pending_invites = [
            i for i in membership.pending_invites if not i.is_expired
        ]

        # Only save if changed
        if len(membership.pending_invites) < before:
            # Would commit via WriteBuffer in real system
            pass


async def handle_mob_death_exp(
    killer_id: str,
    mob_id: str,
    base_exp: int,
    room_id: str,
    game_state,
) -> None:
    """
    Handle experience distribution when a mob dies.

    Called from DeathSystem when a mob is killed.
    """
    from ..components.stats import PlayerStatsData

    exp_system = GroupExpShareSystem()
    shares = await exp_system.distribute_experience(killer_id, base_exp, room_id, game_state)

    for player_id, exp in shares.items():
        # Award experience
        stats = await game_state.get_component(player_id, "PlayerStatsData")
        if stats:
            old_level = stats.level
            stats.experience += exp
            # Check for level up (simplified)
            exp_for_level = stats.level * 1000
            if stats.experience >= exp_for_level:
                stats.level += 1
                stats.experience -= exp_for_level
                await game_state.send_message(
                    player_id,
                    f"*** LEVEL UP! You are now level {stats.level}! ***"
                )
            await game_state.set_component(player_id, "PlayerStatsData", stats)

        # Notify
        if exp > 0:
            await game_state.send_message(player_id, f"You gain {exp} experience.")
