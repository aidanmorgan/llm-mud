"""
Fishing Commands

Commands for fishing at water locations. Integrates with the proficiency system.
"""

import random
from typing import List, Optional

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.spatial import SectorType
from ..components.inventory import ItemRarity
from ..components.proficiency import (
    ProficiencySkill,
    ProficiencyData,
    FISHING_XP_BASE,
    calculate_activity_xp,
)


# =============================================================================
# Fish Data
# =============================================================================

# Fish types by water type and difficulty
FISH_BY_ZONE = {
    "freshwater": [
        {"name": "small trout", "rarity": ItemRarity.COMMON, "level": 1, "weight": (0.5, 2)},
        {"name": "river perch", "rarity": ItemRarity.COMMON, "level": 1, "weight": (0.3, 1.5)},
        {"name": "catfish", "rarity": ItemRarity.COMMON, "level": 3, "weight": (1, 5)},
        {"name": "largemouth bass", "rarity": ItemRarity.UNCOMMON, "level": 5, "weight": (2, 8)},
        {"name": "rainbow trout", "rarity": ItemRarity.UNCOMMON, "level": 7, "weight": (1, 4)},
        {"name": "northern pike", "rarity": ItemRarity.RARE, "level": 10, "weight": (5, 20)},
        {"name": "golden carp", "rarity": ItemRarity.RARE, "level": 15, "weight": (3, 10)},
        {"name": "ancient sturgeon", "rarity": ItemRarity.EPIC, "level": 20, "weight": (20, 100)},
    ],
    "saltwater": [
        {"name": "sardine", "rarity": ItemRarity.COMMON, "level": 1, "weight": (0.1, 0.3)},
        {"name": "mackerel", "rarity": ItemRarity.COMMON, "level": 2, "weight": (0.5, 2)},
        {"name": "sea bass", "rarity": ItemRarity.COMMON, "level": 4, "weight": (1, 4)},
        {"name": "red snapper", "rarity": ItemRarity.UNCOMMON, "level": 8, "weight": (2, 8)},
        {"name": "yellowfin tuna", "rarity": ItemRarity.UNCOMMON, "level": 12, "weight": (10, 50)},
        {"name": "swordfish", "rarity": ItemRarity.RARE, "level": 18, "weight": (30, 150)},
        {"name": "giant grouper", "rarity": ItemRarity.RARE, "level": 22, "weight": (50, 200)},
        {"name": "legendary marlin", "rarity": ItemRarity.EPIC, "level": 30, "weight": (100, 400)},
    ],
    "swamp": [
        {"name": "mudfish", "rarity": ItemRarity.COMMON, "level": 3, "weight": (0.5, 2)},
        {"name": "swamp eel", "rarity": ItemRarity.COMMON, "level": 5, "weight": (1, 3)},
        {"name": "bog leech", "rarity": ItemRarity.UNCOMMON, "level": 8, "weight": (0.1, 0.5)},
        {"name": "toxic puffer", "rarity": ItemRarity.UNCOMMON, "level": 12, "weight": (0.5, 2)},
        {"name": "cursed catfish", "rarity": ItemRarity.RARE, "level": 18, "weight": (5, 15)},
        {"name": "swamp horror", "rarity": ItemRarity.EPIC, "level": 25, "weight": (20, 50)},
    ],
}

# Non-fish catches (junk, treasure, etc.)
JUNK_CATCHES = [
    {"name": "old boot", "rarity": ItemRarity.COMMON, "value": 1},
    {"name": "rusty can", "rarity": ItemRarity.COMMON, "value": 0},
    {"name": "waterlogged log", "rarity": ItemRarity.COMMON, "value": 2},
    {"name": "tangled seaweed", "rarity": ItemRarity.COMMON, "value": 1},
    {"name": "broken fishing rod", "rarity": ItemRarity.COMMON, "value": 5},
]

