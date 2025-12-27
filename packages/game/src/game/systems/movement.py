"""
Movement System

Handles entity movement between rooms, exit validation,
and room transition events.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime

import ray
from ray.actor import ActorHandle

from core import EntityId, ComponentData, System

logger = logging.getLogger(__name__)


@ray.remote
class MovementSystem(System):
    """
    Processes movement requests and transitions entities between rooms.

    Required components:
    - Location: Current position
    - MovementRequest: Pending movement direction (transient component)

    The system:
    1. Finds entities with pending movement requests
    2. Validates the exit exists and is passable
    3. Updates Location to new room
    4. Clears the movement request
    5. Emits movement events for notification
    """

    def __init__(self):
        super().__init__(
            system_type="MovementSystem",
            required_components=["Location", "MovementRequest"],
            optional_components=["Stats", "Combat"],
            dependencies=[],
            priority=10,
        )
        self._movement_events: List[Dict[str, Any]] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Process all pending movement requests.
        """
        processed = 0
        self._movement_events.clear()

        for entity_id, components in entities.items():
            location = components["Location"]
            request = components["MovementRequest"]
            combat = components.get("Combat")

            # Can't move while in combat (unless fleeing)
            if combat and combat.is_in_combat and combat.state.value != "fleeing":
                await self._deny_movement(
                    write_buffer, entity_id, request, "You can't leave while in combat!"
                )
                continue

            # Get current room data
            room_data = await self._get_room_data(location.room_id)
            if not room_data:
                await self._deny_movement(write_buffer, entity_id, request, "You are nowhere.")
                continue

            # Check for valid exit
            exit_data = room_data.get_exit(request.direction)
            if not exit_data:
                await self._deny_movement(
                    write_buffer,
                    entity_id,
                    request,
                    f"You can't go {request.direction}.",
                )
                continue

            # Check if exit is blocked
            if exit_data.is_locked:
                await self._deny_movement(write_buffer, entity_id, request, "The door is locked.")
                continue

            # Check destination room restrictions
            dest_room = await self._get_room_data(exit_data.destination_id)
            if not dest_room:
                await self._deny_movement(
                    write_buffer, entity_id, request, "That exit leads nowhere."
                )
                continue

            # Check no_mob restriction for mobs
            if dest_room.is_no_mob and entity_id.entity_type == "mob":
                await self._deny_movement(
                    write_buffer,
                    entity_id,
                    request,
                    "Something prevents you from going that way.",
                )
                continue

            # Perform the movement
            await self._execute_movement(
                write_buffer,
                entity_id,
                location,
                exit_data.destination_id,
                request.direction,
            )
            processed += 1

        return processed

    async def _get_room_data(self, room_id: Optional[EntityId]):
        """Get room data from Room component actor."""
        if room_id is None:
            return None

        from core.component import get_component_actor

        try:
            room_actor = get_component_actor("Room")
            room_data = await room_actor.get.remote(room_id)
            return room_data
        except Exception as e:
            logger.error(f"Failed to get room data for {room_id}: {e}")
            return None

    async def _deny_movement(
        self, write_buffer: ActorHandle, entity_id: EntityId, request, message: str
    ) -> None:
        """Deny movement and queue message."""
        # Delete the movement request
        await write_buffer.delete.remote("MovementRequest", entity_id)

        # Queue message for the entity
        self._movement_events.append(
            {
                "type": "movement_denied",
                "entity": entity_id,
                "direction": request.direction,
                "message": message,
            }
        )

    async def _execute_movement(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
        location,
        destination_id: EntityId,
        direction: str,
    ) -> None:
        """Execute the movement update."""
        old_room_id = location.room_id

        # Update location via mutation
        def update_location(loc):
            loc.last_room_id = loc.room_id
            loc.room_id = destination_id
            loc.entered_at = datetime.utcnow()

        await write_buffer.mutate.remote("Location", entity_id, update_location)

        # Delete the movement request
        await write_buffer.delete.remote("MovementRequest", entity_id)

        # Queue movement events
        self._movement_events.append(
            {
                "type": "entity_left",
                "entity": entity_id,
                "room": old_room_id,
                "direction": direction,
            }
        )
        self._movement_events.append(
            {
                "type": "entity_entered",
                "entity": entity_id,
                "room": destination_id,
                "from_direction": self._get_opposite_direction(direction),
            }
        )

    def _get_opposite_direction(self, direction: str) -> str:
        """Get opposite direction for entrance messages."""
        opposites = {
            "north": "south",
            "south": "north",
            "east": "west",
            "west": "east",
            "up": "below",
            "down": "above",
            "northeast": "southwest",
            "southwest": "northeast",
            "northwest": "southeast",
            "southeast": "northwest",
        }
        return opposites.get(direction.lower(), "somewhere")

    async def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get movement events from last tick (for notification system)."""
        return self._movement_events.copy()


@dataclass
class MovementRequestData(ComponentData):
    """
    Transient component indicating an entity wants to move.

    Created by command handlers, consumed by MovementSystem.
    """

    direction: str = ""
    requested_at: datetime = field(default_factory=datetime.utcnow)


def create_movement_request(owner: EntityId, direction: str) -> MovementRequestData:
    """Factory to create a movement request."""
    return MovementRequestData(owner=owner, direction=direction, requested_at=datetime.utcnow())
