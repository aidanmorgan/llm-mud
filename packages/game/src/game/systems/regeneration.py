"""
Regeneration System

Handles health, mana, and stamina regeneration over time.
Based on ROM MUD regeneration mechanics.

Regeneration rates are affected by:
- Position (resting/sleeping regenerates faster)
- Location (inns regenerate faster)
- Combat state (no regeneration in combat)
- Hunger/thirst (future feature)
"""

import logging
from typing import Dict, List, Optional, Any

import ray
from ray.actor import ActorHandle

from core import EntityId, ComponentData, System
from ..components.combat import CombatState

logger = logging.getLogger(__name__)


@ray.remote
class RegenerationSystem(System):
    """
    Regenerates health, mana, and stamina for entities.

    Required components:
    - Stats: Has current/max health, mana, stamina and regen rates

    Optional components:
    - Combat: Check if in combat (no regen while fighting)
    - Location: Check room properties (safe rooms regen faster)
    - Position: Position affects regen (standing/sitting/resting/sleeping)
    """

    # Regeneration multipliers
    SAFE_ROOM_MULTIPLIER = 1.5
    COMBAT_MULTIPLIER = 0.0  # No regen in combat

    def __init__(self):
        super().__init__(
            system_type="RegenerationSystem",
            required_components=["Stats"],
            optional_components=["Combat", "Location", "Position"],
            dependencies=["CombatSystem"],
            priority=60,
        )
        self._regen_events: List[Dict[str, Any]] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Apply regeneration to all entities with Stats component.
        """
        processed = 0
        self._regen_events.clear()

        for entity_id, components in entities.items():
            stats = components["Stats"]
            combat = components.get("Combat")
            location = components.get("Location")
            position = components.get("Position")

            # Skip if dead
            if not stats.is_alive:
                continue

            # Calculate regeneration multiplier
            multiplier = self._calculate_multiplier(combat, location, position)

            # Skip if no regeneration (in combat)
            if multiplier <= 0:
                continue

            # Calculate regeneration amounts
            health_regen = 0
            mana_regen = 0
            stamina_regen = 0

            if stats.current_health < stats.max_health:
                health_regen = int(stats.health_regen * multiplier)

            if stats.current_mana < stats.max_mana:
                mana_regen = int(stats.mana_regen * multiplier)

            if stats.current_stamina < stats.max_stamina:
                stamina_regen = int(stats.stamina_regen * multiplier)

            # Apply regeneration if any
            if health_regen > 0 or mana_regen > 0 or stamina_regen > 0:
                await self._apply_regeneration(
                    write_buffer,
                    entity_id,
                    stats,
                    health_regen,
                    mana_regen,
                    stamina_regen,
                )
                processed += 1

        return processed

    def _calculate_multiplier(
        self,
        combat: Optional[ComponentData],
        location: Optional[ComponentData],
        position: Optional[ComponentData],
    ) -> float:
        """Calculate the regeneration multiplier based on state."""
        multiplier = 1.0

        # No regen in combat
        if combat and combat.state == CombatState.ENGAGED:
            return self.COMBAT_MULTIPLIER

        # Position bonus (from Position component)
        if position:
            # Position.regen_multiplier returns:
            # - standing: 1.0
            # - sitting: 1.5
            # - resting: 2.0
            # - sleeping: 3.0
            # - dead: 0.0
            multiplier *= position.position.regen_multiplier

        # Safe room bonus
        if location and location.room_id:
            # Check if in safe room (would need room data lookup)
            # For now, assume location has cached room flags
            is_safe = getattr(location, "_cached_is_safe", False)
            if is_safe:
                multiplier *= self.SAFE_ROOM_MULTIPLIER

        return multiplier

    async def _apply_regeneration(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        stats,
        health_regen: int,
        mana_regen: int,
        stamina_regen: int,
    ) -> None:
        """Apply regeneration amounts to entity stats."""

        def apply_regen(s):
            actual_health = 0
            actual_mana = 0
            actual_stamina = 0

            if health_regen > 0:
                actual_health = s.heal(health_regen)

            if mana_regen > 0:
                actual_mana = s.restore_mana(mana_regen)

            if stamina_regen > 0:
                missing = s.max_stamina - s.current_stamina
                actual_stamina = min(stamina_regen, missing)
                s.current_stamina += actual_stamina

            return (actual_health, actual_mana, actual_stamina)

        await write_buffer.mutate.remote("Stats", entity_id, apply_regen)

        # Track event for debugging/display
        self._regen_events.append(
            {
                "entity": entity_id,
                "health": health_regen,
                "mana": mana_regen,
                "stamina": stamina_regen,
            }
        )

    async def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get regeneration events from last tick."""
        return self._regen_events.copy()