TREASURE_CATCHES = [
    {"name": "small lockbox", "rarity": ItemRarity.UNCOMMON, "value": 50},
    {"name": "waterproof pouch", "rarity": ItemRarity.UNCOMMON, "value": 30},
    {"name": "ancient coin", "rarity": ItemRarity.RARE, "value": 100},
    {"name": "pearl necklace", "rarity": ItemRarity.RARE, "value": 200},
    {"name": "enchanted bottle", "rarity": ItemRarity.EPIC, "value": 500},
]


# =============================================================================
# Helper Functions
# =============================================================================


def _get_water_type(sector_type: SectorType) -> Optional[str]:
    """Determine water type from sector."""
    if sector_type in [SectorType.WATER_SHALLOW, SectorType.WATER_DEEP]:
        return "freshwater"
    elif sector_type == SectorType.UNDERWATER:
        return "saltwater"
    elif sector_type == SectorType.SWAMP:
        return "swamp"
    # Allow fishing at shore/beach tiles too
    return None


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


def _select_catch(
    water_type: str,
    fishing_level: int,
    skill_benefits,
) -> dict:
    """
    Select what the player catches based on skill and luck.

    Higher fishing skill = better chance of rare fish.
    """
    # Base chances
    junk_chance = max(0.05, 0.20 - fishing_level * 0.005)  # Decreases with level
    treasure_chance = min(0.10, 0.01 + fishing_level * 0.002)  # Increases with level
    fish_chance = 1.0 - junk_chance - treasure_chance

    # Apply skill bonuses
    if skill_benefits:
        # Success rate bonus reduces junk
        junk_chance = max(0.02, junk_chance - skill_benefits.success_rate_bonus)
        # Quality bonus increases treasure chance
        treasure_chance = min(0.15, treasure_chance + skill_benefits.quality_bonus)

    roll = random.random()

    if roll < junk_chance:
        return {"type": "junk", "item": random.choice(JUNK_CATCHES)}
    elif roll < junk_chance + treasure_chance:
        # Filter treasures by rarity based on level
        available = [t for t in TREASURE_CATCHES]
        if fishing_level < 10:
            available = [t for t in available if t["rarity"] in [ItemRarity.COMMON, ItemRarity.UNCOMMON]]
        elif fishing_level < 20:
            available = [t for t in available if t["rarity"] != ItemRarity.EPIC]
        return {"type": "treasure", "item": random.choice(available)}
    else:
        # Fish - filter by level
        fish_pool = FISH_BY_ZONE.get(water_type, FISH_BY_ZONE["freshwater"])

        # Filter fish by what player can catch (level + some stretch)
        max_fish_level = fishing_level + 5
        available_fish = [f for f in fish_pool if f["level"] <= max_fish_level]

        if not available_fish:
            available_fish = [fish_pool[0]]  # Fallback to easiest fish

        # Weight selection toward appropriate level fish
        weights = []
        for fish in available_fish:
            level_diff = abs(fish["level"] - fishing_level)
            weight = max(1, 10 - level_diff)
            # Rarity modifier
            rarity_mod = {
                ItemRarity.COMMON: 4,
                ItemRarity.UNCOMMON: 2,
                ItemRarity.RARE: 1,
                ItemRarity.EPIC: 0.5,
            }.get(fish["rarity"], 1)
            # Quality bonus increases rare fish chance
            if skill_benefits:
                rarity_mod *= (1 + skill_benefits.quality_bonus * 2)
            weights.append(weight * rarity_mod)

        # Weighted random selection
        total = sum(weights)
        roll = random.random() * total
        cumulative = 0
        selected_fish = available_fish[0]
        for fish, weight in zip(available_fish, weights):
            cumulative += weight
            if roll <= cumulative:
                selected_fish = fish
                break

        return {"type": "fish", "item": selected_fish}


# =============================================================================
# Fish Command
# =============================================================================


