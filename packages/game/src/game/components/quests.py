"""Quest system components."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime

from core import ComponentData


class QuestState(str, Enum):
    """State of a quest."""
    AVAILABLE = "available"      # Can be started
    ACTIVE = "active"            # Currently in progress
    COMPLETED = "completed"      # Objectives done, turn in available
    TURNED_IN = "turned_in"      # Quest finished and rewarded
    FAILED = "failed"            # Quest failed


class ObjectiveType(str, Enum):
    """Type of quest objective."""
    KILL = "kill"                # Kill X mobs of type Y
    COLLECT = "collect"          # Collect X items of type Y
    DELIVER = "deliver"          # Deliver item to NPC
    EXPLORE = "explore"          # Visit specific room(s)
    TALK = "talk"                # Talk to NPC
    USE = "use"                  # Use item/skill on target
    ESCORT = "escort"            # Escort NPC to location
    DEFEND = "defend"            # Defend location/NPC


class QuestRarity(str, Enum):
    """Quest rarity/importance."""
    COMMON = "common"            # Standard quests
    UNCOMMON = "uncommon"        # Slightly better rewards
    RARE = "rare"                # Significant quests
    EPIC = "epic"                # Major story quests
    LEGENDARY = "legendary"      # World-changing quests


@dataclass
class QuestObjective:
    """A single quest objective."""
    objective_id: str
    objective_type: ObjectiveType
    description: str

    # Target info (interpretation depends on type)
    target_id: str = ""          # Mob template ID, item ID, room ID, NPC ID
    target_name: str = ""        # Display name for target

    # Progress tracking
    required_count: int = 1
    current_count: int = 0

    # Optional conditions
    zone_id: Optional[str] = None      # Must be in this zone
    must_be_equipped: bool = False     # Item must be equipped
    must_be_alive: bool = True         # For escort/defend

    # For deliver quests
    deliver_to_npc: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        """Check if objective is complete."""
        return self.current_count >= self.required_count

    @property
    def progress_text(self) -> str:
        """Get progress display text."""
        return f"{self.current_count}/{self.required_count}"

    def add_progress(self, amount: int = 1) -> bool:
        """
        Add progress to objective.

        Returns True if objective was just completed.
        """
        was_complete = self.is_complete
        self.current_count = min(self.current_count + amount, self.required_count)
        return not was_complete and self.is_complete


@dataclass
class QuestReward:
    """Rewards for completing a quest."""
    experience: int = 0
    gold: int = 0
    items: List[str] = field(default_factory=list)  # Item template IDs
    reputation: Dict[str, int] = field(default_factory=dict)  # faction -> amount
    skill_points: int = 0
    unlocks_quests: List[str] = field(default_factory=list)  # Quest IDs


@dataclass
class QuestDefinition:
    """Definition of a quest (template)."""
    quest_id: str
    name: str
    description: str
    rarity: QuestRarity = QuestRarity.COMMON

    # Requirements
    min_level: int = 1
    max_level: int = 50
    required_class: Optional[str] = None
    required_race: Optional[str] = None
    required_quests: List[str] = field(default_factory=list)  # Prerequisite quests
    required_reputation: Dict[str, int] = field(default_factory=dict)  # faction -> min

    # Quest giver
    giver_id: str = ""           # NPC template ID
    giver_zone: str = ""         # Zone where NPC is
    turn_in_id: Optional[str] = None  # NPC to turn in to (None = same as giver)

    # Objectives
    objectives: List[QuestObjective] = field(default_factory=list)

    # Rewards
    rewards: QuestReward = field(default_factory=QuestReward)

    # Flags
    is_repeatable: bool = False
    repeatable_cooldown_hours: int = 24
    is_daily: bool = False
    is_weekly: bool = False
    is_hidden: bool = False      # Don't show in available lists
    auto_accept: bool = False    # Auto-accept when talking to giver
    auto_complete: bool = False  # Auto-complete when objectives done

    # Chain info
    chain_id: Optional[str] = None     # Quest chain this belongs to
    chain_order: int = 0               # Order in chain
    next_quest: Optional[str] = None   # Next quest in chain

    # Time limit (0 = no limit)
    time_limit_minutes: int = 0

    # Flavor text
    intro_text: str = ""         # Text when accepting
    progress_text: str = ""      # Text when in progress
    complete_text: str = ""      # Text when all objectives done
    reward_text: str = ""        # Text when turning in


@dataclass
class ActiveQuest:
    """An active quest instance for a player."""
    quest_id: str
    state: QuestState = QuestState.ACTIVE
    objectives: List[QuestObjective] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @property
    def is_complete(self) -> bool:
        """Check if all objectives are complete."""
        return all(obj.is_complete for obj in self.objectives)

    @property
    def is_expired(self) -> bool:
        """Check if quest has expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

    def get_objective(self, objective_id: str) -> Optional[QuestObjective]:
        """Get a specific objective by ID."""
        for obj in self.objectives:
            if obj.objective_id == objective_id:
                return obj
        return None

    def update_kill_progress(self, mob_template_id: str, zone_id: str = "") -> List[str]:
        """
        Update progress for kill objectives.

        Returns list of objective IDs that were just completed.
        """
        completed = []
        for obj in self.objectives:
            if obj.objective_type != ObjectiveType.KILL:
                continue
            if obj.target_id != mob_template_id:
                continue
            if obj.zone_id and obj.zone_id != zone_id:
                continue
            if obj.add_progress(1):
                completed.append(obj.objective_id)
        return completed

    def update_collect_progress(self, item_id: str, count: int = 1) -> List[str]:
        """
        Update progress for collect objectives.

        Returns list of objective IDs that were just completed.
        """
        completed = []
        for obj in self.objectives:
            if obj.objective_type != ObjectiveType.COLLECT:
                continue
            if obj.target_id != item_id:
                continue
            if obj.add_progress(count):
                completed.append(obj.objective_id)
        return completed

    def update_explore_progress(self, room_id: str) -> List[str]:
        """
        Update progress for explore objectives.

        Returns list of objective IDs that were just completed.
        """
        completed = []
        for obj in self.objectives:
            if obj.objective_type != ObjectiveType.EXPLORE:
                continue
            if obj.target_id != room_id:
                continue
            if obj.add_progress(1):
                completed.append(obj.objective_id)
        return completed

    def update_talk_progress(self, npc_id: str) -> List[str]:
        """
        Update progress for talk objectives.

        Returns list of objective IDs that were just completed.
        """
        completed = []
        for obj in self.objectives:
            if obj.objective_type != ObjectiveType.TALK:
                continue
            if obj.target_id != npc_id:
                continue
            if obj.add_progress(1):
                completed.append(obj.objective_id)
        return completed


