"""
Item Generation Schemas

Pydantic models for LLM-generated item content.
"""

from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    """Types of items."""

    WEAPON = "weapon"
    ARMOR = "armor"
    CONSUMABLE = "consumable"
    CONTAINER = "container"
    KEY = "key"
    MISC = "misc"
    QUEST = "quest"


class ItemRarity(str, Enum):
    """Rarity tiers for items."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class WeaponType(str, Enum):
    """Weapon categories."""

    SWORD = "sword"
    AXE = "axe"
    MACE = "mace"
    HAMMER = "hammer"
    DAGGER = "dagger"
    SPEAR = "spear"
    STAFF = "staff"
    BOW = "bow"
    CROSSBOW = "crossbow"
    WAND = "wand"


class ArmorType(str, Enum):
    """Armor categories."""

    CLOTH = "cloth"
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"
    SHIELD = "shield"


class EquipmentSlot(str, Enum):
    """Where equipment can be worn."""

    HEAD = "head"
    NECK = "neck"
    TORSO = "torso"
    ARMS = "arms"
    HANDS = "hands"
    WAIST = "waist"
    LEGS = "legs"
    FEET = "feet"
    FINGER = "finger"
    WRIST = "wrist"
    ABOUT = "about"  # Cloaks, etc.
    MAIN_HAND = "main_hand"
    OFF_HAND = "off_hand"


class DamageType(str, Enum):
    """Types of damage."""

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


class WeaponStats(BaseModel):
    """Stats for a weapon item."""

    damage_dice: str = Field(
        ...,
        pattern=r"^\d+d\d+(\+\d+)?$",
        description="Damage in D&D notation (e.g., '1d8', '2d6+1')",
    )
    damage_type: DamageType = Field(..., description="Type of damage dealt")
    weapon_type: WeaponType = Field(..., description="Weapon category")
    two_handed: bool = Field(default=False, description="Requires both hands")
    hit_bonus: int = Field(default=0, ge=-5, le=10, description="Bonus to hit rolls")
    damage_bonus: int = Field(
        default=0, ge=-5, le=10, description="Bonus to damage rolls"
    )
    range: Optional[int] = Field(
        default=None, ge=1, le=100, description="Range in rooms for ranged weapons"
    )


class ArmorStats(BaseModel):
    """Stats for an armor item."""

    armor_bonus: int = Field(..., ge=0, le=20, description="AC bonus provided")
    armor_type: ArmorType = Field(..., description="Armor category")
    max_dex_bonus: Optional[int] = Field(
        default=None, ge=0, le=10, description="Maximum DEX bonus allowed"
    )
    spell_failure: int = Field(
        default=0, ge=0, le=100, description="Arcane spell failure chance"
    )


class ConsumableEffect(BaseModel):
    """Effect of a consumable item."""

    effect_type: Literal[
        "heal",
        "restore_mana",
        "restore_stamina",
        "cure_poison",
        "cure_disease",
        "buff",
        "food",
        "drink",
    ] = Field(..., description="Type of effect")
    effect_value: int = Field(..., ge=1, description="Magnitude of effect")
    duration_seconds: Optional[int] = Field(
        default=None, ge=1, le=3600, description="Duration for buffs"
    )
    buff_stat: Optional[str] = Field(
        default=None, description="Stat affected by buff"
    )


class MagicalProperty(BaseModel):
    """A magical property on an item."""

    name: str = Field(..., max_length=30, description="Property name")
    description: str = Field(..., max_length=100, description="What the property does")
    stat_bonus: Optional[str] = Field(
        default=None, description="Stat this affects (e.g., 'strength')"
    )
    bonus_value: int = Field(
        default=0, ge=-10, le=10, description="Bonus/penalty value"
    )
    damage_type_bonus: Optional[DamageType] = Field(
        default=None, description="Extra damage type"
    )
    resistance: Optional[DamageType] = Field(
        default=None, description="Resistance granted"
    )
    resistance_percent: int = Field(
        default=0, ge=0, le=100, description="Resistance percentage"
    )


class GeneratedItem(BaseModel):
    """Schema for LLM-generated item content."""

    name: str = Field(
        ...,
        min_length=3,
        max_length=40,
        description="Item name with article (e.g., 'a gleaming silver sword')",
    )
    keywords: List[str] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Keywords for targeting (parts of name)",
    )
    short_description: str = Field(
        ..., max_length=80, description="One-line description when on ground"
    )
    long_description: str = Field(
        ..., max_length=300, description="Full description when examined"
    )
    item_type: ItemType = Field(..., description="Category of item")
    rarity: ItemRarity = Field(default=ItemRarity.COMMON, description="Rarity tier")
    level_requirement: int = Field(
        default=1, ge=1, le=50, description="Minimum level to use"
    )
    value_multiplier: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Gold value multiplier"
    )
    weight: float = Field(
        default=1.0, ge=0.1, le=100.0, description="Weight in pounds"
    )
    equipment_slot: Optional[EquipmentSlot] = Field(
        default=None, description="Where item is equipped"
    )
    weapon_stats: Optional[WeaponStats] = Field(
        default=None, description="Stats if weapon"
    )
    armor_stats: Optional[ArmorStats] = Field(
        default=None, description="Stats if armor"
    )
    consumable_effect: Optional[ConsumableEffect] = Field(
        default=None, description="Effect if consumable"
    )
    magical_properties: List[MagicalProperty] = Field(
        default_factory=list, max_length=3, description="Magical enhancements"
    )
    is_quest_item: bool = Field(default=False, description="Cannot be dropped/sold")
    is_unique: bool = Field(
        default=False, description="Only one can exist at a time"
    )


class ItemGenerationContext(BaseModel):
    """Context provided to LLM for item generation."""

    zone_theme: str = Field(..., description="Theme of the zone")
    target_level: int = Field(..., ge=1, le=50, description="Target item level")
    target_rarity: ItemRarity = Field(
        default=ItemRarity.COMMON, description="Target rarity"
    )
    item_type_hint: Optional[ItemType] = Field(
        default=None, description="Suggested item type"
    )
    slot_hint: Optional[EquipmentSlot] = Field(
        default=None, description="Suggested equipment slot"
    )
    dropped_by: Optional[str] = Field(
        default=None, description="Mob that drops this item"
    )
    existing_item_names: List[str] = Field(
        default_factory=list, description="Names already used"
    )
    vocabulary_hints: List[str] = Field(
        default_factory=list, description="Theme-appropriate words"
    )
    is_boss_loot: bool = Field(
        default=False, description="Whether this is boss drop"
    )
