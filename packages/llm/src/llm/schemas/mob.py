"""
Mob Generation Schemas

Pydantic models for LLM-generated creature/NPC content.
"""

from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class MobDisposition(str, Enum):
    """How the mob behaves toward players."""

    HOSTILE = "hostile"  # Attacks on sight
    AGGRESSIVE = "aggressive"  # Attacks if player is lower level
    NEUTRAL = "neutral"  # Only attacks if provoked
    FRIENDLY = "friendly"  # Will not attack, may assist player
    FEARFUL = "fearful"  # Flees from players
    MERCHANT = "merchant"  # Shopkeeper NPC


class DamageType(str, Enum):
    """Types of damage for combat."""

    SLASHING = "slashing"
    PIERCING = "piercing"
    BLUDGEONING = "bludgeoning"
    FIRE = "fire"
    COLD = "cold"
    LIGHTNING = "lightning"
    ACID = "acid"
    POISON = "poison"
    NECROTIC = "necrotic"
    RADIANT = "radiant"
    PSYCHIC = "psychic"


class CombatStyle(str, Enum):
    """How the mob fights in combat."""

    BERSERKER = "berserker"  # All-out offense
    DEFENSIVE = "defensive"  # Focuses on blocking/parrying
    TACTICIAN = "tactician"  # Balanced approach
    CASTER = "caster"  # Prefers spells/abilities
    SKIRMISHER = "skirmisher"  # Hit and run
    SUPPORT = "support"  # Buffs allies, debuffs enemies


class MobAbility(BaseModel):
    """A special ability the mob can use."""

    name: str = Field(
        ..., min_length=2, max_length=30, description="Name of the ability"
    )
    description: str = Field(
        ..., max_length=100, description="What the ability does in flavor terms"
    )
    damage_type: Optional[DamageType] = Field(
        default=None, description="Damage type if ability deals damage"
    )
    cooldown_seconds: int = Field(
        default=0, ge=0, le=300, description="Cooldown between uses in seconds"
    )
    is_aoe: bool = Field(
        default=False, description="Whether ability affects multiple targets"
    )
    healing: bool = Field(default=False, description="Whether ability heals")
    buff: bool = Field(
        default=False, description="Whether ability provides a beneficial effect"
    )
    debuff: bool = Field(
        default=False, description="Whether ability inflicts a harmful effect"
    )


class GeneratedMob(BaseModel):
    """Schema for LLM-generated mob content."""

    name: str = Field(
        ...,
        min_length=3,
        max_length=40,
        description="Mob name with article (e.g., 'a flame-scarred orc')",
    )
    keywords: List[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Keywords for targeting (parts of the name)",
    )
    short_description: str = Field(
        ...,
        min_length=10,
        max_length=80,
        description="One-line description when seen in room",
    )
    long_description: str = Field(
        ...,
        min_length=30,
        max_length=400,
        description="Full description when examined",
    )
    level: int = Field(..., ge=1, le=50, description="Mob level for stat scaling")
    disposition: MobDisposition = Field(
        ..., description="How the mob behaves toward players"
    )
    combat_style: CombatStyle = Field(
        default=CombatStyle.TACTICIAN, description="Combat behavior pattern"
    )
    health_multiplier: float = Field(
        default=1.0,
        ge=0.5,
        le=3.0,
        description="Multiplier for base health (1.0 = normal)",
    )
    damage_dice: str = Field(
        ...,
        pattern=r"^\d+d\d+(\+\d+)?$",
        description="Damage dice in D&D notation (e.g., '1d6', '2d4+2')",
    )
    damage_type: DamageType = Field(
        default=DamageType.BLUDGEONING, description="Primary damage type"
    )
    abilities: List[MobAbility] = Field(
        default_factory=list, max_length=4, description="Special abilities"
    )
    loot_tier: Literal["common", "uncommon", "rare", "epic", "legendary"] = Field(
        default="common", description="Quality tier of loot drops"
    )
    dialogue_style: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Speech pattern description for dialogue generation",
    )
    is_boss: bool = Field(default=False, description="Whether this is a boss mob")
    is_unique: bool = Field(
        default=False, description="Whether only one can exist at a time"
    )
    faction: Optional[str] = Field(
        default=None, max_length=30, description="Faction this mob belongs to"
    )


class MobGenerationContext(BaseModel):
    """Context provided to LLM for mob generation."""

    zone_theme: str = Field(..., description="Theme description of the zone")
    room_description: str = Field(
        ..., max_length=500, description="Description of the room where mob spawns"
    )
    target_level: int = Field(
        ..., ge=1, le=50, description="Target level for the mob"
    )
    disposition_hint: MobDisposition = Field(
        default=MobDisposition.HOSTILE, description="Suggested disposition"
    )
    existing_mob_types: List[str] = Field(
        default_factory=list, description="Mob types already in this area"
    )
    faction_hints: List[str] = Field(
        default_factory=list, description="Factions active in this area"
    )
    combat_style_hint: Optional[CombatStyle] = Field(
        default=None, description="Suggested combat style"
    )
    is_boss_request: bool = Field(
        default=False, description="Whether generating a boss mob"
    )
    boss_phase: Optional[int] = Field(
        default=None, ge=1, le=3, description="Boss phase number if applicable"
    )
    vocabulary_hints: List[str] = Field(
        default_factory=list, description="Theme-appropriate words"
    )
