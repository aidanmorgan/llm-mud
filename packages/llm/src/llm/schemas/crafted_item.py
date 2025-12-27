"""
Crafted Item Generation Schemas

Pydantic models for LLM-generated crafted items with strict balance validation.
All stats are clamped to appropriate ranges based on level and rarity.
"""

from enum import Enum
from typing import List, Optional, Literal, Tuple, Dict

from pydantic import BaseModel, Field, model_validator

from .item import ItemType, ItemRarity, DamageType, EquipmentSlot


# =============================================================================
# Balance Constants
# =============================================================================

# Valid damage dice by level range (min_level, max_level) -> allowed dice
DAMAGE_DICE_BY_LEVEL: Dict[Tuple[int, int], List[str]] = {
    (1, 5): ["1d4", "1d4+1", "1d6"],
    (6, 10): ["1d6", "1d6+1", "1d8"],
    (11, 15): ["1d8", "1d8+1", "1d10"],
    (16, 20): ["1d10", "1d10+1", "2d6"],
    (21, 30): ["2d6", "2d6+1", "2d8"],
    (31, 40): ["2d8", "2d8+1", "2d10"],
    (41, 50): ["2d10", "2d10+1", "3d6"],
}

# Armor class range by level (min_level, max_level) -> (min_ac, max_ac)
ARMOR_BY_LEVEL: Dict[Tuple[int, int], Tuple[int, int]] = {
    (1, 5): (1, 3),
    (6, 10): (2, 5),
    (11, 15): (4, 7),
    (16, 20): (6, 10),
    (21, 30): (8, 12),
    (31, 40): (10, 15),
    (41, 50): (12, 18),
}

# Bonus ranges by rarity (hit/damage bonus) -> (min, max)
BONUS_BY_RARITY: Dict[str, Tuple[int, int]] = {
    "common": (0, 0),
    "uncommon": (0, 1),
    "rare": (1, 2),
    "epic": (2, 3),
    "legendary": (3, 5),
}

# Maximum magical properties by rarity
MAX_PROPERTIES_BY_RARITY: Dict[str, int] = {
    "common": 0,
    "uncommon": 1,
    "rare": 2,
    "epic": 3,
    "legendary": 4,
}

# Quality modifiers applied to output (from component quality)
QUALITY_MODIFIERS: Dict[str, float] = {
    "poor": 0.8,
    "normal": 1.0,
    "fine": 1.1,
    "superior": 1.2,
    "pristine": 1.3,
}


# =============================================================================
# Crafting-Specific Enums
# =============================================================================

class ComponentQuality(str, Enum):
    """Quality levels for crafting components."""

    POOR = "poor"
    NORMAL = "normal"
    FINE = "fine"
    SUPERIOR = "superior"
    PRISTINE = "pristine"


class MagicalPropertyType(str, Enum):
    """Types of magical properties on crafted items."""

    DAMAGE_BONUS = "damage_bonus"
    HIT_BONUS = "hit_bonus"
    ELEMENTAL = "elemental"
    RESISTANCE = "resistance"
    STAT_BONUS = "stat_bonus"
    LIFESTEAL = "lifesteal"
    REGENERATION = "regeneration"
    SPEED = "speed"


# =============================================================================
# Crafted Item Sub-Models
# =============================================================================

class CraftedMagicalProperty(BaseModel):
    """A magical property on a crafted item."""

    property_type: MagicalPropertyType = Field(
        ..., description="Type of magical enhancement"
    )
    name: str = Field(
        ..., min_length=2, max_length=40, description="Display name for the property"
    )
    description: str = Field(
        ..., max_length=100, description="What the property does"
    )
    value: int = Field(
        default=1, ge=1, le=5, description="Magnitude of the effect"
    )
    element: Optional[DamageType] = Field(
        default=None, description="Element for elemental/resistance properties"
    )
    stat_affected: Optional[str] = Field(
        default=None, description="Which stat is affected (for stat_bonus)"
    )


class CraftedWeaponStats(BaseModel):
    """Stats for a crafted weapon."""

    damage_dice: str = Field(
        ...,
        pattern=r"^\d+d\d+(\+\d+)?$",
        description="Damage in D&D notation (e.g., '1d8', '2d6+1')",
    )
    damage_type: DamageType = Field(
        ..., description="Primary type of damage dealt"
    )
    hit_bonus: int = Field(
        default=0, ge=0, le=5, description="Bonus to hit rolls"
    )
    damage_bonus: int = Field(
        default=0, ge=0, le=5, description="Bonus to damage rolls"
    )
    speed: Literal["slow", "normal", "fast"] = Field(
        default="normal", description="Attack speed category"
    )
    two_handed: bool = Field(
        default=False, description="Requires both hands to wield"
    )
    secondary_damage_type: Optional[DamageType] = Field(
        default=None, description="Secondary damage type (from crafting components)"
    )


