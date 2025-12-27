"""
Cooking Commands

Commands for cooking food at campfires and kitchens. Integrates with the proficiency system.
"""

import random
from typing import List, Optional, Dict, Any

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.spatial import SectorType
from ..components.inventory import ItemRarity
from ..components.proficiency import (
    ProficiencySkill,
    ProficiencyData,
    COOKING_XP_BASE,
    calculate_activity_xp,
)


# =============================================================================
# Recipe Data
# =============================================================================

# Recipes: {name: {ingredients: [...], level: X, output: {...}, station: ...}}
COOKING_RECIPES: Dict[str, Dict[str, Any]] = {
    # Level 1 recipes - basic food
    "grilled_fish": {
        "name": "Grilled Fish",
        "ingredients": [("fish", 1)],
        "level": 1,
        "station": "fire",
        "output": {
            "name": "grilled fish",
            "effect": "Restores 20 health over 10 seconds",
            "stats": {"health_regen": 2, "duration": 10},
        },
    },
    "roasted_meat": {
        "name": "Roasted Meat",
        "ingredients": [("raw_meat", 1)],
        "level": 1,
        "station": "fire",
        "output": {
            "name": "roasted meat",
            "effect": "Restores 25 health over 10 seconds",
            "stats": {"health_regen": 2.5, "duration": 10},
        },
    },
    "bread": {
        "name": "Fresh Bread",
        "ingredients": [("flour", 2), ("water", 1)],
        "level": 2,
        "station": "oven",
        "output": {
            "name": "fresh bread",
            "effect": "Restores 15 health",
            "stats": {"health": 15},
        },
    },
    # Level 5 recipes - improved food
    "fish_stew": {
        "name": "Hearty Fish Stew",
        "ingredients": [("fish", 2), ("vegetable", 1), ("water", 1)],
        "level": 5,
        "station": "fire",
        "output": {
            "name": "hearty fish stew",
            "effect": "Restores 50 health and grants +5 stamina for 5 minutes",
            "stats": {"health": 50, "stamina_buff": 5, "duration": 300},
            "rarity": ItemRarity.UNCOMMON,
        },
    },
    "meat_pie": {
        "name": "Savory Meat Pie",
        "ingredients": [("raw_meat", 2), ("flour", 2), ("vegetable", 1)],
        "level": 5,
        "station": "oven",
        "output": {
            "name": "savory meat pie",
            "effect": "Restores 60 health and grants +10% combat damage for 5 minutes",
            "stats": {"health": 60, "damage_buff": 10, "duration": 300},
            "rarity": ItemRarity.UNCOMMON,
        },
    },
    # Level 10 recipes - buff food
    "spiced_wine": {
        "name": "Spiced Wine",
        "ingredients": [("wine", 1), ("spice", 2)],
        "level": 10,
        "station": "fire",
        "output": {
            "name": "spiced wine",
            "effect": "+5 to all stats for 10 minutes",
            "stats": {"all_stats": 5, "duration": 600},
            "rarity": ItemRarity.UNCOMMON,
        },
    },
    "warriors_feast": {
        "name": "Warrior's Feast",
        "ingredients": [("raw_meat", 3), ("vegetable", 2), ("spice", 1)],
        "level": 10,
        "station": "fire",
        "output": {
            "name": "warrior's feast",
            "effect": "+20% damage, +100 max health for 15 minutes",
            "stats": {"damage_buff": 20, "max_health": 100, "duration": 900},
            "rarity": ItemRarity.RARE,
        },
    },
    # Level 15 recipes - advanced buff food
    "mages_delight": {
        "name": "Mage's Delight",
        "ingredients": [("herb", 3), ("arcane_essence", 1), ("honey", 1)],
        "level": 15,
        "station": "fire",
        "output": {
            "name": "mage's delight",
            "effect": "+50 max mana, +20% spell damage for 15 minutes",
            "stats": {"max_mana": 50, "spell_damage": 20, "duration": 900},
            "rarity": ItemRarity.RARE,
        },
    },
    "rangers_rations": {
        "name": "Ranger's Rations",
        "ingredients": [("dried_meat", 2), ("trail_mix", 1), ("herb", 1)],
        "level": 15,
        "station": None,  # No station needed
        "output": {
            "name": "ranger's rations",
            "effect": "Reduces travel time, +20% movement speed for 30 minutes",
            "stats": {"speed_buff": 20, "duration": 1800},
            "rarity": ItemRarity.RARE,
        },
    },
    # Level 20 recipes - feast food
    "royal_banquet": {
        "name": "Royal Banquet",
        "ingredients": [("raw_meat", 5), ("vegetable", 3), ("spice", 3), ("wine", 1)],
        "level": 20,
        "station": "oven",
        "output": {
            "name": "royal banquet",
            "effect": "Full restore, +all stats, +damage for 30 minutes",
            "stats": {"full_restore": True, "all_stats": 10, "damage_buff": 15, "duration": 1800},
            "rarity": ItemRarity.EPIC,
        },
    },
}

