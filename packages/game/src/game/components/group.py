"""
Group and Social Components

Define group membership, following, and social features.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set

from core import ComponentData


class GroupRole(str, Enum):
    """Role within a group."""

    LEADER = "leader"
    OFFICER = "officer"  # Can invite
    MEMBER = "member"


class LootRule(str, Enum):
    """How loot is distributed in the group."""

    FREE_FOR_ALL = "free_for_all"
    ROUND_ROBIN = "round_robin"
    LEADER_ASSIGNS = "leader_assigns"
    NEED_GREED = "need_greed"


class ExpShareMode(str, Enum):
    """How experience is shared in the group."""

    EQUAL = "equal"  # Split equally
    LEVEL_WEIGHTED = "level_weighted"  # Higher levels get more
    KILLER_BONUS = "killer_bonus"  # Killer gets 50%, rest split


@dataclass
class GroupMember:
    """Information about a group member."""

    entity_id: str
    name: str
    role: GroupRole = GroupRole.MEMBER
    joined_at: datetime = field(default_factory=datetime.utcnow)
    exp_earned: int = 0  # Exp earned while in group
    kills: int = 0  # Kills while in group


@dataclass
class GroupInvite:
    """A pending group invitation."""

    from_entity_id: str
    from_name: str
    group_id: str
    invited_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow())

    def __post_init__(self):
        """Set expiration time if not set."""
        from datetime import timedelta

        if self.expires_at <= self.invited_at:
            self.expires_at = self.invited_at + timedelta(minutes=5)

    @property
    def is_expired(self) -> bool:
        """Check if invitation has expired."""
        return datetime.utcnow() > self.expires_at


@dataclass
class GroupData(ComponentData):
    """
    Group membership and settings.

    Applied to the group entity itself, not individual members.
    """

    group_id: str = ""
    name: str = ""  # Optional group name
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Members
    leader_id: str = ""
    members: Dict[str, GroupMember] = field(default_factory=dict)  # entity_id -> member

    # Settings
    max_members: int = 6
    loot_rule: LootRule = LootRule.FREE_FOR_ALL
    exp_share_mode: ExpShareMode = ExpShareMode.EQUAL
    is_open: bool = False  # Anyone can join without invite

    # Statistics
    total_exp_earned: int = 0
    total_gold_earned: int = 0
    total_kills: int = 0

    # Round robin state
    loot_turn_index: int = 0

    @property
    def member_count(self) -> int:
        """Number of members in group."""
        return len(self.members)

    @property
    def is_full(self) -> bool:
        """Check if group is full."""
        return self.member_count >= self.max_members

    @property
    def member_ids(self) -> List[str]:
        """Get list of member entity IDs."""
        return list(self.members.keys())

    def is_member(self, entity_id: str) -> bool:
        """Check if entity is in this group."""
        return entity_id in self.members

    def is_leader(self, entity_id: str) -> bool:
        """Check if entity is the group leader."""
        return entity_id == self.leader_id

    def is_officer(self, entity_id: str) -> bool:
        """Check if entity is an officer or leader."""
        if entity_id not in self.members:
            return False
        return self.members[entity_id].role in [GroupRole.LEADER, GroupRole.OFFICER]

    def add_member(
        self, entity_id: str, name: str, role: GroupRole = GroupRole.MEMBER
    ) -> bool:
        """Add a member to the group."""
        if self.is_full or entity_id in self.members:
            return False

        self.members[entity_id] = GroupMember(
            entity_id=entity_id,
            name=name,
            role=role,
        )
        return True

    def remove_member(self, entity_id: str) -> bool:
        """Remove a member from the group."""
        if entity_id not in self.members:
            return False

        del self.members[entity_id]

        # If leader left, promote someone else
        if entity_id == self.leader_id and self.members:
            # Find an officer first, then any member
            new_leader = None
            for member in self.members.values():
                if member.role == GroupRole.OFFICER:
                    new_leader = member.entity_id
                    break
            if not new_leader:
                new_leader = next(iter(self.members.keys()))

            self.leader_id = new_leader
            self.members[new_leader].role = GroupRole.LEADER

        return True

    def promote(self, entity_id: str) -> bool:
        """Promote a member to officer."""
        if entity_id not in self.members:
            return False
        if self.members[entity_id].role == GroupRole.LEADER:
            return False

        self.members[entity_id].role = GroupRole.OFFICER
        return True

    def demote(self, entity_id: str) -> bool:
        """Demote an officer to member."""
        if entity_id not in self.members:
            return False
        if self.members[entity_id].role != GroupRole.OFFICER:
            return False

        self.members[entity_id].role = GroupRole.MEMBER
        return True

    def transfer_leadership(self, new_leader_id: str) -> bool:
        """Transfer leadership to another member."""
        if new_leader_id not in self.members:
            return False
        if new_leader_id == self.leader_id:
            return False

        # Demote old leader to officer
        if self.leader_id in self.members:
            self.members[self.leader_id].role = GroupRole.OFFICER

        # Promote new leader
        self.members[new_leader_id].role = GroupRole.LEADER
        self.leader_id = new_leader_id
        return True

    def get_next_looter(self) -> Optional[str]:
        """Get next person in round robin loot order."""
        if not self.members:
            return None

        member_list = list(self.members.keys())
        next_looter = member_list[self.loot_turn_index % len(member_list)]
        self.loot_turn_index += 1
        return next_looter

    def record_kill(self, killer_id: str) -> None:
        """Record a kill by a group member."""
        self.total_kills += 1
        if killer_id in self.members:
            self.members[killer_id].kills += 1

    def calculate_exp_shares(self, total_exp: int, killer_id: str) -> Dict[str, int]:
        """Calculate how experience should be split among members."""
        if not self.members:
            return {}

        shares: Dict[str, int] = {}

        if self.exp_share_mode == ExpShareMode.EQUAL:
            # Equal split
            per_member = total_exp // len(self.members)
            remainder = total_exp % len(self.members)
            for i, member_id in enumerate(self.members.keys()):
                shares[member_id] = per_member + (1 if i < remainder else 0)

        elif self.exp_share_mode == ExpShareMode.KILLER_BONUS:
            # Killer gets 50%, rest split equally
            killer_share = total_exp // 2
            remainder = total_exp - killer_share

            if killer_id in self.members:
                shares[killer_id] = killer_share

            others = [m for m in self.members.keys() if m != killer_id]
            if others:
                per_other = remainder // len(others)
                for member_id in others:
                    shares[member_id] = per_other

            # Give any leftover to killer
            leftover = total_exp - sum(shares.values())
            if killer_id in shares:
                shares[killer_id] += leftover

        else:  # LEVEL_WEIGHTED - simplified, would need level access
            # Fall back to equal for now
            per_member = total_exp // len(self.members)
            for member_id in self.members.keys():
                shares[member_id] = per_member

        return shares


@dataclass
class GroupMembershipData(ComponentData):
    """
    Individual entity's group membership.

    Applied to players/NPCs that can join groups.
    """

    # Current group (if any)
    group_id: str = ""
    group_entity_id: str = ""  # The entity ID of the GroupData entity

    # Pending invites
    pending_invites: List[GroupInvite] = field(default_factory=list)

    # Following
    following_id: str = ""  # Entity we're following
    followers: Set[str] = field(default_factory=set)  # Entities following us

    # Settings
    accept_invites: bool = True
    accept_followers: bool = True

    # Statistics
    groups_joined: int = 0
    groups_led: int = 0

    @property
    def is_in_group(self) -> bool:
        """Check if currently in a group."""
        return bool(self.group_id)

    @property
    def is_following(self) -> bool:
        """Check if following someone."""
        return bool(self.following_id)

    @property
    def has_followers(self) -> bool:
        """Check if anyone is following us."""
        return len(self.followers) > 0

    def add_invite(self, invite: GroupInvite) -> None:
        """Add a group invite."""
        # Remove expired invites
        self.pending_invites = [i for i in self.pending_invites if not i.is_expired]
        # Remove any existing invite from same group
        self.pending_invites = [
            i for i in self.pending_invites if i.group_id != invite.group_id
        ]
        self.pending_invites.append(invite)

    def get_invite(self, group_id: str) -> Optional[GroupInvite]:
        """Get an invite for a specific group."""
        for invite in self.pending_invites:
            if invite.group_id == group_id and not invite.is_expired:
                return invite
        return None

    def get_latest_invite(self) -> Optional[GroupInvite]:
        """Get the most recent non-expired invite."""
        valid = [i for i in self.pending_invites if not i.is_expired]
        if valid:
            return valid[-1]
        return None

    def remove_invite(self, group_id: str) -> bool:
        """Remove an invite."""
        before = len(self.pending_invites)
        self.pending_invites = [
            i for i in self.pending_invites if i.group_id != group_id
        ]
        return len(self.pending_invites) < before

    def clear_invites(self) -> None:
        """Clear all pending invites."""
        self.pending_invites = []

    def join_group(self, group_id: str, group_entity_id: str) -> None:
        """Join a group."""
        self.group_id = group_id
        self.group_entity_id = group_entity_id
        self.groups_joined += 1
        self.clear_invites()

    def leave_group(self) -> None:
        """Leave current group."""
        self.group_id = ""
        self.group_entity_id = ""

    def start_following(self, target_id: str) -> None:
        """Start following a target."""
        self.following_id = target_id

    def stop_following(self) -> None:
        """Stop following."""
        self.following_id = ""

    def add_follower(self, follower_id: str) -> None:
        """Add a follower."""
        self.followers.add(follower_id)

    def remove_follower(self, follower_id: str) -> None:
        """Remove a follower."""
        self.followers.discard(follower_id)


@dataclass
class SocialData(ComponentData):
    """
    Social profile and features.

    Applied to players.
    """

    # Profile
    bio: str = ""
    title: str = ""
    prefix: str = ""  # Displayed before name

    # AFK status
    is_afk: bool = False
    afk_message: str = ""
    afk_since: Optional[datetime] = None

    # Privacy settings
    hidden: bool = False  # Don't show on 'who' list
    anonymous: bool = False  # Don't show in 'who' - admin bypass
    no_tell: bool = False  # Block tells from non-friends

    # Friends
    friends: Set[str] = field(default_factory=set)  # Character names
    ignored: Set[str] = field(default_factory=set)  # Character names blocked

    # Social stats
    tells_sent: int = 0
    tells_received: int = 0
    emotes_used: int = 0

    def set_afk(self, message: str = "") -> None:
        """Set AFK status."""
        self.is_afk = True
        self.afk_message = message or "Away from keyboard"
        self.afk_since = datetime.utcnow()

    def clear_afk(self) -> None:
        """Clear AFK status."""
        self.is_afk = False
        self.afk_message = ""
        self.afk_since = None

    def add_friend(self, name: str) -> bool:
        """Add a friend."""
        name_lower = name.lower()
        if name_lower in self.friends:
            return False
        self.friends.add(name_lower)
        # Remove from ignored if present
        self.ignored.discard(name_lower)
        return True

    def remove_friend(self, name: str) -> bool:
        """Remove a friend."""
        name_lower = name.lower()
        if name_lower not in self.friends:
            return False
        self.friends.remove(name_lower)
        return True

    def is_friend(self, name: str) -> bool:
        """Check if someone is a friend."""
        return name.lower() in self.friends

    def ignore(self, name: str) -> bool:
        """Ignore a player."""
        name_lower = name.lower()
        if name_lower in self.ignored:
            return False
        self.ignored.add(name_lower)
        # Remove from friends if present
        self.friends.discard(name_lower)
        return True

    def unignore(self, name: str) -> bool:
        """Stop ignoring a player."""
        name_lower = name.lower()
        if name_lower not in self.ignored:
            return False
        self.ignored.remove(name_lower)
        return True

    def is_ignored(self, name: str) -> bool:
        """Check if someone is ignored."""
        return name.lower() in self.ignored

    def can_receive_tell(self, from_name: str) -> bool:
        """Check if we can receive a tell from someone."""
        if self.is_ignored(from_name):
            return False
        if self.no_tell and not self.is_friend(from_name):
            return False
        return True

    def get_display_name(self, base_name: str) -> str:
        """Get the display name with title/prefix."""
        parts = []
        if self.prefix:
            parts.append(self.prefix)
        parts.append(base_name)
        if self.title:
            parts.append(self.title)
        return " ".join(parts)


# Standard social emotes
SOCIAL_EMOTES: Dict[str, Dict[str, str]] = {
    "smile": {
        "no_target": "You smile happily.",
        "self": "You smile at yourself.",
        "target": "You smile at {target}.",
        "others_no_target": "{actor} smiles happily.",
        "others_target": "{actor} smiles at {target}.",
        "target_sees": "{actor} smiles at you.",
    },
    "wave": {
        "no_target": "You wave.",
        "self": "You wave at yourself... are you okay?",
        "target": "You wave at {target}.",
        "others_no_target": "{actor} waves.",
        "others_target": "{actor} waves at {target}.",
        "target_sees": "{actor} waves at you.",
    },
    "bow": {
        "no_target": "You bow deeply.",
        "self": "You bow to yourself. How humble!",
        "target": "You bow before {target}.",
        "others_no_target": "{actor} bows deeply.",
        "others_target": "{actor} bows before {target}.",
        "target_sees": "{actor} bows before you.",
    },
    "nod": {
        "no_target": "You nod solemnly.",
        "self": "You nod to yourself. Makes sense!",
        "target": "You nod at {target}.",
        "others_no_target": "{actor} nods solemnly.",
        "others_target": "{actor} nods at {target}.",
        "target_sees": "{actor} nods at you.",
    },
    "laugh": {
        "no_target": "You laugh out loud!",
        "self": "You laugh at yourself. At least you have a sense of humor!",
        "target": "You laugh at {target}.",
        "others_no_target": "{actor} laughs out loud!",
        "others_target": "{actor} laughs at {target}.",
        "target_sees": "{actor} laughs at you.",
    },
    "cry": {
        "no_target": "You burst into tears.",
        "self": "You cry on your own shoulder.",
        "target": "You cry on {target}'s shoulder.",
        "others_no_target": "{actor} bursts into tears.",
        "others_target": "{actor} cries on {target}'s shoulder.",
        "target_sees": "{actor} cries on your shoulder.",
    },
    "hug": {
        "no_target": "You hug yourself.",
        "self": "You hug yourself. Self-care is important!",
        "target": "You hug {target} warmly.",
        "others_no_target": "{actor} hugs themselves.",
        "others_target": "{actor} hugs {target} warmly.",
        "target_sees": "{actor} hugs you warmly.",
    },
    "poke": {
        "no_target": "You poke the air aimlessly.",
        "self": "You poke yourself. Ow!",
        "target": "You poke {target}.",
        "others_no_target": "{actor} pokes the air aimlessly.",
        "others_target": "{actor} pokes {target}.",
        "target_sees": "{actor} pokes you.",
    },
    "shrug": {
        "no_target": "You shrug helplessly.",
        "self": "You shrug at yourself.",
        "target": "You shrug at {target}.",
        "others_no_target": "{actor} shrugs helplessly.",
        "others_target": "{actor} shrugs at {target}.",
        "target_sees": "{actor} shrugs at you.",
    },
    "dance": {
        "no_target": "You dance around happily!",
        "self": "You dance with yourself. How romantic!",
        "target": "You dance with {target}.",
        "others_no_target": "{actor} dances around happily!",
        "others_target": "{actor} dances with {target}.",
        "target_sees": "{actor} dances with you.",
    },
    "cheer": {
        "no_target": "You cheer enthusiastically!",
        "self": "You cheer for yourself!",
        "target": "You cheer for {target}!",
        "others_no_target": "{actor} cheers enthusiastically!",
        "others_target": "{actor} cheers for {target}!",
        "target_sees": "{actor} cheers for you!",
    },
    "wink": {
        "no_target": "You wink suggestively.",
        "self": "You wink at yourself in a mirror.",
        "target": "You wink at {target}.",
        "others_no_target": "{actor} winks suggestively.",
        "others_target": "{actor} winks at {target}.",
        "target_sees": "{actor} winks at you.",
    },
    "salute": {
        "no_target": "You salute smartly.",
        "self": "You salute yourself in the mirror.",
        "target": "You salute {target}.",
        "others_no_target": "{actor} salutes smartly.",
        "others_target": "{actor} salutes {target}.",
        "target_sees": "{actor} salutes you.",
    },
    "thank": {
        "no_target": "You thank everyone present.",
        "self": "You thank yourself. You deserve it!",
        "target": "You thank {target}.",
        "others_no_target": "{actor} thanks everyone present.",
        "others_target": "{actor} thanks {target}.",
        "target_sees": "{actor} thanks you.",
    },
    "apologize": {
        "no_target": "You apologize to everyone.",
        "self": "You apologize to yourself.",
        "target": "You apologize to {target}.",
        "others_no_target": "{actor} apologizes to everyone.",
        "others_target": "{actor} apologizes to {target}.",
        "target_sees": "{actor} apologizes to you.",
    },
    "glare": {
        "no_target": "You glare at nothing in particular.",
        "self": "You glare at yourself. Stop it!",
        "target": "You glare icily at {target}.",
        "others_no_target": "{actor} glares at nothing in particular.",
        "others_target": "{actor} glares icily at {target}.",
        "target_sees": "{actor} glares icily at you.",
    },
    "groan": {
        "no_target": "You groan loudly.",
        "self": "You groan at yourself.",
        "target": "You groan at {target}.",
        "others_no_target": "{actor} groans loudly.",
        "others_target": "{actor} groans at {target}.",
        "target_sees": "{actor} groans at you.",
    },
    "sigh": {
        "no_target": "You sigh heavily.",
        "self": "You sigh at yourself.",
        "target": "You sigh at {target}.",
        "others_no_target": "{actor} sighs heavily.",
        "others_target": "{actor} sighs at {target}.",
        "target_sees": "{actor} sighs at you.",
    },
    "yawn": {
        "no_target": "You yawn widely.",
        "self": "You yawn at yourself.",
        "target": "You yawn at {target}.",
        "others_no_target": "{actor} yawns widely.",
        "others_target": "{actor} yawns at {target}.",
        "target_sees": "{actor} yawns at you.",
    },
    "clap": {
        "no_target": "You clap your hands together.",
        "self": "You clap for yourself. Bravo!",
        "target": "You clap for {target}.",
        "others_no_target": "{actor} claps.",
        "others_target": "{actor} claps for {target}.",
        "target_sees": "{actor} claps for you.",
    },
}


def get_social_emote(
    social_name: str,
    actor_name: str,
    target_name: Optional[str] = None,
    is_self: bool = False,
) -> Dict[str, str]:
    """
    Get the messages for a social emote.

    Returns dict with keys:
    - actor_msg: What the actor sees
    - target_msg: What the target sees (if any)
    - others_msg: What others in the room see
    """
    emote = SOCIAL_EMOTES.get(social_name.lower())
    if not emote:
        return {}

    result = {}

    if is_self:
        result["actor_msg"] = emote["self"]
        result["others_msg"] = emote["others_no_target"].format(actor=actor_name)
    elif target_name:
        result["actor_msg"] = emote["target"].format(target=target_name)
        result["target_msg"] = emote["target_sees"].format(actor=actor_name)
        result["others_msg"] = emote["others_target"].format(
            actor=actor_name, target=target_name
        )
    else:
        result["actor_msg"] = emote["no_target"]
        result["others_msg"] = emote["others_no_target"].format(actor=actor_name)

    return result
