"""
Stats Components

Define entity attributes, health, mana, and derived statistics.
"""

from dataclasses import dataclass, field
from typing import Dict

from core import ComponentData


@dataclass
class AttributeBlock:
    """Primary attributes (ROM-style)."""

    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    def get_modifier(self, attribute: str) -> int:
        """Get the modifier for an attribute (D&D style: (attr - 10) / 2)."""
        value = getattr(self, attribute, 10)
        return (value - 10) // 2


@dataclass
class StatsData(ComponentData):
    """
    Base statistics for any entity that can be in combat.

    This includes players, mobs, and potentially NPCs.
    """

    # Primary attributes
    attributes: AttributeBlock = field(default_factory=AttributeBlock)

    # Resource pools
    max_health: int = 100
    current_health: int = 100
    max_mana: int = 100
    current_mana: int = 100
    max_stamina: int = 100
    current_stamina: int = 100

    # Combat stats
    armor_class: int = 10
    attack_bonus: int = 0
    damage_bonus: int = 0

    # Movement
    movement_speed: int = 100  # Percentage of base speed

    # Regeneration rates (per tick)
    health_regen: int = 1
    mana_regen: int = 1
    stamina_regen: int = 2

    @property
    def health_percent(self) -> float:
        """Get health as percentage."""
        if self.max_health <= 0:
            return 0.0
        return self.current_health / self.max_health

    @property
    def mana_percent(self) -> float:
        """Get mana as percentage."""
        if self.max_mana <= 0:
            return 0.0
        return self.current_mana / self.max_mana

    @property
    def is_alive(self) -> bool:
        """Check if entity is alive."""
        return self.current_health > 0

    @property
    def is_full_health(self) -> bool:
        """Check if at full health."""
        return self.current_health >= self.max_health

    def take_damage(self, amount: int) -> int:
        """
        Apply damage, return actual damage taken.
        """
        actual = min(amount, self.current_health)
        self.current_health -= actual
        return actual

    def heal(self, amount: int) -> int:
        """
        Heal, return actual amount healed.
        """
        missing = self.max_health - self.current_health
        actual = min(amount, missing)
        self.current_health += actual
        return actual

    def spend_mana(self, amount: int) -> bool:
        """
        Spend mana if available, return success.
        """
        if self.current_mana >= amount:
            self.current_mana -= amount
            return True
        return False

    def restore_mana(self, amount: int) -> int:
        """
        Restore mana, return actual amount restored.
        """
        missing = self.max_mana - self.current_mana
        actual = min(amount, missing)
        self.current_mana += actual
        return actual


@dataclass
class PlayerStatsData(StatsData):
    """
    Player-specific statistics with experience and leveling.
    """

    # Class and race
    class_name: str = "adventurer"
    race_name: str = "human"

    # Experience and level
    level: int = 1
    experience: int = 0
    experience_to_level: int = 1000

    # Skill points
    skill_points: int = 0
    practice_sessions: int = 0

    # Trained skills: skill_name -> level (0-100)
    skills: Dict[str, int] = field(default_factory=dict)

    # Gold
    gold: int = 0
    bank_gold: int = 0

    @property
    def experience_percent(self) -> float:
        """Get experience progress to next level."""
        if self.experience_to_level <= 0:
            return 1.0
        return self.experience / self.experience_to_level

    def gain_experience(self, amount: int) -> bool:
        """
        Gain experience, return True if leveled up.
        """
        self.experience += amount
        if self.experience >= self.experience_to_level:
            return True
        return False

    def level_up(self) -> None:
        """
        Level up the player.
        """
        self.level += 1
        self.experience -= self.experience_to_level
        self.experience_to_level = int(self.experience_to_level * 1.5)

        # Increase stats
        self.max_health += 10 + self.attributes.constitution // 3
        self.max_mana += 5 + self.attributes.intelligence // 3
        self.current_health = self.max_health
        self.current_mana = self.max_mana

        self.skill_points += 1

    def get_skill_level(self, skill_name: str) -> int:
        """Get level in a skill (0 if not learned)."""
        return self.skills.get(skill_name, 0)


@dataclass
class MobStatsData(StatsData):
    """
    Mob-specific statistics with challenge rating and loot.
    """

    # Challenge rating for difficulty scaling
    challenge_rating: float = 1.0

    # Experience value when killed
    experience_value: int = 100

    # Aggression behavior
    aggro_radius: int = 3  # Rooms away mob will aggro
    leash_radius: int = 10  # Max distance from spawn before returning

    # Gold drop range
    gold_min: int = 0
    gold_max: int = 10

    # Respawn
    respawn_time_s: int = 300  # 5 minutes

    def get_gold_drop(self) -> int:
        """Get random gold drop amount."""
        import random

        return random.randint(self.gold_min, self.gold_max)
