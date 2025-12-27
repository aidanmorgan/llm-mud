"""
Proficiency Commands

Commands for viewing proficiency skill levels and statistics.
"""

from typing import List

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.proficiency import (
    ProficiencySkill,
    ProficiencyData,
    GATHERING_SKILLS,
    CRAFTING_SKILLS,
    UTILITY_SKILLS,
)


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


def _get_skill_category(skill: ProficiencySkill) -> str:
    """Get the category name for a skill."""
    if skill in GATHERING_SKILLS:
        return "Gathering"
    elif skill in CRAFTING_SKILLS:
        return "Crafting"
    elif skill in UTILITY_SKILLS:
        return "Utility"
    return "Other"


def _format_level_bar(current_xp: int, next_level_xp: int, width: int = 20) -> str:
    """Create a visual progress bar for skill XP."""
    if next_level_xp <= 0:
        return "[" + "=" * width + "]"

    progress = min(1.0, current_xp / next_level_xp if next_level_xp > 0 else 1.0)
    filled = int(progress * width)
    empty = width - filled

    return "[" + "=" * filled + "-" * empty + "]"


# =============================================================================
# Proficiency Command
# =============================================================================


@command(
    name="proficiency",
    aliases=["prof", "skills", "proficiencies"],
    category=CommandCategory.INFO,
    help_text="View your proficiency skills.",
)
async def cmd_proficiency(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    proficiency          - View all proficiency skills
    proficiency <skill>  - View detailed info for a skill
    proficiency summary  - View skills summary by category

    Proficiency skills level up through use, improving yields and quality.

    Examples:
        proficiency
        proficiency mining
        prof summary
    """
    proficiency_data = await _get_proficiency_data(player_id)

    if not args:
        # Show all skills
        return await _show_all_skills(proficiency_data)

    arg = args[0].lower()

    if arg == "summary":
        return await _show_summary(proficiency_data)

    # Try to find matching skill
    for skill in ProficiencySkill:
        if skill.value == arg or arg in skill.value:
            return await _show_skill_detail(proficiency_data, skill)

    return f"Unknown skill: {arg}\nUse 'proficiency' to see all skills."


async def _show_all_skills(proficiency_data: ProficiencyData) -> str:
    """Show all proficiency skills organized by category."""
    lines = [
        "{C}=== Proficiency Skills ==={x}",
        f"Total XP Earned: {proficiency_data.total_xp_earned:,}",
        f"Highest Skill: Level {proficiency_data.highest_skill_level}",
        "",
    ]

    # Group skills by category
    categories = {
        "Gathering": [],
        "Crafting": [],
        "Utility": [],
    }

    for skill in ProficiencySkill:
        entry = proficiency_data.get_skill(skill)
        category = _get_skill_category(skill)
        categories[category].append((skill, entry))

    # Display each category
    for category_name, skill_list in categories.items():
        lines.append(f"{{W}}{category_name} Skills:{{x}}")

        for skill, entry in skill_list:
            level = entry.effective_level
            base = entry.base_level

            # Color based on level
            if level >= 50:
                color = "{M}"  # Master
            elif level >= 25:
                color = "{B}"  # Expert
            elif level >= 10:
                color = "{G}"  # Journeyman
            else:
                color = "{w}"  # Novice

            # Show bonuses if any
            bonus_str = ""
            if entry.racial_bonus > 0 or entry.class_bonus > 0:
                bonus_str = f" ({base}"
                if entry.racial_bonus > 0:
                    bonus_str += f"+{entry.racial_bonus}R"
                if entry.class_bonus > 0:
                    bonus_str += f"+{entry.class_bonus}C"
                bonus_str += ")"

            skill_name = skill.value.replace("_", " ").title()
            lines.append(f"  {skill_name:<15} {color}Lv {level:>3}{x}{bonus_str}")

        lines.append("")

    lines.extend([
        "Use 'proficiency <skill>' for detailed information.",
        "Use 'proficiency summary' for a compact overview.",
    ])

    return "\n".join(lines)


async def _show_summary(proficiency_data: ProficiencyData) -> str:
    """Show compact summary of proficiency skills."""
    lines = [
        "{C}=== Proficiency Summary ==={x}",
        "",
    ]

    # Group by category and show only leveled skills
    categories = {
        "Gathering": [],
        "Crafting": [],
        "Utility": [],
    }

    for skill in ProficiencySkill:
        entry = proficiency_data.get_skill(skill)
        if entry.effective_level > 1 or entry.times_used > 0:
            category = _get_skill_category(skill)
            categories[category].append((skill, entry))

    # Sort each category by level (highest first)
    for category, skill_list in categories.items():
        skill_list.sort(key=lambda x: x[1].effective_level, reverse=True)

    for category_name, skill_list in categories.items():
        if skill_list:
            lines.append(f"{{W}}{category_name}:{{x}}")
            for skill, entry in skill_list[:5]:  # Top 5 per category
                level = entry.effective_level
                skill_name = skill.value.replace("_", " ").title()
                bar = _format_level_bar(
                    entry.current_xp - (entry.base_level * entry.base_level * 100),
                    entry.xp_to_next_level() + entry.current_xp - (entry.base_level * entry.base_level * 100),
                    10
                )
                lines.append(f"  {skill_name:<14} Lv{level:>3} {bar}")
            if len(skill_list) > 5:
                lines.append(f"  {{D}}...and {len(skill_list) - 5} more{{x}}")
            lines.append("")

    if all(not s for s in categories.values()):
        lines.append("{D}No skills trained yet. Start gathering, crafting, or fishing!{x}")

    return "\n".join(lines)


async def _show_skill_detail(proficiency_data: ProficiencyData, skill: ProficiencySkill) -> str:
    """Show detailed information for a specific skill."""
    entry = proficiency_data.get_skill(skill)
    benefits = entry.benefits

    skill_name = skill.value.replace("_", " ").title()
    category = _get_skill_category(skill)

    lines = [
        f"{{C}}=== {skill_name} ==={{x}}",
        f"Category: {category}",
        "",
        "{W}Levels:{x}",
        f"  Effective Level: {entry.effective_level}",
        f"  Base Level: {entry.base_level}",
    ]

    if entry.racial_bonus > 0:
        lines.append(f"  Racial Bonus: +{entry.racial_bonus}")
    if entry.class_bonus > 0:
        lines.append(f"  Class Bonus: +{entry.class_bonus}")
    if entry.equipment_bonus > 0:
        lines.append(f"  Equipment Bonus: +{entry.equipment_bonus}")
    if entry.buff_bonus > 0:
        lines.append(f"  Buff Bonus: +{entry.buff_bonus}")

    # XP progress
    lines.extend([
        "",
        "{W}Experience:{x}",
        f"  Current XP: {entry.current_xp:,}",
        f"  To Next Level: {entry.xp_to_next_level():,}",
        f"  Progress: {entry.xp_progress_percent():.1f}%",
    ])

    # Progress bar
    bar = _format_level_bar(
        entry.current_xp - (entry.base_level * entry.base_level * 100),
        entry.xp_to_next_level() + entry.current_xp - (entry.base_level * entry.base_level * 100),
        25
    )
    lines.append(f"  {bar}")

    # Statistics
    lines.extend([
        "",
        "{W}Statistics:{x}",
        f"  Times Used: {entry.times_used:,}",
        f"  Items Produced: {entry.items_produced:,}",
        f"  Critical Successes: {entry.critical_successes:,}",
    ])

    # Skill benefits
    lines.extend([
        "",
        "{W}Current Benefits:{x}",
        f"  Yield Bonus: +{(benefits.yield_multiplier - 1) * 100:.1f}%",
        f"  Quality Bonus: +{benefits.quality_bonus * 100:.1f}%",
        f"  Success Rate: +{benefits.success_rate_bonus * 100:.1f}%",
        f"  Critical Chance: {benefits.critical_chance * 100:.1f}%",
        f"  Speed Bonus: {(1 - benefits.speed_multiplier) * 100:.1f}%",
        f"  Efficiency Chance: {benefits.efficiency_chance * 100:.1f}%",
    ])

    # Skill rank title
    if entry.effective_level >= 75:
        rank = "{M}Grandmaster{x}"
    elif entry.effective_level >= 50:
        rank = "{Y}Master{x}"
    elif entry.effective_level >= 25:
        rank = "{B}Expert{x}"
    elif entry.effective_level >= 10:
        rank = "{G}Journeyman{x}"
    elif entry.effective_level >= 5:
        rank = "{w}Apprentice{x}"
    else:
        rank = "{D}Novice{x}"

    lines.extend([
        "",
        f"Rank: {rank}",
    ])

    return "\n".join(lines)


# =============================================================================
# Skill Ranks Command
# =============================================================================


@command(
    name="skillranks",
    aliases=["ranks"],
    category=CommandCategory.INFO,
    help_text="View proficiency skill ranks and requirements.",
)
async def cmd_skillranks(player_id: EntityId, args: List[str], **kwargs) -> str:
    """
    skillranks - Show skill rank thresholds and benefits.
    """
    lines = [
        "{C}=== Skill Ranks ==={x}",
        "",
        "{W}Rank Thresholds:{x}",
        "  {D}Novice{x}      - Level 1-4",
        "  {w}Apprentice{x}  - Level 5-9",
        "  {G}Journeyman{x}  - Level 10-24",
        "  {B}Expert{x}      - Level 25-49",
        "  {Y}Master{x}      - Level 50-74",
        "  {M}Grandmaster{x} - Level 75+",
        "",
        "{W}Benefits per Level:{x}",
        "  Yield: +0.5% per level (max +50%)",
        "  Quality: +0.2% per level (max +20%)",
        "  Success: +0.2% per level (max +20%)",
        "  Critical: +0.05% per level (starts at 20, max 10%)",
        "  Speed: +0.05% per level (max 30% faster)",
        "  Efficiency: +0.04% per level (max 10%)",
        "",
        "{W}XP Formula:{x}",
        "  XP to level N = N² × 100",
        "  Level 10 requires 10,000 total XP",
        "  Level 50 requires 2,500,000 total XP",
        "  Level 100 requires 10,000,000 total XP",
    ]

    return "\n".join(lines)
