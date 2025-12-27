"""
Level and Guild Commands

Commands for leveling up at class guilds and viewing progression.
"""

from typing import List, Optional

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.leveling import LevelingData, LevelUpQueueData, get_default_title


# =============================================================================
# Level Command
# =============================================================================


@command(
    name="level",
    aliases=["levelup", "train", "advance"],
    category=CommandCategory.CHARACTER,
    help_text="Level up at your class guild master.",
)
async def cmd_level(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    level - Attempt to level up at the guild master.

    Requirements:
    1. Must be in your class's guild hall
    2. Guild master NPC must be present
    3. Must have sufficient XP
    4. Must have any required items (consumed)
    5. Must have completed any required quests
    """
    leveling_actor = get_component_actor("Leveling")
    location_actor = get_component_actor("Location")
    stats_actor = get_component_actor("PlayerStats")
    identity_actor = get_component_actor("Identity")

    # Get player's leveling data
    leveling = await leveling_actor.get.remote(player_id)
    if not leveling:
        # Initialize leveling data
        stats = await stats_actor.get.remote(player_id)
        class_id = stats.character_class if stats else "warrior"
        leveling = LevelingData(
            class_id=class_id,
            class_title=get_default_title(class_id, 1),
        )

    # Check if already at max level
    max_level = 50  # Default max
    try:
        from ..world.class_registry import class_registry_exists, get_class_registry

        if class_registry_exists():
            registry = get_class_registry()
            class_def = await registry.get_class.remote(leveling.class_id)
            if class_def:
                max_level = class_def.max_level
    except Exception:
        pass

    if leveling.current_level >= max_level:
        return f"You have reached the maximum level ({max_level}) for your class!"

    # Check if enough XP
    if leveling.current_xp < leveling.xp_to_next:
        xp_needed = leveling.xp_to_next - leveling.current_xp
        return (
            f"You need {xp_needed:,} more experience points to reach level "
            f"{leveling.current_level + 1}.\n"
            f"Current XP: {leveling.current_xp:,} / {leveling.xp_to_next:,}"
        )

    # Get player location
    location = await location_actor.get.remote(player_id)
    if not location:
        return "You are nowhere."

    # Check if in correct guild
    try:
        from ..world.class_registry import class_registry_exists, get_class_registry

        if class_registry_exists():
            registry = get_class_registry()
            guild_config = await registry.get_guild_for_class.remote(leveling.class_id)

            if guild_config:
                if location.room_id != guild_config.location_id:
                    return (
                        f"You must visit {guild_config.guild_name} to level up.\n"
                        f"Seek out the {leveling.class_id.title()} guild."
                    )

                # Check if guild master is present (simplified - just check room)
                # In full implementation, would check NPC entity
    except Exception:
        pass

    # Get level requirements
    target_level = leveling.current_level + 1
    requirements = None
    try:
        from ..world.class_registry import class_registry_exists, get_class_registry

        if class_registry_exists():
            registry = get_class_registry()
            requirements = await registry.get_level_requirements.remote(
                leveling.class_id, target_level
            )
    except Exception:
        pass

    # Check item requirements
    if requirements and requirements.required_items:
        container_actor = get_component_actor("Container")
        container = await container_actor.get.remote(player_id)

        for req in requirements.required_items:
            item_id = req.get("item_id", "")
            count = req.get("count", 1)
            # Simplified check - would need proper item search
            has_item = False
            if container:
                for inv_item_id in container.item_ids:
                    identity = await identity_actor.get.remote(inv_item_id)
                    if identity and item_id.lower() in identity.name.lower():
                        has_item = True
                        break
            if not has_item:
                return (
                    f"You need {count}x {item_id} to advance to level {target_level}.\n"
                    "Bring the required items to the guild master."
                )

    # Check quest requirements
    if requirements and requirements.required_quests:
        quest_log_actor = get_component_actor("QuestLog")
        quest_log = await quest_log_actor.get.remote(player_id)
        completed_quests = quest_log.completed_quests if quest_log else []

        for quest_id in requirements.required_quests:
            if quest_id not in completed_quests:
                return (
                    f"You must complete the quest '{quest_id}' before advancing "
                    f"to level {target_level}."
                )

    # Check gold requirements
    if requirements and requirements.required_gold > 0:
        container_actor = get_component_actor("Container")
        container = await container_actor.get.remote(player_id)
        current_gold = container.gold if container else 0

        if current_gold < requirements.required_gold:
            return (
                f"You need {requirements.required_gold:,} gold to advance to "
                f"level {target_level}.\nYou have: {current_gold:,} gold"
            )

    # All requirements met - consume items and gold first
    container_actor = get_component_actor("Container")
    container = await container_actor.get.remote(player_id)

    # Consume required items
    consumed_items = []
    if requirements and requirements.required_items and container:
        for req in requirements.required_items:
            item_id = req.get("item_id", "")
            count = req.get("count", 1)
            # Find and remove items from inventory
            items_to_remove = []
            for inv_item_id in list(container.item_ids):
                if len(items_to_remove) >= count:
                    break
                identity = await identity_actor.get.remote(inv_item_id)
                if identity and item_id.lower() in identity.name.lower():
                    items_to_remove.append(inv_item_id)

            for item_to_remove in items_to_remove:
                container.item_ids.remove(item_to_remove)
                consumed_items.append(item_id)

        await container_actor.set.remote(player_id, container)

    # Deduct required gold
    gold_spent = 0
    if requirements and requirements.required_gold > 0 and container:
        gold_spent = requirements.required_gold
        container.gold = max(0, container.gold - gold_spent)
        await container_actor.set.remote(player_id, container)

    # Perform level up
    new_title = requirements.title if requirements else get_default_title(
        leveling.class_id, target_level
    )

    # Calculate new XP requirement
    new_xp_to_next = (target_level + 1) * (target_level + 1) * 1000
    try:
        if class_registry_exists():
            registry = get_class_registry()
            new_xp_to_next = await registry.get_xp_for_level.remote(
                leveling.class_id, target_level + 1
            )
    except Exception:
        pass

    # Apply level up
    leveling.apply_level_up(target_level, new_xp_to_next, new_title)
    await leveling_actor.set.remote(player_id, leveling)

    # Update player stats (health/mana increases)
    stats = await stats_actor.get.remote(player_id)
    if stats:
        stats.level = target_level
        # Add health/mana per level
        health_per_level = 10
        mana_per_level = 5
        try:
            if class_registry_exists():
                registry = get_class_registry()
                class_def = await registry.get_class.remote(leveling.class_id)
                if class_def:
                    health_per_level = class_def.health_per_level
                    mana_per_level = class_def.mana_per_level
        except Exception:
            pass

        stats.max_health += health_per_level
        stats.max_mana += mana_per_level
        stats.current_health = stats.max_health  # Full heal on level
        stats.current_mana = stats.max_mana
        await stats_actor.set.remote(player_id, stats)

    # Grant rewards
    gold_gained = 0
    items_gained = []
    skills_gained = []
    if requirements and requirements.rewards:
        rewards = requirements.rewards
        # Grant gold
        if rewards.gold > 0 and container:
            gold_gained = rewards.gold
            container.gold += gold_gained
            await container_actor.set.remote(player_id, container)

        # Grant items (would need proper item spawning - placeholder)
        items_gained = rewards.items if rewards.items else []

        # Grant skills (would need skill system integration - placeholder)
        skills_gained = rewards.skills if rewards.skills else []

    # Build response
    lines = [
        "",
        "{Y}============================================{x}",
        "{Y}       CONGRATULATIONS!{x}",
        "{Y}============================================{x}",
        "",
        f"You have advanced to level {target_level}!",
        f"You are now known as: {'{C}'}{new_title}{'{x}'}",
        "",
    ]

    # Show consumed items/gold
    if consumed_items or gold_spent > 0:
        lines.append("{D}Costs:{x}")
        if consumed_items:
            for item in consumed_items:
                lines.append(f"  - {item} (consumed)")
        if gold_spent > 0:
            lines.append(f"  - {gold_spent:,} gold")
        lines.append("")

    # Stat increases
    lines.append("{W}Stat Increases:{x}")
    lines.append(f"  Max Health: +{health_per_level}")
    lines.append(f"  Max Mana: +{mana_per_level}")
    lines.append("  You have been fully restored!")

    # Rewards
    if gold_gained > 0 or items_gained or skills_gained:
        lines.append(f"\n{{W}}Rewards:{{x}}")
        if gold_gained > 0:
            lines.append(f"  Gold: +{gold_gained:,}")
        for item in items_gained:
            lines.append(f"  Item: {item}")
        if skills_gained:
            lines.append(f"\n{{W}}New Skills Learned:{{x}}")
            for skill in skills_gained:
                lines.append(f"  {'{G}'}{skill}{'{x}'}")

    lines.append("")
    lines.append("{Y}============================================{x}")

    return "\n".join(lines)


# =============================================================================
# Requirements Command
# =============================================================================


@command(
    name="requirements",
    aliases=["reqs", "levelreq", "levelreqs"],
    category=CommandCategory.INFO,
    help_text="Check requirements for your next level.",
)
async def cmd_requirements(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    requirements [level] - Show level-up requirements.

    Examples:
        requirements      - Show requirements for next level
        requirements 10   - Show requirements for level 10
    """
    leveling_actor = get_component_actor("Leveling")
    stats_actor = get_component_actor("PlayerStats")

    leveling = await leveling_actor.get.remote(player_id)
    if not leveling:
        stats = await stats_actor.get.remote(player_id)
        class_id = stats.character_class if stats else "warrior"
        leveling = LevelingData(
            class_id=class_id,
            class_title=get_default_title(class_id, 1),
        )

    # Parse optional level argument
    target_level = leveling.current_level + 1
    if args:
        try:
            target_level = int(args[0])
            if target_level <= 0:
                return "Level must be positive."
        except ValueError:
            return "Usage: requirements [level]"

    # Get requirements
    requirements = None
    class_def = None
    try:
        from ..world.class_registry import class_registry_exists, get_class_registry

        if class_registry_exists():
            registry = get_class_registry()
            requirements = await registry.get_level_requirements.remote(
                leveling.class_id, target_level
            )
            class_def = await registry.get_class.remote(leveling.class_id)
    except Exception:
        pass

    if not requirements:
        # Use defaults
        xp_required = target_level * target_level * 1000
        title = get_default_title(leveling.class_id, target_level)
        lines = [
            f"{{C}}=== Requirements for Level {target_level} ==={{x}}",
            f"Title: {title}",
            f"Experience: {xp_required:,} XP",
            "",
            f"Your current XP: {leveling.current_xp:,}",
        ]
        if leveling.current_xp >= xp_required:
            lines.append("{G}You meet the XP requirement!{x}")
        else:
            lines.append(f"{{R}}Need {xp_required - leveling.current_xp:,} more XP{{x}}")
        return "\n".join(lines)

    # Build detailed requirements display
    lines = [
        f"{{C}}=== Requirements for Level {target_level} ({requirements.title}) ==={{x}}",
        "",
        "{W}Experience:{x}",
        f"  Required: {requirements.xp_required:,} XP",
        f"  Your XP:  {leveling.current_xp:,} XP",
    ]

    if leveling.current_xp >= requirements.xp_required:
        lines.append("  {G}READY{x}")
    else:
        needed = requirements.xp_required - leveling.current_xp
        lines.append(f"  {{R}}Need {needed:,} more{{x}}")

    if requirements.required_items:
        lines.append("\n{W}Required Items (consumed):{x}")
        for req in requirements.required_items:
            lines.append(f"  - {req.get('count', 1)}x {req.get('item_id', 'unknown')}")

    if requirements.required_quests:
        lines.append("\n{W}Required Quests:{x}")
        for quest_id in requirements.required_quests:
            lines.append(f"  - {quest_id}")

    if requirements.required_gold > 0:
        lines.append(f"\n{{W}}Gold Cost:{{x}} {requirements.required_gold:,}")

    if requirements.rewards:
        lines.append("\n{W}Rewards:{x}")
        if requirements.rewards.gold > 0:
            lines.append(f"  Gold: +{requirements.rewards.gold:,}")
        for item in requirements.rewards.items:
            lines.append(f"  Item: {item}")
        for skill in requirements.rewards.skills:
            lines.append(f"  Skill: {skill}")

    # Guild location
    if class_def and class_def.guild:
        lines.append(f"\n{{D}}Level up at: {class_def.guild.guild_name}{{x}}")

    return "\n".join(lines)


# =============================================================================
# Experience Command
# =============================================================================


@command(
    name="experience",
    aliases=["exp", "xp"],
    category=CommandCategory.INFO,
    help_text="View your experience progress.",
)
async def cmd_experience(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    experience - View your current experience and progress to next level.
    """
    leveling_actor = get_component_actor("Leveling")
    stats_actor = get_component_actor("PlayerStats")

    leveling = await leveling_actor.get.remote(player_id)
    if not leveling:
        stats = await stats_actor.get.remote(player_id)
        class_id = stats.character_class if stats else "warrior"
        level = stats.level if stats else 1
        return (
            f"Level: {level}\n"
            f"Class: {class_id.title()}\n"
            f"Experience tracking not initialized."
        )

    current, needed, percentage = leveling.get_xp_progress()

    # Build progress bar
    bar_width = 20
    filled = int(bar_width * percentage / 100)
    bar = "{G}" + "=" * filled + "{D}" + "-" * (bar_width - filled) + "{x}"

    lines = [
        f"{{C}}=== Experience ==={{x}}",
        "",
        f"Level: {leveling.current_level} - {leveling.class_title}",
        f"Class: {leveling.class_id.title()}",
        "",
        f"XP: {current:,} / {needed:,}",
        f"[{bar}] {percentage:.1f}%",
        "",
        f"Lifetime XP: {leveling.lifetime_xp:,}",
        f"Levels gained: {leveling.total_levels_gained}",
    ]

    # XP breakdown
    breakdown = leveling.get_xp_breakdown()
    if any(breakdown.values()):
        lines.append("\n{W}XP Sources:{x}")
        for source, amount in sorted(breakdown.items(), key=lambda x: -x[1]):
            if amount > 0:
                lines.append(f"  {source.title()}: {amount:,}")

    # Check if can level
    if leveling.pending_level_up:
        lines.append("\n{Y}You have enough XP to level up!{x}")
        lines.append("Visit your class guild to advance.")

    return "\n".join(lines)


# =============================================================================
# Guild Command
# =============================================================================


@command(
    name="guild",
    aliases=["guilds", "classguild"],
    category=CommandCategory.INFO,
    help_text="View guild information for your class.",
)
async def cmd_guild(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    guild          - View your class guild info
    guild <class>  - View info for a specific class guild

    Examples:
        guild
        guild warrior
    """
    leveling_actor = get_component_actor("Leveling")
    stats_actor = get_component_actor("PlayerStats")

    # Get player's class
    leveling = await leveling_actor.get.remote(player_id)
    stats = await stats_actor.get.remote(player_id)
    player_class = leveling.class_id if leveling else (
        stats.character_class if stats else "warrior"
    )

    # Which class to show
    target_class = args[0].lower() if args else player_class

    try:
        from ..world.class_registry import class_registry_exists, get_class_registry

        if not class_registry_exists():
            return "Class registry not available."

        registry = get_class_registry()
        class_def = await registry.get_class.remote(target_class)

        if not class_def:
            available = await registry.get_class_ids.remote()
            return (
                f"Unknown class: {target_class}\n"
                f"Available classes: {', '.join(available)}"
            )

        guild = class_def.guild

        lines = [
            f"{{C}}=== {class_def.name} Guild ==={{x}}",
            "",
            f"Guild Name: {guild.guild_name}",
            f"Location: {guild.location_id}",
            f"Guild Master: {guild.guild_master_id.replace('_', ' ').title()}",
            "",
            f"{{W}}About the {class_def.name}:{{x}}",
            f"{class_def.description}",
            "",
            f"{{W}}Class Features:{{x}}",
            f"  Prime Attribute: {class_def.prime_attribute.title()}",
            f"  Health per Level: +{class_def.health_per_level}",
            f"  Mana per Level: +{class_def.mana_per_level}",
        ]

        if class_def.class_skills:
            lines.append(f"\n{{W}}Class Skills:{{x}}")
            for skill in class_def.class_skills[:5]:
                lines.append(f"  - {skill}")
            if len(class_def.class_skills) > 5:
                lines.append(f"  ... and {len(class_def.class_skills) - 5} more")

        if target_class == player_class:
            lines.append(f"\n{{G}}This is your class guild.{{x}}")
        else:
            lines.append(f"\n{{D}}Your class: {player_class.title()}{{x}}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving guild information: {e}"


# =============================================================================
# Classes Command
# =============================================================================


@command(
    name="classes",
    aliases=["classlist"],
    category=CommandCategory.INFO,
    help_text="List all available character classes.",
)
async def cmd_classes(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    classes - List all available character classes and their guilds.
    """
    try:
        from ..world.class_registry import class_registry_exists, get_class_registry

        if not class_registry_exists():
            return (
                "Available Classes:\n"
                "  Warrior - Masters of martial combat\n"
                "  Mage - Wielders of arcane power\n"
                "  Cleric - Servants of the divine\n"
                "  Rogue - Masters of stealth and subtlety\n"
                "  Ranger - Wardens of the wild\n"
                "\nUse 'guild <class>' for more information."
            )

        registry = get_class_registry()
        all_classes = await registry.get_all_classes.remote()

        if not all_classes:
            return "No classes registered."

        lines = [
            "{C}=== Character Classes ==={x}",
            "",
        ]

        for class_def in sorted(all_classes, key=lambda c: c.name):
            lines.append(f"{'{W}'}{class_def.name}{'{x}'}")
            lines.append(f"  {class_def.description[:60]}...")
            lines.append(f"  Guild: {class_def.guild.guild_name}")
            lines.append(f"  Prime: {class_def.prime_attribute.title()}")
            lines.append("")

        lines.append("Use 'guild <class>' for detailed information.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error listing classes: {e}"