class CraftedArmorStats(BaseModel):
    """Stats for a crafted armor piece."""

    armor_class: int = Field(
        ..., ge=1, le=20, description="Armor class bonus"
    )
    slot: Literal["head", "body", "hands", "feet", "back", "waist", "legs"] = Field(
        ..., description="Where armor is worn"
    )
    resistances: List[DamageType] = Field(
        default_factory=list, max_length=2, description="Damage resistances granted"
    )
    resistance_percent: int = Field(
        default=10, ge=5, le=25, description="Resistance percentage"
    )
    max_dex_bonus: Optional[int] = Field(
        default=None, ge=0, le=10, description="Maximum DEX bonus allowed"
    )
    spell_failure: int = Field(
        default=0, ge=0, le=50, description="Arcane spell failure chance"
    )


class ComponentDescription(BaseModel):
    """Description of a crafting component used."""

    component_type: str = Field(
        ..., min_length=2, max_length=50, description="Type of component (e.g., 'metal_ore')"
    )
    component_subtype: str = Field(
        ..., min_length=2, max_length=50, description="Specific subtype (e.g., 'mithril')"
    )
    quality: ComponentQuality = Field(
        default=ComponentQuality.NORMAL, description="Quality level"
    )
    rarity: ItemRarity = Field(
        default=ItemRarity.COMMON, description="Rarity of the component"
    )
    origin_zone: str = Field(
        default="", max_length=50, description="Zone where component was gathered"
    )


# =============================================================================
# Main Crafted Item Schema
# =============================================================================

class GeneratedCraftedItem(BaseModel):
    """
    LLM-generated crafted item with strict balance validation.

    The model_validator enforces that all stats are appropriate for the
    item's level and rarity, clamping values that exceed allowed ranges.
    """

    name: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Crafted item name reflecting components used",
    )
    short_description: str = Field(
        ...,
        min_length=10,
        max_length=100,
        description="One-line description when on ground",
    )
    long_description: str = Field(
        ...,
        min_length=20,
        max_length=400,
        description="Full description mentioning crafting materials",
    )
    item_type: ItemType = Field(
        ..., description="Category of item (weapon, armor, etc.)"
    )
    rarity: ItemRarity = Field(
        default=ItemRarity.COMMON, description="Rarity tier of the crafted item"
    )
    level_requirement: int = Field(
        ..., ge=1, le=50, description="Minimum level to use"
    )
    weight: float = Field(
        default=1.0, ge=0.1, le=50.0, description="Weight in pounds"
    )
    value: int = Field(
        default=10, ge=1, le=100000, description="Base gold value"
    )
    equipment_slot: Optional[EquipmentSlot] = Field(
        default=None, description="Where item is equipped"
    )
    weapon_stats: Optional[CraftedWeaponStats] = Field(
        default=None, description="Stats if weapon"
    )
    armor_stats: Optional[CraftedArmorStats] = Field(
        default=None, description="Stats if armor"
    )
    magical_properties: List[CraftedMagicalProperty] = Field(
        default_factory=list, description="Magical enhancements"
    )
    crafting_style: str = Field(
        default="", max_length=100, description="Flavor text about crafting technique"
    )

    @model_validator(mode="after")
    def validate_and_clamp_balance(self) -> "GeneratedCraftedItem":
        """
        Validate and clamp all stats to appropriate ranges.

        This ensures LLM output doesn't break game balance by enforcing:
        - Damage dice must be valid for item level
        - Hit/damage bonuses capped by rarity
        - Armor class capped by level
        - Magical properties count capped by rarity
        """
        level = self.level_requirement
        rarity = self.rarity.value

        # Clamp magical properties count
        max_props = MAX_PROPERTIES_BY_RARITY.get(rarity, 0)
        if len(self.magical_properties) > max_props:
            self.magical_properties = self.magical_properties[:max_props]

        # Get bonus limits for this rarity
        min_bonus, max_bonus = BONUS_BY_RARITY.get(rarity, (0, 0))

        # Validate weapon stats
        if self.weapon_stats:
            # Clamp hit bonus
            self.weapon_stats.hit_bonus = min(
                max(self.weapon_stats.hit_bonus, 0), max_bonus
            )
            # Clamp damage bonus
            self.weapon_stats.damage_bonus = min(
                max(self.weapon_stats.damage_bonus, 0), max_bonus
            )

            # Validate damage dice is appropriate for level
            valid_dice = self._get_valid_damage_dice(level)
            if self.weapon_stats.damage_dice not in valid_dice and valid_dice:
                # Use the highest valid dice for this level
                self.weapon_stats.damage_dice = valid_dice[-1]

        # Validate armor stats
        if self.armor_stats:
            # Get armor class range for this level
            min_ac, max_ac = self._get_armor_range(level)
            self.armor_stats.armor_class = min(
                max(self.armor_stats.armor_class, min_ac), max_ac
            )

            # Apply rarity bonus to resistance if present
            if self.armor_stats.resistances:
                base_resist = 10
                rarity_bonus = {"common": 0, "uncommon": 5, "rare": 10, "epic": 15, "legendary": 20}
                max_resist = base_resist + rarity_bonus.get(rarity, 0)
                self.armor_stats.resistance_percent = min(
                    self.armor_stats.resistance_percent, max_resist
                )

        # Validate magical property values
        for prop in self.magical_properties:
            # Clamp property value based on rarity
            max_value = 1 + list(BONUS_BY_RARITY.keys()).index(rarity)
            prop.value = min(max(prop.value, 1), min(max_value, 5))

        return self

    def _get_valid_damage_dice(self, level: int) -> List[str]:
        """Get valid damage dice for a given level."""
        for (min_level, max_level), dice_list in DAMAGE_DICE_BY_LEVEL.items():
            if min_level <= level <= max_level:
                return dice_list
        # Default to lowest if not found
        return DAMAGE_DICE_BY_LEVEL[(1, 5)]

    def _get_armor_range(self, level: int) -> Tuple[int, int]:
        """Get valid armor class range for a given level."""
        for (min_level, max_level), ac_range in ARMOR_BY_LEVEL.items():
            if min_level <= level <= max_level:
                return ac_range
        # Default to lowest if not found
        return ARMOR_BY_LEVEL[(1, 5)]