@dataclass
class QuestLogData(ComponentData):
    """
    Player's quest log.

    Tracks active, completed, and available quests.
    """

    # Active quests (quest_id -> ActiveQuest)
    active_quests: Dict[str, ActiveQuest] = field(default_factory=dict)

    # Completed quest IDs with completion timestamps
    completed_quests: Dict[str, datetime] = field(default_factory=dict)

    # Quests that can be repeated again (after cooldown)
    repeatable_cooldowns: Dict[str, datetime] = field(default_factory=dict)

    # Discovered but not accepted quests
    discovered_quests: List[str] = field(default_factory=list)

    # Maximum active quests
    max_active_quests: int = 25

    @property
    def active_count(self) -> int:
        """Get number of active quests."""
        return len(self.active_quests)

    @property
    def can_accept_quest(self) -> bool:
        """Check if player can accept another quest."""
        return self.active_count < self.max_active_quests

    def has_quest(self, quest_id: str) -> bool:
        """Check if player has this quest active."""
        return quest_id in self.active_quests

    def has_completed(self, quest_id: str) -> bool:
        """Check if player has completed this quest."""
        return quest_id in self.completed_quests

    def can_repeat(self, quest_id: str) -> bool:
        """Check if a repeatable quest can be taken again."""
        if quest_id not in self.repeatable_cooldowns:
            return True
        return datetime.utcnow() > self.repeatable_cooldowns[quest_id]

    def accept_quest(self, definition: QuestDefinition) -> Optional[ActiveQuest]:
        """
        Accept a quest.

        Returns the ActiveQuest if accepted, None if can't accept.
        """
        if not self.can_accept_quest:
            return None

        if self.has_quest(definition.quest_id):
            return None

        if not definition.is_repeatable and self.has_completed(definition.quest_id):
            return None

        if definition.is_repeatable and not self.can_repeat(definition.quest_id):
            return None

        # Create active quest with copied objectives
        import copy
        objectives = [copy.deepcopy(obj) for obj in definition.objectives]
        for obj in objectives:
            obj.current_count = 0

        now = datetime.utcnow()
        expires_at = None
        if definition.time_limit_minutes > 0:
            from datetime import timedelta
            expires_at = now + timedelta(minutes=definition.time_limit_minutes)

        active = ActiveQuest(
            quest_id=definition.quest_id,
            state=QuestState.ACTIVE,
            objectives=objectives,
            started_at=now,
            expires_at=expires_at,
        )

        self.active_quests[definition.quest_id] = active

        # Remove from discovered if it was there
        if definition.quest_id in self.discovered_quests:
            self.discovered_quests.remove(definition.quest_id)

        return active

    def complete_quest(self, quest_id: str) -> bool:
        """
        Mark a quest as turned in/complete.

        Returns True if completed successfully.
        """
        if quest_id not in self.active_quests:
            return False

        active = self.active_quests[quest_id]
        if not active.is_complete:
            return False

        active.state = QuestState.TURNED_IN
        active.completed_at = datetime.utcnow()

        # Move to completed
        self.completed_quests[quest_id] = active.completed_at
        del self.active_quests[quest_id]

        return True

    def abandon_quest(self, quest_id: str) -> bool:
        """
        Abandon an active quest.

        Returns True if abandoned.
        """
        if quest_id not in self.active_quests:
            return False

        del self.active_quests[quest_id]
        return True

    def fail_quest(self, quest_id: str) -> bool:
        """
        Fail a quest (e.g., timer expired).

        Returns True if failed.
        """
        if quest_id not in self.active_quests:
            return False

        active = self.active_quests[quest_id]
        active.state = QuestState.FAILED
        del self.active_quests[quest_id]
        return True

    def set_repeatable_cooldown(
        self, quest_id: str, cooldown_hours: int
    ) -> None:
        """Set cooldown for a repeatable quest."""
        from datetime import timedelta
        self.repeatable_cooldowns[quest_id] = (
            datetime.utcnow() + timedelta(hours=cooldown_hours)
        )

    def get_quests_by_state(self, state: QuestState) -> List[ActiveQuest]:
        """Get all quests in a specific state."""
        return [q for q in self.active_quests.values() if q.state == state]

    def discover_quest(self, quest_id: str) -> None:
        """Mark a quest as discovered but not accepted."""
        if quest_id not in self.discovered_quests:
            if not self.has_quest(quest_id) and not self.has_completed(quest_id):
                self.discovered_quests.append(quest_id)


