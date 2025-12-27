"""
Leveling Components

Define leveling state, guild configuration, and level requirements.
Player advancement happens through class guilds with configurable requirements.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time

from core import ComponentData, EntityId


# =============================================================================
# Level Requirements
# =============================================================================


@dataclass
class LevelReward:
    """Rewards granted upon reaching a level."""

    gold: int = 0
    items: List[str] = field(default_factory=list)  # Template IDs
    skills: List[str] = field(default_factory=list)  # Skill IDs
    title: Optional[str] = None  # If set, overrides default title


@dataclass
class LevelRequirement:
    """Requirements to reach a specific level."""

    level: int
    xp_required: int
    title: str  # Display title at this level

    # Optional requirements (consumed/checked on level-up)
    required_items: List[Dict[str, Any]] = field(
        default_factory=list
    )  # [{item_id, count}]
    required_quests: List[str] = field(default_factory=list)  # Quest IDs
    required_gold: int = 0  # Gold cost (consumed)

    # Rewards
    rewards: LevelReward = field(default_factory=LevelReward)

    def get_missing_requirements_text(
        self,
        current_xp: int,
        completed_quests: List[str],
        has_items_fn=None,
        current_gold: int = 0,
    ) -> List[str]:
        """Get list of missing requirements as text."""
        missing = []

        if current_xp < self.xp_required:
            xp_needed = self.xp_required - current_xp
            missing.append(f"Need {xp_needed:,} more experience points")

        for quest_id in self.required_quests:
            if quest_id not in completed_quests:
                missing.append(f"Must complete quest: {quest_id}")

        if self.required_gold > 0 and current_gold < self.required_gold:
            gold_needed = self.required_gold - current_gold
            missing.append(f"Need {gold_needed:,} more gold")

        if has_items_fn:
            for req in self.required_items:
                item_id = req.get("item_id", "")
                count = req.get("count", 1)
                if not has_items_fn(item_id, count):
                    missing.append(f"Need {count}x {item_id}")

        return missing


# =============================================================================
# Guild Configuration
# =============================================================================


@dataclass
class GuildConfig:
    """Configuration for a class guild hall."""

    guild_name: str  # Display name of the guild
    location_id: str  # Room ID where guild is located
    guild_master_id: str  # NPC entity ID of the guild master
    entrance_message: str = "You enter the guild hall."
    rejection_message: str = "Only members of this class may enter."

    # Optional additional guild rooms (all restricted to this class)
    additional_rooms: List[str] = field(default_factory=list)


# =============================================================================
# Extended Class Definition with Guild/Leveling
# =============================================================================


@dataclass
class GuildClassDefinition:
    """
    Extended class definition with guild and leveling configuration.
    Loaded from YAML, stored in ClassRegistry.
    """

    class_id: str
    name: str
    description: str

    # Guild configuration
    guild: GuildConfig = field(default_factory=lambda: GuildConfig(
        guild_name="Guild Hall",
        location_id="ravenmoor_square",
        guild_master_id="guild_master",
    ))

    # Base stats for this class
    base_stats: Dict[str, int] = field(
        default_factory=lambda: {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        }
    )

    # Starting configuration
    starting_location: str = "ravenmoor_square"
    starting_equipment: List[str] = field(default_factory=list)
    starting_skills: List[str] = field(default_factory=list)
    starting_gold: int = 100

    # Health/Mana per level
    health_per_level: int = 10
    mana_per_level: int = 5
    starting_health: int = 100
    starting_mana: int = 50

    # Level requirements (level -> LevelRequirement)
    levels: Dict[int, LevelRequirement] = field(default_factory=dict)

    # Max level for this class
    max_level: int = 50

    # XP formula for levels not explicitly defined
    # Expression with {level} placeholder, evaluated at runtime
    xp_formula: str = "level * level * 1000"

    # Prime attribute for this class
    prime_attribute: str = "strength"

    # Proficiencies
    armor_proficiency: List[str] = field(default_factory=list)
    weapon_proficiency: List[str] = field(default_factory=list)
    class_skills: List[str] = field(default_factory=list)

    def get_level_requirement(self, level: int) -> LevelRequirement:
        """Get requirements for a specific level."""
        if level in self.levels:
            return self.levels[level]

        # Interpolate using formula
        return self._interpolate_level(level)

    def _interpolate_level(self, level: int) -> LevelRequirement:
        """Generate level requirements using formula."""
        try:
            xp_required = eval(
                self.xp_formula.replace("level", str(level)),
                {"__builtins__": {}},
            )
        except Exception:
            xp_required = level * level * 1000

        return LevelRequirement(
            level=level,
            xp_required=int(xp_required),
            title=f"Level {level} {self.name}",
        )

    def get_xp_for_level(self, level: int) -> int:
        """Get XP required for a specific level."""
        return self.get_level_requirement(level).xp_required

    def get_title_for_level(self, level: int) -> str:
        """Get display title for a level."""
        return self.get_level_requirement(level).title


# =============================================================================
# Player Leveling State
# =============================================================================


@dataclass
class LevelingData(ComponentData):
    """
    Player's leveling state.

    Tracks current level, XP, and level-up state.
    """

    # Current state
    current_level: int = 1
    current_xp: int = 0
    xp_to_next: int = 1000  # Cached XP requirement for next level
    lifetime_xp: int = 0  # Total XP ever earned

    # Class info (denormalized for quick access)
    class_id: str = "warrior"
    class_title: str = "Recruit"  # Current title based on level

    # Level-up tracking
    pending_level_up: bool = False  # True when XP meets requirement
    last_level_up_at: float = 0.0  # Timestamp of last level-up
    levels_gained_session: int = 0  # Levels gained this session

    # Statistics
    total_levels_gained: int = 0
    xp_from_combat: int = 0
    xp_from_quests: int = 0
    xp_from_crafting: int = 0
    xp_from_exploration: int = 0

    def add_xp(self, amount: int, source: str = "combat") -> bool:
        """
        Add experience points.

        Returns True if this pushed XP past the level-up threshold.
        """
        self.current_xp += amount
        self.lifetime_xp += amount

        # Track source
        source_attr = f"xp_from_{source}"
        if hasattr(self, source_attr):
            setattr(self, source_attr, getattr(self, source_attr) + amount)

        # Check if we can level up
        if self.current_xp >= self.xp_to_next and not self.pending_level_up:
            self.pending_level_up = True
            return True

        return False

    def apply_level_up(self, new_level: int, new_xp_to_next: int, new_title: str) -> None:
        """Apply a level-up after validation."""
        self.current_level = new_level
        self.xp_to_next = new_xp_to_next
        self.class_title = new_title
        self.pending_level_up = False
        self.last_level_up_at = time.time()
        self.total_levels_gained += 1
        self.levels_gained_session += 1

    def get_xp_progress(self) -> tuple:
        """Get current XP progress as (current, needed, percentage)."""
        percentage = (self.current_xp / self.xp_to_next * 100) if self.xp_to_next > 0 else 100
        return (self.current_xp, self.xp_to_next, min(100.0, percentage))

    def get_xp_breakdown(self) -> Dict[str, int]:
        """Get breakdown of XP by source."""
        return {
            "combat": self.xp_from_combat,
            "quests": self.xp_from_quests,
            "crafting": self.xp_from_crafting,
            "exploration": self.xp_from_exploration,
        }


@dataclass
class LevelUpQueueData(ComponentData):
    """
    Queued level-up request awaiting system processing.

    Created when player uses 'level' command at guild master.
    Processed by LevelingSystem each tick.
    """

    target_level: int = 0
    guild_master_id: str = ""
    validated: bool = False  # True if all requirements verified
    validation_message: str = ""  # Error message if validation failed

    # Items to be consumed (entity IDs)
    items_to_consume: List[EntityId] = field(default_factory=list)
    gold_to_consume: int = 0

    # Timestamp for timeout
    created_at: float = field(default_factory=time.time)


# =============================================================================
# Guild Room Markers
# =============================================================================


@dataclass
class GuildRoomData(ComponentData):
    """
    Marks a room as belonging to a class guild.

    Players of other classes cannot enter.
    """

    class_id: str = ""  # Which class this guild belongs to
    is_main_hall: bool = False  # True for the main guild room
    guild_master_present: bool = False  # True if guild master is here

    # Optional rank requirements
    min_level: int = 1  # Minimum level to enter this room
    required_title: Optional[str] = None  # Optional specific title required


# =============================================================================
# Helper Functions
# =============================================================================


def calculate_xp_for_level(level: int, formula: str = "level * level * 1000") -> int:
    """Calculate XP required for a level using formula."""
    try:
        return int(eval(formula.replace("level", str(level)), {"__builtins__": {}}))
    except Exception:
        return level * level * 1000


def calculate_total_xp_to_level(target_level: int, formula: str = "level * level * 1000") -> int:
    """Calculate total XP needed to reach a level from level 1."""
    total = 0
    for level in range(2, target_level + 1):
        total += calculate_xp_for_level(level, formula)
    return total


# =============================================================================
# Default Level Titles by Class
# =============================================================================

# These are fallback titles if not specified in YAML
DEFAULT_TITLES = {
    "warrior": {
        1: "Recruit",
        5: "Footman",
        10: "Sergeant",
        15: "Lieutenant",
        20: "Captain",
        25: "Commander",
        30: "Champion",
        35: "War Chief",
        40: "Warlord",
        45: "Battle Master",
        50: "Legend",
    },
    "mage": {
        1: "Apprentice",
        5: "Initiate",
        10: "Adept",
        15: "Evoker",
        20: "Conjurer",
        25: "Sorcerer",
        30: "Wizard",
        35: "Magus",
        40: "Archmage",
        45: "High Magus",
        50: "Archon",
    },
    "cleric": {
        1: "Acolyte",
        5: "Devotee",
        10: "Priest",
        15: "Curate",
        20: "Vicar",
        25: "Canon",
        30: "Bishop",
        35: "Archbishop",
        40: "High Priest",
        45: "Prelate",
        50: "Patriarch",
    },
    "rogue": {
        1: "Pickpocket",
        5: "Cutpurse",
        10: "Burglar",
        15: "Footpad",
        20: "Thief",
        25: "Assassin",
        30: "Shadow",
        35: "Nightblade",
        40: "Shadow Master",
        45: "Grandmaster",
        50: "Legend",
    },
    "ranger": {
        1: "Scout",
        5: "Tracker",
        10: "Pathfinder",
        15: "Warden",
        20: "Hunter",
        25: "Stalker",
        30: "Ranger",
        35: "Beast Master",
        40: "High Ranger",
        45: "Archdruid",
        50: "Legend",
    },
}


def get_default_title(class_id: str, level: int) -> str:
    """Get default title for a class and level."""
    class_titles = DEFAULT_TITLES.get(class_id, DEFAULT_TITLES["warrior"])

    # Find the highest tier at or below this level
    best_title = class_titles.get(1, "Adventurer")
    for tier_level, title in sorted(class_titles.items()):
        if tier_level <= level:
            best_title = title

    return best_title