# =============================================================================
# Crafting Context for LLM
# =============================================================================

class CraftingContext(BaseModel):
    """Context provided to LLM for crafted item generation."""

    # Components used in crafting
    components_used: List[ComponentDescription] = Field(
        ..., min_length=1, max_length=5, description="Components being combined"
    )
    component_summary: str = Field(
        default="", max_length=200, description="Summary of components for LLM prompt"
    )

    # Quality calculation (pre-computed)
    total_quality_modifier: float = Field(
        default=1.0, ge=0.5, le=1.5, description="Combined quality modifier"
    )
    average_quality: ComponentQuality = Field(
        default=ComponentQuality.NORMAL, description="Average component quality"
    )

    # Target output parameters
    target_item_type: ItemType = Field(
        ..., description="Type of item to craft"
    )
    target_rarity: ItemRarity = Field(
        default=ItemRarity.COMMON, description="Target rarity (from component analysis)"
    )
    target_level: int = Field(
        ..., ge=1, le=50, description="Target item level (usually player level)"
    )
    target_slot: Optional[EquipmentSlot] = Field(
        default=None, description="Target equipment slot if applicable"
    )

    # Context for flavor
    zone_theme: str = Field(
        default="", max_length=100, description="Theme from component origin zones"
    )
    player_class: str = Field(
        default="", max_length=30, description="Crafter's class for style hints"
    )
    player_level: int = Field(
        default=1, ge=1, le=50, description="Crafter's level"
    )

    # Recipe info if following known recipe
    recipe_id: Optional[str] = Field(
        default=None, description="Recipe ID if following a known recipe"
    )
    recipe_name: Optional[str] = Field(
        default=None, description="Recipe name for flavor text"
    )

    # Existing items to avoid duplication
    existing_item_names: List[str] = Field(
        default_factory=list, max_length=20, description="Names to avoid"
    )


# =============================================================================
# Crafting Result for Return Value
# =============================================================================

class CraftingResultType(str, Enum):
    """Outcome types for crafting attempts."""

    SUCCESS = "success"
    CRITICAL_SUCCESS = "critical_success"  # Extra bonus
    FAILURE = "failure"  # Components lost
    PARTIAL_FAILURE = "partial_failure"  # Inferior item created


class CraftingResult(BaseModel):
    """Result of a crafting attempt."""

    result_type: CraftingResultType = Field(
        ..., description="Outcome of the crafting attempt"
    )
    item: Optional[GeneratedCraftedItem] = Field(
        default=None, description="Crafted item if successful"
    )
    message: str = Field(
        ..., max_length=300, description="Flavor text describing the result"
    )
    recipe_discovered: Optional[str] = Field(
        default=None, description="Recipe ID if a new recipe was discovered"
    )
    experience_gained: int = Field(
        default=0, ge=0, description="Crafting XP gained"
    )
    components_consumed: bool = Field(
        default=True, description="Whether components were consumed"
    )
