"""
Skill and Spell Commands

Commands for using skills, viewing abilities, and managing active effects.

Commands:
- cast/use: Use a skill or spell
- skills/spells: List known skills
- affects: Show active effects
- practice: Improve skill proficiency at trainers
"""

from __future__ import annotations

import logging
from typing import List, NamedTuple, Optional

from core import EntityId
from core.component import get_component_actor

from .registry import CommandCategory, command
from ..components.position import Position

logger = logging.getLogger(__name__)


# =============================================================================
# Result Types
# =============================================================================


class SkillInfo(NamedTuple):
    """Information about a skill for display."""

    skill_id: str
    name: str
    category: str
    level: int
    proficiency: int
    mana_cost: int
    cooldown: float
    is_ready: bool


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_player_skills(player_id: EntityId) -> Optional[dict]:
    """Get player's SkillSet component."""
    try:
        skill_actor = get_component_actor("SkillSet")
        return await skill_actor.get.remote(player_id)
    except Exception:
        return None


async def _get_active_effects(entity_id: EntityId) -> Optional[dict]:
    """Get entity's ActiveEffects component."""
    try:
        effects_actor = get_component_actor("ActiveEffects")
        return await effects_actor.get.remote(entity_id)
    except Exception:
        return None


async def _get_player_stats(player_id: EntityId) -> Optional[dict]:
    """Get player's Stats component."""
    try:
        stats_actor = get_component_actor("Stats")
        return await stats_actor.get.remote(player_id)
    except Exception:
        return None


async def _get_skill_definition(skill_id: str):
    """Get a skill definition from the registry."""
    from ..world.skill_registry import get_skill_registry

    try:
        registry = get_skill_registry()
        return await registry.get.remote(skill_id)
    except Exception as e:
        logger.error(f"Failed to get skill {skill_id}: {e}")
        return None


async def _find_target_in_room(
    player_id: EntityId, keyword: str
) -> Optional[EntityId]:
    """Find a target in the same room as the player."""
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")

    player_loc = await location_actor.get.remote(player_id)
    if not player_loc:
        return None

    room_id = player_loc.room_id
    all_locations = await location_actor.get_all.remote()

    for entity_id, loc in all_locations.items():
        if loc.room_id != room_id or entity_id == player_id:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if not identity:
            continue

        # Check name match
        if keyword.lower() in identity.name.lower():
            return entity_id

        # Check keywords
        for kw in getattr(identity, "keywords", []):
            if keyword.lower() in kw.lower():
                return entity_id

    return None


async def _queue_skill_use(
    player_id: EntityId, skill_id: str, target_id: Optional[EntityId], target_keyword: str
) -> None:
    """Queue a skill request for the SkillExecutionSystem."""
    from ..systems.skills import SkillRequestData

    try:
        request_actor = get_component_actor("SkillRequest")

        # Create request component
        request = SkillRequestData(
            skill_id=skill_id,
            target_id=target_id,
            target_keyword=target_keyword,
        )

        await request_actor.set.remote(player_id, request)
    except Exception as e:
        logger.error(f"Failed to queue skill request: {e}")
        raise


# =============================================================================
# Cast/Use Command
# =============================================================================