# Quest registry for loaded definitions
_quest_registry: Dict[str, QuestDefinition] = {}


def register_quest(definition: QuestDefinition) -> None:
    """Register a quest definition."""
    _quest_registry[definition.quest_id] = definition


def get_quest_definition(quest_id: str) -> Optional[QuestDefinition]:
    """Get a quest definition by ID."""
    return _quest_registry.get(quest_id)


def get_all_quest_definitions() -> Dict[str, QuestDefinition]:
    """Get all registered quest definitions."""
    return _quest_registry.copy()


def get_quests_by_giver(npc_id: str) -> List[QuestDefinition]:
    """Get all quests given by an NPC."""
    return [q for q in _quest_registry.values() if q.giver_id == npc_id]


def get_quests_in_chain(chain_id: str) -> List[QuestDefinition]:
    """Get all quests in a chain, ordered."""
    chain_quests = [
        q for q in _quest_registry.values()
        if q.chain_id == chain_id
    ]
    return sorted(chain_quests, key=lambda q: q.chain_order)


def check_quest_requirements(
    definition: QuestDefinition,
    player_level: int,
    player_class: Optional[str] = None,
    player_race: Optional[str] = None,
    completed_quests: Optional[Dict[str, datetime]] = None,
    reputation: Optional[Dict[str, int]] = None,
) -> tuple[bool, str]:
    """
    Check if a player meets quest requirements.

    Returns (can_accept, reason_if_not).
    """
    if player_level < definition.min_level:
        return False, f"Requires level {definition.min_level}"

    if player_level > definition.max_level:
        return False, f"Maximum level {definition.max_level}"

    if definition.required_class and player_class != definition.required_class:
        return False, f"Requires class: {definition.required_class}"

    if definition.required_race and player_race != definition.required_race:
        return False, f"Requires race: {definition.required_race}"

    if definition.required_quests and completed_quests:
        for req_quest in definition.required_quests:
            if req_quest not in completed_quests:
                req_def = get_quest_definition(req_quest)
                req_name = req_def.name if req_def else req_quest
                return False, f"Requires completion of: {req_name}"

    if definition.required_reputation and reputation:
        for faction, min_rep in definition.required_reputation.items():
            player_rep = reputation.get(faction, 0)
            if player_rep < min_rep:
                return False, f"Requires {min_rep} reputation with {faction}"

    return True, ""