@ray.remote
class DeathSystem(System):
    """
    Handles entity death and corpse creation.

    Required components:
    - Stats: Check for death (current_health <= 0)
    - Combat: Check/set DEAD state

    This system runs after CombatSystem to catch deaths.
    """

    def __init__(self):
        super().__init__(
            system_type="DeathSystem",
            required_components=["Stats", "Combat"],
            optional_components=["Location", "Identity", "Container"],
            dependencies=["CombatSystem"],
            priority=40,
        )
        self._death_events: List[Dict[str, Any]] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Process death for entities with 0 or less health.
        """
        processed = 0
        self._death_events.clear()

        for entity_id, components in entities.items():
            stats = components["Stats"]
            combat = components["Combat"]

            # Skip if already marked dead
            if combat.state == CombatState.DEAD:
                continue

            # Check for death
            if stats.current_health <= 0:
                await self._handle_death(write_buffer, entity_id, components)
                processed += 1

        return processed

    async def _handle_death(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        components: Dict[str, ComponentData],
    ) -> None:
        """Handle the death of an entity."""
        location = components.get("Location")
        identity = components.get("Identity")
        combat = components["Combat"]

        # Set combat state to dead
        await write_buffer.mutate.remote(
            "Combat", entity_id, lambda c: setattr(c, "state", CombatState.DEAD)
        )

        # Clear all combat relationships
        for attacker_id in combat.targeted_by:
            await write_buffer.mutate.remote(
                "Combat", attacker_id, lambda c: c.remove_attacker(entity_id)
            )

        room_id = location.room_id if location else None
        name = identity.name if identity else "something"

        # For mobs: create corpse and drop items
        if entity_id.entity_type == "mob":
            # Queue corpse creation and mob cleanup
            self._death_events.append(
                {
                    "type": "mob_death",
                    "entity": entity_id,
                    "room": room_id,
                    "name": name,
                    "create_corpse": True,
                }
            )

        # For players: different handling
        elif entity_id.entity_type == "player":
            self._death_events.append(
                {
                    "type": "player_death",
                    "entity": entity_id,
                    "room": room_id,
                    "name": name,
                }
            )

    async def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get death events from last tick."""
        return self._death_events.copy()


@ray.remote
class RespawnSystem(System):
    """
    Handles mob respawning in rooms.

    Required components:
    - Room: Has respawn configuration

    This system checks each room's respawn timer and spawns
    mobs/items from their configured spawn lists.
    """

    def __init__(self):
        super().__init__(
            system_type="RespawnSystem",
            required_components=["Room"],
            optional_components=["Identity"],
            dependencies=["DeathSystem"],
            priority=50,
        )

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Check and trigger respawns for rooms.
        """
        from datetime import datetime, timedelta

        processed = 0

        for entity_id, components in entities.items():
            room = components["Room"]

            # Only process static rooms with respawn config
            if not hasattr(room, "respawn_mobs"):
                continue

            if not room.respawn_mobs and not room.respawn_items:
                continue

            # Check respawn timer
            now = datetime.utcnow()
            last_respawn = getattr(room, "last_respawn", None)
            respawn_interval = getattr(room, "respawn_interval_s", 300)

            if last_respawn:
                next_respawn = last_respawn + timedelta(seconds=respawn_interval)
                if now < next_respawn:
                    continue

            # Trigger respawn
            await self._do_respawn(write_buffer, entity_id, room)
            processed += 1

        return processed

    async def _do_respawn(self, write_buffer: ActorHandle, room_id: EntityId, room) -> None:
        """Spawn mobs and items in the room."""
        from datetime import datetime

        # Update last respawn time
        await write_buffer.mutate.remote(
            "Room", room_id, lambda r: setattr(r, "last_respawn", datetime.utcnow())
        )

        # Spawn mobs
        for template_id in room.respawn_mobs:
            await self._spawn_mob(room_id, template_id)

        # Spawn items
        for template_id in room.respawn_items:
            await self._spawn_item(room_id, template_id)

    async def _spawn_mob(self, room_id: EntityId, template_id: str) -> Optional[EntityId]:
        """Spawn a mob from template."""
        from ..world.factory import get_entity_factory

        try:
            factory = get_entity_factory()
            mob_id = await factory.create_mob(template_id, room_id)
            logger.debug(f"Spawned mob {template_id} in {room_id}")
            return mob_id
        except Exception as e:
            logger.error(f"Failed to spawn mob {template_id}: {e}")
            return None

    async def _spawn_item(self, room_id: EntityId, template_id: str) -> Optional[EntityId]:
        """Spawn an item from template."""
        from ..world.factory import get_entity_factory

        try:
            factory = get_entity_factory()
            item_id = await factory.create_item(template_id, room_id=room_id)
            logger.debug(f"Spawned item {template_id} in {room_id}")
            return item_id
        except Exception as e:
            logger.error(f"Failed to spawn item {template_id}: {e}")
            return None