@command(
    "cast",
    aliases=["c"],
    category=CommandCategory.COMBAT,
    min_position=Position.STANDING,
    help_text="Cast a spell or use an ability on a target.",
    usage="cast <spell> [target]",
    in_combat=True,
)
async def cmd_cast(player_id: EntityId, args: List[str]) -> str:
    """Cast a spell or ability."""
    if not args:
        return "Cast what? Usage: cast <spell> [target]"

    skill_name = args[0].lower()
    target_keyword = args[1] if len(args) > 1 else ""

    # Get player's skill set
    skill_set = await _get_player_skills(player_id)
    if not skill_set:
        return "You don't have any skills."

    # Find skill by name or partial match
    skill_id = None
    for sid in skill_set.known_skills.keys():
        if sid.lower() == skill_name or sid.lower().startswith(skill_name):
            skill_id = sid
            break

    if not skill_id:
        # Try to find by skill name in registry
        from ..world.skill_registry import get_skill_registry

        try:
            registry = get_skill_registry()
            all_skills = await registry.get_all.remote()

            for sid, skill_def in all_skills.items():
                if skill_def.name.lower() == skill_name or skill_def.name.lower().startswith(skill_name):
                    if skill_set.knows_skill(sid):
                        skill_id = sid
                        break
        except Exception:
            pass

    if not skill_id:
        return f"You don't know any skill called '{skill_name}'."

    # Get skill definition
    skill = await _get_skill_definition(skill_id)
    if not skill:
        return "That skill is not available."

    # Check basic requirements before queueing
    stats = await _get_player_stats(player_id)
    if stats:
        if skill.mana_cost > getattr(stats, "current_mana", 0):
            return f"You don't have enough mana ({skill.mana_cost} required)."
        if skill.stamina_cost > getattr(stats, "current_stamina", 0):
            return f"You don't have enough stamina ({skill.stamina_cost} required)."

    # Check cooldown
    if skill_set.is_on_cooldown(skill_id):
        info = skill_set.get_cooldown_info(skill_id, skill.cooldown_seconds)
        return f"{skill.name} is on cooldown ({info.remaining_seconds:.1f}s remaining)."

    # Resolve target for single-target skills
    target_id = None
    from ..components.skills import TargetType

    if skill.target_type == TargetType.SELF:
        target_id = player_id
    elif target_keyword and skill.target_type in (
        TargetType.SINGLE_ENEMY,
        TargetType.SINGLE_ALLY,
        TargetType.SINGLE_ANY,
    ):
        target_id = await _find_target_in_room(player_id, target_keyword)
        if not target_id:
            return f"You don't see '{target_keyword}' here."

    # Queue the skill request
    try:
        await _queue_skill_use(player_id, skill_id, target_id, target_keyword)
        return f"You begin to cast {skill.name}..."
    except Exception as e:
        return f"Failed to use skill: {e}"


@command(
    "use",
    aliases=["u"],
    category=CommandCategory.COMBAT,
    min_position=Position.STANDING,
    help_text="Use a skill or ability on a target.",
    usage="use <skill> [target]",
    in_combat=True,
)
async def cmd_use(player_id: EntityId, args: List[str]) -> str:
    """Use a skill or ability (alias for cast)."""
    return await cmd_cast(player_id, args)


# =============================================================================
# Skills List Command
# =============================================================================


@command(
    "skills",
    aliases=["sk", "abilities"],
    category=CommandCategory.INFORMATION,
    min_position=Position.RESTING,
    help_text="List your known skills and abilities.",
    usage="skills [category]",
    in_combat=False,
)
async def cmd_skills(player_id: EntityId, args: List[str]) -> str:
    """List known skills."""
    skill_set = await _get_player_skills(player_id)
    if not skill_set:
        return "You don't have any skills."

    if not skill_set.known_skills:
        return "You haven't learned any skills yet."

    # Optional category filter
    filter_category = args[0].lower() if args else None

    from ..world.skill_registry import get_skill_registry
    from ..components.skills import SkillCategory

    try:
        registry = get_skill_registry()
    except Exception:
        return "Skill information is not available."

    # Build skill list
    lines = ["Your skills and abilities:", ""]

    # Group by category
    by_category: dict = {}
    for skill_id, proficiency in skill_set.known_skills.items():
        skill = await registry.get.remote(skill_id)
        if not skill:
            continue

        if filter_category:
            if skill.category.value != filter_category:
                continue

        cat_name = skill.category.value.capitalize()
        if cat_name not in by_category:
            by_category[cat_name] = []

        # Check cooldown
        is_ready = not skill_set.is_on_cooldown(skill_id)
        cd_str = ""
        if not is_ready:
            info = skill_set.get_cooldown_info(skill_id, skill.cooldown_seconds)
            cd_str = f" (CD: {info.remaining_seconds:.0f}s)"

        # Format: SkillName (75%) - 10 mana
        cost_parts = []
        if skill.mana_cost:
            cost_parts.append(f"{skill.mana_cost} mana")
        if skill.stamina_cost:
            cost_parts.append(f"{skill.stamina_cost} stamina")
        cost_str = " - " + ", ".join(cost_parts) if cost_parts else ""

        by_category[cat_name].append(
            f"  {skill.name} ({proficiency}%){cost_str}{cd_str}"
        )

    if not by_category:
        if filter_category:
            return f"You don't have any {filter_category} skills."
        return "You haven't learned any skills yet."

    # Format output
    for category, skills in sorted(by_category.items()):
        lines.append(f"[{category}]")
        lines.extend(skills)
        lines.append("")

    lines.append("Use 'cast <skill> [target]' to use a skill.")
    return "\n".join(lines)


