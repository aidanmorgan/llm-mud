"""
Crafting Engine Actor

Ray actor for LLM-driven item crafting with balance enforcement.
Combines crafting components to generate unique items.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import ray
from ray.actor import ActorHandle

from llm.agents import crafting_agent
from llm.cache import create_cached_agent, CachedAgent
from llm.schemas import (
    GeneratedCraftedItem,
    CraftingContext,
    CraftingResult,
    CraftingResultType,
    ComponentDescription,
    ComponentQuality,
    QUALITY_MODIFIERS,
    BONUS_BY_RARITY,
    MAX_PROPERTIES_BY_RARITY,
)
from llm.schemas.item import ItemType, ItemRarity

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

ACTOR_NAME = "crafting_engine"
ACTOR_NAMESPACE = "llmmud"


@dataclass
class CraftingRecipe:
    """A known crafting recipe."""

    recipe_id: str
    name: str
    description: str = ""
    required_components: Dict[str, int] = field(default_factory=dict)  # type -> count
    output_item_type: ItemType = ItemType.MISC
    output_rarity: ItemRarity = ItemRarity.COMMON
    min_level: int = 1
    crafting_xp: int = 10


@dataclass
class CraftingAttempt:
    """Record of a crafting attempt."""

    player_id: str
    components_used: List[str]  # Component descriptions
    result_type: CraftingResultType
    item_name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Helper Functions
# =============================================================================


def calculate_quality_modifier(qualities: List[ComponentQuality]) -> float:
    """Calculate combined quality modifier from component qualities."""
    if not qualities:
        return 1.0
    total = sum(QUALITY_MODIFIERS.get(q.value, 1.0) for q in qualities)
    return total / len(qualities)


def determine_output_rarity(rarities: List[ItemRarity]) -> ItemRarity:
    """Determine output rarity based on component rarities."""
    rarity_order = [
        ItemRarity.COMMON,
        ItemRarity.UNCOMMON,
        ItemRarity.RARE,
        ItemRarity.EPIC,
        ItemRarity.LEGENDARY,
    ]

    if not rarities:
        return ItemRarity.COMMON

    # Use highest rarity among components
    max_idx = 0
    for r in rarities:
        try:
            idx = rarity_order.index(r)
            max_idx = max(max_idx, idx)
        except ValueError:
            pass

    return rarity_order[max_idx]


def infer_item_type(component_types: List[str]) -> ItemType:
    """Infer output item type from component types."""
    type_hints = {
        "metal_ore": ItemType.WEAPON,
        "metal": ItemType.WEAPON,
        "blade": ItemType.WEAPON,
        "hilt": ItemType.WEAPON,
        "leather": ItemType.ARMOR,
        "cloth": ItemType.ARMOR,
        "hide": ItemType.ARMOR,
        "chain": ItemType.ARMOR,
        "plate": ItemType.ARMOR,
        "herb": ItemType.CONSUMABLE,
        "potion": ItemType.CONSUMABLE,
        "flask": ItemType.CONSUMABLE,
        "essence": ItemType.MISC,
        "gem": ItemType.MISC,
        "crystal": ItemType.MISC,
    }

    for comp_type in component_types:
        comp_lower = comp_type.lower()
        for hint, item_type in type_hints.items():
            if hint in comp_lower:
                return item_type

    return ItemType.MISC


def get_average_quality(qualities: List[ComponentQuality]) -> ComponentQuality:
    """Get average quality level from list."""
    if not qualities:
        return ComponentQuality.NORMAL

    quality_order = [
        ComponentQuality.POOR,
        ComponentQuality.NORMAL,
        ComponentQuality.FINE,
        ComponentQuality.SUPERIOR,
        ComponentQuality.PRISTINE,
    ]

    indices = []
    for q in qualities:
        try:
            indices.append(quality_order.index(q))
        except ValueError:
            indices.append(1)  # Default to NORMAL

    avg_idx = round(sum(indices) / len(indices))
    return quality_order[min(avg_idx, len(quality_order) - 1)]


# =============================================================================
# Crafting Engine Actor
# =============================================================================


@ray.remote
class CraftingEngine:
    """
    Ray actor for LLM-driven item crafting with balance enforcement.

    Features:
    - Generate unique items from components
    - Balance validation built into schemas
    - Recipe discovery and tracking
    - Caching for repeated crafts
    - Experimentation mode for discovery

    Usage:
        engine = get_crafting_engine()
        result = await engine.craft_item.remote(
            components=[...],
            player_class="warrior",
            player_level=10,
        )
    """

    def __init__(self, cache_ttl: int = 3600):
        """
        Initialize the crafting engine.

        Args:
            cache_ttl: TTL for cached crafts in seconds (default 1 hour)
        """
        self._cached_agent: CachedAgent = create_cached_agent(
            crafting_agent, ttl_seconds=cache_ttl
        )
        self._recipes: Dict[str, CraftingRecipe] = {}
        self._discovered_combos: Dict[str, str] = {}  # combo_key -> recipe_id
        self._recent_crafts: List[CraftingAttempt] = []
        self._max_recent_crafts = 100

        # Statistics
        self._stats = {
            "crafts_attempted": 0,
            "crafts_succeeded": 0,
            "crafts_failed": 0,
            "experiments": 0,
            "recipes_discovered": 0,
            "cache_hits": 0,
        }

        logger.info(f"CraftingEngine initialized with cache TTL {cache_ttl}s")

    async def craft_item(
        self,
        components: List[ComponentDescription],
        player_class: str,
        player_level: int,
        player_id: str = "",
        recipe_id: Optional[str] = None,
        existing_item_names: Optional[List[str]] = None,
    ) -> CraftingResult:
        """
        Craft an item from components.

        Args:
            components: List of component descriptions
            player_class: Crafter's class for style hints
            player_level: Crafter's level (affects output level)
            player_id: Player ID for tracking
            recipe_id: Optional recipe to follow
            existing_item_names: Names to avoid for uniqueness

        Returns:
            CraftingResult with item or failure info
        """
        self._stats["crafts_attempted"] += 1

        if not components:
            return CraftingResult(
                result_type=CraftingResultType.FAILURE,
                message="No components provided for crafting.",
                components_consumed=False,
            )

        # Validate recipe if specified
        recipe = None
        if recipe_id and recipe_id in self._recipes:
            recipe = self._recipes[recipe_id]
            # Check requirements
            valid, missing = self._validate_recipe_requirements(components, recipe)
            if not valid:
                return CraftingResult(
                    result_type=CraftingResultType.FAILURE,
                    message=f"Missing components for {recipe.name}: {missing}",
                    components_consumed=False,
                )

        # Calculate crafting parameters
        qualities = [c.quality for c in components]
        rarities = [c.rarity for c in components]
        component_types = [c.component_type for c in components]

        quality_modifier = calculate_quality_modifier(qualities)
        output_rarity = recipe.output_rarity if recipe else determine_output_rarity(rarities)
        output_type = recipe.output_item_type if recipe else infer_item_type(component_types)
        avg_quality = get_average_quality(qualities)

        # Build zone theme from component origins
        zones = [c.origin_zone for c in components if c.origin_zone]
        zone_theme = ", ".join(set(zones)) if zones else ""

        # Build component summary
        summary_parts = []
        for c in components:
            summary_parts.append(f"{c.component_subtype} {c.component_type}")
        component_summary = ", ".join(summary_parts)

        # Create context
        context = CraftingContext(
            components_used=components,
            component_summary=component_summary,
            total_quality_modifier=quality_modifier,
            average_quality=avg_quality,
            target_item_type=output_type,
            target_rarity=output_rarity,
            target_level=player_level,
            zone_theme=zone_theme,
            player_class=player_class,
            player_level=player_level,
            recipe_id=recipe.recipe_id if recipe else None,
            recipe_name=recipe.name if recipe else None,
            existing_item_names=existing_item_names or [],
        )

        # Generate item
        try:
            item = await self._cached_agent.run(
                "Craft an item from these components.",
                deps=context,
            )

            self._stats["crafts_succeeded"] += 1

            # Check for critical success (high quality modifier)
            result_type = CraftingResultType.SUCCESS
            if quality_modifier >= 1.25:
                result_type = CraftingResultType.CRITICAL_SUCCESS

            # Track the craft
            self._record_craft(player_id, components, result_type, item.name)

            # Check for recipe discovery
            recipe_discovered = None
            if not recipe:
                combo_key = self._make_combo_key(components)
                if combo_key not in self._discovered_combos:
                    recipe_discovered = await self._discover_recipe(
                        components, item, output_type, output_rarity
                    )

            # Calculate experience
            xp_base = 10 * (list(ItemRarity).index(output_rarity) + 1)
            xp_gained = int(xp_base * quality_modifier)
            if result_type == CraftingResultType.CRITICAL_SUCCESS:
                xp_gained = int(xp_gained * 1.5)

            message = self._build_success_message(item, result_type, quality_modifier)

            return CraftingResult(
                result_type=result_type,
                item=item,
                message=message,
                recipe_discovered=recipe_discovered,
                experience_gained=xp_gained,
                components_consumed=True,
            )

        except Exception as e:
            logger.warning(f"Crafting generation failed: {e}")
            self._stats["crafts_failed"] += 1

            # Partial failure - create inferior item
            return CraftingResult(
                result_type=CraftingResultType.FAILURE,
                message=f"The crafting attempt failed. The components were consumed. ({e})",
                components_consumed=True,
            )

    async def experiment(
        self,
        components: List[ComponentDescription],
        player_class: str,
        player_level: int,
        player_id: str = "",
    ) -> CraftingResult:
        """
        Experiment with components to discover new recipes.

        Same as craft_item but marked as experiment for tracking.

        Args:
            components: List of component descriptions
            player_class: Crafter's class
            player_level: Crafter's level
            player_id: Player ID

        Returns:
            CraftingResult with potential recipe discovery
        """
        self._stats["experiments"] += 1
        result = await self.craft_item(
            components=components,
            player_class=player_class,
            player_level=player_level,
            player_id=player_id,
        )

        # Add experiment bonus message
        if result.recipe_discovered:
            result.message += "\n\nYou've discovered a new crafting recipe!"

        return result

    async def _discover_recipe(
        self,
        components: List[ComponentDescription],
        item: GeneratedCraftedItem,
        output_type: ItemType,
        output_rarity: ItemRarity,
    ) -> Optional[str]:
        """Discover and register a new recipe from successful craft."""
        combo_key = self._make_combo_key(components)

        # Create recipe from successful craft
        recipe_id = f"discovered_{len(self._recipes) + 1:04d}"

        # Count component types
        type_counts: Dict[str, int] = {}
        for c in components:
            key = f"{c.component_type}:{c.component_subtype}"
            type_counts[key] = type_counts.get(key, 0) + 1

        recipe = CraftingRecipe(
            recipe_id=recipe_id,
            name=f"Recipe: {item.name}",
            description=f"Create {item.name} from {len(components)} components.",
            required_components=type_counts,
            output_item_type=output_type,
            output_rarity=output_rarity,
            min_level=item.level_requirement,
            crafting_xp=15 * (list(ItemRarity).index(output_rarity) + 1),
        )

        self._recipes[recipe_id] = recipe
        self._discovered_combos[combo_key] = recipe_id
        self._stats["recipes_discovered"] += 1

        logger.info(f"Recipe discovered: {recipe.name}")
        return recipe_id

    def _make_combo_key(self, components: List[ComponentDescription]) -> str:
        """Create a unique key for a component combination."""
        sorted_types = sorted(
            f"{c.component_type}:{c.component_subtype}" for c in components
        )
        return "|".join(sorted_types)

    def _validate_recipe_requirements(
        self, components: List[ComponentDescription], recipe: CraftingRecipe
    ) -> tuple[bool, str]:
        """Validate that components meet recipe requirements."""
        available: Dict[str, int] = {}
        for c in components:
            key = f"{c.component_type}:{c.component_subtype}"
            available[key] = available.get(key, 0) + 1

        missing = []
        for req_key, req_count in recipe.required_components.items():
            have = available.get(req_key, 0)
            if have < req_count:
                missing.append(f"{req_key} ({req_count - have} more needed)")

        return len(missing) == 0, ", ".join(missing)

    def _build_success_message(
        self,
        item: GeneratedCraftedItem,
        result_type: CraftingResultType,
        quality_mod: float,
    ) -> str:
        """Build a flavor message for successful craft."""
        if result_type == CraftingResultType.CRITICAL_SUCCESS:
            return (
                f"Masterful work! You've created {item.name}. "
                f"The craftsmanship is exceptional, imbuing the item with extra power."
            )
        elif quality_mod >= 1.1:
            return f"Excellent work! You've crafted {item.name}. The quality is impressive."
        elif quality_mod <= 0.9:
            return (
                f"You've crafted {item.name}, though the result is somewhat rough. "
                f"Better components might yield superior results."
            )
        else:
            return f"You've successfully crafted {item.name}."

    def _record_craft(
        self,
        player_id: str,
        components: List[ComponentDescription],
        result_type: CraftingResultType,
        item_name: Optional[str],
    ) -> None:
        """Record a crafting attempt for history."""
        attempt = CraftingAttempt(
            player_id=player_id,
            components_used=[f"{c.component_subtype} {c.component_type}" for c in components],
            result_type=result_type,
            item_name=item_name,
        )
        self._recent_crafts.append(attempt)

        # Trim history
        if len(self._recent_crafts) > self._max_recent_crafts:
            self._recent_crafts = self._recent_crafts[-self._max_recent_crafts:]

    async def register_recipe(self, recipe: CraftingRecipe) -> None:
        """Register a predefined recipe."""
        self._recipes[recipe.recipe_id] = recipe
        logger.info(f"Registered recipe: {recipe.name}")

    async def get_recipe(self, recipe_id: str) -> Optional[CraftingRecipe]:
        """Get a recipe by ID."""
        return self._recipes.get(recipe_id)

    async def get_all_recipes(self) -> List[CraftingRecipe]:
        """Get all registered recipes."""
        return list(self._recipes.values())

    async def get_discovered_recipes(self, player_id: str = "") -> List[str]:
        """Get list of discovered recipe IDs."""
        # In a full implementation, this would track per-player discoveries
        return list(self._discovered_combos.values())

    async def get_stats(self) -> Dict[str, Any]:
        """Get crafting statistics."""
        agent_stats = self._cached_agent.get_stats()
        return {
            **self._stats,
            "cache_stats": agent_stats,
            "total_recipes": len(self._recipes),
            "discovered_recipes": len(self._discovered_combos),
            "recent_crafts": len(self._recent_crafts),
        }

    async def get_recent_crafts(self, count: int = 10) -> List[CraftingAttempt]:
        """Get recent crafting attempts."""
        return self._recent_crafts[-count:]


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_crafting_engine(cache_ttl: int = 3600) -> ActorHandle:
    """Start the crafting engine actor."""
    actor: ActorHandle = CraftingEngine.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote(cache_ttl)
    logger.info(f"Started CraftingEngine as {ACTOR_NAMESPACE}/{ACTOR_NAME}")
    return actor


def get_crafting_engine() -> ActorHandle:
    """Get the crafting engine actor."""
    return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)


def crafting_engine_exists() -> bool:
    """Check if the crafting engine exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_crafting_engine() -> bool:
    """Stop the crafting engine."""
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped CraftingEngine")
        return True
    except ValueError:
        return False


__all__ = [
    "CraftingEngine",
    "CraftingRecipe",
    "CraftingAttempt",
    "calculate_quality_modifier",
    "determine_output_rarity",
    "infer_item_type",
    "start_crafting_engine",
    "get_crafting_engine",
    "crafting_engine_exists",
    "stop_crafting_engine",
]
