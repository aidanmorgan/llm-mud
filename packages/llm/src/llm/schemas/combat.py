"""
Combat Narration Schemas

Pydantic models for LLM-generated combat descriptions.
"""

from typing import Optional

from pydantic import BaseModel, Field

from .mob import DamageType


class CombatNarration(BaseModel):
    """Schema for LLM-generated combat text."""

    attack_description: str = Field(
        ...,
        min_length=10,
        max_length=150,
        description="Description of the attack action",
    )
    damage_description: str = Field(
        ...,
        min_length=5,
        max_length=100,
        description="Description of damage dealt/taken",
    )
    flavor_text: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Optional additional flavor/atmosphere",
    )
    attacker_emote: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Attacker's expression/action during attack",
    )
    defender_reaction: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Defender's visible reaction to the hit",
    )
    sound_effect: Optional[str] = Field(
        default=None,
        max_length=30,
        description="Sound of the attack (e.g., 'CLANG!', 'THUD')",
    )


class CombatNarrationContext(BaseModel):
    """Context provided to LLM for combat narration."""

    attacker_name: str = Field(..., description="Name of the attacker")
    attacker_race: str = Field(..., description="Race of the attacker")
    attacker_class: Optional[str] = Field(
        default=None, description="Class if applicable"
    )
    attacker_weapon: Optional[str] = Field(
        default=None, description="Weapon being used"
    )
    attacker_weapon_type: Optional[str] = Field(
        default=None, description="Type of weapon (sword, axe, etc.)"
    )
    defender_name: str = Field(..., description="Name of the defender")
    defender_race: str = Field(..., description="Race of the defender")
    defender_armor: Optional[str] = Field(
        default=None, description="Armor being worn"
    )
    damage_amount: int = Field(..., ge=0, description="Damage dealt")
    damage_type: DamageType = Field(..., description="Type of damage")
    is_critical: bool = Field(default=False, description="Whether this is a crit")
    is_miss: bool = Field(default=False, description="Whether attack missed")
    is_killing_blow: bool = Field(
        default=False, description="Whether this kills the defender"
    )
    combat_round: int = Field(
        ..., ge=1, description="Current round of combat"
    )
    attacker_health_percent: int = Field(
        ..., ge=0, le=100, description="Attacker's remaining HP %"
    )
    defender_health_percent: int = Field(
        ..., ge=0, le=100, description="Defender's remaining HP %"
    )
    skill_used: Optional[str] = Field(
        default=None, description="Special skill/ability used"
    )
    environment_hint: Optional[str] = Field(
        default=None, description="Room environment for context"
    )


class SkillNarration(BaseModel):
    """Schema for skill/spell use narration."""

    casting_description: str = Field(
        ...,
        max_length=150,
        description="Description of skill/spell activation",
    )
    effect_description: str = Field(
        ...,
        max_length=100,
        description="Description of the effect",
    )
    target_reaction: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Target's reaction to the effect",
    )
    visual_effect: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Visual manifestation of the skill",
    )


class DeathNarration(BaseModel):
    """Schema for death/defeat narration."""

    death_description: str = Field(
        ...,
        max_length=200,
        description="Description of the killing blow's effect",
    )
    final_words: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Dying words if applicable",
    )
    aftermath: Optional[str] = Field(
        default=None,
        max_length=80,
        description="What happens after death",
    )
    loot_hint: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Hint about loot dropped",
    )
