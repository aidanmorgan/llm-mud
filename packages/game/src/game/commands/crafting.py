"""
Crafting Commands

Commands for gathering resources, crafting items, viewing recipes, and dismantling.
"""

import random
import time
from typing import List, Optional, Tuple

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.inventory import ItemType, ItemRarity
from ..components.crafting import (
    ComponentQuality,
    ComponentCategory,
    GatheringSkill,
    CraftingProfession,
    QUALITY_MODIFIERS,
    CraftingComponentData,
    GatherNodeData,
    RecipeBookData,
    CraftingSkillData,
    CraftingRecipeData,
    get_combo_key,
)
from ..components.proficiency import (
    ProficiencySkill,
    ProficiencyData,
    GATHERING_XP_BASE,
    CRAFTING_XP_BASE,
    DISMANTLING_XP_BASE,
    calculate_activity_xp,
)


# =============================================================================
# Skill Mapping
# =============================================================================

# Map GatheringSkill to ProficiencySkill
GATHERING_TO_PROFICIENCY = {
    GatheringSkill.MINING: ProficiencySkill.MINING,
    GatheringSkill.HERBALISM: ProficiencySkill.HERBALISM,
    GatheringSkill.SKINNING: ProficiencySkill.SKINNING,
    GatheringSkill.LOGGING: ProficiencySkill.LOGGING,
    GatheringSkill.FISHING: ProficiencySkill.FISHING,
    GatheringSkill.FORAGING: ProficiencySkill.FORAGING,
}

# Map CraftingProfession to ProficiencySkill
PROFESSION_TO_PROFICIENCY = {
    CraftingProfession.BLACKSMITHING: ProficiencySkill.BLACKSMITHING,
    CraftingProfession.ARMORSMITHING: ProficiencySkill.ARMORSMITHING,
    CraftingProfession.LEATHERWORKING: ProficiencySkill.LEATHERWORKING,
    CraftingProfession.TAILORING: ProficiencySkill.TAILORING,
    CraftingProfession.ALCHEMY: ProficiencySkill.ALCHEMY,
    CraftingProfession.ENCHANTING: ProficiencySkill.ENCHANTING,
    CraftingProfession.JEWELCRAFTING: ProficiencySkill.JEWELCRAFTING,
    CraftingProfession.COOKING: ProficiencySkill.COOKING,
}


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_proficiency_data(player_id: EntityId) -> ProficiencyData:
    """Get or create proficiency data for a player."""
    proficiency_actor = get_component_actor("Proficiency")
    data = await proficiency_actor.get.remote(player_id)
    if not data:
        data = ProficiencyData()
    return data


async def _save_proficiency_data(player_id: EntityId, data: ProficiencyData) -> None:
    """Save proficiency data for a player."""
    proficiency_actor = get_component_actor("Proficiency")
    await proficiency_actor.set.remote(player_id, data)


async def _find_gather_node_in_room(
    room_id: EntityId,
    keyword: Optional[str] = None,
) -> Optional[Tuple[EntityId, GatherNodeData]]:
    """
    Find a gather node in the room by keyword.

    Args:
        room_id: The room to search in
        keyword: Optional keyword to match (if None, returns first node)

    Returns:
        Tuple of (EntityId, GatherNodeData) or None
    """
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")
    gather_actor = get_component_actor("GatherNode")

    all_locations = await location_actor.get_all.remote()
    all_gather_nodes = await gather_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue

        # Check if this entity is a gather node
        node_data = all_gather_nodes.get(entity_id)
        if not node_data:
            continue

        # If no keyword specified, return first node
        if not keyword:
            return (entity_id, node_data)

        # Match keyword against identity
        identity = await identity_actor.get.remote(entity_id)
        if identity:
            keyword_lower = keyword.lower()
            if keyword_lower in identity.name.lower():
                return (entity_id, node_data)
            for kw in identity.keywords:
                if keyword_lower in kw.lower():
                    return (entity_id, node_data)

    return None


async def _get_player_crafting_components(
    player_id: EntityId,
) -> List[Tuple[EntityId, CraftingComponentData]]:
    """
    Get all crafting components in player's inventory.

    Returns:
        List of (EntityId, CraftingComponentData) tuples
    """
    container_actor = get_component_actor("Container")
    component_actor = get_component_actor("CraftingComponent")

    container = await container_actor.get.remote(player_id)
    if not container:
        return []

    components = []
    all_component_data = await component_actor.get_all.remote()

    for item_id in container.item_ids:
        comp_data = all_component_data.get(item_id)
        if comp_data:
            components.append((item_id, comp_data))

    return components


