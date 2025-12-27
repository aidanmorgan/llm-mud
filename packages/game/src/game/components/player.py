"""
Player Components

Define player-specific data: connections, progress, quests.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from datetime import datetime

from core import ComponentData


@dataclass
class PlayerConnectionData(ComponentData):
    """
    Network connection state for a player.
    """

    # Connection info
    session_id: str = ""
    account_id: str = ""

    # Timing
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_input: datetime = field(default_factory=datetime.utcnow)
    last_command: str = ""

    # Connection state
    is_connected: bool = True
    is_linkdead: bool = False  # Disconnected but not logged out
    linkdead_at: Optional[datetime] = None

    # Idle handling
    idle_timeout_s: int = 300  # 5 minutes
    idle_warned: bool = False

    # Client info
    client_type: str = "unknown"  # telnet, websocket, etc.
    terminal_width: int = 80
    terminal_height: int = 24
    supports_color: bool = True

    # Input buffer
    input_buffer: List[str] = field(default_factory=list)

    @property
    def idle_seconds(self) -> float:
        """Get seconds since last input."""
        return (datetime.utcnow() - self.last_input).total_seconds()

    @property
    def is_idle(self) -> bool:
        """Check if player is idle."""
        return self.idle_seconds > self.idle_timeout_s

    def record_input(self, command: str) -> None:
        """Record player input."""
        self.last_input = datetime.utcnow()
        self.last_command = command
        self.idle_warned = False

    def go_linkdead(self) -> None:
        """Mark player as linkdead."""
        self.is_connected = False
        self.is_linkdead = True
        self.linkdead_at = datetime.utcnow()

    def reconnect(self) -> None:
        """Reconnect player."""
        self.is_connected = True
        self.is_linkdead = False
        self.linkdead_at = None
        self.last_input = datetime.utcnow()


@dataclass
class PlayerProgressData(ComponentData):
    """
    Long-term player progress and achievements.
    """

    # Account linking
    account_id: str = ""
    character_name: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Play time
    total_play_time_s: int = 0
    session_start: datetime = field(default_factory=datetime.utcnow)

    # Discovery
    discovered_rooms: Set[str] = field(default_factory=set)  # Room template IDs
    discovered_areas: Set[str] = field(default_factory=set)  # Area IDs

    # Combat stats
    mobs_killed: Dict[str, int] = field(default_factory=dict)  # template_id -> count
    total_kills: int = 0
    total_deaths: int = 0
    current_kill_streak: int = 0
    best_kill_streak: int = 0

    # Achievements
    achievements: Set[str] = field(default_factory=set)  # Achievement IDs
    achievement_points: int = 0

    # Reputation
    reputation: Dict[str, int] = field(default_factory=dict)  # faction_id -> rep value

    # Statistics
    damage_dealt_total: int = 0
    damage_taken_total: int = 0
    healing_done_total: int = 0
    gold_earned_total: int = 0
    gold_spent_total: int = 0

    def discover_room(self, room_id: str) -> bool:
        """Discover a room, return True if newly discovered."""
        if room_id in self.discovered_rooms:
            return False
        self.discovered_rooms.add(room_id)
        return True

    def record_kill(self, mob_template_id: str) -> None:
        """Record a mob kill."""
        self.total_kills += 1
        self.current_kill_streak += 1
        self.best_kill_streak = max(self.best_kill_streak, self.current_kill_streak)
        current = self.mobs_killed.get(mob_template_id, 0)
        self.mobs_killed[mob_template_id] = current + 1

    def record_death(self) -> None:
        """Record player death."""
        self.total_deaths += 1
        self.current_kill_streak = 0

    def unlock_achievement(self, achievement_id: str, points: int = 10) -> bool:
        """Unlock an achievement, return True if newly unlocked."""
        if achievement_id in self.achievements:
            return False
        self.achievements.add(achievement_id)
        self.achievement_points += points
        return True

    def modify_reputation(self, faction_id: str, amount: int) -> int:
        """Modify reputation, return new value."""
        current = self.reputation.get(faction_id, 0)
        new_value = current + amount
        self.reputation[faction_id] = new_value
        return new_value

    def get_play_time_formatted(self) -> str:
        """Get total play time as formatted string."""
        session_time = (datetime.utcnow() - self.session_start).total_seconds()
        total = int(self.total_play_time_s + session_time)

        days = total // 86400
        hours = (total % 86400) // 3600
        minutes = (total % 3600) // 60

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"


@dataclass
class QuestLogData(ComponentData):
    """
    Active and completed quest tracking.
    """

    # Active quests: quest_id -> progress data
    active_quests: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Completed quests
    completed_quests: Set[str] = field(default_factory=set)

    # Failed/abandoned quests
    failed_quests: Set[str] = field(default_factory=set)

    # Limits
    max_active_quests: int = 20

    @property
    def active_count(self) -> int:
        """Number of active quests."""
        return len(self.active_quests)

    @property
    def can_accept_quest(self) -> bool:
        """Check if can accept another quest."""
        return len(self.active_quests) < self.max_active_quests

    def has_quest(self, quest_id: str) -> bool:
        """Check if quest is active."""
        return quest_id in self.active_quests

    def has_completed(self, quest_id: str) -> bool:
        """Check if quest was completed."""
        return quest_id in self.completed_quests

    def accept_quest(self, quest_id: str, initial_progress: Optional[Dict] = None) -> bool:
        """Accept a quest."""
        if not self.can_accept_quest:
            return False
        if quest_id in self.active_quests:
            return False

        self.active_quests[quest_id] = initial_progress or {
            "started_at": datetime.utcnow().isoformat(),
            "objectives": {},
        }
        return True

    def update_quest_progress(self, quest_id: str, objective: str, value: Any) -> bool:
        """Update quest objective progress."""
        if quest_id not in self.active_quests:
            return False

        if "objectives" not in self.active_quests[quest_id]:
            self.active_quests[quest_id]["objectives"] = {}

        self.active_quests[quest_id]["objectives"][objective] = value
        return True

    def complete_quest(self, quest_id: str) -> bool:
        """Mark quest as completed."""
        if quest_id not in self.active_quests:
            return False

        del self.active_quests[quest_id]
        self.completed_quests.add(quest_id)
        return True

    def fail_quest(self, quest_id: str) -> bool:
        """Mark quest as failed."""
        if quest_id not in self.active_quests:
            return False

        del self.active_quests[quest_id]
        self.failed_quests.add(quest_id)
        return True

    def abandon_quest(self, quest_id: str) -> bool:
        """Abandon a quest (can be retaken)."""
        if quest_id not in self.active_quests:
            return False

        del self.active_quests[quest_id]
        return True
