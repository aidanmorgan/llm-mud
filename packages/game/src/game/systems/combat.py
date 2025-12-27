"""
Combat System

Handles combat state, attack resolution, damage calculation,
and combat-related events.

Based on ROM MUD combat mechanics with tick-based rounds.
"""

import random
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

import ray
from ray.actor import ActorHandle

from core import EntityId, ComponentData, System
from ..components.combat import CombatData, CombatState, parse_dice_roll

logger = logging.getLogger(__name__)


@dataclass
class CombatEvent:
    """Represents a combat event for notification."""

    event_type: str  # 'attack_hit', 'attack_miss', 'death', 'flee', etc.
    attacker: EntityId
    defender: EntityId
    damage: int = 0
    damage_type: str = ""
    message: str = ""
    room_id: Optional[EntityId] = None


@ray.remote
class CombatSystem(System):
    """
    Processes combat each tick.

    Combat Flow (per tick):
    1. Find all entities in ENGAGED state with valid targets
    2. Check if attack cooldown has elapsed
    3. Resolve attacks (hit/miss based on attack_bonus vs armor_class)
    4. Apply damage
    5. Check for death
    6. Handle flee attempts
    7. Generate combat messages

    Required components:
    - Combat: Combat state and targeting
    - Stats: Health, attributes, armor class

    Optional components:
    - Location: For room-based combat notifications
    - Weapon: Equipped weapon data
    - Equipment: Equipped gear affecting combat
    """

    def __init__(self):
        super().__init__(
            system_type="CombatSystem",
            required_components=["Combat", "Stats"],
            optional_components=["Location", "Weapon", "Equipment", "Identity"],
            dependencies=["MovementSystem"],
            priority=30,
        )
        self._combat_events: List[CombatEvent] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Process combat for all entities in combat state.
        """
        processed = 0
        self._combat_events.clear()

        # First pass: process attacks
        for entity_id, components in entities.items():
            combat = components["Combat"]
            stats = components["Stats"]

            # Skip if not in combat or dead
            if combat.state != CombatState.ENGAGED:
                continue

            if not stats.is_alive:
                continue

            # Check for valid target
            if not combat.target:
                # Auto-clear combat if no target
                await self._exit_combat(write_buffer, entity_id, combat)
                continue

            # Check if target exists and is in combat entities
            target_components = entities.get(combat.target)
            if not target_components:
                # Target not found in this tick's snapshot
                await self._exit_combat(write_buffer, entity_id, combat)
                continue

            target_combat = target_components["Combat"]
            target_stats = target_components["Stats"]

            # Target already dead?
            if not target_stats.is_alive:
                await self._handle_target_death(
                    write_buffer, entity_id, combat, combat.target, target_stats
                )
                continue

            # Can we attack this tick?
            if not combat.can_attack:
                continue

            # Process the attack
            await self._process_attack(
                write_buffer,
                entity_id,
                combat,
                stats,
                components.get("Location"),
                combat.target,
                target_combat,
                target_stats,
            )
            processed += 1

        # Second pass: process flee attempts
        for entity_id, components in entities.items():
            combat = components["Combat"]

            if combat.state == CombatState.FLEEING:
                await self._process_flee(write_buffer, entity_id, combat, components)

        return processed

    async def _process_attack(
        self,
        write_buffer: ActorHandle,
        attacker_id: EntityId,
        attacker_combat: CombatData,
        attacker_stats,
        attacker_location,
        defender_id: EntityId,
        defender_combat: CombatData,
        defender_stats,
    ) -> None:
        """Process a single attack."""
        # Calculate hit
        hit_roll = random.randint(1, 20)
        attack_bonus = attacker_stats.attack_bonus + attacker_combat.hit_bonus

        # Get DEX modifier for AC
        dex_mod = attacker_stats.attributes.get_modifier("dexterity")
        total_attack = hit_roll + attack_bonus + dex_mod

        target_ac = defender_stats.armor_class + defender_combat.defense_bonus

        # Natural 1 always misses, natural 20 always hits
        is_crit = False
        if hit_roll == 1:
            hit = False
        elif hit_roll == 20:
            hit = True
            is_crit = True
        else:
            hit = total_attack >= target_ac

        if not hit:
            # Miss
            self._combat_events.append(
                CombatEvent(
                    event_type="attack_miss",
                    attacker=attacker_id,
                    defender=defender_id,
                    room_id=attacker_location.room_id if attacker_location else None,
                )
            )

            # Record attack time
            await write_buffer.mutate.remote("Combat", attacker_id, lambda c: c.record_attack())
            return

        # Calculate damage
        damage = parse_dice_roll(attacker_combat.weapon_damage_dice)
        damage += attacker_combat.damage_bonus
        damage += attacker_stats.damage_bonus

        # Strength modifier for melee
        str_mod = attacker_stats.attributes.get_modifier("strength")
        damage += str_mod

        # Critical hit doubles damage
        if is_crit:
            damage *= 2

        damage = max(1, damage)  # Minimum 1 damage on hit

        # Apply damage to defender
        await write_buffer.mutate.remote("Stats", defender_id, lambda s: s.take_damage(damage))

        # Update combat tracking
        await write_buffer.mutate.remote(
            "Combat",
            attacker_id,
            lambda c: (c.record_attack(), c.record_damage_dealt(damage)),
        )
        await write_buffer.mutate.remote(
            "Combat", defender_id, lambda c: c.record_damage_taken(damage)
        )

        # Ensure defender is in combat with attacker
        if attacker_id not in defender_combat.targeted_by:
            await write_buffer.mutate.remote(
                "Combat", defender_id, lambda c: c.add_attacker(attacker_id)
            )

        # Generate event
        event_type = "attack_crit" if is_crit else "attack_hit"
        self._combat_events.append(
            CombatEvent(
                event_type=event_type,
                attacker=attacker_id,
                defender=defender_id,
                damage=damage,
                damage_type=attacker_combat.weapon_damage_type.value,
                room_id=attacker_location.room_id if attacker_location else None,
            )
        )

        # Check for death
        updated_health = defender_stats.current_health - damage
        if updated_health <= 0:
            await self._handle_death(
                write_buffer,
                defender_id,
                defender_combat,
                defender_stats,
                attacker_id,
                attacker_combat,
                attacker_stats,
            )

    async def _handle_death(
        self,
        write_buffer: ActorHandle,
        dead_id: EntityId,
        dead_combat: CombatData,
        dead_stats,
        killer_id: EntityId,
        killer_combat: CombatData,
        killer_stats,
    ) -> None:
        """Handle entity death."""
        # Set combat state to dead
        await write_buffer.mutate.remote(
            "Combat", dead_id, lambda c: setattr(c, "state", CombatState.DEAD)
        )

        # Clear killer's target
        await write_buffer.mutate.remote("Combat", killer_id, lambda c: c.clear_target())

        # Remove dead from killer's targeted_by
        await write_buffer.mutate.remote("Combat", killer_id, lambda c: c.remove_attacker(dead_id))

        # Generate death event
        self._combat_events.append(
            CombatEvent(
                event_type="death",
                attacker=killer_id,
                defender=dead_id,
            )
        )

        # Grant experience if killer is player and dead is mob
        if killer_id.entity_type == "player" and dead_id.entity_type == "mob":
            exp_value = getattr(dead_stats, "experience_value", 100)
            await write_buffer.mutate.remote(
                "Stats", killer_id, lambda s: s.gain_experience(exp_value)
            )

    async def _handle_target_death(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        combat: CombatData,
        dead_target: EntityId,
        target_stats,
    ) -> None:
        """Handle when our target has died."""
        # Look for another attacker to target
        new_target = None
        for attacker in combat.targeted_by:
            if attacker != dead_target:
                new_target = attacker
                break

        if new_target:
            await write_buffer.mutate.remote(
                "Combat", entity_id, lambda c: c.set_target(new_target)
            )
        else:
            await self._exit_combat(write_buffer, entity_id, combat)

    async def _exit_combat(
        self, write_buffer: ActorHandle, entity_id: EntityId, combat: CombatData
    ) -> None:
        """Exit combat state."""
        await write_buffer.mutate.remote("Combat", entity_id, lambda c: c.clear_target())

    async def _process_flee(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        combat: CombatData,
        components: Dict[str, ComponentData],
    ) -> None:
        """Process a flee attempt."""
        stats = components.get("Stats")
        location = components.get("Location")

        if not stats or not location or not location.room_id:
            return

        # Flee chance based on DEX
        dex_mod = stats.attributes.get_modifier("dexterity")
        flee_chance = 50 + (dex_mod * 5)  # Base 50% + 5% per DEX mod

        # Each attacker reduces flee chance
        flee_chance -= len(combat.targeted_by) * 10

        flee_chance = max(10, min(90, flee_chance))

        if random.randint(1, 100) <= flee_chance:
            # Successful flee - get random exit
            room_data = await self._get_room_data(location.room_id)
            if room_data:
                exits = room_data.get_available_exits()
                if exits:
                    flee_dir = random.choice(exits)
                    exit_data = room_data.get_exit(flee_dir)
                    if exit_data:
                        # Create movement request
                        await self._create_flee_movement(write_buffer, entity_id, flee_dir)

                        # Exit combat
                        await write_buffer.mutate.remote(
                            "Combat", entity_id, lambda c: c.clear_target()
                        )

                        # Remove from attackers' target lists
                        for attacker_id in combat.targeted_by:
                            await write_buffer.mutate.remote(
                                "Combat",
                                attacker_id,
                                lambda c: c.remove_attacker(entity_id),
                            )

                        self._combat_events.append(
                            CombatEvent(
                                event_type="flee_success",
                                attacker=entity_id,
                                defender=entity_id,
                                message=flee_dir,
                                room_id=location.room_id,
                            )
                        )
                        return

        # Failed flee
        self._combat_events.append(
            CombatEvent(
                event_type="flee_fail",
                attacker=entity_id,
                defender=entity_id,
                room_id=location.room_id if location else None,
            )
        )

        # Return to engaged state
        await write_buffer.mutate.remote(
            "Combat", entity_id, lambda c: setattr(c, "state", CombatState.ENGAGED)
        )

    async def _get_room_data(self, room_id: EntityId):
        """Get room data from Room component actor."""
        from core.component import get_component_actor

        try:
            room_actor = get_component_actor("Room")
            room_data = await room_actor.get.remote(room_id)
            return room_data
        except Exception as e:
            logger.error(f"Failed to get room data for {room_id}: {e}")
            return None

    async def _create_flee_movement(
        self, write_buffer: ActorHandle, entity_id: EntityId, direction: str
    ) -> None:
        """Create a movement request for fleeing."""
        from .movement import MovementRequestData

        request = MovementRequestData(owner=entity_id, direction=direction)
        await write_buffer.create.remote("MovementRequest", entity_id, request)

    async def get_pending_events(self) -> List[CombatEvent]:
        """Get combat events from last tick (for notification system)."""
        return self._combat_events.copy()


@dataclass
class AttackRequestData(ComponentData):
    """
    Transient component indicating an entity wants to initiate combat.

    Created by command handlers (e.g., "kill goblin"), consumed by CombatSystem.
    """

    target: Optional[EntityId] = None
    target_keyword: str = ""  # For resolving target by name
    requested_at: datetime = field(default_factory=datetime.utcnow)


@ray.remote
class CombatInitiationSystem(System):
    """
    Handles initiating combat from attack requests.

    This runs before CombatSystem to set up targeting.
    Also interrupts rest/sleep when combat begins.
    """

    def __init__(self):
        super().__init__(
            system_type="CombatInitiationSystem",
            required_components=["AttackRequest", "Combat", "Location"],
            optional_components=["Stats", "Position"],
            dependencies=["MovementSystem"],
            priority=20,
        )

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """Process attack initiation requests."""
        processed = 0

        for entity_id, components in entities.items():
            request = components["AttackRequest"]
            combat = components["Combat"]
            location = components["Location"]

            # Already in combat?
            if combat.is_in_combat:
                await write_buffer.delete.remote("AttackRequest", entity_id)
                continue

            # Find target
            target_id = request.target
            if not target_id and request.target_keyword:
                target_id = await self._find_target_by_keyword(
                    location.room_id, request.target_keyword
                )

            if not target_id:
                await write_buffer.delete.remote("AttackRequest", entity_id)
                continue

            # Verify target is valid (exists, in same room, can be attacked)
            if not await self._validate_target(location.room_id, target_id):
                await write_buffer.delete.remote("AttackRequest", entity_id)
                continue

            # Initiate combat
            await write_buffer.mutate.remote("Combat", entity_id, lambda c: c.set_target(target_id))
            await write_buffer.mutate.remote(
                "Combat", target_id, lambda c: c.add_attacker(entity_id)
            )

            # Interrupt position (stand up from rest/sleep)
            position = components.get("Position")
            if position:
                await write_buffer.mutate.remote("Position", entity_id, lambda p: p.interrupt())

            # Also interrupt the target's position
            await self._interrupt_target_position(write_buffer, target_id)

            # Clear the request
            await write_buffer.delete.remote("AttackRequest", entity_id)
            processed += 1

        return processed

    async def _interrupt_target_position(
        self, write_buffer: ActorHandle, target_id: EntityId
    ) -> None:
        """Interrupt target's rest/sleep when attacked."""
        from core.component import get_component_actor

        try:
            position_actor = get_component_actor("Position")
            target_position = await position_actor.get.remote(target_id)
            if target_position:
                await write_buffer.mutate.remote("Position", target_id, lambda p: p.interrupt())
        except Exception:
            pass  # Position component may not exist for this entity

    async def _find_target_by_keyword(self, room_id: EntityId, keyword: str) -> Optional[EntityId]:
        """Find a target in the room by keyword."""
        from core.component import get_component_actor

        try:
            # Get all entities with Location in this room
            location_actor = get_component_actor("Location")
            all_locations = await location_actor.get_all.remote()

            candidates = []
            for eid, loc in all_locations.items():
                if loc.room_id == room_id:
                    candidates.append(eid)

            # Check each candidate's identity for keyword match
            if not candidates:
                return None

            identity_actor = get_component_actor("Identity")
            for candidate in candidates:
                identity = await identity_actor.get.remote(candidate)
                if identity and self._matches_keyword(identity, keyword):
                    return candidate

            return None

        except Exception as e:
            logger.error(f"Error finding target by keyword: {e}")
            return None

    def _matches_keyword(self, identity, keyword: str) -> bool:
        """Check if identity matches keyword."""
        keyword = keyword.lower()
        if keyword in identity.name.lower():
            return True
        for kw in identity.keywords:
            if keyword in kw.lower():
                return True
        return False

    async def _validate_target(self, room_id: EntityId, target_id: EntityId) -> bool:
        """Validate that target can be attacked."""
        from core.component import get_component_actor

        try:
            # Check target has Combat component
            combat_actor = get_component_actor("Combat")
            target_combat = await combat_actor.get.remote(target_id)
            if not target_combat:
                return False

            # Check target is in same room
            location_actor = get_component_actor("Location")
            target_location = await location_actor.get.remote(target_id)
            if not target_location or target_location.room_id != room_id:
                return False

            # Check room allows combat
            room_actor = get_component_actor("Room")
            room_data = await room_actor.get.remote(room_id)
            if room_data and room_data.is_safe:
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating target: {e}")
            return False