async def _find_component_in_inventory(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> Optional[Tuple[EntityId, CraftingComponentData]]:
    """
    Find a crafting component in player's inventory by keyword.

    Args:
        player_id: Player to search inventory of
        keyword: Component keyword to match
        ordinal: Which match to return (1 = first, 2 = second, etc.)

    Returns:
        Tuple of (EntityId, CraftingComponentData) or None
    """
    identity_actor = get_component_actor("Identity")
    components = await _get_player_crafting_components(player_id)

    keyword_lower = keyword.lower()
    matches = 0

    for entity_id, comp_data in components:
        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        # Check name and keywords
        matched = False
        if keyword_lower in identity.name.lower():
            matched = True
        else:
            for kw in identity.keywords:
                if keyword_lower in kw.lower():
                    matched = True
                    break

        # Also check component type/subtype
        if not matched:
            if keyword_lower in comp_data.component_type.lower():
                matched = True
            elif keyword_lower in comp_data.component_subtype.lower():
                matched = True

        if matched:
            matches += 1
            if matches == ordinal:
                return (entity_id, comp_data)

    return None


def _roll_quality(weights: dict) -> ComponentQuality:
    """Roll for component quality based on weights."""
    total = sum(weights.values())
    roll = random.random() * total
    cumulative = 0.0

    for quality_str, weight in weights.items():
        cumulative += weight
        if roll <= cumulative:
            return ComponentQuality(quality_str)

    return ComponentQuality.NORMAL


def _get_quality_color(quality: ComponentQuality) -> str:
    """Get ANSI color code for quality display."""
    colors = {
        ComponentQuality.POOR: "{D}",      # Dark gray
        ComponentQuality.NORMAL: "{w}",    # White
        ComponentQuality.FINE: "{G}",      # Green
        ComponentQuality.SUPERIOR: "{B}",  # Blue
        ComponentQuality.PRISTINE: "{M}",  # Magenta/Purple
    }
    return colors.get(quality, "{w}")


def _get_rarity_color(rarity: ItemRarity) -> str:
    """Get ANSI color code for rarity display."""
    colors = {
        ItemRarity.COMMON: "{w}",       # White
        ItemRarity.UNCOMMON: "{G}",     # Green
        ItemRarity.RARE: "{B}",         # Blue
        ItemRarity.EPIC: "{M}",         # Purple
        ItemRarity.LEGENDARY: "{Y}",    # Gold/Yellow
    }
    return colors.get(rarity, "{w}")


# =============================================================================
# Gather Command
# =============================================================================


@command(
    name="gather",
    aliases=["harvest", "mine", "pick", "collect"],
    category=CommandCategory.OBJECT,
    help_text="Gather resources from a node in the room.",
)
async def cmd_gather(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    gather [node] - Gather crafting components from resource nodes.

    Examples:
        gather          - Gather from any available node
        gather ore      - Gather from an ore vein
        gather herbs    - Gather from herb patch
    """
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")
    gather_actor = get_component_actor("GatherNode")
    container_actor = get_component_actor("Container")
    component_actor = get_component_actor("CraftingComponent")
    skill_actor = get_component_actor("CraftingSkill")

    # Get player location
    location = await location_actor.get.remote(player_id)
    if not location:
        return "You are nowhere."

    # Find a gather node
    keyword = args[0] if args else None
    node_result = await _find_gather_node_in_room(location.room_id, keyword)

    if not node_result:
        if keyword:
            return f"You don't see '{keyword}' to gather from here."
        return "There is nothing to gather here."

    node_id, node_data = node_result

    # Get node identity for display
    node_identity = await identity_actor.get.remote(node_id)
    node_name = node_identity.name if node_identity else "resource node"

    # Check if node is depleted
    if node_data.is_depleted:
        if not node_data.respawns:
            return f"The {node_name} has been completely exhausted."
        remaining = node_data.get_respawn_remaining()
        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            if mins > 0:
                return f"The {node_name} is depleted. It will replenish in about {mins} minute(s)."
            return f"The {node_name} is depleted. It will replenish in about {secs} second(s)."

    # Check skill requirements
    if node_data.required_skill:
        skill_data = await skill_actor.get.remote(player_id)
        if skill_data:
            player_skill = skill_data.get_gathering_level(
                GatheringSkill(node_data.required_skill)
            )
            if player_skill < node_data.skill_level_required:
                return (
                    f"You need {node_data.required_skill.replace('_', ' ').title()} "
                    f"level {node_data.skill_level_required} to gather from the {node_name}."
                )

    # Check tool requirements (simplified - just check inventory)
    if node_data.required_tool:
        container = await container_actor.get.remote(player_id)
        has_tool = False
        if container:
            for item_id in container.item_ids:
                item_identity = await identity_actor.get.remote(item_id)
                if item_identity and node_data.required_tool.lower() in item_identity.name.lower():
                    has_tool = True
                    break
        if not has_tool:
            return f"You need a {node_data.required_tool} to gather from the {node_name}."

    # Get proficiency data for skill bonuses
    proficiency_data = await _get_proficiency_data(player_id)
    prof_skill = None
    skill_benefits = None

    if node_data.required_skill:
        try:
            gathering_skill = GatheringSkill(node_data.required_skill)
            prof_skill = GATHERING_TO_PROFICIENCY.get(gathering_skill)
            if prof_skill:
                skill_benefits = proficiency_data.get_benefits(prof_skill)
        except ValueError:
            pass

    # Roll for yield amount (modified by proficiency)
    base_yield = random.randint(node_data.yield_min, node_data.yield_max)
    yield_amount = base_yield

    # Apply yield multiplier from proficiency
    if skill_benefits:
        yield_amount = int(base_yield * skill_benefits.yield_multiplier)
        # Check for critical success (double yield)
        if random.random() < skill_benefits.critical_chance:
            yield_amount *= 2

    yield_amount = max(1, yield_amount)

    # Roll for quality (modified by proficiency)
    modified_weights = dict(node_data.quality_weights)
    if skill_benefits:
        # Shift quality weights toward higher tiers
        quality_bonus = skill_benefits.quality_bonus
        if quality_bonus > 0:
            # Reduce poor weight
            if "poor" in modified_weights:
                modified_weights["poor"] = max(0, modified_weights["poor"] * (1 - quality_bonus * 2))
            # Increase higher quality weights
            for q in ["fine", "superior", "pristine"]:
                if q in modified_weights:
                    modified_weights[q] = modified_weights[q] * (1 + quality_bonus * 2)

    quality = _roll_quality(modified_weights)

    # Use the node
    was_depleted = node_data.use()

    # Update node state
    await gather_actor.set.remote(node_id, node_data)

    # Create the component(s) in player inventory
    container = await container_actor.get.remote(player_id)
    if not container:
        return "You have no inventory to store gathered materials."

    # Create component data
    new_component = CraftingComponentData(
        component_type=node_data.component_type,
        component_subtype=node_data.component_subtype,
        category=node_data.component_category,
        quality=quality,
        rarity=ItemRarity.COMMON,  # Gathered materials are usually common
        origin_zone=location.room_id.split("_")[0] if "_" in location.room_id else "unknown",
        stack_size=yield_amount,
    )

    # For simplicity, we'll just track this gathering without creating actual entities
    # In a full implementation, this would create item entities

    # Build response
    quality_color = _get_quality_color(quality)
    quality_name = quality.value.title()
    comp_name = f"{node_data.component_subtype} {node_data.component_type}".strip()

    result_lines = [
        f"You gather from the {node_name}...",
        f"  Obtained: {quality_color}[{quality_name}]{'{x}'} {comp_name} x{yield_amount}",
    ]

    if was_depleted:
        if node_data.respawns:
            result_lines.append(f"\nThe {node_name} is now depleted. It will replenish over time.")
        else:
            result_lines.append(f"\nThe {node_name} has been completely exhausted.")

    # Award proficiency XP
    if prof_skill:
        # Calculate XP based on difficulty and quality
        quality_mult = QUALITY_MODIFIERS.get(quality, 1.0)
        difficulty = node_data.skill_level_required if node_data.skill_level_required else 1
        xp_gained = calculate_activity_xp(
            GATHERING_XP_BASE,
            difficulty,
            proficiency_data.get_effective_level(prof_skill),
            quality_mult,
        )

        leveled = proficiency_data.add_skill_xp(prof_skill, xp_gained)
        proficiency_data.record_use(prof_skill, items_produced=yield_amount)
        await _save_proficiency_data(player_id, proficiency_data)

        if leveled:
            new_level = proficiency_data.get_skill(prof_skill).base_level
            result_lines.append(
                f"\n{{Y}}Your {prof_skill.value.replace('_', ' ').title()} skill has increased to level {new_level}!{{x}}"
            )
        else:
            result_lines.append(f"\n{{D}}+{xp_gained} {prof_skill.value.title()} XP{{x}}")

    # Also award old gathering XP for backwards compatibility
    skill_data = await skill_actor.get.remote(player_id)
    if skill_data and node_data.required_skill:
        xp_gained = 5 * QUALITY_MODIFIERS.get(quality, 1.0)
        skill = GatheringSkill(node_data.required_skill)
        new_level = skill_data.add_gathering_xp(skill, int(xp_gained))
        skill_data.total_resources_gathered += yield_amount
        await skill_actor.set.remote(player_id, skill_data)

    return "\n".join(result_lines)


# =============================================================================
# Craft Command
# =============================================================================


@command(
    name="craft",
    aliases=["create", "make"],
    category=CommandCategory.OBJECT,
    help_text="Craft items from components.",
)
async def cmd_craft(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    craft <recipe> - Craft using a known recipe
    craft with <component1> <component2> ... - Experiment with components

    Examples:
        craft iron_sword       - Craft using the iron_sword recipe
        craft with iron ore leather - Experiment with components
    """
    if not args:
        return (
            "Usage: craft <recipe_name>\n"
            "       craft with <component1> <component2> ...\n\n"
            "Use 'recipes' to see your known recipes.\n"
            "Use 'craft with' to experiment with new combinations."
        )

    recipe_actor = get_component_actor("RecipeBook")
    skill_actor = get_component_actor("CraftingSkill")
    stats_actor = get_component_actor("PlayerStats")

    # Get player's recipe book
    recipe_book = await recipe_actor.get.remote(player_id)
    if not recipe_book:
        recipe_book = RecipeBookData()

    # Get player stats for class/level
    player_stats = await stats_actor.get.remote(player_id)
    player_class = player_stats.character_class if player_stats else "adventurer"
    player_level = player_stats.level if player_stats else 1

    # Check if experimenting
    if args[0].lower() == "with":
        if len(args) < 2:
            return "Usage: craft with <component1> <component2> ..."
        return await _craft_experiment(player_id, args[1:], player_class, player_level)

    # Try to craft from a recipe
    recipe_name = "_".join(args).lower()

    if recipe_name not in recipe_book.known_recipes:
        # Check if it's close to any known recipe
        suggestions = []
        for known_id in recipe_book.known_recipes:
            if recipe_name in known_id or known_id in recipe_name:
                suggestions.append(known_id)

        msg = f"You don't know a recipe called '{recipe_name}'."
        if suggestions:
            msg += f"\nDid you mean: {', '.join(suggestions[:3])}?"
        msg += "\nUse 'recipes' to see your known recipes, or 'craft with <components>' to experiment."
        return msg

    recipe = recipe_book.known_recipes[recipe_name]

    # Check requirements
    if recipe.min_player_level > player_level:
        return f"You need to be level {recipe.min_player_level} to craft {recipe.name}."

    if recipe.required_profession:
        skill_data = await skill_actor.get.remote(player_id)
        if skill_data:
            prof_level = skill_data.get_profession_level(recipe.required_profession)
            if prof_level < recipe.profession_level_required:
                return (
                    f"You need {recipe.required_profession.value.title()} level "
                    f"{recipe.profession_level_required} to craft {recipe.name}."
                )

    # Check if player has required components
    components = await _get_player_crafting_components(player_id)
    missing = []
    used_components = []

    for comp_key, count_needed in recipe.required_components.items():
        # Parse "type:subtype" format
        parts = comp_key.split(":")
        comp_type = parts[0]
        comp_subtype = parts[1] if len(parts) > 1 else None

        count_found = 0
        for entity_id, comp_data in components:
            if entity_id in used_components:
                continue
            if comp_data.component_type == comp_type:
                if comp_subtype is None or comp_data.component_subtype == comp_subtype:
                    count_found += comp_data.stack_size
                    used_components.append(entity_id)
                    if count_found >= count_needed:
                        break

        if count_found < count_needed:
            missing.append(f"{count_needed}x {comp_key.replace(':', ' ')}")

    if missing:
        return f"Missing components to craft {recipe.name}:\n  " + "\n  ".join(missing)

    # Craft the item using CraftingEngine
    try:
        from generation.crafting import crafting_engine_exists, get_crafting_engine

        if crafting_engine_exists():
            engine = get_crafting_engine()
            # Build component descriptions for the engine
            component_descriptions = []
            for entity_id in used_components:
                for eid, comp_data in components:
                    if eid == entity_id:
                        component_descriptions.append({
                            "type": comp_data.component_type,
                            "subtype": comp_data.component_subtype,
                            "quality": comp_data.quality.value,
                            "origin_zone": comp_data.origin_zone,
                        })
                        break

            result = await engine.craft_item.remote(
                components=component_descriptions,
                player_class=player_class,
                player_level=player_level,
                player_id=str(player_id),
                recipe_id=recipe_name,
            )

            if result.success:
                # Update recipe book stats
                recipe_book.items_crafted += 1
                await recipe_actor.set.remote(player_id, recipe_book)

                # Build success message
                item = result.item
                rarity_color = _get_rarity_color(ItemRarity(item.rarity.value))
                msg_lines = [
                    f"You craft using the {recipe.name} recipe...",
                    "",
                    f"  {rarity_color}** You created: {item.name} **{{x}}",
                    f"  {item.short_description}",
                ]

                if result.experience_gained > 0:
                    msg_lines.append(f"\n  Crafting XP: +{result.experience_gained}")

                return "\n".join(msg_lines)
            else:
                return f"Crafting failed: {result.message}"
        else:
            # Fallback - simple crafting without LLM
            recipe_book.items_crafted += 1
            await recipe_actor.set.remote(player_id, recipe_book)
            return f"You craft a {recipe.name}. (CraftingEngine not available - simplified crafting)"

    except Exception as e:
        return f"Crafting error: {e}"


async def _craft_experiment(
    player_id: EntityId,
    component_keywords: List[str],
    player_class: str,
    player_level: int,
) -> str:
    """Handle experimental crafting with components."""
    if len(component_keywords) < 2:
        return "You need at least 2 components to experiment with crafting."

    # Find the components in inventory
    found_components = []
    identity_actor = get_component_actor("Identity")

    for i, keyword in enumerate(component_keywords):
        result = await _find_component_in_inventory(player_id, keyword, ordinal=1)
        if not result:
            return f"You don't have any '{keyword}' in your inventory."

        entity_id, comp_data = result
        # Check for duplicates
        if entity_id in [fc[0] for fc in found_components]:
            # Try to find another one
            result = await _find_component_in_inventory(player_id, keyword, ordinal=2)
            if not result:
                return f"You only have one '{keyword}' - you need separate components."
            entity_id, comp_data = result

        found_components.append((entity_id, comp_data))

    # Build component descriptions
    component_descriptions = []
    component_names = []
    for entity_id, comp_data in found_components:
        identity = await identity_actor.get.remote(entity_id)
        comp_name = identity.name if identity else f"{comp_data.component_subtype} {comp_data.component_type}"
        component_names.append(comp_name)
        component_descriptions.append({
            "type": comp_data.component_type,
            "subtype": comp_data.component_subtype,
            "quality": comp_data.quality.value,
            "origin_zone": comp_data.origin_zone,
        })

    # Check if this combination was already tried
    recipe_actor = get_component_actor("RecipeBook")
    recipe_book = await recipe_actor.get.remote(player_id)
    if not recipe_book:
        recipe_book = RecipeBookData()

    combo_key = get_combo_key([comp_data for _, comp_data in found_components])

    # Call the CraftingEngine
    try:
        from generation.crafting import crafting_engine_exists, get_crafting_engine

        if crafting_engine_exists():
            engine = get_crafting_engine()
            result = await engine.experiment.remote(
                components=component_descriptions,
                player_class=player_class,
                player_level=player_level,
                player_id=str(player_id),
            )

            # Record the experiment
            recipe_book.record_experiment(combo_key)
            recipe_book.experiments_attempted += 1
            await recipe_actor.set.remote(player_id, recipe_book)

            if result.success:
                item = result.item
                rarity_color = _get_rarity_color(ItemRarity(item.rarity.value))

                msg_lines = [
                    f"You experiment with: {', '.join(component_names)}...",
                    "",
                    f"  {rarity_color}** Success! You created: {item.name} **{{x}}",
                    f"  {item.short_description}",
                ]

                if result.recipe_discovered:
                    msg_lines.append(
                        f"\n  {{Y}}You discovered a new recipe: {result.recipe_discovered}!{{x}}"
                    )
                    # Add to recipe book would happen here

                if result.experience_gained > 0:
                    msg_lines.append(f"\n  Crafting XP: +{result.experience_gained}")

                return "\n".join(msg_lines)
            else:
                return f"Your experiment with {', '.join(component_names)} failed. {result.message}"
        else:
            # Record the experiment even without engine
            recipe_book.record_experiment(combo_key)
            recipe_book.experiments_attempted += 1
            await recipe_actor.set.remote(player_id, recipe_book)
            return (
                f"You experiment with: {', '.join(component_names)}...\n"
                "(CraftingEngine not available - experimentation disabled)"
            )

    except Exception as e:
        return f"Experimentation error: {e}"


# =============================================================================
# Recipes Command
# =============================================================================


@command(
    name="recipes",
    aliases=["recipebook", "cookbook"],
    category=CommandCategory.INFO,
    help_text="View your known crafting recipes.",
)
async def cmd_recipes(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    recipes          - List all known recipes
    recipes <name>   - View details of a specific recipe

    Examples:
        recipes
        recipes iron_sword
    """
    recipe_actor = get_component_actor("RecipeBook")

    recipe_book = await recipe_actor.get.remote(player_id)
    if not recipe_book:
        return (
            "You don't have a recipe book yet.\n"
            "Learn recipes from trainers or discover them through experimentation."
        )

    if not recipe_book.known_recipes:
        return (
            "Your recipe book is empty.\n"
            "Learn recipes from trainers or discover them through experimentation."
        )

    # If specific recipe requested
    if args:
        recipe_name = "_".join(args).lower()
        if recipe_name not in recipe_book.known_recipes:
            return f"You don't know a recipe called '{recipe_name}'."

        recipe = recipe_book.known_recipes[recipe_name]
        return _format_recipe_details(recipe)

    # List all recipes
    lines = [
        "{C}=== Your Recipe Book ==={x}",
        f"Recipes known: {len(recipe_book.known_recipes)}",
        f"Items crafted: {recipe_book.items_crafted}",
        f"Experiments: {recipe_book.experiments_attempted}",
        "",
        "{W}Known Recipes:{x}",
    ]

    # Group by output type
    by_type: dict = {}
    for recipe_id, recipe in recipe_book.known_recipes.items():
        item_type = recipe.output_item_type.value if recipe.output_item_type else "misc"
        if item_type not in by_type:
            by_type[item_type] = []
        by_type[item_type].append(recipe)

    for item_type, recipes in sorted(by_type.items()):
        lines.append(f"\n  {item_type.title()}:")
        for recipe in sorted(recipes, key=lambda r: r.name):
            rarity_color = _get_rarity_color(ItemRarity(recipe.output_rarity)) if recipe.output_rarity else "{w}"
            lines.append(f"    {rarity_color}{recipe.name}{'{x}'} (Lv.{recipe.min_player_level})")

    lines.append("\nUse 'recipes <name>' for details.")
    return "\n".join(lines)


def _format_recipe_details(recipe: CraftingRecipeData) -> str:
    """Format detailed recipe information."""
    lines = [
        f"{{C}}=== {recipe.name} ==={{x}}",
        f"{recipe.description}" if recipe.description else "",
        "",
    ]

    # Requirements
    lines.append("{W}Requirements:{x}")
    lines.append(f"  Level: {recipe.min_player_level}")
    if recipe.required_profession:
        lines.append(
            f"  Profession: {recipe.required_profession.value.title()} "
            f"Lv.{recipe.profession_level_required}"
        )

    # Components
    lines.append("\n{W}Components:{x}")
    for comp_key, count in recipe.required_components.items():
        comp_display = comp_key.replace(":", " ").title()
        lines.append(f"  {count}x {comp_display}")

    # Output
    lines.append("\n{W}Creates:{x}")
    rarity = recipe.output_rarity if recipe.output_rarity else "common"
    rarity_color = _get_rarity_color(ItemRarity(rarity))
    item_type = recipe.output_item_type.value if recipe.output_item_type else "item"
    lines.append(f"  {rarity_color}{rarity.title()} {item_type.title()}{'{x}'}")

    # Discovery info
    if recipe.discovered:
        source = recipe.discovery_source or "unknown"
        lines.append(f"\n{{D}}Discovered via: {source}{{x}}")

    return "\n".join(lines)


# =============================================================================
# Dismantle Command
# =============================================================================


@command(
    name="dismantle",
    aliases=["salvage", "breakdown"],
    category=CommandCategory.OBJECT,
    help_text="Break down items into crafting components.",
)
async def cmd_dismantle(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    dismantle <item> - Salvage an item for components

    Not all items can be dismantled. Quest items and certain special
    items cannot be broken down.

    Examples:
        dismantle sword
        dismantle old armor
    """
    if not args:
        return "What do you want to dismantle? Usage: dismantle <item>"

    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")
    item_actor = get_component_actor("Item")
    weapon_actor = get_component_actor("Weapon")
    armor_actor = get_component_actor("Armor")

    # Find the item in inventory
    keyword = " ".join(args).lower()
    container = await container_actor.get.remote(player_id)

    if not container or not container.item_ids:
        return "You don't have anything in your inventory."

    target_item = None
    target_identity = None

    for item_id in container.item_ids:
        identity = await identity_actor.get.remote(item_id)
        if not identity:
            continue

        if keyword in identity.name.lower():
            target_item = item_id
            target_identity = identity
            break

        for kw in identity.keywords:
            if keyword in kw.lower():
                target_item = item_id
                target_identity = identity
                break

        if target_item:
            break

    if not target_item:
        return f"You don't have '{args[0]}' in your inventory."

    # Check if item can be dismantled
    item_data = await item_actor.get.remote(target_item)
    if item_data and item_data.is_quest_item:
        return f"You cannot dismantle {target_identity.name} - it's a quest item."

    if item_data and item_data.is_bound:
        return f"You cannot dismantle {target_identity.name} - it's soulbound."

    # Determine what components to yield based on item type
    weapon_data = await weapon_actor.get.remote(target_item)
    armor_data = await armor_actor.get.remote(target_item)

    components_gained = []
    base_count = 1

    # Get proficiency data for skill bonuses
    proficiency_data = await _get_proficiency_data(player_id)
    skill_benefits = proficiency_data.get_benefits(ProficiencySkill.DISMANTLING)

    # Scale yield by rarity
    rarity = item_data.rarity if item_data else ItemRarity.COMMON
    rarity_multiplier = {
        ItemRarity.COMMON: 1,
        ItemRarity.UNCOMMON: 2,
        ItemRarity.RARE: 3,
        ItemRarity.EPIC: 4,
        ItemRarity.LEGENDARY: 5,
    }.get(rarity, 1)

    # Apply proficiency yield bonus
    yield_multiplier = skill_benefits.yield_multiplier
    was_critical = random.random() < skill_benefits.critical_chance

    if weapon_data:
        # Weapons yield metal/wood components
        metal_count = int(base_count * rarity_multiplier * yield_multiplier)
        if was_critical:
            metal_count *= 2
        components_gained.append(("metal_ore", "scrap", max(1, metal_count)))
        if weapon_data.weapon_type in ["staff", "bow"]:
            wood_count = int(base_count * yield_multiplier)
            if was_critical:
                wood_count *= 2
            components_gained.append(("wood", "scraps", max(1, wood_count)))
    elif armor_data:
        # Armor yields based on type
        count = int(base_count * rarity_multiplier * yield_multiplier)
        if was_critical:
            count *= 2
        count = max(1, count)
        if armor_data.armor_type in ["plate", "mail"]:
            components_gained.append(("metal_ore", "scrap", count))
        elif armor_data.armor_type == "leather":
            components_gained.append(("leather", "scraps", count))
        else:
            components_gained.append(("cloth", "scraps", count))
    else:
        # Generic items yield misc components
        count = int(base_count * yield_multiplier)
        if was_critical:
            count *= 2
        components_gained.append(("misc", "salvage", max(1, count)))

    # Roll for quality of salvaged components (modified by proficiency)
    base_weights = {
        "poor": 0.3,
        "normal": 0.5,
        "fine": 0.15,
        "superior": 0.04,
        "pristine": 0.01,
    }

    # Apply quality bonus from proficiency
    quality_bonus = skill_benefits.quality_bonus
    if quality_bonus > 0:
        base_weights["poor"] = max(0, base_weights["poor"] * (1 - quality_bonus * 2))
        for q in ["fine", "superior", "pristine"]:
            base_weights[q] = base_weights[q] * (1 + quality_bonus * 2)

    quality = _roll_quality(base_weights)

    # Remove the item from inventory
    # In full implementation, would call entity deletion

    # Build response
    quality_color = _get_quality_color(quality)
    lines = [
        f"You carefully dismantle {target_identity.name}...",
    ]

    if was_critical:
        lines.append("{Y}** Critical Success! **{x}")

    lines.extend([
        "",
        "{W}Components salvaged:{x}",
    ])

    total_items = 0
    for comp_type, comp_subtype, count in components_gained:
        comp_name = f"{comp_subtype} {comp_type}".strip()
        lines.append(f"  {quality_color}[{quality.value.title()}]{'{x}'} {comp_name} x{count}")
        total_items += count

    # Award proficiency XP
    item_level = item_data.level if item_data and hasattr(item_data, 'level') else 1
    xp_gained = calculate_activity_xp(
        DISMANTLING_XP_BASE,
        item_level,
        proficiency_data.get_effective_level(ProficiencySkill.DISMANTLING),
        rarity_multiplier * 0.5,  # Higher rarity = more XP
    )

    leveled = proficiency_data.add_skill_xp(ProficiencySkill.DISMANTLING, xp_gained)
    proficiency_data.record_use(ProficiencySkill.DISMANTLING, items_produced=total_items, was_critical=was_critical)
    await _save_proficiency_data(player_id, proficiency_data)

    if leveled:
        new_level = proficiency_data.get_skill(ProficiencySkill.DISMANTLING).base_level
        lines.append(
            f"\n{{Y}}Your Dismantling skill has increased to level {new_level}!{{x}}"
        )
    else:
        lines.append(f"\n{{D}}+{xp_gained} Dismantling XP{{x}}")

    return "\n".join(lines)


# =============================================================================
# Components Command
# =============================================================================


@command(
    name="components",
    aliases=["materials", "mats"],
    category=CommandCategory.INFO,
    help_text="View crafting components in your inventory.",
)
async def cmd_components(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    components - List all crafting components you're carrying.

    Shows component type, quality, and quantity.
    """
    identity_actor = get_component_actor("Identity")
    components = await _get_player_crafting_components(player_id)

    if not components:
        return "You don't have any crafting components in your inventory."

    lines = [
        "{C}=== Crafting Components ==={x}",
        "",
    ]

    # Group by category
    by_category: dict = {}
    for entity_id, comp_data in components:
        cat = comp_data.category.value
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((entity_id, comp_data))

    for category, items in sorted(by_category.items()):
        lines.append(f"{category.title()}:")

        for entity_id, comp_data in items:
            identity = await identity_actor.get.remote(entity_id)
            name = identity.name if identity else f"{comp_data.component_subtype} {comp_data.component_type}"
            quality_color = _get_quality_color(comp_data.quality)
            quality_name = comp_data.quality.value.title()

            lines.append(
                f"  {quality_color}[{quality_name}]{'{x}'} {name} x{comp_data.stack_size}"
            )

        lines.append("")

    lines.append(f"Total: {len(components)} type(s) of components")
    return "\n".join(lines)


# =============================================================================
# Skills Command (Crafting skills)
# =============================================================================


@command(
    name="craftskills",
    aliases=["professions", "tradeskills"],
    category=CommandCategory.INFO,
    help_text="View your crafting and gathering skill levels.",
)
async def cmd_craftskills(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    craftskills - View your crafting profession and gathering skill levels.
    """
    skill_actor = get_component_actor("CraftingSkill")

    skill_data = await skill_actor.get.remote(player_id)
    if not skill_data:
        return (
            "You haven't learned any crafting skills yet.\n"
            "Visit a profession trainer to begin your crafting journey."
        )

    lines = [
        "{C}=== Crafting Skills ==={x}",
        "",
    ]

    # Gathering skills
    if skill_data.gathering_levels:
        lines.append("{W}Gathering Skills:{x}")
        for skill_name, level in sorted(skill_data.gathering_levels.items()):
            xp = skill_data.gathering_xp.get(skill_name, 0)
            next_xp = skill_data._xp_for_gathering_level(level + 1)
            display_name = skill_name.replace("_", " ").title()
            lines.append(f"  {display_name}: Level {level} ({xp}/{next_xp} XP)")
        lines.append("")

    # Crafting professions
    if skill_data.profession_levels:
        lines.append("{W}Crafting Professions:{x}")
        for prof_name, level in sorted(skill_data.profession_levels.items()):
            xp = skill_data.profession_xp.get(prof_name, 0)
            next_xp = skill_data._xp_for_profession_level(level + 1)
            display_name = prof_name.replace("_", " ").title()
            active = " {G}(Active){x}" if prof_name in skill_data.active_professions else ""
            lines.append(f"  {display_name}: Level {level} ({xp}/{next_xp} XP){active}")
        lines.append("")

    # Statistics
    lines.append("{W}Statistics:{x}")
    lines.append(f"  Items crafted: {skill_data.total_items_crafted}")
    lines.append(f"  Resources gathered: {skill_data.total_resources_gathered}")

    # Profession slots
    active_count = len(skill_data.active_professions)
    lines.append(f"\n  Profession slots: {active_count}/{skill_data.max_professions}")

    return "\n".join(lines)