# Ingredient synonyms (what item keywords map to ingredient types)
INGREDIENT_KEYWORDS: Dict[str, List[str]] = {
    "fish": ["fish", "trout", "bass", "salmon", "perch", "tuna", "sardine", "carp"],
    "raw_meat": ["meat", "venison", "beef", "pork", "chicken", "mutton", "steak"],
    "flour": ["flour", "wheat"],
    "water": ["water", "flask", "canteen"],
    "vegetable": ["vegetable", "carrot", "potato", "onion", "cabbage", "turnip"],
    "spice": ["spice", "pepper", "salt", "cinnamon", "clove"],
    "wine": ["wine", "ale", "mead"],
    "herb": ["herb", "mint", "thyme", "rosemary", "sage"],
    "honey": ["honey", "honeycomb"],
    "dried_meat": ["jerky", "dried", "smoked"],
    "trail_mix": ["nuts", "berries", "trail"],
    "arcane_essence": ["essence", "arcane", "magical"],
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


def _get_rarity_color(rarity: ItemRarity) -> str:
    """Get ANSI color code for rarity display."""
    colors = {
        ItemRarity.COMMON: "{w}",
        ItemRarity.UNCOMMON: "{G}",
        ItemRarity.RARE: "{B}",
        ItemRarity.EPIC: "{M}",
        ItemRarity.LEGENDARY: "{Y}",
    }
    return colors.get(rarity, "{w}")


def _match_ingredient(item_name: str) -> Optional[str]:
    """Match an item name to an ingredient type."""
    name_lower = item_name.lower()
    for ingredient, keywords in INGREDIENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in name_lower:
                return ingredient
    return None


async def _check_cooking_station(player_id: EntityId, required_station: Optional[str]) -> bool:
    """Check if player has access to required cooking station."""
    if required_station is None:
        return True  # No station required

    location_actor = get_component_actor("Location")
    room_actor = get_component_actor("Room")
    identity_actor = get_component_actor("Identity")

    location = await location_actor.get.remote(player_id)
    if not location:
        return False

    room_data = await room_actor.get.remote(location.room_id)
    room_identity = await identity_actor.get.remote(location.room_id)

    # Check room sector and description for cooking stations
    if required_station == "fire":
        # Look for campfire, fireplace, hearth
        if room_identity:
            desc_lower = (room_identity.name + " " + room_identity.short_description).lower()
            if any(word in desc_lower for word in ["fire", "campfire", "hearth", "flames", "cooking"]):
                return True
        # Also check room type
        if room_data and room_data.sector_type == SectorType.CAMPSITE:
            return True

    elif required_station == "oven":
        # Look for kitchen, bakery, oven
        if room_identity:
            desc_lower = (room_identity.name + " " + room_identity.short_description).lower()
            if any(word in desc_lower for word in ["kitchen", "bakery", "oven", "stove"]):
                return True
        if room_data and room_data.sector_type == SectorType.INSIDE:
            # Most inside locations might have cooking facilities
            if room_identity and "inn" in room_identity.name.lower():
                return True

    return False


async def _get_inventory_ingredients(player_id: EntityId) -> Dict[str, List[EntityId]]:
    """Get all ingredients from player inventory, grouped by type."""
    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")

    container = await container_actor.get.remote(player_id)
    if not container:
        return {}

    ingredients: Dict[str, List[EntityId]] = {}

    for item_id in container.item_ids:
        item_identity = await identity_actor.get.remote(item_id)
        if item_identity:
            ingredient_type = _match_ingredient(item_identity.name)
            if ingredient_type:
                if ingredient_type not in ingredients:
                    ingredients[ingredient_type] = []
                ingredients[ingredient_type].append(item_id)

    return ingredients


def _can_make_recipe(recipe: Dict, available: Dict[str, List[EntityId]]) -> bool:
    """Check if player has ingredients for a recipe."""
    for ingredient, count in recipe["ingredients"]:
        if ingredient not in available or len(available[ingredient]) < count:
            return False
    return True


def _get_quality_modifier(cooking_level: int, recipe_level: int, skill_benefits) -> float:
    """Calculate quality modifier for cooked food."""
    base = 1.0

    # Level difference bonus
    level_diff = cooking_level - recipe_level
    if level_diff > 0:
        base += min(0.3, level_diff * 0.02)  # Up to +30% for 15 levels above

    # Skill benefits
    if skill_benefits:
        base += skill_benefits.quality_bonus

    return base


# =============================================================================
# Cook Command
# =============================================================================


@command(
    name="cook",
    aliases=["prepare", "bake"],
    category=CommandCategory.OBJECT,
    help_text="Cook food from ingredients.",
)
async def cmd_cook(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    cook <recipe>     - Cook a specific recipe
    cook              - Show available recipes

    Higher cooking skill produces higher quality food with better effects.

    Examples:
        cook grilled_fish
        cook warriors_feast
    """
    # Get proficiency data
    proficiency_data = await _get_proficiency_data(player_id)
    cooking_skill = proficiency_data.get_skill(ProficiencySkill.COOKING)
    skill_benefits = cooking_skill.benefits
    cooking_level = cooking_skill.effective_level

    if not args:
        # Show available recipes
        lines = ["{C}=== Cooking Recipes ==={x}", ""]

        available_ingredients = await _get_inventory_ingredients(player_id)

        for recipe_id, recipe in sorted(COOKING_RECIPES.items(), key=lambda x: x[1]["level"]):
            level_req = recipe["level"]
            can_learn = cooking_level >= level_req
            has_ingredients = _can_make_recipe(recipe, available_ingredients)

            if can_learn:
                status = "{G}[CAN MAKE]{x}" if has_ingredients else "{D}[need ingredients]{x}"
            else:
                status = f"{{R}}[Requires level {level_req}]{{x}}"

            lines.append(f"  {recipe['name']:<20} {status}")

        lines.extend([
            "",
            "Use 'cook <recipe_id>' to cook something.",
            "Use 'recipes' to see detailed recipe info.",
        ])
        return "\n".join(lines)

    # Cook a specific recipe
    recipe_id = "_".join(args).lower()

    if recipe_id not in COOKING_RECIPES:
        # Try partial match
        matches = [r for r in COOKING_RECIPES if recipe_id in r]
        if len(matches) == 1:
            recipe_id = matches[0]
        elif len(matches) > 1:
            return f"Multiple recipes match '{recipe_id}': {', '.join(matches)}"
        else:
            return f"Unknown recipe: {recipe_id}\nUse 'cook' to see available recipes."

    recipe = COOKING_RECIPES[recipe_id]

    # Check level requirement
    if cooking_level < recipe["level"]:
        return (
            f"You need Cooking level {recipe['level']} to make {recipe['name']}.\n"
            f"Your current level is {cooking_level}."
        )

    # Check cooking station
    has_station = await _check_cooking_station(player_id, recipe.get("station"))
    if not has_station:
        station = recipe.get("station", "cooking station")
        return f"You need a {station} to make {recipe['name']}."

    # Check ingredients
    available_ingredients = await _get_inventory_ingredients(player_id)
    if not _can_make_recipe(recipe, available_ingredients):
        lines = [f"You don't have the ingredients for {recipe['name']}:", ""]
        for ingredient, count in recipe["ingredients"]:
            have = len(available_ingredients.get(ingredient, []))
            status = "{G}[OK]{x}" if have >= count else f"{{R}}[have {have}]{{x}}"
            lines.append(f"  {ingredient}: {count} {status}")
        return "\n".join(lines)

    # Check for critical success
    was_critical = random.random() < skill_benefits.critical_chance

    # Calculate quality
    quality_mod = _get_quality_modifier(cooking_level, recipe["level"], skill_benefits)
    if was_critical:
        quality_mod *= 1.25

    # Determine quality tier
    if quality_mod >= 1.3:
        quality_name = "exceptional"
        quality_prefix = "{M}"
    elif quality_mod >= 1.15:
        quality_name = "fine"
        quality_prefix = "{B}"
    elif quality_mod >= 1.0:
        quality_name = "good"
        quality_prefix = "{G}"
    else:
        quality_name = "decent"
        quality_prefix = "{w}"

    # Build result
    output = recipe["output"]
    rarity = output.get("rarity", ItemRarity.COMMON)
    rarity_color = _get_rarity_color(rarity)

    lines = [
        f"You begin preparing {recipe['name']}...",
        "",
    ]

    if was_critical:
        lines.append("{Y}** Perfect execution! **{x}")

    lines.extend([
        f"You created: {quality_prefix}{quality_name} {output['name']}{{x}}",
        f"  {rarity_color}[{rarity.value}]{{x}}",
        f"  Effect: {output['effect']}",
    ])

    if quality_mod > 1.0:
        bonus_pct = (quality_mod - 1) * 100
        lines.append(f"  {{G}}Quality bonus: +{bonus_pct:.0f}% effectiveness{{x}}")

    # Calculate and award XP
    xp_mult = 1.0
    if was_critical:
        xp_mult = 1.5
    if rarity in [ItemRarity.RARE, ItemRarity.EPIC]:
        xp_mult *= 1.5

    xp_gained = calculate_activity_xp(
        COOKING_XP_BASE,
        recipe["level"],
        cooking_level,
        xp_mult,
    )

    leveled = proficiency_data.add_skill_xp(ProficiencySkill.COOKING, xp_gained)
    proficiency_data.record_use(
        ProficiencySkill.COOKING,
        items_produced=1,
        was_critical=was_critical,
    )
    await _save_proficiency_data(player_id, proficiency_data)

    if leveled:
        new_level = proficiency_data.get_skill(ProficiencySkill.COOKING).base_level
        lines.append(f"\n{{Y}}Your Cooking skill has increased to level {new_level}!{{x}}")
    else:
        lines.append(f"\n{{D}}+{xp_gained} Cooking XP{{x}}")

    # Note: In a full implementation, we would:
    # 1. Remove ingredients from inventory
    # 2. Create the food item in inventory

    return "\n".join(lines)


# =============================================================================
# Recipes Command
# =============================================================================


@command(
    name="recipes",
    aliases=["recipelist", "cookbook"],
    category=CommandCategory.INFO,
    help_text="View detailed cooking recipes.",
)
async def cmd_recipes(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    recipes           - List all known recipes
    recipes <name>    - View specific recipe details
    """
    # Get proficiency data
    proficiency_data = await _get_proficiency_data(player_id)
    cooking_skill = proficiency_data.get_skill(ProficiencySkill.COOKING)
    cooking_level = cooking_skill.effective_level

    if not args:
        lines = [
            "{C}=== Your Cookbook ==={x}",
            f"Cooking Level: {cooking_level}",
            "",
            "{W}Known Recipes:{x}",
        ]

        learned = []
        locked = []

        for recipe_id, recipe in sorted(COOKING_RECIPES.items(), key=lambda x: x[1]["level"]):
            if cooking_level >= recipe["level"]:
                learned.append((recipe_id, recipe))
            else:
                locked.append((recipe_id, recipe))

        if learned:
            for recipe_id, recipe in learned:
                output = recipe["output"]
                rarity = output.get("rarity", ItemRarity.COMMON)
                rarity_color = _get_rarity_color(rarity)
                lines.append(
                    f"  {recipe['name']:<20} [Lv{recipe['level']:>2}] {rarity_color}{rarity.value}{x}"
                )
        else:
            lines.append("  {D}No recipes learned yet{x}")

        if locked:
            lines.append("")
            lines.append("{D}Locked Recipes:{x}")
            for recipe_id, recipe in locked[:5]:  # Show first 5 locked
                lines.append(f"  {recipe['name']:<20} {{R}}[Requires Lv{recipe['level']}]{{x}}")
            if len(locked) > 5:
                lines.append(f"  {{D}}...and {len(locked) - 5} more{{x}}")

        lines.extend([
            "",
            "Use 'recipes <name>' for details.",
        ])
        return "\n".join(lines)

    # Show specific recipe
    recipe_search = "_".join(args).lower()

    # Find matching recipe
    recipe_id = None
    for rid in COOKING_RECIPES:
        if recipe_search in rid or recipe_search in COOKING_RECIPES[rid]["name"].lower():
            recipe_id = rid
            break

    if not recipe_id:
        return f"Unknown recipe: {recipe_search}"

    recipe = COOKING_RECIPES[recipe_id]
    output = recipe["output"]
    rarity = output.get("rarity", ItemRarity.COMMON)
    rarity_color = _get_rarity_color(rarity)

    # Check if player knows it
    known = cooking_level >= recipe["level"]
    available_ingredients = await _get_inventory_ingredients(player_id)
    can_make = known and _can_make_recipe(recipe, available_ingredients)

    lines = [
        f"{{C}}=== {recipe['name']} ==={{x}}",
        f"Level Required: {recipe['level']} {'({G}Known{x})' if known else '({R}Locked{x})'}",
        f"Station: {recipe.get('station', 'none')}",
        "",
        "{W}Ingredients:{x}",
    ]

    for ingredient, count in recipe["ingredients"]:
        have = len(available_ingredients.get(ingredient, []))
        status = "{G}[OK]{x}" if have >= count else f"{{R}}[{have}/{count}]{{x}}"
        lines.append(f"  {ingredient}: {count} {status}")

    lines.extend([
        "",
        "{W}Output:{x}",
        f"  {rarity_color}{output['name']}{x}",
        f"  Rarity: {rarity_color}{rarity.value}{{x}}",
        f"  Effect: {output['effect']}",
    ])

    if can_make:
        lines.append("\n{G}You can make this recipe!{x}")
    elif known:
        lines.append("\n{Y}You need more ingredients.{x}")
    else:
        lines.append(f"\n{{R}}Learn at Cooking level {recipe['level']}.{{x}}")

    return "\n".join(lines)


# =============================================================================
# Cooking Stats Command
# =============================================================================


@command(
    name="cookstats",
    aliases=["chefstats"],
    category=CommandCategory.INFO,
    help_text="View your cooking statistics.",
)
async def cmd_cookstats(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    cookstats - View your cooking statistics and skill level.
    """
    proficiency_data = await _get_proficiency_data(player_id)
    cooking_skill = proficiency_data.get_skill(ProficiencySkill.COOKING)

    lines = [
        "{C}=== Cooking Statistics ==={x}",
        "",
        f"Cooking Level: {cooking_skill.effective_level}",
        f"  Base level: {cooking_skill.base_level}",
    ]

    if cooking_skill.racial_bonus > 0:
        lines.append(f"  Racial bonus: +{cooking_skill.racial_bonus}")
    if cooking_skill.class_bonus > 0:
        lines.append(f"  Class bonus: +{cooking_skill.class_bonus}")

    lines.extend([
        "",
        f"Experience: {cooking_skill.current_xp:,} XP",
        f"Next level: {cooking_skill.xp_to_next_level():,} XP needed",
        f"Progress: {cooking_skill.xp_progress_percent():.1f}%",
        "",
        "{W}Statistics:{x}",
        f"  Dishes prepared: {cooking_skill.times_used}",
        f"  Total items made: {cooking_skill.items_produced}",
        f"  Perfect dishes: {cooking_skill.critical_successes}",
    ])

    # Count known recipes
    known_count = sum(
        1 for r in COOKING_RECIPES.values()
        if cooking_skill.effective_level >= r["level"]
    )
    lines.append(f"  Recipes known: {known_count}/{len(COOKING_RECIPES)}")

    lines.extend([
        "",
        "{W}Skill Benefits:{x}",
    ])

    benefits = cooking_skill.benefits
    lines.extend([
        f"  Quality bonus: +{benefits.quality_bonus * 100:.1f}%",
        f"  Perfect dish chance: {benefits.critical_chance * 100:.1f}%",
        f"  Efficiency: {benefits.efficiency_chance * 100:.1f}% less ingredients",
        f"  Speed bonus: {(1 - benefits.speed_multiplier) * 100:.1f}% faster",
    ])

    return "\n".join(lines)
