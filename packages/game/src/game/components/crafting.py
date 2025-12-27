"""
Crafting Components

Define crafting materials, gather nodes, recipes, and player crafting data.

Components:
- CraftingComponentData: Gatherable crafting material
- GatherNodeData: Resource node that yields components
- RecipeBookData: Player's known recipes
- CraftingSkillData: Player's crafting skill levels
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum
import time

from core import EntityId, ComponentData
from .inventory import ItemRarity, ItemType


class ComponentQuality(str, Enum):
    """Quality levels for crafting components."""

    POOR = "poor"
    NORMAL = "normal"
    FINE = "fine"
    SUPERIOR = "superior"
    PRISTINE = "pristine"


class ComponentCategory(str, Enum):
    """Categories of crafting components."""

    METAL = "metal"  # Ores, ingots, alloys
    LEATHER = "leather"  # Hides, pelts, treated leather
    CLOTH = "cloth"  # Fabrics, silk, wool
    WOOD = "wood"  # Timber, planks, branches
    STONE = "stone"  # Gems, crystite, obsidian
    HERB = "herb"  # Plants, roots, flowers
    ESSENCE = "essence"  # Magical components
    BONE = "bone"  # Bones, chitin, scales
    MISC = "misc"  # Other crafting materials


class GatheringSkill(str, Enum):
    """Skills for gathering different components."""

    MINING = "mining"  # Metal, stone
    SKINNING = "skinning"  # Leather, bone
    HERBALISM = "herbalism"  # Herbs
    LOGGING = "logging"  # Wood
    WEAVING = "weaving"  # Cloth
    ESSENCE_TAP = "essence_tap"  # Magical essences


class CraftingProfession(str, Enum):
    """Crafting professions."""

    BLACKSMITH = "blacksmith"  # Weapons, heavy armor
    ARMORSMITH = "armorsmith"  # Armor
    LEATHERWORKER = "leatherworker"  # Leather armor
    TAILOR = "tailor"  # Cloth armor
    ALCHEMIST = "alchemist"  # Potions, consumables
    ENCHANTER = "enchanter"  # Magical enhancements
    JEWELER = "jeweler"  # Rings, amulets


# Quality modifiers for crafting output
QUALITY_MODIFIERS: Dict[ComponentQuality, float] = {
    ComponentQuality.POOR: 0.8,
    ComponentQuality.NORMAL: 1.0,
    ComponentQuality.FINE: 1.1,
    ComponentQuality.SUPERIOR: 1.2,
    ComponentQuality.PRISTINE: 1.3,
}


@dataclass
class CraftingComponentData(ComponentData):
    """
    A gatherable/lootable crafting component.

    Used on: items that serve as crafting materials.
    """

    # Component identification
    component_type: str = ""  # e.g., "metal_ore", "leather", "essence"
    component_subtype: str = ""  # e.g., "iron", "dragon_hide", "fire"
    category: ComponentCategory = ComponentCategory.MISC

    # Quality and rarity
    quality: ComponentQuality = ComponentQuality.NORMAL
    rarity: ItemRarity = ItemRarity.COMMON

    # Level range (what level items can be crafted)
    min_level: int = 1
    max_level: int = 10

    # Origin tracking (affects crafted item flavor)
    origin_zone: str = ""
    origin_mob: str = ""  # If dropped from a creature

    # Stacking
    stack_size: int = 1
    max_stack: int = 99

    # Gathering info
    required_skill: Optional[GatheringSkill] = None
    skill_level_required: int = 0

    @property
    def quality_modifier(self) -> float:
        """Get the quality modifier for crafting."""
        return QUALITY_MODIFIERS.get(self.quality, 1.0)

    @property
    def display_name(self) -> str:
        """Get display name with quality indicator."""
        quality_prefix = {
            ComponentQuality.POOR: "Poor",
            ComponentQuality.NORMAL: "",
            ComponentQuality.FINE: "Fine",
            ComponentQuality.SUPERIOR: "Superior",
            ComponentQuality.PRISTINE: "Pristine",
        }
        prefix = quality_prefix.get(self.quality, "")
        if prefix:
            return f"{prefix} {self.component_subtype} {self.component_type}"
        return f"{self.component_subtype} {self.component_type}"


@dataclass
class GatherNodeData(ComponentData):
    """
    A resource node in the world that yields components.

    Used on: environmental objects that can be gathered from.
    """

    # What this node yields
    component_template_id: str = ""  # Template of component to spawn
    component_type: str = ""
    component_subtype: str = ""
    component_category: ComponentCategory = ComponentCategory.MISC

    # Yield amounts
    yield_min: int = 1
    yield_max: int = 3

    # Quality distribution (quality -> weight)
    quality_weights: Dict[str, float] = field(default_factory=lambda: {
        ComponentQuality.POOR.value: 0.10,
        ComponentQuality.NORMAL.value: 0.50,
        ComponentQuality.FINE.value: 0.25,
        ComponentQuality.SUPERIOR.value: 0.10,
        ComponentQuality.PRISTINE.value: 0.05,
    })

    # Usage tracking
    current_uses: int = 3
    max_uses: int = 3
    is_depleted: bool = False
    depleted_at: float = 0.0

    # Respawn
    respawn_time_s: int = 300  # 5 minutes default
    respawns: bool = True

    # Requirements
    required_skill: Optional[GatheringSkill] = None
    skill_level_required: int = 0
    required_tool: Optional[str] = None  # e.g., "pickaxe", "skinning_knife"

    # Level requirement
    min_player_level: int = 1

    @property
    def is_ready(self) -> bool:
        """Check if node is ready to gather from."""
        if not self.is_depleted:
            return True
        if not self.respawns:
            return False
        return time.time() >= self.depleted_at + self.respawn_time_s

    def use(self) -> bool:
        """Use one charge. Returns True if this caused depletion."""
        if self.is_depleted and not self.is_ready:
            return False

        if self.is_depleted and self.is_ready:
            # Respawned
            self.is_depleted = False
            self.current_uses = self.max_uses

        self.current_uses -= 1
        if self.current_uses <= 0:
            self.is_depleted = True
            self.depleted_at = time.time()
            return True
        return False

    def get_respawn_remaining(self) -> float:
        """Get seconds until respawn, or 0 if ready."""
        if not self.is_depleted:
            return 0
        elapsed = time.time() - self.depleted_at
        remaining = self.respawn_time_s - elapsed
        return max(0, remaining)


@dataclass
class CraftingRecipeData:
    """
    A known crafting recipe.

    Not a ComponentData - this is stored within RecipeBookData.
    """

    recipe_id: str = ""
    name: str = ""
    description: str = ""

    # Requirements
    required_components: Dict[str, int] = field(default_factory=dict)  # type:subtype -> count
    required_profession: Optional[CraftingProfession] = None
    profession_level_required: int = 0
    min_player_level: int = 1

    # Output
    output_item_type: ItemType = ItemType.MISC
    output_rarity: ItemRarity = ItemRarity.COMMON
    output_template_id: str = ""  # If static item, otherwise LLM generates

    # Discovery
    discovered: bool = False
    discovered_at: float = 0.0
    discovery_source: str = ""  # "experiment", "quest", "trainer", etc.

    # Crafting info
    crafting_time_s: float = 1.0
    crafting_xp: int = 10


@dataclass
class RecipeBookData(ComponentData):
    """
    Player's crafting knowledge and recipe collection.

    Used on: players to track their known recipes.
    """

    # Known recipes (recipe_id -> CraftingRecipeData)
    known_recipes: Dict[str, CraftingRecipeData] = field(default_factory=dict)

    # Experimentation tracking
    experimented_combinations: List[str] = field(default_factory=list)
    max_experiments_tracked: int = 100

    # Statistics
    items_crafted: int = 0
    experiments_attempted: int = 0
    recipes_discovered: int = 0

    # Favorite recipes for quick access
    favorite_recipes: List[str] = field(default_factory=list)

    def add_recipe(
        self,
        recipe: CraftingRecipeData,
        source: str = "unknown",
    ) -> bool:
        """Add a recipe. Returns True if new."""
        if recipe.recipe_id in self.known_recipes:
            return False

        recipe.discovered = True
        recipe.discovered_at = time.time()
        recipe.discovery_source = source
        self.known_recipes[recipe.recipe_id] = recipe
        self.recipes_discovered += 1
        return True

    def has_recipe(self, recipe_id: str) -> bool:
        """Check if player knows a recipe."""
        return recipe_id in self.known_recipes

    def record_experiment(self, combo_key: str) -> None:
        """Record an experimented combination."""
        if combo_key not in self.experimented_combinations:
            self.experimented_combinations.append(combo_key)
            self.experiments_attempted += 1

            # Trim old experiments
            if len(self.experimented_combinations) > self.max_experiments_tracked:
                self.experimented_combinations = self.experimented_combinations[
                    -self.max_experiments_tracked:
                ]

    def was_experimented(self, combo_key: str) -> bool:
        """Check if a combination was already experimented."""
        return combo_key in self.experimented_combinations


@dataclass
class CraftingSkillData(ComponentData):
    """
    Player's crafting skill levels.

    Used on: players to track their profession levels.
    """

    # Profession levels (profession -> level)
    profession_levels: Dict[str, int] = field(default_factory=dict)

    # Profession XP (profession -> current XP)
    profession_xp: Dict[str, int] = field(default_factory=dict)

    # Gathering skill levels
    gathering_levels: Dict[str, int] = field(default_factory=dict)
    gathering_xp: Dict[str, int] = field(default_factory=dict)

    # Current active professions (limited)
    active_professions: List[str] = field(default_factory=list)
    max_professions: int = 2

    # Statistics
    total_items_crafted: int = 0
    total_resources_gathered: int = 0

    def get_profession_level(self, profession: CraftingProfession) -> int:
        """Get level in a profession."""
        return self.profession_levels.get(profession.value, 0)

    def get_gathering_level(self, skill: GatheringSkill) -> int:
        """Get level in a gathering skill."""
        return self.gathering_levels.get(skill.value, 0)

    def add_profession_xp(self, profession: CraftingProfession, xp: int) -> int:
        """Add XP to a profession. Returns new level if leveled up, 0 otherwise."""
        key = profession.value
        current_xp = self.profession_xp.get(key, 0) + xp
        self.profession_xp[key] = current_xp

        current_level = self.profession_levels.get(key, 1)
        xp_for_next = self._xp_for_profession_level(current_level + 1)

        if current_xp >= xp_for_next:
            self.profession_levels[key] = current_level + 1
            return current_level + 1
        return 0

    def add_gathering_xp(self, skill: GatheringSkill, xp: int) -> int:
        """Add XP to a gathering skill. Returns new level if leveled up."""
        key = skill.value
        current_xp = self.gathering_xp.get(key, 0) + xp
        self.gathering_xp[key] = current_xp

        current_level = self.gathering_levels.get(key, 1)
        xp_for_next = self._xp_for_gathering_level(current_level + 1)

        if current_xp >= xp_for_next:
            self.gathering_levels[key] = current_level + 1
            return current_level + 1
        return 0

    def can_learn_profession(self, profession: CraftingProfession) -> bool:
        """Check if player can learn a new profession."""
        if profession.value in self.active_professions:
            return True  # Already know it
        return len(self.active_professions) < self.max_professions

    def _xp_for_profession_level(self, level: int) -> int:
        """Get XP required for a profession level."""
        return level * level * 100

    def _xp_for_gathering_level(self, level: int) -> int:
        """Get XP required for a gathering level."""
        return level * level * 50


@dataclass
class WorkbenchData(ComponentData):
    """
    A crafting station in the world.

    Used on: objects that provide crafting bonuses or enable specific recipes.
    """

    # Station type
    station_type: str = ""  # "forge", "alchemy_table", "loom", etc.
    supported_professions: List[CraftingProfession] = field(default_factory=list)

    # Bonuses
    quality_bonus: float = 0.0  # Added to quality modifier
    success_bonus: float = 0.0  # Chance to upgrade result
    speed_multiplier: float = 1.0  # Crafting time multiplier

    # Requirements
    min_level: int = 1
    required_reputation: Optional[str] = None
    reputation_amount: int = 0

    # Usage
    in_use_by: Optional[EntityId] = None
    in_use_until: float = 0.0

    @property
    def is_available(self) -> bool:
        """Check if workbench is available for use."""
        if self.in_use_by is None:
            return True
        return time.time() >= self.in_use_until


# Helper functions for component matching
def components_match(
    component: CraftingComponentData,
    type_pattern: str,
    subtype_pattern: Optional[str] = None,
) -> bool:
    """Check if a component matches type/subtype patterns."""
    if type_pattern != "*" and component.component_type != type_pattern:
        return False
    if subtype_pattern and subtype_pattern != "*":
        if component.component_subtype != subtype_pattern:
            return False
    return True


def get_combo_key(components: List[CraftingComponentData]) -> str:
    """Generate a unique key for a component combination."""
    parts = sorted(
        f"{c.component_type}:{c.component_subtype}" for c in components
    )
    return "|".join(parts)
