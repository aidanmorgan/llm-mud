"""
Proficiency Components

Player skill proficiency system for gathering, crafting, and utility skills.
Skills level up through use, providing better yields, quality, and efficiency.
Race and class provide initial bonuses to specific skills.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
import math

from core import ComponentData


# =============================================================================
# Proficiency Skills
# =============================================================================


class ProficiencySkill(str, Enum):
    """All proficiency skills available in the game."""

    # Gathering skills
    MINING = "mining"  # Extract ores and gems from nodes
    SKINNING = "skinning"  # Skin creatures for leather/hide
    HERBALISM = "herbalism"  # Gather plants and herbs
    LOGGING = "logging"  # Chop trees for wood
    FISHING = "fishing"  # Catch fish from water
    FORAGING = "foraging"  # Find food and materials in the wild

    # Crafting skills
    BLACKSMITHING = "blacksmithing"  # Forge weapons
    ARMORSMITHING = "armorsmithing"  # Forge armor
    LEATHERWORKING = "leatherworking"  # Craft leather items
    TAILORING = "tailoring"  # Craft cloth items
    ALCHEMY = "alchemy"  # Brew potions
    ENCHANTING = "enchanting"  # Enchant items with magic
    JEWELCRAFTING = "jewelcrafting"  # Craft jewelry and gems
    COOKING = "cooking"  # Prepare food for buffs

    # Utility skills
    DISMANTLING = "dismantling"  # Break down items for components
    PROSPECTING = "prospecting"  # Find hidden resource nodes
    TINKERING = "tinkering"  # Modify and repair items


# Skill categories for organization
GATHERING_SKILLS = {
    ProficiencySkill.MINING,
    ProficiencySkill.SKINNING,
    ProficiencySkill.HERBALISM,
    ProficiencySkill.LOGGING,
    ProficiencySkill.FISHING,
    ProficiencySkill.FORAGING,
}

CRAFTING_SKILLS = {
    ProficiencySkill.BLACKSMITHING,
    ProficiencySkill.ARMORSMITHING,
    ProficiencySkill.LEATHERWORKING,
    ProficiencySkill.TAILORING,
    ProficiencySkill.ALCHEMY,
    ProficiencySkill.ENCHANTING,
    ProficiencySkill.JEWELCRAFTING,
    ProficiencySkill.COOKING,
}

UTILITY_SKILLS = {
    ProficiencySkill.DISMANTLING,
    ProficiencySkill.PROSPECTING,
    ProficiencySkill.TINKERING,
}


# =============================================================================
# Skill Benefits
# =============================================================================


@dataclass
class SkillBenefits:
    """Calculated benefits based on skill level."""

    yield_multiplier: float = 1.0  # Multiplier for resource yields
    quality_bonus: float = 0.0  # Bonus chance for higher quality
    success_rate_bonus: float = 0.0  # Bonus to success chance
    critical_chance: float = 0.0  # Chance for critical success (2x yield)
    speed_multiplier: float = 1.0  # Speed bonus (lower = faster)
    efficiency_chance: float = 0.0  # Chance to not consume resources


def calculate_skill_benefits(effective_level: int) -> SkillBenefits:
    """
    Calculate benefits for a given effective skill level.

    Benefits scale logarithmically to prevent runaway power at high levels.
    """
    if effective_level <= 0:
        return SkillBenefits()

    # Base calculations using logarithmic scaling
    level_factor = math.log10(effective_level + 1)

    return SkillBenefits(
        # Yield: +5% per 10 levels, caps at +50%
        yield_multiplier=1.0 + min(0.5, effective_level * 0.005),
        # Quality: +2% per 10 levels, caps at +20%
        quality_bonus=min(0.2, effective_level * 0.002),
        # Success rate: +1% per 5 levels, caps at +20%
        success_rate_bonus=min(0.2, effective_level * 0.002),
        # Critical: starts at level 20, +0.5% per 10 levels, caps at 10%
        critical_chance=min(0.1, max(0, (effective_level - 20) * 0.0005)),
        # Speed: -1% per 20 levels, minimum 0.7 (30% faster)
        speed_multiplier=max(0.7, 1.0 - effective_level * 0.0005),
        # Efficiency: +0.5% per 25 levels, caps at 10%
        efficiency_chance=min(0.1, effective_level * 0.0004),
    )


# =============================================================================
# XP and Level Calculations
# =============================================================================


def calculate_xp_for_skill_level(level: int) -> int:
    """Calculate XP required to reach a skill level."""
    if level <= 1:
        return 0
    # Quadratic scaling: level 2 = 100, level 10 = 10000, level 100 = 1000000
    return level * level * 100


def calculate_total_xp_for_skill_level(level: int) -> int:
    """Calculate total XP needed from level 1 to reach target level."""
    total = 0
    for lvl in range(2, level + 1):
        total += calculate_xp_for_skill_level(lvl)
    return total


def get_skill_level_from_xp(total_xp: int) -> int:
    """Determine skill level from total XP accumulated."""
    level = 1
    xp_spent = 0
    while True:
        next_level_xp = calculate_xp_for_skill_level(level + 1)
        if xp_spent + next_level_xp > total_xp:
            break
        xp_spent += next_level_xp
        level += 1
        if level >= 100:  # Cap at level 100
            break
    return level


# =============================================================================
# Proficiency Entry
# =============================================================================


@dataclass
class ProficiencyEntry:
    """Tracking data for a single proficiency skill."""

    skill: ProficiencySkill
    current_xp: int = 0
    base_level: int = 1  # Calculated from XP
    racial_bonus: int = 0  # Bonus from race
    class_bonus: int = 0  # Bonus from class
    equipment_bonus: int = 0  # Bonus from gear
    buff_bonus: int = 0  # Temporary bonus from buffs

    # Statistics
    times_used: int = 0
    critical_successes: int = 0
    items_produced: int = 0

    @property
    def effective_level(self) -> int:
        """Total effective level including all bonuses."""
        return (
            self.base_level
            + self.racial_bonus
            + self.class_bonus
            + self.equipment_bonus
            + self.buff_bonus
        )

    @property
    def benefits(self) -> SkillBenefits:
        """Get calculated benefits for this skill."""
        return calculate_skill_benefits(self.effective_level)

    def add_xp(self, amount: int) -> bool:
        """
        Add XP to this skill.

        Returns True if the skill leveled up.
        """
        old_level = self.base_level
        self.current_xp += amount
        self.base_level = get_skill_level_from_xp(self.current_xp)
        return self.base_level > old_level

    def xp_to_next_level(self) -> int:
        """Calculate XP remaining to next level."""
        if self.base_level >= 100:
            return 0
        next_level_total = calculate_total_xp_for_skill_level(self.base_level + 1)
        return max(0, next_level_total - self.current_xp)

    def xp_progress_percent(self) -> float:
        """Calculate percentage progress to next level."""
        if self.base_level >= 100:
            return 100.0
        current_level_xp = calculate_total_xp_for_skill_level(self.base_level)
        next_level_xp = calculate_total_xp_for_skill_level(self.base_level + 1)
        level_range = next_level_xp - current_level_xp
        if level_range <= 0:
            return 100.0
        progress = self.current_xp - current_level_xp
        return min(100.0, (progress / level_range) * 100)


# =============================================================================
# Proficiency Data Component
# =============================================================================


@dataclass
class ProficiencyData(ComponentData):
    """
    Player's proficiency skills tracking.

    Stores all skill progress and provides methods for skill usage.
    """

    skills: Dict[str, ProficiencyEntry] = field(default_factory=dict)

    # Global statistics
    total_xp_earned: int = 0
    highest_skill_level: int = 1

    def get_skill(self, skill: ProficiencySkill) -> ProficiencyEntry:
        """Get or create a proficiency entry for a skill."""
        skill_key = skill.value
        if skill_key not in self.skills:
            self.skills[skill_key] = ProficiencyEntry(skill=skill)
        return self.skills[skill_key]

    def set_racial_bonus(self, skill: ProficiencySkill, bonus: int) -> None:
        """Set racial bonus for a skill."""
        entry = self.get_skill(skill)
        entry.racial_bonus = bonus

    def set_class_bonus(self, skill: ProficiencySkill, bonus: int) -> None:
        """Set class bonus for a skill."""
        entry = self.get_skill(skill)
        entry.class_bonus = bonus

    def add_skill_xp(self, skill: ProficiencySkill, amount: int) -> bool:
        """
        Add XP to a skill.

        Returns True if the skill leveled up.
        """
        entry = self.get_skill(skill)
        self.total_xp_earned += amount
        leveled = entry.add_xp(amount)
        if entry.base_level > self.highest_skill_level:
            self.highest_skill_level = entry.base_level
        return leveled

    def get_effective_level(self, skill: ProficiencySkill) -> int:
        """Get the effective level for a skill."""
        return self.get_skill(skill).effective_level

    def get_benefits(self, skill: ProficiencySkill) -> SkillBenefits:
        """Get calculated benefits for a skill."""
        return self.get_skill(skill).benefits

    def record_use(
        self,
        skill: ProficiencySkill,
        items_produced: int = 1,
        was_critical: bool = False,
    ) -> None:
        """Record usage of a skill for statistics."""
        entry = self.get_skill(skill)
        entry.times_used += 1
        entry.items_produced += items_produced
        if was_critical:
            entry.critical_successes += 1

    def get_all_skills_summary(self) -> List[Dict]:
        """Get summary of all skills with levels."""
        summaries = []
        for skill in ProficiencySkill:
            entry = self.get_skill(skill)
            summaries.append(
                {
                    "skill": skill.value,
                    "base_level": entry.base_level,
                    "effective_level": entry.effective_level,
                    "xp": entry.current_xp,
                    "times_used": entry.times_used,
                }
            )
        return summaries

    def apply_racial_bonuses(self, bonuses: Dict[str, int]) -> None:
        """Apply racial proficiency bonuses from race definition."""
        for skill_name, bonus in bonuses.items():
            try:
                skill = ProficiencySkill(skill_name)
                self.set_racial_bonus(skill, bonus)
            except ValueError:
                pass  # Skip invalid skill names

    def apply_class_bonuses(self, bonuses: Dict[str, int]) -> None:
        """Apply class proficiency bonuses from class definition."""
        for skill_name, bonus in bonuses.items():
            try:
                skill = ProficiencySkill(skill_name)
                self.set_class_bonus(skill, bonus)
            except ValueError:
                pass  # Skip invalid skill names


# =============================================================================
# XP Award Amounts
# =============================================================================

# Base XP awards for different activities
GATHERING_XP_BASE = 10  # Per successful gather
CRAFTING_XP_BASE = 25  # Per item crafted
DISMANTLING_XP_BASE = 5  # Per item dismantled
FISHING_XP_BASE = 15  # Per fish caught
COOKING_XP_BASE = 20  # Per dish cooked


def calculate_activity_xp(
    base_xp: int,
    difficulty_level: int,
    player_skill_level: int,
    quality_multiplier: float = 1.0,
) -> int:
    """
    Calculate XP award for an activity.

    XP is reduced if player level greatly exceeds difficulty.
    XP is boosted slightly for challenging content.
    """
    level_diff = player_skill_level - difficulty_level

    if level_diff > 10:
        # Trivial content gives minimal XP
        modifier = 0.25
    elif level_diff > 5:
        # Easy content gives reduced XP
        modifier = 0.5
    elif level_diff >= -5:
        # Appropriate level content
        modifier = 1.0
    else:
        # Challenging content gives bonus XP
        modifier = 1.25

    return max(1, int(base_xp * modifier * quality_multiplier))


# =============================================================================
# Default Race Proficiency Bonuses
# =============================================================================

# These are applied when a character is created based on their race
DEFAULT_RACE_PROFICIENCY_BONUSES: Dict[str, Dict[str, int]] = {
    "human": {
        # Humans are versatile, small bonuses to many skills
        "blacksmithing": 5,
        "tailoring": 5,
        "cooking": 5,
    },
    "elf": {
        # Elves excel at nature and magic
        "herbalism": 10,
        "enchanting": 10,
        "foraging": 5,
    },
    "dwarf": {
        # Dwarves are master miners and smiths
        "mining": 15,
        "blacksmithing": 10,
        "armorsmithing": 10,
        "jewelcrafting": 5,
    },
    "halfling": {
        # Halflings are skilled at cooking and gathering
        "cooking": 15,
        "foraging": 10,
        "fishing": 5,
    },
    "orc": {
        # Orcs are skilled at skinning and leatherwork
        "skinning": 15,
        "leatherworking": 10,
        "dismantling": 5,
    },
}


# =============================================================================
# Default Class Proficiency Bonuses
# =============================================================================

# These are applied when a character is created based on their class
DEFAULT_CLASS_PROFICIENCY_BONUSES: Dict[str, Dict[str, int]] = {
    "warrior": {
        "blacksmithing": 10,
        "armorsmithing": 10,
        "dismantling": 5,
    },
    "mage": {
        "enchanting": 15,
        "alchemy": 10,
        "herbalism": 5,
    },
    "cleric": {
        "alchemy": 10,
        "herbalism": 10,
        "cooking": 5,
    },
    "rogue": {
        "dismantling": 10,
        "prospecting": 10,
        "tinkering": 10,
    },
    "ranger": {
        "skinning": 10,
        "herbalism": 10,
        "foraging": 10,
        "fishing": 5,
    },
}