@command(
    name="fish",
    aliases=["fishing", "cast"],
    category=CommandCategory.OBJECT,
    help_text="Fish in nearby water.",
)
async def cmd_fish(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    fish - Cast your line and try to catch something.

    You must be near water to fish. Different water types have different fish.
    Higher fishing skill increases your chances of catching rare fish.

    Examples:
        fish
        cast
    """
    location_actor = get_component_actor("Location")
    room_actor = get_component_actor("Room")
    identity_actor = get_component_actor("Identity")
    container_actor = get_component_actor("Container")

    # Get player location
    location = await location_actor.get.remote(player_id)
    if not location:
        return "You are nowhere."

    # Get room data
    room_data = await room_actor.get.remote(location.room_id)
    if not room_data:
        return "You can't fish here."

    # Check if near water
    water_type = _get_water_type(room_data.sector_type)

    # Also check exits for adjacent water
    if not water_type:
        # Check if any description mentions water
        room_identity = await identity_actor.get.remote(location.room_id)
        if room_identity:
            desc_lower = room_identity.name.lower()
            if "river" in desc_lower or "lake" in desc_lower or "pond" in desc_lower:
                water_type = "freshwater"
            elif "ocean" in desc_lower or "sea" in desc_lower or "beach" in desc_lower or "bay" in desc_lower:
                water_type = "saltwater"
            elif "swamp" in desc_lower or "marsh" in desc_lower or "bog" in desc_lower:
                water_type = "swamp"

    if not water_type:
        return "There's no water here to fish in."

    # Check for fishing rod (simplified - just check inventory keywords)
    container = await container_actor.get.remote(player_id)
    has_rod = False
    if container:
        for item_id in container.item_ids:
            item_identity = await identity_actor.get.remote(item_id)
            if item_identity:
                name_lower = item_identity.name.lower()
                if "rod" in name_lower or "pole" in name_lower or "line" in name_lower:
                    has_rod = True
                    break

    if not has_rod:
        return (
            "You need a fishing rod to fish.\n"
            "Try buying one from a general store or finding one."
        )

    # Get proficiency data
    proficiency_data = await _get_proficiency_data(player_id)
    fishing_skill = proficiency_data.get_skill(ProficiencySkill.FISHING)
    skill_benefits = fishing_skill.benefits
    fishing_level = fishing_skill.effective_level

    # Select what we catch
    catch = _select_catch(water_type, fishing_level, skill_benefits)
    catch_type = catch["type"]
    item = catch["item"]

    # Check for critical catch (bigger fish, more treasure)
    was_critical = random.random() < skill_benefits.critical_chance

    # Build response
    lines = ["You cast your line into the water...", ""]

    # Simulate fishing time based on skill (faster at higher levels)
    # (In a real implementation, this might be a delayed action)

    if catch_type == "junk":
        rarity_color = _get_rarity_color(item["rarity"])
        lines.append(f"You reel in... {rarity_color}{item['name']}{{x}}")
        lines.append("{D}Just some junk. Better luck next time.{x}")
        xp_mult = 0.5
    elif catch_type == "treasure":
        rarity_color = _get_rarity_color(item["rarity"])
        lines.append(f"{{Y}}Something shiny!{{x}}")
        lines.append(f"You pulled up: {rarity_color}{item['name']}{{x}}")
        lines.append(f"  Worth approximately {item['value']} gold")
        xp_mult = 2.0
    else:
        # Fish
        rarity_color = _get_rarity_color(item["rarity"])
        weight_min, weight_max = item["weight"]
        fish_weight = random.uniform(weight_min, weight_max)

        if was_critical:
            fish_weight *= 1.5
            lines.append("{Y}** MONSTER CATCH! **{x}")

        fish_weight = round(fish_weight, 1)

        lines.append(f"You caught a {rarity_color}{item['name']}{{x}}!")
        lines.append(f"  Weight: {fish_weight} lbs")

        if item["rarity"] == ItemRarity.RARE:
            lines.append("  {B}A rare catch!{x}")
        elif item["rarity"] == ItemRarity.EPIC:
            lines.append("  {M}An incredible catch! This is one for the record books!{x}")

        xp_mult = 1.0

    # Calculate and award XP
    difficulty = item.get("level", 1)
    xp_gained = calculate_activity_xp(
        FISHING_XP_BASE,
        difficulty,
        fishing_level,
        xp_mult,
    )

    leveled = proficiency_data.add_skill_xp(ProficiencySkill.FISHING, xp_gained)
    proficiency_data.record_use(
        ProficiencySkill.FISHING,
        items_produced=1,
        was_critical=was_critical,
    )
    await _save_proficiency_data(player_id, proficiency_data)

    if leveled:
        new_level = proficiency_data.get_skill(ProficiencySkill.FISHING).base_level
        lines.append(
            f"\n{{Y}}Your Fishing skill has increased to level {new_level}!{{x}}"
        )
    else:
        lines.append(f"\n{{D}}+{xp_gained} Fishing XP{{x}}")

    return "\n".join(lines)


# =============================================================================
# Bait Command
# =============================================================================


@command(
    name="bait",
    category=CommandCategory.OBJECT,
    help_text="Check or set your fishing bait.",
)
async def cmd_bait(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    bait          - Check current bait
    bait <type>   - Set bait type

    Different bait attracts different fish.
    """
    if not args:
        return (
            "Current bait: None\n\n"
            "Bait types affect what you can catch:\n"
            "  worms   - Good for freshwater fish\n"
            "  shrimp  - Good for saltwater fish\n"
            "  insects - Good for swamp fishing\n"
            "  lures   - Better chance at rare fish\n\n"
            "Use 'bait <type>' to set your bait."
        )

    bait_type = args[0].lower()
    valid_baits = ["worms", "shrimp", "insects", "lures", "none"]

    if bait_type not in valid_baits:
        return f"Unknown bait type: {bait_type}\nValid types: {', '.join(valid_baits)}"

    # In a full implementation, would update player state
    return f"You set your bait to: {bait_type}"


# =============================================================================
# Fishing Stats Command
# =============================================================================


@command(
    name="fishstats",
    aliases=["catchlog"],
    category=CommandCategory.INFO,
    help_text="View your fishing statistics.",
)
async def cmd_fishstats(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    fishstats - View your fishing statistics and records.
    """
    proficiency_data = await _get_proficiency_data(player_id)
    fishing_skill = proficiency_data.get_skill(ProficiencySkill.FISHING)

    lines = [
        "{C}=== Fishing Statistics ==={x}",
        "",
        f"Fishing Level: {fishing_skill.effective_level}",
        f"  Base level: {fishing_skill.base_level}",
    ]

    if fishing_skill.racial_bonus > 0:
        lines.append(f"  Racial bonus: +{fishing_skill.racial_bonus}")
    if fishing_skill.class_bonus > 0:
        lines.append(f"  Class bonus: +{fishing_skill.class_bonus}")

    lines.extend([
        "",
        f"Experience: {fishing_skill.current_xp:,} XP",
        f"Next level: {fishing_skill.xp_to_next_level():,} XP needed",
        f"Progress: {fishing_skill.xp_progress_percent():.1f}%",
        "",
        "{W}Statistics:{x}",
        f"  Total casts: {fishing_skill.times_used}",
        f"  Fish caught: {fishing_skill.items_produced}",
        f"  Monster catches: {fishing_skill.critical_successes}",
        "",
        "{W}Skill Benefits:{x}",
    ])

    benefits = fishing_skill.benefits
    lines.extend([
        f"  Yield bonus: +{(benefits.yield_multiplier - 1) * 100:.1f}%",
        f"  Quality bonus: +{benefits.quality_bonus * 100:.1f}%",
        f"  Critical chance: {benefits.critical_chance * 100:.1f}%",
        f"  Speed bonus: {(1 - benefits.speed_multiplier) * 100:.1f}% faster",
    ])

    return "\n".join(lines)
