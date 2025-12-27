"""
Skill Execution and Buff/Effect Systems

Handles skill usage, effect application, and periodic effect ticking.

Design Principles:
- Separation of concerns: validation, execution, and effect application are distinct
- Immutable data flow where possible
- Clear event generation for UI/logging
- @singledispatch for polymorphic effect handling
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import singledispatch
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import ray
from ray.actor import ActorHandle

from core import ComponentData, EntityId, System
from ..components.skills import (
    ActiveEffect,
    ActiveEffectsData,
    AnyEffect,
    BuffEffect,
    ControlEffect,
    DamageEffect,
    EffectType,
    HealEffect,
    PeriodicEffect,
    SkillCategory,
    SkillDefinition,
    SkillResult,
    SkillSetData,
    TargetType,
    calculate_effect_value,
    validate_skill_use,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Skill Event Types - Immutable event records
# =============================================================================


class SkillUseEvent(NamedTuple):
    """Record of a skill being used."""

    caster_id: EntityId
    skill_id: str
    skill_name: str
    target_ids: Tuple[EntityId, ...]
    room_id: Optional[EntityId]
    success: bool
    message: str


class EffectAppliedEvent(NamedTuple):
    """Record of an effect being applied."""

    source_id: EntityId
    target_id: EntityId
    effect_type: EffectType
    effect_id: str
    value: int
    duration_seconds: Optional[float]


class EffectTickEvent(NamedTuple):
    """Record of a periodic effect ticking."""

    effect_id: str
    target_id: EntityId
    effect_type: EffectType
    value: int
    remaining_seconds: float


class EffectExpiredEvent(NamedTuple):
    """Record of an effect expiring."""

    effect_id: str
    target_id: EntityId
    effect_type: EffectType
    skill_name: str


# =============================================================================
# Skill Request Component - Queued skill usage
# =============================================================================


@dataclass
class SkillRequestData(ComponentData):
    """
    Transient component for queuing skill usage.

    Created by command handlers, consumed by SkillExecutionSystem.
    """

    skill_id: str
    target_id: Optional[EntityId] = None
    target_keyword: str = ""  # For resolving by name
    requested_at: datetime = field(default_factory=datetime.utcnow)
    force: bool = False  # Skip validation (for AI/scripted usage)


# =============================================================================
# Effect Application - Polymorphic via @singledispatch
# =============================================================================


@singledispatch
def apply_effect(
    effect: AnyEffect,
    source_id: EntityId,
    target_id: EntityId,
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    proficiency: int,
) -> Tuple[Optional[ActiveEffect], int, str]:
    """
    Apply an effect to a target.

    Returns:
        Tuple of (ActiveEffect to add or None, immediate value, message)
    """
    # Default: unknown effect type
    logger.warning(f"Unknown effect type: {type(effect)}")
    return None, 0, ""


@apply_effect.register(DamageEffect)
def _apply_damage(
    effect: DamageEffect,
    source_id: EntityId,
    target_id: EntityId,
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    proficiency: int,
) -> Tuple[Optional[ActiveEffect], int, str]:
    """Apply instant damage."""
    damage = calculate_effect_value(effect, caster_stats, proficiency)
    message = f"deals {damage} {effect.damage_school.value} damage"
    return None, damage, message


@apply_effect.register(HealEffect)
def _apply_heal(
    effect: HealEffect,
    source_id: EntityId,
    target_id: EntityId,
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    proficiency: int,
) -> Tuple[Optional[ActiveEffect], int, str]:
    """Apply instant healing."""
    healing = calculate_effect_value(effect, caster_stats, proficiency)
    message = f"heals for {healing}"
    return None, healing, message


@apply_effect.register(BuffEffect)
def _apply_buff(
    effect: BuffEffect,
    source_id: EntityId,
    target_id: EntityId,
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    proficiency: int,
) -> Tuple[Optional[ActiveEffect], int, str]:
    """Apply a buff or debuff."""
    value = calculate_effect_value(effect, caster_stats, proficiency)

    active = ActiveEffect(
        effect_id=str(uuid.uuid4()),
        skill_id=skill.skill_id,
        source_id=source_id,
        effect_type=effect.effect_type,
        stat_modified=effect.stat_modified,
        value=value,
        expires_at=datetime.utcnow() + timedelta(seconds=effect.duration_seconds),
        stacks=1,
        max_stacks=effect.max_stacks,
    )

    sign = "-" if effect.is_debuff else "+"
    message = f"gains {sign}{value} {effect.stat_modified} for {effect.duration_seconds}s"
    return active, 0, message


@apply_effect.register(PeriodicEffect)
def _apply_periodic(
    effect: PeriodicEffect,
    source_id: EntityId,
    target_id: EntityId,
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    proficiency: int,
) -> Tuple[Optional[ActiveEffect], int, str]:
    """Apply a DOT or HOT effect."""
    value_per_tick = calculate_effect_value(effect, caster_stats, proficiency)

    active = ActiveEffect(
        effect_id=str(uuid.uuid4()),
        skill_id=skill.skill_id,
        source_id=source_id,
        effect_type=effect.effect_type,
        value=value_per_tick,
        expires_at=datetime.utcnow() + timedelta(seconds=effect.duration_seconds),
        tick_interval_seconds=effect.tick_interval_seconds,
        last_tick_at=datetime.utcnow(),  # First tick is when applied
    )

    total = value_per_tick * effect.total_ticks
    if effect.effect_type == EffectType.DOT:
        message = f"takes {total} damage over {effect.duration_seconds}s"
    else:
        message = f"will heal {total} over {effect.duration_seconds}s"

    return active, 0, message


@apply_effect.register(ControlEffect)
def _apply_control(
    effect: ControlEffect,
    source_id: EntityId,
    target_id: EntityId,
    skill: SkillDefinition,
    caster_stats: Dict[str, int],
    proficiency: int,
) -> Tuple[Optional[ActiveEffect], int, str]:
    """Apply a crowd control effect."""
    active = ActiveEffect(
        effect_id=str(uuid.uuid4()),
        skill_id=skill.skill_id,
        source_id=source_id,
        effect_type=effect.effect_type,
        value=0,
        expires_at=datetime.utcnow() + timedelta(seconds=effect.duration_seconds),
    )

    effect_names = {
        EffectType.STUN: "stunned",
        EffectType.ROOT: "rooted",
        EffectType.SILENCE: "silenced",
    }
    name = effect_names.get(effect.effect_type, "affected")
    message = f"is {name} for {effect.duration_seconds}s"

    return active, 0, message


# =============================================================================
# Skill Execution System
# =============================================================================


@ray.remote
class SkillExecutionSystem(System):
    """
    Processes skill usage requests.

    Flow:
    1. Find entities with SkillRequest components
    2. Validate skill can be used (mana, cooldown, etc.)
    3. Resolve target(s)
    4. Apply effects
    5. Generate events
    6. Remove request component
    """

    def __init__(self):
        super().__init__(
            system_type="SkillExecutionSystem",
            required_components=["SkillRequest", "SkillSet", "Stats"],
            optional_components=["Location", "ActiveEffects", "Identity"],
            dependencies=["MovementSystem"],
            priority=25,  # Before CombatSystem
        )
        self._events: List[SkillUseEvent] = []
        self._effect_events: List[EffectAppliedEvent] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """Process all pending skill requests."""
        processed = 0
        self._events.clear()
        self._effect_events.clear()

        for entity_id, components in entities.items():
            request = components["SkillRequest"]
            skill_set = components["SkillSet"]
            stats = components["Stats"]
            location = components.get("Location")
            effects = components.get("ActiveEffects")

            # Get skill definition
            skill = await self._get_skill(request.skill_id)
            if not skill:
                await write_buffer.delete.remote("SkillRequest", entity_id)
                continue

            # Validate
            if not request.force:
                caster_stats = self._extract_stats(stats)
                can_use, error = validate_skill_use(skill, caster_stats, skill_set, effects)
                if not can_use:
                    self._events.append(
                        SkillUseEvent(
                            caster_id=entity_id,
                            skill_id=skill.skill_id,
                            skill_name=skill.name,
                            target_ids=(),
                            room_id=location.room_id if location else None,
                            success=False,
                            message=error,
                        )
                    )
                    await write_buffer.delete.remote("SkillRequest", entity_id)
                    continue

            # Resolve targets
            targets = await self._resolve_targets(
                entity_id, skill, request, location, entities
            )

            if skill.target_type != TargetType.SELF and not targets:
                self._events.append(
                    SkillUseEvent(
                        caster_id=entity_id,
                        skill_id=skill.skill_id,
                        skill_name=skill.name,
                        target_ids=(),
                        room_id=location.room_id if location else None,
                        success=False,
                        message="No valid target.",
                    )
                )
                await write_buffer.delete.remote("SkillRequest", entity_id)
                continue

            # Execute skill
            result = await self._execute_skill(
                write_buffer, entity_id, skill, skill_set, stats, targets, location
            )

            # Record event
            self._events.append(
                SkillUseEvent(
                    caster_id=entity_id,
                    skill_id=skill.skill_id,
                    skill_name=skill.name,
                    target_ids=tuple(targets),
                    room_id=location.room_id if location else None,
                    success=result.success,
                    message=result.message,
                )
            )

            # Remove request
            await write_buffer.delete.remote("SkillRequest", entity_id)
            processed += 1

        return processed

    async def _get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        """Get skill definition from registry."""
        from ..world.skill_registry import get_skill_registry

        try:
            registry = get_skill_registry()
            return await registry.get.remote(skill_id)
        except Exception as e:
            logger.error(f"Failed to get skill {skill_id}: {e}")
            return None

    def _extract_stats(self, stats: ComponentData) -> Dict[str, int]:
        """Extract stat values into a dict for calculations."""
        return {
            "current_health": getattr(stats, "current_health", 0),
            "max_health": getattr(stats, "max_health", 100),
            "current_mana": getattr(stats, "current_mana", 0),
            "max_mana": getattr(stats, "max_mana", 100),
            "current_stamina": getattr(stats, "current_stamina", 0),
            "max_stamina": getattr(stats, "max_stamina", 100),
            "strength": getattr(stats.attributes, "strength", 10) if hasattr(stats, "attributes") else 10,
            "dexterity": getattr(stats.attributes, "dexterity", 10) if hasattr(stats, "attributes") else 10,
            "constitution": getattr(stats.attributes, "constitution", 10) if hasattr(stats, "attributes") else 10,
            "intelligence": getattr(stats.attributes, "intelligence", 10) if hasattr(stats, "attributes") else 10,
            "wisdom": getattr(stats.attributes, "wisdom", 10) if hasattr(stats, "attributes") else 10,
            "charisma": getattr(stats.attributes, "charisma", 10) if hasattr(stats, "attributes") else 10,
        }

    async def _resolve_targets(
        self,
        caster_id: EntityId,
        skill: SkillDefinition,
        request: SkillRequestData,
        location: Optional[ComponentData],
        all_entities: Dict[EntityId, Dict[str, ComponentData]],
    ) -> List[EntityId]:
        """Resolve skill targets based on targeting type."""
        targets: List[EntityId] = []

        if skill.target_type == TargetType.SELF:
            return [caster_id]

        room_id = location.room_id if location else None
        if not room_id:
            return []

        # Single target from request
        if request.target_id:
            # Verify target is in same room
            target_comps = all_entities.get(request.target_id)
            if target_comps:
                target_loc = target_comps.get("Location")
                if target_loc and target_loc.room_id == room_id:
                    return [request.target_id]

        # Resolve by keyword
        if request.target_keyword:
            target = await self._find_target_by_keyword(room_id, request.target_keyword, caster_id)
            if target:
                return [target]

        # Area effects
        if skill.target_type in (TargetType.AREA_ENEMIES, TargetType.AREA_ALLIES, TargetType.AREA_ALL):
            return await self._get_area_targets(room_id, caster_id, skill.target_type)

        return targets

    async def _find_target_by_keyword(
        self, room_id: EntityId, keyword: str, exclude_id: EntityId
    ) -> Optional[EntityId]:
        """Find a target in room by keyword."""
        from core.component import get_component_actor

        try:
            location_actor = get_component_actor("Location")
            identity_actor = get_component_actor("Identity")

            all_locations = await location_actor.get_all.remote()

            for entity_id, loc in all_locations.items():
                if loc.room_id != room_id or entity_id == exclude_id:
                    continue

                identity = await identity_actor.get.remote(entity_id)
                if identity and keyword.lower() in identity.name.lower():
                    return entity_id

                if identity:
                    for kw in getattr(identity, "keywords", []):
                        if keyword.lower() in kw.lower():
                            return entity_id

            return None
        except Exception as e:
            logger.error(f"Error finding target by keyword: {e}")
            return None

    async def _get_area_targets(
        self, room_id: EntityId, caster_id: EntityId, target_type: TargetType
    ) -> List[EntityId]:
        """Get all valid targets in room for area effects."""
        from core.component import get_component_actor

        try:
            location_actor = get_component_actor("Location")
            combat_actor = get_component_actor("Combat")

            all_locations = await location_actor.get_all.remote()
            targets = []

            for entity_id, loc in all_locations.items():
                if loc.room_id != room_id:
                    continue

                if target_type == TargetType.AREA_ALL:
                    targets.append(entity_id)
                elif target_type == TargetType.AREA_ENEMIES:
                    # Enemies = entities with Combat component that aren't allied
                    combat = await combat_actor.get.remote(entity_id)
                    if combat and entity_id != caster_id:
                        targets.append(entity_id)
                elif target_type == TargetType.AREA_ALLIES:
                    # For now, allies = self only (would need party system)
                    if entity_id == caster_id:
                        targets.append(entity_id)

            return targets
        except Exception as e:
            logger.error(f"Error getting area targets: {e}")
            return []

    async def _execute_skill(
        self,
        write_buffer: ActorHandle,
        caster_id: EntityId,
        skill: SkillDefinition,
        skill_set: SkillSetData,
        caster_stats: ComponentData,
        targets: List[EntityId],
        location: Optional[ComponentData],
    ) -> SkillResult:
        """Execute a skill on targets."""
        stats_dict = self._extract_stats(caster_stats)
        proficiency = skill_set.get_proficiency(skill.skill_id)

        total_damage = 0
        total_healing = 0
        effects_applied: List[str] = []
        messages: List[str] = []

        # Consume resources
        if skill.mana_cost > 0:
            await write_buffer.mutate.remote(
                "Stats", caster_id, lambda s: setattr(s, "current_mana", s.current_mana - skill.mana_cost)
            )

        if skill.stamina_cost > 0:
            await write_buffer.mutate.remote(
                "Stats", caster_id, lambda s: setattr(s, "current_stamina", s.current_stamina - skill.stamina_cost)
            )

        # Set cooldown
        if skill.cooldown_seconds > 0:
            await write_buffer.mutate.remote(
                "SkillSet", caster_id, lambda ss: ss.set_cooldown(skill.skill_id, skill.cooldown_seconds)
            )

        # Apply effects to each target
        for target_id in targets:
            for effect in skill.effects:
                active_effect, value, message = apply_effect(
                    effect, caster_id, target_id, skill, stats_dict, proficiency
                )

                # Apply damage
                if effect.effect_type == EffectType.DAMAGE:
                    total_damage += value
                    await write_buffer.mutate.remote(
                        "Stats", target_id, lambda s: s.take_damage(value)
                    )

                # Apply healing
                elif effect.effect_type == EffectType.HEAL:
                    total_healing += value
                    await write_buffer.mutate.remote(
                        "Stats", target_id, lambda s: s.heal(value)
                    )

                # Apply mana restore
                elif effect.effect_type == EffectType.RESTORE_MANA:
                    await write_buffer.mutate.remote(
                        "Stats", target_id, lambda s: s.restore_mana(value)
                    )

                # Add active effect (buffs, debuffs, dots, hots, cc)
                if active_effect:
                    await write_buffer.mutate.remote(
                        "ActiveEffects", target_id, lambda ae: ae.add_effect(active_effect)
                    )
                    effects_applied.append(active_effect.effect_id)

                    self._effect_events.append(
                        EffectAppliedEvent(
                            source_id=caster_id,
                            target_id=target_id,
                            effect_type=active_effect.effect_type,
                            effect_id=active_effect.effect_id,
                            value=active_effect.value,
                            duration_seconds=active_effect.remaining_seconds if active_effect.expires_at else None,
                        )
                    )

                if message:
                    messages.append(message)

        # Chance to improve proficiency
        await self._maybe_improve_skill(write_buffer, caster_id, skill.skill_id, proficiency)

        result_message = f"You use {skill.name}. " + ", ".join(messages) if messages else f"You use {skill.name}."

        return SkillResult(
            success=True,
            message=result_message,
            damage_dealt=total_damage,
            healing_done=total_healing,
            effects_applied=tuple(effects_applied),
            mana_spent=skill.mana_cost,
            stamina_spent=skill.stamina_cost,
        )

    async def _maybe_improve_skill(
        self, write_buffer: ActorHandle, entity_id: EntityId, skill_id: str, current_proficiency: int
    ) -> None:
        """Small chance to improve skill proficiency on use."""
        import random

        if current_proficiency >= 100:
            return

        # Higher proficiency = lower chance to improve
        improve_chance = max(5, 50 - (current_proficiency // 2))
        if random.randint(1, 100) <= improve_chance:
            await write_buffer.mutate.remote(
                "SkillSet", entity_id, lambda ss: ss.improve_skill(skill_id, 1)
            )

    async def get_pending_events(self) -> Tuple[List[SkillUseEvent], List[EffectAppliedEvent]]:
        """Get events from last tick."""
        return self._events.copy(), self._effect_events.copy()


# =============================================================================
# Buff Effect System - Handles periodic effects and expiration
# =============================================================================


@ray.remote
class BuffEffectSystem(System):
    """
    Processes active effects (buffs, debuffs, DOTs, HOTs).

    Responsibilities:
    - Tick periodic effects (DOT/HOT)
    - Remove expired effects
    - Generate events for UI updates
    """

    def __init__(self):
        super().__init__(
            system_type="BuffEffectSystem",
            required_components=["ActiveEffects"],
            optional_components=["Stats", "Identity"],
            dependencies=["SkillExecutionSystem"],
            priority=55,  # After skills, before regeneration
        )
        self._tick_events: List[EffectTickEvent] = []
        self._expired_events: List[EffectExpiredEvent] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """Process all entities with active effects."""
        processed = 0
        self._tick_events.clear()
        self._expired_events.clear()

        for entity_id, components in entities.items():
            effects_data = components["ActiveEffects"]
            stats = components.get("Stats")

            if not effects_data.effects:
                continue

            # Process ticks
            for effect in effects_data.get_effects_to_tick():
                await self._process_tick(write_buffer, entity_id, effect, stats)

            # Remove expired effects
            expired = await self._remove_expired(write_buffer, entity_id, effects_data)

            if effects_data.effects or expired:
                processed += 1

        return processed

    async def _process_tick(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        effect: ActiveEffect,
        stats: Optional[ComponentData],
    ) -> None:
        """Process a single effect tick."""
        value = effect.value * effect.stacks

        if effect.effect_type == EffectType.DOT:
            # Apply damage
            if stats:
                await write_buffer.mutate.remote(
                    "Stats", entity_id, lambda s: s.take_damage(value)
                )

        elif effect.effect_type == EffectType.HOT:
            # Apply healing
            if stats:
                await write_buffer.mutate.remote(
                    "Stats", entity_id, lambda s: s.heal(value)
                )

        # Record tick
        await write_buffer.mutate.remote(
            "ActiveEffects",
            entity_id,
            lambda ae: next(
                (e.record_tick() for e in ae.effects if e.effect_id == effect.effect_id),
                None,
            ),
        )

        self._tick_events.append(
            EffectTickEvent(
                effect_id=effect.effect_id,
                target_id=entity_id,
                effect_type=effect.effect_type,
                value=value,
                remaining_seconds=effect.remaining_seconds,
            )
        )

    async def _remove_expired(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        effects_data: ActiveEffectsData,
    ) -> List[ActiveEffect]:
        """Remove expired effects and generate events."""
        expired = [e for e in effects_data.effects if e.is_expired]

        if not expired:
            return []

        # Remove from component
        await write_buffer.mutate.remote(
            "ActiveEffects", entity_id, lambda ae: ae.clear_expired()
        )

        # Generate events
        for effect in expired:
            self._expired_events.append(
                EffectExpiredEvent(
                    effect_id=effect.effect_id,
                    target_id=entity_id,
                    effect_type=effect.effect_type,
                    skill_name=effect.skill_id,  # Would need skill registry for actual name
                )
            )

        return expired

    async def get_pending_events(self) -> Tuple[List[EffectTickEvent], List[EffectExpiredEvent]]:
        """Get events from last tick."""
        return self._tick_events.copy(), self._expired_events.copy()