@command(
    "spells",
    category=CommandCategory.INFORMATION,
    min_position=Position.RESTING,
    help_text="List your known spells (magic skills).",
    usage="spells",
    in_combat=False,
)
async def cmd_spells(player_id: EntityId, args: List[str]) -> str:
    """List known spells (magic category only)."""
    return await cmd_skills(player_id, ["magic"])


# =============================================================================
# Affects Command
# =============================================================================


@command(
    "affects",
    aliases=["af", "buffs", "effects"],
    category=CommandCategory.INFORMATION,
    min_position=Position.SLEEPING,
    help_text="Show your active effects (buffs and debuffs).",
    usage="affects",
    in_combat=True,
)
async def cmd_affects(player_id: EntityId, args: List[str]) -> str:
    """Show active effects."""
    effects_data = await _get_active_effects(player_id)

    if not effects_data or not effects_data.effects:
        return "You are not affected by any spells or effects."

    from ..components.skills import EffectType

    lines = ["You are affected by:", ""]

    # Group effects by type
    buffs = []
    debuffs = []
    dots = []
    hots = []
    controls = []

    for effect in effects_data.effects:
        if effect.is_expired:
            continue

        remaining = effect.remaining_seconds
        if remaining == float("inf"):
            time_str = "permanent"
        else:
            time_str = f"{remaining:.0f}s remaining"

        # Build effect line
        if effect.stat_modified:
            sign = "+" if effect.effect_type == EffectType.BUFF else "-"
            value_str = f" ({sign}{effect.value * effect.stacks} {effect.stat_modified})"
        elif effect.value:
            value_str = f" ({effect.value}/tick)"
        else:
            value_str = ""

        line = f"  {effect.skill_id}{value_str} - {time_str}"

        # Categorize
        if effect.effect_type == EffectType.BUFF:
            buffs.append(line)
        elif effect.effect_type == EffectType.DEBUFF:
            debuffs.append(line)
        elif effect.effect_type == EffectType.DOT:
            dots.append(line)
        elif effect.effect_type == EffectType.HOT:
            hots.append(line)
        elif effect.effect_type in (EffectType.STUN, EffectType.ROOT, EffectType.SILENCE):
            controls.append(line)

    # Format output
    if buffs:
        lines.append("[Buffs]")
        lines.extend(buffs)
        lines.append("")

    if debuffs:
        lines.append("[Debuffs]")
        lines.extend(debuffs)
        lines.append("")

    if dots:
        lines.append("[Damage Over Time]")
        lines.extend(dots)
        lines.append("")

    if hots:
        lines.append("[Healing Over Time]")
        lines.extend(hots)
        lines.append("")

    if controls:
        lines.append("[Crowd Control]")
        lines.extend(controls)
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Practice Command
# =============================================================================


