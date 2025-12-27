"""
Portal and Instance Components

Define connections to dynamic LLM-generated content.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple
from datetime import datetime
from enum import Enum

from core import EntityId, ComponentData


class InstanceType(str, Enum):
    """Types of dynamic instances."""

    DUNGEON = "dungeon"
    WILDERNESS = "wilderness"
    POCKET_DIMENSION = "pocket_dimension"
    DREAM = "dream"
    MEMORY = "memory"
    CHALLENGE = "challenge"


class PersistenceLevel(str, Enum):
    """How long generated content persists."""

    EPHEMERAL = "ephemeral"  # Deleted immediately when empty
    SESSION = "session"  # Persists for some time after empty
    PERMANENT = "permanent"  # Saved to disk


@dataclass
class PortalData(ComponentData):
    """
    A portal that connects to dynamic (LLM-generated) instances.
    """

    # Portal identity
    portal_id: str = ""
    name: str = "mysterious portal"
    description: str = "A shimmering gateway to unknown realms."

    # Theme for generation
    theme_id: str = ""  # References ThemeDefinition
    theme_description: str = ""  # Detailed description for LLM

    # Instance configuration
    instance_type: InstanceType = InstanceType.DUNGEON
    difficulty_min: int = 1
    difficulty_max: int = 10
    max_rooms: int = 15
    max_players: int = 8

    # Current instance
    active_instance_id: Optional[str] = None

    # Cooldowns
    cooldown_s: int = 3600  # 1 hour between uses per player
    player_cooldowns: Dict[str, datetime] = field(default_factory=dict)

    # Requirements
    min_level: int = 1
    required_items: List[str] = field(default_factory=list)  # Template IDs
    consumes_items: bool = False  # Whether to consume required items

    # Flags
    is_active: bool = True
    is_hidden: bool = False
    one_way: bool = False  # Can't return through portal

    def can_enter(self, player_id: str, player_level: int) -> Tuple[bool, str]:
        """Check if player can enter, return (can_enter, reason)."""
        if not self.is_active:
            return False, "The portal is inactive."

        if player_level < self.min_level:
            return False, f"You must be level {self.min_level} to enter."

        if player_id in self.player_cooldowns:
            cooldown_end = self.player_cooldowns[player_id]
            if datetime.utcnow() < cooldown_end:
                remaining = (cooldown_end - datetime.utcnow()).total_seconds()
                minutes = int(remaining // 60)
                return False, f"You must wait {minutes} more minutes."

        return True, ""

    def record_entry(self, player_id: str) -> None:
        """Record player entering portal (for cooldown)."""
        from datetime import timedelta

        self.player_cooldowns[player_id] = datetime.utcnow() + timedelta(seconds=self.cooldown_s)

    def clear_expired_cooldowns(self) -> None:
        """Clear expired cooldowns."""
        now = datetime.utcnow()
        self.player_cooldowns = {
            pid: time for pid, time in self.player_cooldowns.items() if time > now
        }


@dataclass
class InstanceData(ComponentData):
    """
    Metadata for an active dynamic instance.
    """

    # Instance identity
    instance_id: str = ""
    name: str = "Unknown Instance"
    description: str = ""

    # Source
    portal_id: str = ""  # Portal that created this
    theme_id: str = ""

    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)

    # Players
    current_players: Set[str] = field(default_factory=set)
    max_players: int = 8
    total_players_entered: int = 0

    # Rooms
    entry_room_id: Optional[EntityId] = None
    exit_room_id: Optional[EntityId] = None
    room_ids: List[EntityId] = field(default_factory=list)
    boss_room_id: Optional[EntityId] = None

    # Difficulty
    difficulty: int = 1

    # State
    is_completed: bool = False
    completion_time: Optional[datetime] = None

    # Persistence
    persistence_level: PersistenceLevel = PersistenceLevel.SESSION
    persist_until: Optional[datetime] = None  # For session persistence

    # Generation seed for reproducibility
    generation_seed: Optional[int] = None

    # Loot/rewards tracking
    boss_defeated: bool = False
    chests_opened: Set[str] = field(default_factory=set)

    @property
    def player_count(self) -> int:
        """Number of players currently in instance."""
        return len(self.current_players)

    @property
    def room_count(self) -> int:
        """Number of rooms in instance."""
        return len(self.room_ids)

    @property
    def is_empty(self) -> bool:
        """Check if instance has no players."""
        return len(self.current_players) == 0

    @property
    def is_full(self) -> bool:
        """Check if instance is at max capacity."""
        return len(self.current_players) >= self.max_players

    def should_cleanup(self) -> bool:
        """Check if instance should be cleaned up."""
        if self.persistence_level == PersistenceLevel.EPHEMERAL:
            return self.is_empty

        if self.persistence_level == PersistenceLevel.SESSION:
            if self.persist_until and datetime.utcnow() > self.persist_until:
                return True

        return False

    def player_enter(self, player_id: str) -> bool:
        """Record player entering instance."""
        if self.is_full:
            return False

        self.current_players.add(player_id)
        self.total_players_entered += 1
        self.last_activity = datetime.utcnow()
        return True

    def player_leave(self, player_id: str) -> None:
        """Record player leaving instance."""
        self.current_players.discard(player_id)
        self.last_activity = datetime.utcnow()

        # Set persist_until when instance becomes empty
        if self.is_empty and self.persistence_level == PersistenceLevel.SESSION:
            if self.persist_until is None:
                from datetime import timedelta

                # Default: persist for 10 minutes after empty
                self.persist_until = datetime.utcnow() + timedelta(minutes=10)

    def mark_completed(self) -> None:
        """Mark instance as completed."""
        self.is_completed = True
        self.completion_time = datetime.utcnow()

    def open_chest(self, chest_id: str) -> bool:
        """Mark chest as opened, return True if newly opened."""
        if chest_id in self.chests_opened:
            return False
        self.chests_opened.add(chest_id)
        return True
