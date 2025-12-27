"""
Instance Manager for Dynamic Dungeons

Manages the lifecycle of dynamically generated dungeon instances,
including creation, player tracking, room generation, and cleanup.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import ray
from ray.actor import ActorHandle

from llm import GeneratedRoom
from llm.prompts import RoomContext, MobContext, ItemContext
from llm.schemas import ExitDirection

from .engine import get_generation_engine, generation_engine_exists

logger = logging.getLogger(__name__)


class InstanceState(str, Enum):
    """State of a dungeon instance."""

    CREATING = "creating"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class InstanceRoom:
    """A room within an instance."""

    room_id: str
    instance_id: str
    depth: int  # Distance from entrance
    generated: GeneratedRoom
    entity_id: Optional[str] = None  # ECS entity ID once created
    exits: dict[str, str] = field(default_factory=dict)  # direction -> room_id
    mobs: list[str] = field(default_factory=list)  # Entity IDs of mobs in room
    items: list[str] = field(default_factory=list)  # Entity IDs of items in room
    visited: bool = False


@dataclass
class InstanceConfig:
    """Configuration for instance generation."""

    portal_template_id: str
    theme_id: str
    difficulty: int
    max_rooms: int = 15
    max_depth: int = 5
    mobs_per_room_min: int = 0
    mobs_per_room_max: int = 3
    items_per_room_chance: float = 0.3
    boss_room_depth: int = -1  # -1 means max depth


@dataclass
class Instance:
    """A dungeon instance."""

    instance_id: str
    config: InstanceConfig
    state: InstanceState = InstanceState.CREATING
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Rooms
    rooms: dict[str, InstanceRoom] = field(default_factory=dict)
    entrance_room_id: Optional[str] = None

    # Players currently in instance
    players: set[str] = field(default_factory=set)  # Entity IDs

    # Generation state
    rooms_generated: int = 0
    generation_complete: bool = False


@ray.remote
class InstanceManager:
    """
    Ray actor managing all dungeon instances.

    Handles instance lifecycle:
    1. Creation - Generate entrance room, prepare instance
    2. Expansion - Generate rooms as players explore
    3. Population - Add mobs and items to rooms
    4. Cleanup - Remove instances after timeout

    Usage:
        manager = get_instance_manager()

        # Create instance from portal
        instance_id = await manager.create_instance.remote(portal_template, player_id)

        # Get room for player
        room = await manager.get_or_generate_room.remote(instance_id, direction)

        # Player leaves
        await manager.player_leave.remote(instance_id, player_id)
    """

    def __init__(self, cleanup_interval_s: float = 60.0, instance_timeout_s: float = 300.0):
        self._instances: dict[str, Instance] = {}
        self._cleanup_interval = cleanup_interval_s
        self._instance_timeout = instance_timeout_s
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Map player -> current instance
        self._player_instances: dict[str, str] = {}

        logger.info("InstanceManager initialized")

    # =========================================================================
    # Instance Lifecycle
    # =========================================================================

    async def create_instance(
        self,
        portal_template_id: str,
        theme_id: str,
        difficulty: int,
        player_id: str,
        max_rooms: int = 15,
    ) -> Optional[str]:
        """
        Create a new instance from a portal.

        Generates the entrance room and prepares the instance for exploration.

        Returns:
            Instance ID if successful, None if generation failed
        """
        instance_id = f"inst_{uuid.uuid4().hex[:12]}"

        config = InstanceConfig(
            portal_template_id=portal_template_id,
            theme_id=theme_id,
            difficulty=difficulty,
            max_rooms=max_rooms,
            max_depth=min(max_rooms // 3, 8),
        )

        instance = Instance(
            instance_id=instance_id,
            config=config,
        )

        self._instances[instance_id] = instance

        # Generate entrance room
        entrance = await self._generate_room(
            instance=instance,
            depth=0,
            entrance_direction=None,
        )

        if not entrance:
            logger.error(f"Failed to generate entrance for instance {instance_id}")
            del self._instances[instance_id]
            return None

        instance.entrance_room_id = entrance.room_id
        instance.state = InstanceState.ACTIVE

        # Add player
        await self.player_enter(instance_id, player_id)

        logger.info(f"Created instance {instance_id} (theme: {theme_id}, difficulty: {difficulty})")
        return instance_id

    async def close_instance(self, instance_id: str) -> bool:
        """Close an instance and clean up resources."""
        instance = self._instances.get(instance_id)
        if not instance:
            return False

        if instance.state == InstanceState.CLOSED:
            return True

        instance.state = InstanceState.CLOSING

        # Remove all players
        for player_id in list(instance.players):
            await self.player_leave(instance_id, player_id)

        # TODO: Remove room/mob/item entities from ECS

        instance.state = InstanceState.CLOSED
        del self._instances[instance_id]

        logger.info(f"Closed instance {instance_id}")
        return True

    # =========================================================================
    # Player Management
    # =========================================================================

    async def player_enter(self, instance_id: str, player_id: str) -> bool:
        """Add a player to an instance."""
        instance = self._instances.get(instance_id)
        if not instance or instance.state != InstanceState.ACTIVE:
            return False

        # Leave any existing instance
        if player_id in self._player_instances:
            old_instance = self._player_instances[player_id]
            if old_instance != instance_id:
                await self.player_leave(old_instance, player_id)

        instance.players.add(player_id)
        instance.last_activity = time.time()
        self._player_instances[player_id] = instance_id

        logger.debug(f"Player {player_id} entered instance {instance_id}")
        return True

    async def player_leave(self, instance_id: str, player_id: str) -> bool:
        """Remove a player from an instance."""
        instance = self._instances.get(instance_id)
        if not instance:
            return False

        instance.players.discard(player_id)
        if player_id in self._player_instances:
            del self._player_instances[player_id]

        instance.last_activity = time.time()

        logger.debug(
            f"Player {player_id} left instance {instance_id} "
            f"({len(instance.players)} remaining)"
        )
        return True

    async def get_player_instance(self, player_id: str) -> Optional[str]:
        """Get the instance a player is currently in."""
        return self._player_instances.get(player_id)

    # =========================================================================
    # Room Generation & Navigation
    # =========================================================================

    async def get_entrance_room(self, instance_id: str) -> Optional[InstanceRoom]:
        """Get the entrance room for an instance."""
        instance = self._instances.get(instance_id)
        if not instance or not instance.entrance_room_id:
            return None
        return instance.rooms.get(instance.entrance_room_id)

    async def get_room(self, instance_id: str, room_id: str) -> Optional[InstanceRoom]:
        """Get a specific room in an instance."""
        instance = self._instances.get(instance_id)
        if not instance:
            return None
        return instance.rooms.get(room_id)

    async def get_or_generate_room(
        self,
        instance_id: str,
        from_room_id: str,
        direction: str,
    ) -> Optional[InstanceRoom]:
        """
        Get or generate a room in a direction from another room.

        If the room already exists, returns it. Otherwise generates a new room
        if the instance hasn't reached its room limit.

        Args:
            instance_id: Instance to generate in
            from_room_id: Room the player is coming from
            direction: Direction of travel (north, south, etc.)

        Returns:
            The room in that direction, or None if generation failed/not allowed
        """
        instance = self._instances.get(instance_id)
        if not instance or instance.state != InstanceState.ACTIVE:
            return None

        from_room = instance.rooms.get(from_room_id)
        if not from_room:
            return None

        # Check if room already exists in that direction
        if direction in from_room.exits:
            target_room_id = from_room.exits[direction]
            return instance.rooms.get(target_room_id)

        # Check if we can generate more rooms
        if instance.rooms_generated >= instance.config.max_rooms:
            logger.debug(f"Instance {instance_id} at room limit")
            return None

        # Check if exit is valid based on generated room
        valid_exits = [e.direction.value for e in from_room.generated.exits]
        if direction not in valid_exits:
            return None

        # Generate new room
        entrance_dir = self._opposite_direction(direction)
        new_room = await self._generate_room(
            instance=instance,
            depth=from_room.depth + 1,
            entrance_direction=entrance_dir,
            from_room=from_room,
        )

        if not new_room:
            return None

        # Link rooms bidirectionally
        from_room.exits[direction] = new_room.room_id
        new_room.exits[entrance_dir] = from_room_id

        instance.last_activity = time.time()

        return new_room

    async def _generate_room(
        self,
        instance: Instance,
        depth: int,
        entrance_direction: Optional[str],
        from_room: Optional[InstanceRoom] = None,
    ) -> Optional[InstanceRoom]:
        """Generate a new room for an instance."""
        if not generation_engine_exists():
            logger.error("Generation engine not available")
            return None

        engine = get_generation_engine()

        # Determine room characteristics
        is_boss_room = instance.config.boss_room_depth == depth or (
            instance.config.boss_room_depth == -1 and depth >= instance.config.max_depth
        )
        is_dead_end = depth >= instance.config.max_depth

        # Build context
        context = RoomContext(
            entrance_direction=ExitDirection(entrance_direction) if entrance_direction else None,
            entrance_room_description=(
                from_room.generated.short_description if from_room else None
            ),
            depth_from_portal=depth,
            max_depth=instance.config.max_depth,
            is_dead_end=is_dead_end,
            is_boss_room=is_boss_room,
        )

        # Generate room content
        generated = await engine.get_room.remote(
            instance.config.theme_id,
            context,
            force_generate=is_boss_room,  # Always generate fresh for boss rooms
        )

        if not generated:
            return None

        room_id = f"{instance.instance_id}_room_{len(instance.rooms)}"
        room = InstanceRoom(
            room_id=room_id,
            instance_id=instance.instance_id,
            depth=depth,
            generated=generated,
        )

        instance.rooms[room_id] = room
        instance.rooms_generated += 1

        # Generate mobs for room
        await self._populate_room_mobs(instance, room, is_boss_room)

        # Maybe generate items
        if not is_boss_room:  # Boss rooms get special loot
            await self._populate_room_items(instance, room)

        logger.debug(
            f"Generated room {room_id} at depth {depth} "
            f"(boss: {is_boss_room}, dead_end: {is_dead_end})"
        )

        return room

    async def _populate_room_mobs(
        self, instance: Instance, room: InstanceRoom, is_boss: bool
    ) -> None:
        """Generate and add mobs to a room."""
        if not generation_engine_exists():
            return

        engine = get_generation_engine()

        if is_boss:
            # Generate boss mob
            context = MobContext(
                room_description=room.generated.short_description,
                target_level=instance.config.difficulty + room.depth,
                is_boss=True,
            )
            mob = await engine.get_mob.remote(
                instance.config.theme_id, context, force_generate=True
            )
            if mob:
                # TODO: Create mob entity in ECS and add to room.mobs
                pass
        else:
            # Random number of regular mobs
            import random

            num_mobs = random.randint(
                instance.config.mobs_per_room_min,
                instance.config.mobs_per_room_max,
            )

            for _ in range(num_mobs):
                context = MobContext(
                    room_description=room.generated.short_description,
                    target_level=instance.config.difficulty + room.depth // 2,
                )
                mob = await engine.get_mob.remote(instance.config.theme_id, context)
                if mob:
                    # TODO: Create mob entity in ECS and add to room.mobs
                    pass

    async def _populate_room_items(self, instance: Instance, room: InstanceRoom) -> None:
        """Maybe generate items for a room."""
        import random

        if random.random() > instance.config.items_per_room_chance:
            return

        if not generation_engine_exists():
            return

        engine = get_generation_engine()

        context = ItemContext(
            found_in_room=room.generated.short_description,
            target_level=instance.config.difficulty + room.depth // 2,
            target_rarity="common" if room.depth < 3 else "uncommon",
        )

        item = await engine.get_item.remote(instance.config.theme_id, context)
        if item:
            # TODO: Create item entity in ECS and add to room.items
            pass

    def _opposite_direction(self, direction: str) -> str:
        """Get the opposite direction."""
        opposites = {
            "north": "south",
            "south": "north",
            "east": "west",
            "west": "east",
            "up": "down",
            "down": "up",
        }
        return opposites.get(direction, direction)

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def start_cleanup_loop(self) -> None:
        """Start the background cleanup loop."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Started instance cleanup loop")

    async def stop_cleanup_loop(self) -> None:
        """Stop the background cleanup loop."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped instance cleanup loop")

    async def _cleanup_loop(self) -> None:
        """Background loop that cleans up inactive instances."""
        while self._running:
            try:
                await self._cleanup_inactive_instances()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

            await asyncio.sleep(self._cleanup_interval)

    async def _cleanup_inactive_instances(self) -> None:
        """Clean up instances that have been inactive too long."""
        now = time.time()
        to_close = []

        for instance_id, instance in self._instances.items():
            if instance.state != InstanceState.ACTIVE:
                continue

            # Check if empty and timed out
            if not instance.players:
                idle_time = now - instance.last_activity
                if idle_time > self._instance_timeout:
                    to_close.append(instance_id)
                    logger.info(f"Instance {instance_id} timed out " f"(idle: {idle_time:.0f}s)")

        for instance_id in to_close:
            await self.close_instance(instance_id)

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_instance_info(self, instance_id: str) -> Optional[dict]:
        """Get information about an instance."""
        instance = self._instances.get(instance_id)
        if not instance:
            return None

        return {
            "instance_id": instance.instance_id,
            "theme_id": instance.config.theme_id,
            "difficulty": instance.config.difficulty,
            "state": instance.state.value,
            "created_at": instance.created_at,
            "last_activity": instance.last_activity,
            "rooms_generated": instance.rooms_generated,
            "max_rooms": instance.config.max_rooms,
            "player_count": len(instance.players),
            "players": list(instance.players),
        }

    async def get_stats(self) -> dict:
        """Get overall instance manager statistics."""
        active = sum(1 for i in self._instances.values() if i.state == InstanceState.ACTIVE)
        total_rooms = sum(i.rooms_generated for i in self._instances.values())
        total_players = len(self._player_instances)

        return {
            "total_instances": len(self._instances),
            "active_instances": active,
            "total_rooms_generated": total_rooms,
            "players_in_instances": total_players,
            "cleanup_running": self._running,
        }


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================

INSTANCE_MANAGER_NAME = "instance_manager"
INSTANCE_NAMESPACE = "llmmud"


def start_instance_manager(
    cleanup_interval_s: float = 60.0,
    instance_timeout_s: float = 300.0,
) -> ActorHandle:
    """Start the instance manager actor."""
    actor: ActorHandle = InstanceManager.options(
        name=INSTANCE_MANAGER_NAME,
        namespace=INSTANCE_NAMESPACE,
        lifetime="detached",
    ).remote(
        cleanup_interval_s, instance_timeout_s
    )  # type: ignore[assignment]
    logger.info(f"Started InstanceManager as {INSTANCE_NAMESPACE}/{INSTANCE_MANAGER_NAME}")
    return actor


def get_instance_manager() -> ActorHandle:
    """Get the instance manager actor."""
    return ray.get_actor(INSTANCE_MANAGER_NAME, namespace=INSTANCE_NAMESPACE)


def instance_manager_exists() -> bool:
    """Check if the instance manager exists."""
    try:
        ray.get_actor(INSTANCE_MANAGER_NAME, namespace=INSTANCE_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_instance_manager() -> bool:
    """Stop the instance manager actor."""
    try:
        actor = ray.get_actor(INSTANCE_MANAGER_NAME, namespace=INSTANCE_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped InstanceManager")
        return True
    except ValueError:
        return False
