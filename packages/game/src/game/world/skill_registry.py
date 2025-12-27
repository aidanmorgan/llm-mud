"""
Distributed Skill Registry Actor

A Ray actor that provides distributed storage for skill definitions.
This enables multiple Python processes to share skill data via the Ray cluster.

Design:
- Immutable SkillDefinition storage (frozen dataclasses)
- Lookup by skill_id, category, or class requirements
- Version tracking for cache invalidation
- YAML loading support
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import ray
import yaml
from ray.actor import ActorHandle

from ..components.skills import (
    AnyEffect,
    BuffEffect,
    ControlEffect,
    DamageEffect,
    DamageSchool,
    EffectType,
    HealEffect,
    PeriodicEffect,
    SkillCategory,
    SkillDefinition,
    TargetType,
)

logger = logging.getLogger(__name__)

ACTOR_NAME = "skill_registry"
ACTOR_NAMESPACE = "llmmud"


# =============================================================================
# YAML Parsing - Convert YAML dicts to frozen dataclasses
# =============================================================================


def _parse_damage_school(value: str) -> DamageSchool:
    """Parse damage school from string."""
    try:
        return DamageSchool(value.lower())
    except ValueError:
        logger.warning(f"Unknown damage school '{value}', defaulting to PHYSICAL")
        return DamageSchool.PHYSICAL


def _parse_effect(effect_data: Dict[str, Any]) -> AnyEffect:
    """Parse an effect definition from YAML data."""
    effect_type_str = effect_data.get("type", "damage").lower()

    base_value = effect_data.get("base_value", 0)
    scaling_stat = effect_data.get("scaling_stat")
    scaling_factor = effect_data.get("scaling_factor", 0.0)

    if effect_type_str == "damage":
        return DamageEffect(
            effect_type=EffectType.DAMAGE,
            base_value=base_value,
            scaling_stat=scaling_stat,
            scaling_factor=scaling_factor,
            damage_school=_parse_damage_school(effect_data.get("damage_school", "physical")),
            can_crit=effect_data.get("can_crit", True),
            crit_multiplier=effect_data.get("crit_multiplier", 2.0),
        )

    elif effect_type_str == "heal":
        return HealEffect(
            effect_type=EffectType.HEAL,
            base_value=base_value,
            scaling_stat=scaling_stat,
            scaling_factor=scaling_factor,
            can_crit=effect_data.get("can_crit", True),
            crit_multiplier=effect_data.get("crit_multiplier", 1.5),
        )

    elif effect_type_str in ("buff", "debuff"):
        return BuffEffect(
            effect_type=EffectType.DEBUFF if effect_type_str == "debuff" else EffectType.BUFF,
            base_value=base_value,
            scaling_stat=scaling_stat,
            scaling_factor=scaling_factor,
            stat_modified=effect_data.get("stat_modified", "armor_class"),
            duration_seconds=effect_data.get("duration_seconds", 60),
            is_debuff=effect_type_str == "debuff",
            stacks=effect_data.get("stacks", False),
            max_stacks=effect_data.get("max_stacks", 1),
        )

    elif effect_type_str in ("dot", "hot"):
        return PeriodicEffect(
            effect_type=EffectType.DOT if effect_type_str == "dot" else EffectType.HOT,
            base_value=base_value,
            scaling_stat=scaling_stat,
            scaling_factor=scaling_factor,
            duration_seconds=effect_data.get("duration_seconds", 12),
            tick_interval_seconds=effect_data.get("tick_interval_seconds", 3),
            damage_school=_parse_damage_school(effect_data.get("damage_school", "physical")),
        )

    elif effect_type_str in ("stun", "root", "silence"):
        effect_type_map = {
            "stun": EffectType.STUN,
            "root": EffectType.ROOT,
            "silence": EffectType.SILENCE,
        }
        return ControlEffect(
            effect_type=effect_type_map[effect_type_str],
            base_value=0,
            duration_seconds=effect_data.get("duration_seconds", 3),
            breaks_on_damage=effect_data.get("breaks_on_damage", False),
            diminishing_returns=effect_data.get("diminishing_returns", True),
        )

    else:
        logger.warning(f"Unknown effect type '{effect_type_str}', creating base damage effect")
        return DamageEffect(
            effect_type=EffectType.DAMAGE,
            base_value=base_value,
            scaling_stat=scaling_stat,
            scaling_factor=scaling_factor,
        )


def _parse_skill_definition(skill_id: str, data: Dict[str, Any]) -> SkillDefinition:
    """Parse a skill definition from YAML data."""
    # Parse category
    category_str = data.get("category", "combat").lower()
    try:
        category = SkillCategory(category_str)
    except ValueError:
        logger.warning(f"Unknown category '{category_str}' for skill {skill_id}, defaulting to COMBAT")
        category = SkillCategory.COMBAT

    # Parse target type
    target_str = data.get("target_type", "single_enemy").lower()
    try:
        target_type = TargetType(target_str)
    except ValueError:
        logger.warning(f"Unknown target type '{target_str}' for skill {skill_id}, defaulting to SINGLE_ENEMY")
        target_type = TargetType.SINGLE_ENEMY

    # Parse effects
    effects_data = data.get("effects", [])
    effects = tuple(_parse_effect(e) for e in effects_data)

    # Parse class requirements
    class_reqs = data.get("class_requirements", [])
    if isinstance(class_reqs, str):
        class_reqs = [class_reqs]

    return SkillDefinition(
        skill_id=skill_id,
        name=data.get("name", skill_id.replace("_", " ").title()),
        description=data.get("description", ""),
        category=category,
        target_type=target_type,
        mana_cost=data.get("mana_cost", 0),
        stamina_cost=data.get("stamina_cost", 0),
        health_cost=data.get("health_cost", 0),
        cooldown_seconds=data.get("cooldown_seconds", 0.0),
        level_requirement=data.get("level_requirement", 1),
        class_requirements=tuple(class_reqs),
        effects=effects,
        range_rooms=data.get("range_rooms", 0),
        requires_line_of_sight=data.get("requires_line_of_sight", True),
        cast_time_seconds=data.get("cast_time_seconds", 0.0),
        can_be_interrupted=data.get("can_be_interrupted", True),
        is_passive=data.get("is_passive", False),
        is_hidden=data.get("is_hidden", False),
    )


def load_skills_from_yaml(file_path: Path) -> List[SkillDefinition]:
    """Load skill definitions from a YAML file."""
    if not file_path.exists():
        logger.warning(f"Skill file not found: {file_path}")
        return []

    try:
        with open(file_path, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            return []

        skills = []
        skills_data = data.get("skills", data)  # Support both wrapped and unwrapped format

        if isinstance(skills_data, dict):
            for skill_id, skill_data in skills_data.items():
                if isinstance(skill_data, dict):
                    skills.append(_parse_skill_definition(skill_id, skill_data))
        elif isinstance(skills_data, list):
            for skill_data in skills_data:
                if isinstance(skill_data, dict) and "skill_id" in skill_data:
                    skill_id = skill_data["skill_id"]
                    skills.append(_parse_skill_definition(skill_id, skill_data))

        logger.info(f"Loaded {len(skills)} skills from {file_path}")
        return skills

    except Exception as e:
        logger.error(f"Error loading skills from {file_path}: {e}")
        return []


# =============================================================================
# Skill Registry Actor
# =============================================================================


@ray.remote
class SkillRegistryActor:
    """
    Distributed registry for skill definitions.

    Provides:
    - Storage for SkillDefinition objects
    - Lookup by skill_id
    - Filtering by category, class, level
    - Version tracking for cache invalidation
    """

    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}
        self._by_category: Dict[SkillCategory, List[str]] = {cat: [] for cat in SkillCategory}
        self._version: int = 0

        logger.info("SkillRegistryActor initialized")

    def _increment_version(self) -> None:
        """Increment version after any mutation."""
        self._version += 1

    def _update_category_index(self, skill: SkillDefinition) -> None:
        """Update category index for a skill."""
        if skill.skill_id not in self._by_category[skill.category]:
            self._by_category[skill.category].append(skill.skill_id)

    def _remove_from_category_index(self, skill: SkillDefinition) -> None:
        """Remove skill from category index."""
        if skill.skill_id in self._by_category[skill.category]:
            self._by_category[skill.category].remove(skill.skill_id)

    # =========================================================================
    # Version / Stats
    # =========================================================================

    def get_version(self) -> int:
        """Get current registry version for cache invalidation."""
        return self._version

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_skills": len(self._skills),
            "by_category": {cat.value: len(ids) for cat, ids in self._by_category.items()},
            "version": self._version,
        }

    # =========================================================================
    # Registration
    # =========================================================================

    def register(self, skill: SkillDefinition) -> None:
        """Register a single skill definition."""
        old_skill = self._skills.get(skill.skill_id)
        if old_skill:
            self._remove_from_category_index(old_skill)

        self._skills[skill.skill_id] = skill
        self._update_category_index(skill)
        self._increment_version()
        logger.debug(f"Registered skill: {skill.skill_id}")

    def register_batch(self, skills: List[SkillDefinition]) -> int:
        """Register multiple skills at once. Returns count."""
        for skill in skills:
            old_skill = self._skills.get(skill.skill_id)
            if old_skill:
                self._remove_from_category_index(old_skill)

            self._skills[skill.skill_id] = skill
            self._update_category_index(skill)

        self._increment_version()
        logger.info(f"Registered {len(skills)} skills (batch)")
        return len(skills)

    def unregister(self, skill_id: str) -> bool:
        """Remove a skill. Returns True if found."""
        skill = self._skills.pop(skill_id, None)
        if skill:
            self._remove_from_category_index(skill)
            self._increment_version()
            return True
        return False

    # =========================================================================
    # Lookup
    # =========================================================================

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def get_all(self) -> Dict[str, SkillDefinition]:
        """Get all skills."""
        return self._skills.copy()

    def get_by_category(self, category: SkillCategory) -> Sequence[SkillDefinition]:
        """Get all skills in a category."""
        skill_ids = self._by_category.get(category, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def get_learnable_for_class(
        self, class_name: str, max_level: int
    ) -> Sequence[SkillDefinition]:
        """
        Get skills learnable by a class up to a level.

        Returns skills where:
        - class_requirements is empty (any class) OR contains class_name
        - level_requirement <= max_level
        - is_passive is False
        - is_hidden is False
        """
        result = []
        for skill in self._skills.values():
            if skill.is_hidden:
                continue
            if skill.level_requirement > max_level:
                continue
            if skill.class_requirements and class_name not in skill.class_requirements:
                continue
            result.append(skill)

        # Sort by level requirement
        result.sort(key=lambda s: (s.level_requirement, s.name))
        return result

    def get_by_level_range(
        self, min_level: int = 1, max_level: int = 100
    ) -> Sequence[SkillDefinition]:
        """Get skills within a level range."""
        return [
            s for s in self._skills.values()
            if min_level <= s.level_requirement <= max_level and not s.is_hidden
        ]

    def search(self, query: str) -> Sequence[SkillDefinition]:
        """Search skills by name or description."""
        query_lower = query.lower()
        return [
            s for s in self._skills.values()
            if query_lower in s.name.lower() or query_lower in s.description.lower()
        ]

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def clear_all(self) -> None:
        """Remove all skills."""
        self._skills.clear()
        for cat in self._by_category:
            self._by_category[cat].clear()
        self._increment_version()
        logger.info("Cleared all skills")

    def load_from_yaml(self, file_path: str) -> int:
        """Load skills from a YAML file. Returns count loaded."""
        skills = load_skills_from_yaml(Path(file_path))
        if skills:
            return self.register_batch(skills)
        return 0


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_skill_registry() -> ActorHandle:
    """
    Start the skill registry actor.

    Should be called once during server initialization.
    Returns the actor handle.
    """
    actor: ActorHandle = SkillRegistryActor.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote()
    logger.info(f"Started SkillRegistryActor as {ACTOR_NAMESPACE}/{ACTOR_NAME}")
    return actor


def get_skill_registry() -> ActorHandle:
    """
    Get the skill registry actor.

    Returns the existing actor handle from the Ray cluster.
    Raises ValueError if the actor doesn't exist.
    """
    try:
        return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
    except ValueError:
        raise ValueError(
            "SkillRegistryActor not found. "
            "Ensure start_skill_registry() was called first."
        )


def skill_registry_exists() -> bool:
    """Check if the skill registry actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_skill_registry() -> bool:
    """
    Stop and kill the skill registry actor.

    Returns True if successfully killed, False if actor wasn't found.
    """
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info(f"Stopped SkillRegistryActor {ACTOR_NAMESPACE}/{ACTOR_NAME}")
        return True
    except ValueError:
        logger.warning("SkillRegistryActor not found, nothing to stop")
        return False
    except Exception as e:
        logger.error(f"Error stopping SkillRegistryActor: {e}")
        return False
