"""
Dynamic AI System

Processes AI-controlled entities (mobs) each tick, using personality-driven
decision making for combat and behavior. Supports both static AI patterns
and dynamic LLM-enhanced behavior.

Features:
- Static AI patterns for simple mobs
- Dynamic AI with PersonalityEngine for complex mobs
- Skill/ability selection and queueing
- Integration with SkillExecutionSystem
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import ray
from ray.actor import ActorHandle

from core import EntityId, ComponentData, System

logger = logging.getLogger(__name__)


@dataclass
class AIDecision:
    """Result of AI decision making."""

    action: str  # 'attack', 'defend', 'flee', 'special', 'idle', 'wander'
    target: Optional[EntityId] = None
    ability: Optional[str] = None
    message: Optional[str] = None


@ray.remote
class DynamicAISystem(System):
    """
    Processes AI decisions for mobs each tick.

    AI Flow (per tick):
    1. Find all entities with AI components (static or dynamic)
    2. Gather context (combat state, health, nearby entities)
    3. For static AI: Use behavior patterns
    4. For dynamic AI: Use PersonalityEngine
    5. Queue resulting actions

    Required components:
    - AI: AI configuration and behavior type
    - Stats: Health, attributes

    Optional components:
    - Combat: Current combat state
    - Location: For movement decisions
    - DynamicAI: LLM-generated personality data
    """

    def __init__(self):
        super().__init__(
            system_type="DynamicAISystem",
            required_components=["AI", "Stats"],
            optional_components=["Combat", "Location", "DynamicAI", "Identity"],
            dependencies=[],  # Runs early in tick
            priority=5,
        )

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """Process AI decisions for all AI-controlled entities."""
        processed = 0

        for entity_id, components in entities.items():
            stats = components["Stats"]

            # Skip dead entities
            if not stats.get("is_alive", True):
                continue

            # Get combat state if in combat
            combat = components.get("Combat")
            in_combat = combat and combat.get("state") == "engaged"

            # Make decision based on AI type
            if "DynamicAI" in components:
                decision = await self._dynamic_decision(entity_id, components, in_combat)
            else:
                decision = await self._static_decision(entity_id, components, in_combat)

            # Apply decision
            if decision:
                await self._apply_decision(entity_id, decision, write_buffer, components)
                processed += 1

        return processed

    async def _static_decision(
        self,
        entity_id: EntityId,
        components: Dict[str, ComponentData],
        in_combat: bool,
    ) -> Optional[AIDecision]:
        """
        Make decision using static AI patterns.

        Behavior types:
        - passive: Never attacks, only defends
        - aggressive: Attacks on sight
        - defensive: Attacks if attacked first
        - patrol: Wanders on patrol route
        """
        ai = components["AI"]
        behavior = ai.get("behavior_type", "passive")

        if in_combat:
            # In combat: decide combat action
            return await self._static_combat_decision(behavior, components, entity_id)
        else:
            # Not in combat: decide behavior
            return self._static_idle_decision(behavior, components)

    async def _static_combat_decision(
        self, behavior: str, components: Dict[str, ComponentData], entity_id: EntityId
    ) -> AIDecision:
        """Make a combat decision using static patterns."""
        stats = components["Stats"]
        ai = components["AI"]
        combat = components.get("Combat", {})

        health_pct = stats.get("current_hp", 100) / max(stats.get("max_hp", 100), 1)
        flee_threshold = ai.get("flee_threshold", 0.2)

        # Check flee condition
        if health_pct <= flee_threshold and behavior != "berserker":
            return AIDecision(action="flee", message="tries to flee!")

        # Check if mob has abilities to use
        abilities = ai.get("abilities", [])
        if abilities:
            # Get ready abilities (not on cooldown)
            ability_cooldowns = ai.get("ability_cooldowns", {})
            available_abilities = await self._build_ability_info_list(abilities, ability_cooldowns)

            ready_abilities = [a for a in available_abilities if a.cooldown_ready]

            # Use ability with some probability based on combat style
            combat_style = ai.get("combat_style", "tactician")

            ability_chance = {
                "berserker": 0.2,  # Berserkers prefer basic attacks
                "tactician": 0.5,  # Tacticians use abilities often
                "caster": 0.8,     # Casters almost always use abilities
                "defender": 0.3,   # Defenders occasionally use abilities
                "ambusher": 0.6,   # Ambushers use abilities for burst
            }.get(combat_style, 0.4)

            if ready_abilities and random.random() < ability_chance:
                # Pick a random ability (weighted toward preferred ones)
                preferred = ai.get("preferred_abilities", [])
                for pref in preferred:
                    for ability in ready_abilities:
                        if ability.skill_id == pref:
                            return AIDecision(
                                action="special",
                                target=combat.get("target"),
                                ability=ability.skill_id,
                                message=f"uses {ability.name}!",
                            )

                # Fall back to random ability
                ability = random.choice(ready_abilities)
                return AIDecision(
                    action="special",
                    target=combat.get("target"),
                    ability=ability.skill_id,
                    message=f"uses {ability.name}!",
                )

        # Normal attack
        return AIDecision(
            action="attack",
            target=combat.get("target"),
        )

    def _static_idle_decision(
        self, behavior: str, components: Dict[str, ComponentData]
    ) -> Optional[AIDecision]:
        """Make an idle decision using static patterns."""
        ai = components["AI"]

        # Aggressive mobs might look for targets
        if behavior == "aggressive":
            aggro_radius = ai.get("aggro_radius", 0)
            if aggro_radius > 0:
                # Would need to query nearby entities
                # For now, this is handled by a separate aggro system
                pass

        # Patrol behavior
        if behavior == "patrol":
            patrol_path = ai.get("patrol_path", [])
            if patrol_path and random.random() < 0.1:  # 10% chance to move
                return AIDecision(action="wander")

        return AIDecision(action="idle")

    async def _dynamic_decision(
        self,
        entity_id: EntityId,
        components: Dict[str, ComponentData],
        in_combat: bool,
    ) -> Optional[AIDecision]:
        """
        Make decision using dynamic AI with personality engine.
        """
        from generation.personality import (
            PersonalityEngine,
            CombatContext,
            CombatAction,
            AbilityInfo,
        )
        from llm.schemas import MobPersonality, CombatStyle, PersonalityTrait

        dynamic_ai = components["DynamicAI"]
        stats = components["Stats"]
        combat = components.get("Combat", {})

        # Build personality from stored data
        personality_data = dynamic_ai.get("personality", {})
        try:
            personality = MobPersonality(
                traits=[PersonalityTrait(t) for t in personality_data.get("traits", ["hostile"])],
                combat_style=CombatStyle(personality_data.get("combat_style", "tactical")),
                flee_threshold=personality_data.get("flee_threshold", 0.2),
                dialogue_style=personality_data.get("dialogue_style", ""),
                motivations=personality_data.get("motivations", []),
                fears=personality_data.get("fears", []),
            )
        except (ValueError, KeyError):
            # Fallback to default personality
            personality = MobPersonality(
                traits=[PersonalityTrait.HOSTILE],
                combat_style=CombatStyle.TACTICAL,
                flee_threshold=0.2,
                dialogue_style="speaks tersely",
            )

        engine = PersonalityEngine(personality)

        if in_combat:
            # Build ability info list
            abilities = dynamic_ai.get("abilities", [])
            ability_cooldowns = dynamic_ai.get("ability_cooldowns", {})
            available_abilities = await self._build_ability_info_list(
                abilities, ability_cooldowns
            )

            current_mana = stats.get("current_mana", 0)
            max_mana = max(stats.get("max_mana", 1), 1)
            current_stamina = stats.get("current_stamina", 100)
            max_stamina = max(stats.get("max_stamina", 100), 1)

            # Build combat context
            context = CombatContext(
                mob_health_pct=stats.get("current_hp", 100) / max(stats.get("max_hp", 100), 1),
                target_health_pct=0.5,  # Would need to query target
                mob_mana_pct=current_mana / max_mana,
                mob_stamina_pct=current_stamina / max_stamina,
                round_number=combat.get("rounds_in_combat", 0),
                allies_nearby=0,  # Would need spatial query
                enemies_nearby=1,
                has_special_abilities=len(available_abilities) > 0,
                special_ability_ready=any(a.cooldown_ready for a in available_abilities),
                available_abilities=available_abilities,
            )

            decision = engine.decide_combat_action(context)

            # Convert to AIDecision
            action_map = {
                CombatAction.ATTACK: "attack",
                CombatAction.DEFEND: "defend",
                CombatAction.FLEE: "flee",
                CombatAction.SPECIAL_ABILITY: "special",
                CombatAction.CALL_FOR_HELP: "call_help",
                CombatAction.TAUNT: "taunt",
                CombatAction.HEAL: "heal",
                CombatAction.WAIT: "idle",
            }

            return AIDecision(
                action=action_map.get(decision.action, "attack"),
                target=combat.get("target"),
                ability=decision.ability_name,
                message=decision.message,
            )
        else:
            # Idle behavior for dynamic AI
            # Could use personality for wandering, dialogue, etc.
            return AIDecision(action="idle")

    async def _build_ability_info_list(
        self,
        ability_ids: List[str],
        cooldowns: Dict[str, datetime],
    ) -> List:
        """Build AbilityInfo objects from skill IDs."""
        from generation.personality import AbilityInfo

        if not ability_ids:
            return []

        # Get skill registry
        try:
            from ..world.skill_registry import get_skill_registry
            registry = get_skill_registry()
        except Exception as e:
            logger.debug(f"Could not get skill registry: {e}")
            return []

        abilities = []
        now = datetime.utcnow()

        for skill_id in ability_ids:
            try:
                skill_def = await registry.get.remote(skill_id)
                if not skill_def:
                    continue

                # Check cooldown
                cooldown_ready = True
                if skill_id in cooldowns:
                    cooldown_ready = now >= cooldowns[skill_id]

                # Determine ability properties from skill definition
                from ..components.skills import SkillCategory, TargetType, EffectType

                is_offensive = skill_def.target_type in (
                    TargetType.SINGLE_ENEMY,
                    TargetType.AREA_ENEMIES,
                )
                is_healing = skill_def.category == SkillCategory.HEALING
                is_buff = any(
                    hasattr(e, 'effect_type') and e.effect_type == EffectType.BUFF
                    for e in skill_def.effects
                )
                is_aoe = skill_def.target_type in (
                    TargetType.AREA_ENEMIES,
                    TargetType.AREA_ALLIES,
                    TargetType.AREA_ALL,
                )

                abilities.append(AbilityInfo(
                    skill_id=skill_id,
                    name=skill_def.name,
                    mana_cost=skill_def.mana_cost,
                    stamina_cost=skill_def.stamina_cost,
                    category=skill_def.category.value,
                    is_offensive=is_offensive,
                    is_healing=is_healing,
                    is_buff=is_buff,
                    is_aoe=is_aoe,
                    cooldown_ready=cooldown_ready,
                ))

            except Exception as e:
                logger.debug(f"Could not load skill {skill_id}: {e}")
                continue

        return abilities

    async def _apply_decision(
        self,
        entity_id: EntityId,
        decision: AIDecision,
        write_buffer: ActorHandle,
        components: Dict[str, ComponentData],
    ) -> None:
        """Apply an AI decision by queueing the appropriate action."""
        from ..systems.skills import SkillRequestData

        if decision.action == "attack":
            # Set up attack in combat component
            if decision.target:
                combat = components.get("Combat", {})
                combat["pending_action"] = "attack"
                combat["action_target"] = decision.target
                await write_buffer.write.remote("Combat", entity_id, combat)

        elif decision.action == "flee":
            # Set flee flag
            combat = components.get("Combat", {})
            combat["pending_action"] = "flee"
            await write_buffer.write.remote("Combat", entity_id, combat)

        elif decision.action == "defend":
            combat = components.get("Combat", {})
            combat["pending_action"] = "defend"
            await write_buffer.write.remote("Combat", entity_id, combat)

        elif decision.action == "special" and decision.ability:
            # Queue a skill request for the SkillExecutionSystem
            combat = components.get("Combat", {})
            target_id = combat.get("target") if combat else None

            # Create SkillRequest component
            skill_request = SkillRequestData(
                skill_id=decision.ability,
                target_id=target_id,
                force=True,  # AI bypasses validation (it's pre-validated)
            )
            await write_buffer.write.remote("SkillRequest", entity_id, skill_request)

            # Also update AI component to track we're using this ability
            ai = components.get("AI") or components.get("DynamicAI")
            if ai:
                ai["pending_skill_id"] = decision.ability
                ai["pending_skill_target"] = target_id
                component_name = "DynamicAI" if "DynamicAI" in components else "AI"
                await write_buffer.write.remote(component_name, entity_id, ai)

        elif decision.action == "heal" and decision.ability:
            # Queue healing ability targeting self
            skill_request = SkillRequestData(
                skill_id=decision.ability,
                target_id=entity_id,  # Self-heal
                force=True,
            )
            await write_buffer.write.remote("SkillRequest", entity_id, skill_request)

        elif decision.action == "wander":
            # Would trigger movement to a random adjacent room
            pass

        # Messages are handled by the combat system when processing actions


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_ai_system() -> ActorHandle:
    """Start the AI system actor."""
    actor: ActorHandle = DynamicAISystem.options(
        name="llmmud/systems/ai",
        namespace="llmmud",
        lifetime="detached",
    ).remote()  # type: ignore[assignment]
    logger.info("Started DynamicAISystem")
    return actor


def get_ai_system() -> ActorHandle:
    """Get the AI system actor."""
    return ray.get_actor("llmmud/systems/ai", namespace="llmmud")
