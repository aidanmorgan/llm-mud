"""
Character Components

Define class, race, and character creation systems.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from core import ComponentData


class CharacterClass(str, Enum):
    """Available character classes."""

    WARRIOR = "warrior"
    MAGE = "mage"
    CLERIC = "cleric"
    ROGUE = "rogue"
    RANGER = "ranger"


class CharacterRace(str, Enum):
    """Available character races."""

    HUMAN = "human"
    ELF = "elf"
    DWARF = "dwarf"
    HALFLING = "halfling"
    ORC = "orc"


class CreationState(str, Enum):
    """States in character creation flow."""

    WELCOME = "welcome"
    CHOOSE_NAME = "choose_name"
    CHOOSE_RACE = "choose_race"
    CHOOSE_CLASS = "choose_class"
    ALLOCATE_STATS = "allocate_stats"
    CONFIRM = "confirm"
    COMPLETE = "complete"


@dataclass
class StatModifiers:
    """Stat modifiers for race or class."""

    strength: int = 0
    dexterity: int = 0
    constitution: int = 0
    intelligence: int = 0
    wisdom: int = 0
    charisma: int = 0

    max_health_bonus: int = 0
    max_mana_bonus: int = 0

    def apply_to_base(self, base: int, attribute: str) -> int:
        """Apply modifier to a base stat value."""
        modifier = getattr(self, attribute, 0)
        return base + modifier


@dataclass
class ClassDefinition:
    """
    Definition of a character class.
    Loaded from YAML, stored in template registry.
    """

    class_id: str
    name: str
    description: str

    # Stat modifiers per level
    stat_modifiers: StatModifiers = field(default_factory=StatModifiers)

    # Level-up gains
    health_per_level: int = 10
    mana_per_level: int = 5

    # Starting values
    starting_health: int = 100
    starting_mana: int = 50
    starting_gold: int = 100

    # Skills available to this class
    class_skills: List[str] = field(default_factory=list)

    # Starting skills (learned at level 1)
    starting_skills: List[str] = field(default_factory=list)

    # Starting equipment (template IDs)
    starting_equipment: List[str] = field(default_factory=list)

    # Starting room (template ID)
    starting_room: str = "ravenmoor_square"

    # Prime attribute (used for various checks)
    prime_attribute: str = "strength"

    # Armor proficiencies
    armor_proficiency: List[str] = field(default_factory=list)

    # Weapon proficiencies
    weapon_proficiency: List[str] = field(default_factory=list)

    # Proficiency skill bonuses: skill_name -> bonus levels
    proficiency_bonuses: Dict[str, int] = field(default_factory=dict)


@dataclass
class RaceDefinition:
    """
    Definition of a character race.
    Loaded from YAML, stored in template registry.
    """

    race_id: str
    name: str
    description: str

    # Stat modifiers
    stat_modifiers: StatModifiers = field(default_factory=StatModifiers)

    # Racial abilities
    racial_abilities: List[str] = field(default_factory=list)

    # Size (affects some mechanics)
    size: str = "medium"  # small, medium, large

    # Movement speed modifier (percentage)
    speed_modifier: int = 100

    # Special vision
    infravision: bool = False
    darkvision: bool = False

    # Resistances: damage_type -> percentage reduction
    resistances: Dict[str, int] = field(default_factory=dict)

    # Languages known
    languages: List[str] = field(default_factory=lambda: ["common"])

    # Lifespan (for flavor)
    lifespan: str = "average"

    # Starting room override (optional)
    starting_room_override: Optional[str] = None

    # Proficiency skill bonuses: skill_name -> bonus levels
    proficiency_bonuses: Dict[str, int] = field(default_factory=dict)


@dataclass
class ClassData(ComponentData):
    """
    A player's class information.
    """

    class_id: str = "warrior"
    class_name: str = "Warrior"

    # Skills granted by class
    class_skills: List[str] = field(default_factory=list)

    # Level-up bonuses stored for this character
    health_per_level: int = 10
    mana_per_level: int = 5

    # Prime attribute
    prime_attribute: str = "strength"


@dataclass
class RaceData(ComponentData):
    """
    A player's race information.
    """

    race_id: str = "human"
    race_name: str = "Human"

    # Stat modifiers applied
    stat_modifiers: StatModifiers = field(default_factory=StatModifiers)

    # Racial abilities
    racial_abilities: List[str] = field(default_factory=list)

    # Vision
    infravision: bool = False
    darkvision: bool = False

    # Resistances
    resistances: Dict[str, int] = field(default_factory=dict)

    # Languages
    languages: List[str] = field(default_factory=lambda: ["common"])

    def has_ability(self, ability: str) -> bool:
        """Check if race has a specific ability."""
        return ability in self.racial_abilities

    def get_resistance(self, damage_type: str) -> int:
        """Get resistance percentage for a damage type."""
        return self.resistances.get(damage_type, 0)


@dataclass
class CharacterCreationData(ComponentData):
    """
    Tracks character creation state for new players.
    """

    # Current state in creation flow
    state: CreationState = CreationState.WELCOME

    # Choices made so far
    chosen_name: str = ""
    chosen_race: Optional[str] = None
    chosen_class: Optional[str] = None

    # Attribute allocation (point buy system)
    points_remaining: int = 15
    allocated_stats: Dict[str, int] = field(
        default_factory=lambda: {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        }
    )

    # Validation tracking
    name_attempts: int = 0
    max_name_attempts: int = 5

    # Timeout (minutes until creation times out)
    timeout_minutes: int = 30

    def advance_state(self) -> None:
        """Advance to next creation state."""
        states = list(CreationState)
        current_idx = states.index(self.state)
        if current_idx < len(states) - 1:
            self.state = states[current_idx + 1]

    def go_back(self) -> bool:
        """Go back to previous state. Returns False if at first state."""
        states = list(CreationState)
        current_idx = states.index(self.state)
        if current_idx > 0:
            self.state = states[current_idx - 1]
            return True
        return False

    def is_complete(self) -> bool:
        """Check if creation is complete."""
        return self.state == CreationState.COMPLETE

    def can_allocate(self, attribute: str, amount: int = 1) -> bool:
        """Check if points can be allocated to an attribute."""
        if amount > self.points_remaining:
            return False
        current = self.allocated_stats.get(attribute, 10)
        return current + amount <= 18  # Max stat is 18

    def allocate(self, attribute: str, amount: int = 1) -> bool:
        """Allocate points to an attribute."""
        if not self.can_allocate(attribute, amount):
            return False
        self.allocated_stats[attribute] = self.allocated_stats.get(attribute, 10) + amount
        self.points_remaining -= amount
        return True

    def deallocate(self, attribute: str, amount: int = 1) -> bool:
        """Remove points from an attribute."""
        current = self.allocated_stats.get(attribute, 10)
        if current - amount < 8:  # Min stat is 8
            return False
        self.allocated_stats[attribute] = current - amount
        self.points_remaining += amount
        return True

    def get_summary(self) -> Dict:
        """Get summary of choices made."""
        return {
            "name": self.chosen_name,
            "race": self.chosen_race,
            "class": self.chosen_class,
            "stats": self.allocated_stats.copy(),
            "points_remaining": self.points_remaining,
        }

    def reset(self) -> None:
        """Reset all choices."""
        self.state = CreationState.WELCOME
        self.chosen_name = ""
        self.chosen_race = None
        self.chosen_class = None
        self.points_remaining = 15
        self.allocated_stats = {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        }


# =============================================================================
# Template Registry Types
# =============================================================================


@dataclass
class ClassTemplate:
    """Template for a character class (stored in registry)."""

    class_id: str
    name: str
    description: str
    stat_modifiers: Dict[str, int] = field(default_factory=dict)
    health_per_level: int = 10
    mana_per_level: int = 5
    starting_health: int = 100
    starting_mana: int = 50
    starting_gold: int = 100
    class_skills: List[str] = field(default_factory=list)
    starting_skills: List[str] = field(default_factory=list)
    starting_equipment: List[str] = field(default_factory=list)
    starting_room: str = "ravenmoor_square"
    prime_attribute: str = "strength"
    armor_proficiency: List[str] = field(default_factory=list)
    weapon_proficiency: List[str] = field(default_factory=list)
    proficiency_bonuses: Dict[str, int] = field(default_factory=dict)


@dataclass
class RaceTemplate:
    """Template for a character race (stored in registry)."""

    race_id: str
    name: str
    description: str
    stat_modifiers: Dict[str, int] = field(default_factory=dict)
    racial_abilities: List[str] = field(default_factory=list)
    size: str = "medium"
    speed_modifier: int = 100
    infravision: bool = False
    darkvision: bool = False
    resistances: Dict[str, int] = field(default_factory=dict)
    languages: List[str] = field(default_factory=lambda: ["common"])
    lifespan: str = "average"
    starting_room_override: Optional[str] = None
    proficiency_bonuses: Dict[str, int] = field(default_factory=dict)
