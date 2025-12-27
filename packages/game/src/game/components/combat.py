"""
Combat Components

Define combat state, targeting, and damage handling.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
from datetime import datetime

from core import EntityId, ComponentData


class DamageType(str, Enum):
    """Types of damage."""

    PHYSICAL = "physical"
    SLASHING = "slashing"
    PIERCING = "piercing"
    BLUDGEONING = "bludgeoning"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    POISON = "poison"
    ACID = "acid"
    HOLY = "holy"
    UNHOLY = "unholy"
    PSYCHIC = "psychic"


class CombatState(str, Enum):
    """Combat engagement state."""

    IDLE = "idle"
    ENGAGED = "engaged"  # In combat
    FLEEING = "fleeing"  # Attempting to flee
    STUNNED = "stunned"  # Can't act
    DEAD = "dead"


@dataclass
class CombatData(ComponentData):
    """
    Combat state and targeting for entities that can fight.
    """

    # Current state
    state: CombatState = CombatState.IDLE

    # Targeting
    target: Optional[EntityId] = None
    targeted_by: List[EntityId] = field(default_factory=list)  # Who is targeting us

    # Weapon info
    weapon_damage_dice: str = "1d4"  # Dice notation: "2d6+3"
    weapon_damage_type: DamageType = DamageType.BLUDGEONING

    # Combat timing
    attack_speed: float = 1.0  # Attacks per round
    last_attack_time: Optional[datetime] = None
    attack_cooldown_s: float = 4.0  # Seconds between attacks

    # Combat stats (can be modified by buffs/equipment)
    hit_bonus: int = 0
    damage_bonus: int = 0
    defense_bonus: int = 0

    # Tracking
    combat_start_time: Optional[datetime] = None
    damage_dealt: int = 0
    damage_taken: int = 0

    @property
    def is_in_combat(self) -> bool:
        """Check if currently in combat."""
        return self.state == CombatState.ENGAGED

    @property
    def has_target(self) -> bool:
        """Check if has a valid target."""
        return self.target is not None

    @property
    def can_attack(self) -> bool:
        """Check if can perform an attack."""
        if self.state in (CombatState.STUNNED, CombatState.DEAD, CombatState.FLEEING):
            return False
        if self.last_attack_time is None:
            return True
        elapsed = (datetime.utcnow() - self.last_attack_time).total_seconds()
        return elapsed >= self.attack_cooldown_s / self.attack_speed

    def set_target(self, target: EntityId) -> None:
        """Set combat target and enter combat."""
        self.target = target
        self.state = CombatState.ENGAGED
        if self.combat_start_time is None:
            self.combat_start_time = datetime.utcnow()

    def clear_target(self) -> None:
        """Clear target and exit combat."""
        self.target = None
        self.state = CombatState.IDLE
        self.combat_start_time = None

    def add_attacker(self, attacker: EntityId) -> None:
        """Add entity to list of those targeting us."""
        if attacker not in self.targeted_by:
            self.targeted_by.append(attacker)
        if self.state == CombatState.IDLE:
            self.state = CombatState.ENGAGED
            self.combat_start_time = datetime.utcnow()

    def remove_attacker(self, attacker: EntityId) -> None:
        """Remove entity from attackers list."""
        if attacker in self.targeted_by:
            self.targeted_by.remove(attacker)
        # Exit combat if no more attackers and no target
        if not self.targeted_by and self.target is None:
            self.state = CombatState.IDLE
            self.combat_start_time = None

    def record_attack(self) -> None:
        """Record that an attack was made."""
        self.last_attack_time = datetime.utcnow()

    def record_damage_dealt(self, amount: int) -> None:
        """Record damage dealt."""
        self.damage_dealt += amount

    def record_damage_taken(self, amount: int) -> None:
        """Record damage taken."""
        self.damage_taken += amount

    def roll_damage(self) -> int:
        """Roll weapon damage."""
        return parse_dice_roll(self.weapon_damage_dice) + self.damage_bonus


def parse_dice_roll(dice_str: str) -> int:
    """
    Parse and roll dice notation like "2d6+3".

    Format: NdS+M where N=number of dice, S=sides, M=modifier
    """
    import random
    import re

    dice_str = dice_str.lower().strip()

    # Match pattern: optional number, d, sides, optional modifier
    match = re.match(r"(\d*)d(\d+)([+-]\d+)?", dice_str)
    if not match:
        return 0

    num_dice = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    total = sum(random.randint(1, sides) for _ in range(num_dice))
    return max(0, total + modifier)