@command(
    "practice",
    aliases=["prac"],
    category=CommandCategory.INFORMATION,
    min_position=Position.STANDING,
    help_text="Practice a skill at a trainer to improve proficiency.",
    usage="practice [skill]",
    in_combat=False,
)
async def cmd_practice(player_id: EntityId, args: List[str]) -> str:
    """
    Practice a skill at a trainer.

    Without arguments, shows available skills to practice.
    With a skill name, practices that skill (requires being at a trainer).
    """
    # Check if at a trainer
    location_actor = get_component_actor("Location")
    player_loc = await location_actor.get.remote(player_id)
    if not player_loc:
        return "You need to find a trainer to practice skills."

    # Find trainer in room
    identity_actor = get_component_actor("Identity")
    dialogue_actor = get_component_actor("Dialogue")

    all_locations = await location_actor.get_all.remote()
    trainer_id = None

    for entity_id, loc in all_locations.items():
        if loc.room_id != player_loc.room_id:
            continue
        if entity_id == player_id:
            continue

        dialogue = await dialogue_actor.get.remote(entity_id)
        if dialogue and getattr(dialogue, "is_trainer", False):
            trainer_id = entity_id
            break

    if not trainer_id:
        return "You need to find a trainer to practice skills."

    skill_set = await _get_player_skills(player_id)
    if not skill_set:
        return "You don't have any skills to practice."

    # Get trainer info
    trainer_identity = await identity_actor.get.remote(trainer_id)
    trainer_name = trainer_identity.name if trainer_identity else "the trainer"

    if not args:
        # List practicable skills
        lines = [f"{trainer_name} can help you improve these skills:", ""]

        from ..world.skill_registry import get_skill_registry

        try:
            registry = get_skill_registry()
        except Exception:
            return "Practice is not available right now."

        for skill_id, proficiency in skill_set.known_skills.items():
            if proficiency >= 100:
                continue

            skill = await registry.get.remote(skill_id)
            if not skill:
                continue

            # Calculate practice cost (higher proficiency = higher cost)
            cost = 50 + (proficiency * 2)
            lines.append(f"  {skill.name}: {proficiency}% (costs {cost} gold)")

        if len(lines) == 2:
            return "You have mastered all your skills!"

        lines.append("")
        lines.append("Use 'practice <skill>' to improve a skill.")
        return "\n".join(lines)

    # Practice specific skill
    skill_name = " ".join(args).lower()

    # Find matching skill
    from ..world.skill_registry import get_skill_registry

    try:
        registry = get_skill_registry()
    except Exception:
        return "Practice is not available right now."

    target_skill_id = None
    for skill_id in skill_set.known_skills:
        skill = await registry.get.remote(skill_id)
        if skill and skill.name.lower() == skill_name:
            target_skill_id = skill_id
            break
        if skill and skill.name.lower().startswith(skill_name):
            target_skill_id = skill_id
            break

    if not target_skill_id:
        return f"You don't know any skill called '{skill_name}'."

    current_prof = skill_set.get_proficiency(target_skill_id)
    if current_prof >= 100:
        skill = await registry.get.remote(target_skill_id)
        skill_name = skill.name if skill else target_skill_id
        return f"You have already mastered {skill_name}!"

    # Check gold cost
    cost = 50 + (current_prof * 2)
    stats = await _get_player_stats(player_id)
    if not stats:
        return "Practice is not available right now."

    current_gold = getattr(stats, "gold", 0)
    if current_gold < cost:
        return f"You need {cost} gold to practice that skill. You have {current_gold} gold."

    # Perform practice - improve skill and deduct gold
    skill = await registry.get.remote(target_skill_id)
    skill_name = skill.name if skill else target_skill_id

    # Improvement amount (higher base proficiency = smaller gains)
    improvement = max(1, 5 - (current_prof // 25))

    # Update skill set
    skill_actor = get_component_actor("SkillSet")
    await skill_actor.mutate.remote(
        player_id, lambda ss: ss.improve_skill(target_skill_id, improvement)
    )

    # Deduct gold
    stats_actor = get_component_actor("Stats")
    await stats_actor.mutate.remote(
        player_id, lambda s: setattr(s, "gold", s.gold - cost)
    )

    new_prof = current_prof + improvement
    return (
        f"You practice with {trainer_name}.\n"
        f"Your proficiency in {skill_name} increases from {current_prof}% to {new_prof}%.\n"
        f"You pay {cost} gold."
    )


# =============================================================================
# Train Command
# =============================================================================


@command(
    "train",
    category=CommandCategory.INFORMATION,
    min_position=Position.STANDING,
    help_text="Train a new skill or attribute at a trainer.",
    usage="train [skill|attribute]",
    in_combat=False,
)
async def cmd_train(player_id: EntityId, args: List[str]) -> str:
    """
    Train a new skill or attribute at a trainer.

    Without arguments, shows available training options.
    With an argument, learns the specified skill or improves an attribute.
    """
    # Check if at a trainer
    location_actor = get_component_actor("Location")
    player_loc = await location_actor.get.remote(player_id)
    if not player_loc:
        return "You need to find a trainer to learn skills."

    # Find trainer in room
    identity_actor = get_component_actor("Identity")
    dialogue_actor = get_component_actor("Dialogue")

    all_locations = await location_actor.get_all.remote()
    trainer_id = None

    for entity_id, loc in all_locations.items():
        if loc.room_id != player_loc.room_id:
            continue
        if entity_id == player_id:
            continue

        dialogue = await dialogue_actor.get.remote(entity_id)
        if dialogue and getattr(dialogue, "is_trainer", False):
            trainer_id = entity_id
            break

    if not trainer_id:
        return "You need to find a trainer to learn skills."

    skill_set = await _get_player_skills(player_id)
    stats = await _get_player_stats(player_id)

    trainer_identity = await identity_actor.get.remote(trainer_id)
    trainer_name = trainer_identity.name if trainer_identity else "the trainer"

    if not args:
        # List available training
        lines = [f"{trainer_name} can teach you:", ""]

        # Get player level and class
        player_level = getattr(stats, "level", 1) if stats else 1
        player_class = getattr(stats, "player_class", "warrior") if stats else "warrior"

        from ..world.skill_registry import get_skill_registry

        try:
            registry = get_skill_registry()
            learnable = await registry.get_learnable_for_class.remote(player_class, player_level)
        except Exception:
            return "Training is not available right now."

        # Filter to skills not yet known
        available = []
        for skill in learnable:
            if skill_set and skill_set.knows_skill(skill.skill_id):
                continue
            cost = 100 + (skill.level_requirement * 50)
            available.append(f"  {skill.name} (Level {skill.level_requirement}) - {cost} gold")

        if available:
            lines.append("[Skills]")
            lines.extend(available[:10])  # Limit display
            if len(available) > 10:
                lines.append(f"  ... and {len(available) - 10} more")
            lines.append("")

        # Attribute training
        train_sessions = getattr(stats, "train_sessions", 0) if stats else 0
        if train_sessions > 0:
            lines.append(f"[Attributes] ({train_sessions} sessions available)")
            lines.append("  strength, dexterity, constitution")
            lines.append("  intelligence, wisdom, charisma")
            lines.append("")

        if len(lines) == 2:
            return "There is nothing available for you to train right now."

        lines.append("Use 'train <skill|attribute>' to learn.")
        return "\n".join(lines)

    # Train specific thing
    target = " ".join(args).lower()

    # Check if it's an attribute
    attributes = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    if target in attributes or target[:3] in [a[:3] for a in attributes]:
        # Find full attribute name
        attr_name = None
        for a in attributes:
            if target == a or target == a[:3]:
                attr_name = a
                break

        if not attr_name:
            return f"Unknown attribute: {target}"

        # Check training sessions
        train_sessions = getattr(stats, "train_sessions", 0) if stats else 0
        if train_sessions <= 0:
            return "You don't have any training sessions available."

        # Get current value
        if stats and hasattr(stats, "attributes"):
            current = getattr(stats.attributes, attr_name, 10)
        else:
            current = 10

        if current >= 25:
            return f"Your {attr_name} is already at maximum!"

        # Perform training
        stats_actor = get_component_actor("Stats")

        def update_attr(s):
            s.train_sessions -= 1
            if hasattr(s, "attributes"):
                setattr(s.attributes, attr_name, getattr(s.attributes, attr_name, 10) + 1)

        await stats_actor.mutate.remote(player_id, update_attr)

        return (
            f"You train with {trainer_name}.\n"
            f"Your {attr_name} increases from {current} to {current + 1}!"
        )

    # Otherwise, try to learn a skill
    from ..world.skill_registry import get_skill_registry

    try:
        registry = get_skill_registry()
        all_skills = await registry.get_all.remote()
    except Exception:
        return "Training is not available right now."

    # Find matching skill
    target_skill = None
    for skill in all_skills.values():
        if skill.name.lower() == target or skill.name.lower().startswith(target):
            target_skill = skill
            break

    if not target_skill:
        return f"Unknown skill or attribute: {target}"

    # Check if already known
    if skill_set and skill_set.knows_skill(target_skill.skill_id):
        return f"You already know {target_skill.name}."

    # Check level requirement
    player_level = getattr(stats, "level", 1) if stats else 1
    if target_skill.level_requirement > player_level:
        return f"You must be level {target_skill.level_requirement} to learn {target_skill.name}."

    # Check class requirement
    if target_skill.class_requirements:
        player_class = getattr(stats, "player_class", "warrior") if stats else "warrior"
        if player_class not in target_skill.class_requirements:
            return f"{target_skill.name} can only be learned by: {', '.join(target_skill.class_requirements)}"

    # Check gold
    cost = 100 + (target_skill.level_requirement * 50)
    current_gold = getattr(stats, "gold", 0) if stats else 0
    if current_gold < cost:
        return f"You need {cost} gold to learn {target_skill.name}. You have {current_gold} gold."

    # Learn the skill
    skill_actor = get_component_actor("SkillSet")
    await skill_actor.mutate.remote(
        player_id, lambda ss: ss.learn_skill(target_skill.skill_id, 1)
    )

    # Deduct gold
    stats_actor = get_component_actor("Stats")
    await stats_actor.mutate.remote(
        player_id, lambda s: setattr(s, "gold", s.gold - cost)
    )

    return (
        f"You train with {trainer_name}.\n"
        f"You have learned {target_skill.name}!\n"
        f"You pay {cost} gold."
    )
