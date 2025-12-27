"""
Skills & Spells Components

Professional implementation using:
- Enums for type safety
- Dataclasses with proper typing
- Protocol for extensible effect handling
- NamedTuple for immutable results
- @singledispatch for polymorphic effect application
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import singledispatch
from typing import (
    Dict,
    List,
    NamedTuple,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
    runtime_checkable,
)

from core import ComponentData, EntityId

logger = logging.getLogger(__name__)


# =============================================================================
# Enums - Type-safe categorization
# =============================================================================


class SkillCategory(str, Enum):
    """Categories of skills for organization and filtering."""

    COMBAT = "combat"
    MAGIC = "magic"
    HEALING = "healing"
    UTILITY = "utility"
    PASSIVE = "passive"


class TargetType(str, Enum):
    """Valid targeting modes for skills."""

    SELF = "self"  # Can only target self
    SINGLE_ENEMY = "single_enemy"  # One hostile target
    SINGLE_ALLY = "single_ally"  # One friendly target
    SINGLE_ANY = "single_any"  # Any single target
    AREA_ENEMIES = "area_enemies"  # All enemies in room
    AREA_ALLIES = "area_allies"  # All allies in room
    AREA_ALL = "area_all"  # Everyone in room


class EffectType(str, Enum):
    """Types of effects that skills can apply."""

    DAMAGE = "damage"
    HEAL = "heal"
    BUFF = "buff"
    DEBUFF = "debuff"
    DOT = "dot"  # Damage over time
    HOT = "hot"  # Heal over time
    RESTORE_MANA = "restore_mana"
    RESTORE_STAMINA = "restore_stamina"
    STUN = "stun"
    ROOT = "root"  # Immobilize
    SILENCE = "silence"  # Prevent casting
    DISPEL = "dispel"


class DamageSchool(str, Enum):
    """Damage types for magical effects."""

    PHYSICAL = "physical"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    POISON = "poison"
    HOLY = "holy"
    SHADOW = "shadow"
    ARCANE = "arcane"


class SkillState(str, Enum):
    """State of a skill for a particular entity."""

    READY = "ready"
    ON_COOLDOWN = "on_cooldown"
    INSUFFICIENT_MANA = "insufficient_mana"
    INSUFFICIENT_STAMINA = "insufficient_stamina"


# =============================================================================
# NamedTuples - Immutable result types
# =============================================================================


class SkillResult(NamedTuple):
    """Immutable result of a skill execution attempt."""

    success: bool
    message: str
    damage_dealt: int = 0
    healing_done: int = 0
    effects_applied: Tuple[str, ...] = ()
    mana_spent: int = 0
    stamina_spent: int = 0


class EffectTick(NamedTuple):
    """Result of a single effect tick (DOT/HOT)."""

    effect_id: str
    target_id: EntityId
    value: int
    remaining_ticks: int
    message: str


class CooldownInfo(NamedTuple):
    """Information about a skill's cooldown state."""

    skill_id: str
    remaining_seconds: float
    total_seconds: float

    @property
    def is_ready(self) -> bool:
        return self.remaining_seconds <= 0

    @property
    def percent_remaining(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return self.remaining_seconds / self.total_seconds


# =============================================================================
# Effect Definitions - Using dataclasses for clean structure
# =============================================================================


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """
    Base definition for a skill effect.

    Using frozen=True for immutability (definitions shouldn't change).
    Using slots=True for memory efficiency.
    """

    effect_type: EffectType
    base_value: int = 0
    scaling_stat: Optional[str] = None  # Attribute that scales the effect
    scaling_factor: float = 0.0  # How much the stat contributes


@dataclass(frozen=True, slots=True)
class DamageEffect(EffectDefinition):
    """Instant damage effect."""

    damage_school: DamageSchool = DamageSchool.PHYSICAL
    can_crit: bool = True
    crit_multiplier: float = 2.0

    def __post_init__(self):
        # Validate that effect_type is correct
        object.__setattr__(self, "effect_type", EffectType.DAMAGE)


@dataclass(frozen=True, slots=True)
class HealEffect(EffectDefinition):
    """Instant healing effect."""

    can_crit: bool = True
    crit_multiplier: float = 1.5

    def __post_init__(self):
        object.__setattr__(self, "effect_type", EffectType.HEAL)


@dataclass(frozen=True, slots=True)
class BuffEffect(EffectDefinition):
    """Stat-modifying buff/debuff effect."""

    stat_modified: str = "armor_class"
    duration_seconds: int = 60
    is_debuff: bool = False
    stacks: bool = False
    max_stacks: int = 1

    def __post_init__(self):
        effect_type = EffectType.DEBUFF if self.is_debuff else EffectType.BUFF
        object.__setattr__(self, "effect_type", effect_type)


@dataclass(frozen=True, slots=True)
class PeriodicEffect(EffectDefinition):
    """Damage or healing over time effect."""

    duration_seconds: int = 12
    tick_interval_seconds: int = 3
    damage_school: DamageSchool = DamageSchool.PHYSICAL  # For DOTs

    @property
    def total_ticks(self) -> int:
        if self.tick_interval_seconds <= 0:
            return 0
        return self.duration_seconds // self.tick_interval_seconds


@dataclass(frozen=True, slots=True)
class ControlEffect(EffectDefinition):
    """Crowd control effect (stun, root, silence)."""

    duration_seconds: int = 3
    breaks_on_damage: bool = False
    diminishing_returns: bool = True


# Type alias for any effect
AnyEffect = Union[DamageEffect, HealEffect, BuffEffect, PeriodicEffect, ControlEffect, EffectDefinition]


# =============================================================================
# Skill Definition - The template for a skill
# =============================================================================


@dataclass(frozen=True)
class SkillDefinition:
    """
    Immutable definition of a skill/spell.

    This is the template - actual skill usage creates SkillInstance.
    Loaded from YAML and cached in the skill registry.
    """

    skill_id: str
    name: str
    description: str
    category: SkillCategory
    target_type: TargetType

    # Resource costs
    mana_cost: int = 0
    stamina_cost: int = 0
    health_cost: int = 0  # For life-tap abilities

    # Cooldown
    cooldown_seconds: float = 0.0

    # Requirements
    level_requirement: int = 1
    class_requirements: Tuple[str, ...] = ()  # Empty = any class

    # Effects (tuple for immutability)
    effects: Tuple[AnyEffect, ...] = ()

    # Range and targeting
    range_rooms: int = 0  # 0 = same room only
    requires_line_of_sight: bool = True

    # Casting
    cast_time_seconds: float = 0.0  # 0 = instant
    can_be_interrupted: bool = True

    # Flags
    is_passive: bool = False
    is_hidden: bool = False  # Don't show in skill list

    def can_use(self, caster_level: int, caster_class: str) -> Tuple[bool, str]:
        """Check if a caster can use this skill."""
        if caster_level < self.level_requirement:
            return False, f"Requires level {self.level_requirement}"

        if self.class_requirements and caster_class not in self.class_requirements:
            classes = ", ".join(self.class_requirements)
            return False, f"Requires class: {classes}"

        return True, ""


# =============================================================================
# Active Effects - Applied to entities
# =============================================================================


@dataclass
class ActiveEffect:
    """
    An effect currently active on an entity.

    This is mutable (unlike definitions) because it tracks state.
    """

    effect_id: str  # Unique instance ID
    skill_id: str  # Which skill applied this
    source_id: EntityId  # Who cast it
    effect_type: EffectType
    stat_modified: Optional[str] = None
    value: int = 0
    applied_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    tick_interval_seconds: int = 0
    last_tick_at: Optional[datetime] = None
    stacks: int = 1
    max_stacks: int = 1

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() >= self.expires_at

    @property
    def remaining_seconds(self) -> float:
        if self.expires_at is None:
            return float("inf")
        delta = self.expires_at - datetime.utcnow()
        return max(0.0, delta.total_seconds())

    @property
    def should_tick(self) -> bool:
        if self.tick_interval_seconds <= 0:
            return False
        if self.last_tick_at is None:
            return True
        elapsed = (datetime.utcnow() - self.last_tick_at).total_seconds()
        return elapsed >= self.tick_interval_seconds

    def add_stack(self) -> bool:
        """Add a stack, return True if successful."""
        if self.stacks >= self.max_stacks:
            return False
        self.stacks += 1
        return True

    def record_tick(self) -> None:
        """Record that this effect just ticked."""
        self.last_tick_at = datetime.utcnow()


# =============================================================================
# Component Data Classes
# =============================================================================


@dataclass
class SkillSetData(ComponentData):
    """
    Tracks an entity's known skills and their states.

    This is the main component attached to entities that can use skills.
    """

    # Known skills: skill_id -> proficiency level (0-100)
    known_skills: Dict[str, int] = field(default_factory=dict)

    # Active cooldowns: skill_id -> expires_at
    cooldowns: Dict[str, datetime] = field(default_factory=dict)

    # Skill slots for quick access (optional hotbar)
    skill_slots: Dict[int, str] = field(default_factory=dict)

    # Currently casting (for cast-time spells)
    casting_skill_id: Optional[str] = None
    casting_started_at: Optional[datetime] = None
    casting_target_id: Optional[EntityId] = None

    def knows_skill(self, skill_id: str) -> bool:
        """Check if entity knows a skill."""
        return skill_id in self.known_skills

    def get_proficiency(self, skill_id: str) -> int:
        """Get proficiency level in a skill (0-100)."""
        return self.known_skills.get(skill_id, 0)

    def learn_skill(self, skill_id: str, initial_level: int = 1) -> bool:
        """Learn a new skill. Returns False if already known."""
        if skill_id in self.known_skills:
            return False
        self.known_skills[skill_id] = min(100, max(1, initial_level))
        return True

    def improve_skill(self, skill_id: str, amount: int = 1) -> int:
        """Improve skill proficiency. Returns new level."""
        if skill_id not in self.known_skills:
            return 0
        new_level = min(100, self.known_skills[skill_id] + amount)
        self.known_skills[skill_id] = new_level
        return new_level

    def get_cooldown_info(self, skill_id: str, total_cooldown: float) -> CooldownInfo:
        """Get cooldown information for a skill."""
        expires_at = self.cooldowns.get(skill_id)
        if expires_at is None:
            return CooldownInfo(skill_id, 0.0, total_cooldown)

        remaining = (expires_at - datetime.utcnow()).total_seconds()
        return CooldownInfo(skill_id, max(0.0, remaining), total_cooldown)

    def is_on_cooldown(self, skill_id: str) -> bool:
        """Check if a skill is on cooldown."""
        expires_at = self.cooldowns.get(skill_id)
        if expires_at is None:
            return False
        return datetime.utcnow() < expires_at

    def set_cooldown(self, skill_id: str, seconds: float) -> None:
        """Put a skill on cooldown."""
        if seconds <= 0:
            self.cooldowns.pop(skill_id, None)
        else:
            self.cooldowns[skill_id] = datetime.utcnow() + timedelta(seconds=seconds)

    def clear_expired_cooldowns(self) -> int:
        """Remove expired cooldowns. Returns count removed."""
        now = datetime.utcnow()
        expired = [sid for sid, exp in self.cooldowns.items() if exp <= now]
        for sid in expired:
            del self.cooldowns[sid]
        return len(expired)

    def start_casting(self, skill_id: str, target_id: Optional[EntityId]) -> None:
        """Begin casting a spell."""
        self.casting_skill_id = skill_id
        self.casting_started_at = datetime.utcnow()
        self.casting_target_id = target_id

    def cancel_casting(self) -> Optional[str]:
        """Cancel current casting. Returns skill_id that was cancelled."""
        skill_id = self.casting_skill_id
        self.casting_skill_id = None
        self.casting_started_at = None
        self.casting_target_id = None
        return skill_id

    @property
    def is_casting(self) -> bool:
        return self.casting_skill_id is not None


@dataclass
class ActiveEffectsData(ComponentData):
    """
    Tracks all active effects (buffs/debuffs) on an entity.

    Separated from SkillSetData because NPCs/mobs can have effects
    but may not have a full skill set.
    """

    effects: List[ActiveEffect] = field(default_factory=list)

    def add_effect(self, effect: ActiveEffect) -> None:
        """Add a new effect, handling stacking logic."""
        # Check for existing effect of same type from same skill
        for existing in self.effects:
            if existing.skill_id == effect.skill_id and existing.effect_type == effect.effect_type:
                if existing.max_stacks > 1:
                    existing.add_stack()
                    existing.expires_at = effect.expires_at  # Refresh duration
                    return
                else:
                    # Replace with new effect (refresh)
                    existing.expires_at = effect.expires_at
                    existing.value = effect.value
                    return

        self.effects.append(effect)

    def remove_effect(self, effect_id: str) -> Optional[ActiveEffect]:
        """Remove an effect by ID. Returns the removed effect."""
        for i, effect in enumerate(self.effects):
            if effect.effect_id == effect_id:
                return self.effects.pop(i)
        return None

    def remove_effects_by_skill(self, skill_id: str) -> int:
        """Remove all effects from a skill. Returns count removed."""
        original_count = len(self.effects)
        self.effects = [e for e in self.effects if e.skill_id != skill_id]
        return original_count - len(self.effects)

    def remove_effects_by_type(self, effect_type: EffectType) -> int:
        """Remove all effects of a type. Returns count removed."""
        original_count = len(self.effects)
        self.effects = [e for e in self.effects if e.effect_type != effect_type]
        return original_count - len(self.effects)

    def clear_expired(self) -> List[ActiveEffect]:
        """Remove expired effects. Returns list of removed effects."""
        expired = [e for e in self.effects if e.is_expired]
        self.effects = [e for e in self.effects if not e.is_expired]
        return expired

    def get_effects_to_tick(self) -> List[ActiveEffect]:
        """Get effects that should tick this update."""
        return [e for e in self.effects if e.should_tick and not e.is_expired]

    def get_stat_modifier(self, stat: str) -> int:
        """Get total modifier to a stat from all effects."""
        total = 0
        for effect in self.effects:
            if effect.stat_modified == stat and not effect.is_expired:
                if effect.effect_type == EffectType.BUFF:
                    total += effect.value * effect.stacks
                elif effect.effect_type == EffectType.DEBUFF:
                    total -= effect.value * effect.stacks
        return total

    def has_effect_type(self, effect_type: EffectType) -> bool:
        """Check if entity has any effect of this type."""
        return any(e.effect_type == effect_type and not e.is_expired for e in self.effects)

    def get_effects_by_type(self, effect_type: EffectType) -> List[ActiveEffect]:
        """Get all active effects of a type."""
        return [e for e in self.effects if e.effect_type == effect_type and not e.is_expired]

    @property
    def is_stunned(self) -> bool:
        return self.has_effect_type(EffectType.STUN)

    @property
    def is_rooted(self) -> bool:
        return self.has_effect_type(EffectType.ROOT)

    @property
    def is_silenced(self) -> bool:
        return self.has_effect_type(EffectType.SILENCE)


# =============================================================================
# Effect Application - Using @singledispatch for polymorphism
# =============================================================================


@singledispatch
def calculate_effect_value(effect: EffectDefinition, caster_stats: Dict[str, int], proficiency: int) -> int:
    """
    Calculate the actual value of an effect based on caster stats.

    Uses @singledispatch for clean polymorphic handling of different effect types.
    """
    base = effect.base_value

    # Apply stat scaling
    if effect.scaling_stat and effect.scaling_stat in caster_stats:
        stat_value = caster_stats[effect.scaling_stat]
        base += int(stat_value * effect.scaling_factor)

    # Apply proficiency bonus (up to 50% at max proficiency)
    proficiency_bonus = 1.0 + (proficiency / 200.0)
    return int(base * proficiency_bonus)


@calculate_effect_value.register(DamageEffect)
def _calculate_damage(effect: DamageEffect, caster_stats: Dict[str, int], proficiency: int) -> int:
    """Calculate damage with potential crit."""
    import random

    base = calculate_effect_value.dispatch(EffectDefinition)(effect, caster_stats, proficiency)

    # Check for crit (10% base + 0.5% per proficiency)
    if effect.can_crit:
        crit_chance = 10 + (proficiency * 0.5)
        if random.randint(1, 100) <= crit_chance:
            base = int(base * effect.crit_multiplier)

    return base


@calculate_effect_value.register(HealEffect)
def _calculate_heal(effect: HealEffect, caster_stats: Dict[str, int], proficiency: int) -> int:
    """Calculate healing with potential crit."""
    import random

    base = calculate_effect_value.dispatch(EffectDefinition)(effect, caster_stats, proficiency)

    # Healing crit chance (8% base + 0.4% per proficiency)
    if effect.can_crit:
        crit_chance = 8 + (proficiency * 0.4)
        if random.randint(1, 100) <= crit_chance:
            base = int(base * effect.crit_multiplier)

    return base


# =============================================================================
# Skill Registry Protocol
# =============================================================================


@runtime_checkable
class SkillRegistry(Protocol):
    """Protocol for skill registry implementations."""

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """Get a skill definition by ID."""
        ...

    def get_by_category(self, category: SkillCategory) -> Sequence[SkillDefinition]:
        """Get all skills in a category."""
        ...

    def get_learnable_for_class(self, class_name: str, level: int) -> Sequence[SkillDefinition]:
        """Get skills a class can learn at a level."""
        ...


# =============================================================================
# Skill Validation - Pure functions for validation logic
# =============================================================================


def validate_skill_use(
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    skill_set: SkillSetData,
    effects: Optional[ActiveEffectsData] = None,
) -> Tuple[bool, str]:
    """
    Validate if a skill can be used.

    Returns (can_use, error_message).
    Pure function - no side effects.
    """
    # Check if known
    if not skill_set.knows_skill(skill.skill_id):
        return False, f"You don't know {skill.name}."

    # Check cooldown
    if skill_set.is_on_cooldown(skill.skill_id):
        info = skill_set.get_cooldown_info(skill.skill_id, skill.cooldown_seconds)
        return False, f"{skill.name} is on cooldown ({info.remaining_seconds:.1f}s remaining)."

    # Check mana
    current_mana = caster_stats.get("current_mana", 0)
    if skill.mana_cost > current_mana:
        return False, f"Not enough mana ({skill.mana_cost} required, {current_mana} available)."

    # Check stamina
    current_stamina = caster_stats.get("current_stamina", 0)
    if skill.stamina_cost > current_stamina:
        return False, f"Not enough stamina ({skill.stamina_cost} required, {current_stamina} available)."

    # Check if silenced (for magic skills)
    if effects and effects.is_silenced and skill.category == SkillCategory.MAGIC:
        return False, "You are silenced and cannot cast spells."

    # Check if stunned
    if effects and effects.is_stunned:
        return False, "You are stunned and cannot act."

    # Check if already casting
    if skill_set.is_casting:
        return False, "You are already casting a spell."

    return True, ""


def calculate_skill_effectiveness(
    skill: SkillDefinition,
    proficiency: int,
    caster_stats: Dict[str, int],
) -> float:
    """
    Calculate skill effectiveness multiplier.

    Returns a multiplier (1.0 = normal, >1.0 = improved).
    Pure function.
    """
    # Base effectiveness from proficiency (50% at 0, 150% at 100)
    base = 0.5 + (proficiency / 100.0)

    # Intelligence bonus for magic
    if skill.category == SkillCategory.MAGIC:
        int_mod = (caster_stats.get("intelligence", 10) - 10) / 20.0
        base += int_mod

    # Wisdom bonus for healing
    elif skill.category == SkillCategory.HEALING:
        wis_mod = (caster_stats.get("wisdom", 10) - 10) / 20.0
        base += wis_mod

    # Strength/Dex bonus for combat
    elif skill.category == SkillCategory.COMBAT:
        str_mod = (caster_stats.get("strength", 10) - 10) / 40.0
        dex_mod = (caster_stats.get("dexterity", 10) - 10) / 40.0
        base += str_mod + dex_mod

    return max(0.5, base)  # Minimum 50% effectiveness
