"""
Region Manager

Ray actor that manages dynamic regions - the LLM-generated transition zones
between static areas. Unlike portal instances, dynamic regions are part of
the overworld coordinate grid and rooms are generated on-demand as players explore.

Key responsibilities:
- Track runtime state for all active regions
- Generate rooms on-demand using GenerationEngine
- Ensure bidirectional exit consistency
- Publish events for region entry/exit
- Manage room lifecycle and cleanup
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
import uuid

import ray
from ray.actor import ActorHandle

from core import (
    EntityId,
    get_event_bus,
    EventScope,
    EventTopic,
    EventTarget,
    GameEvent,
    generate_event_id,
)
from llm import GeneratedRoom, Theme
from llm.prompts import RoomContext

from game.components import (
    Direction,
    SectorType,
    WorldCoordinate,
    RegionState,
    RegionRoomData,
    ExitData,
    PersistenceLevel,
)
from game.world.templates import (
    RegionTemplate,
    RegionThemeTemplate,
    TemplateRegistry,
    get_template_registry,
)

from .engine import get_generation_engine, generation_engine_exists

logger = logging.getLogger(__name__)


# =============================================================================
# Region Event Types
# =============================================================================


@dataclass
class RegionEnterEvent(GameEvent):
    """Event fired when an entity enters a dynamic region."""

    region_id: str = ""
    region_name: str = ""
    entry_coordinate: Optional[WorldCoordinate] = None
    from_static_room: Optional[str] = None

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.REGION_ENTER)


@dataclass
class RegionExitEvent(GameEvent):
    """Event fired when an entity exits a dynamic region."""

    region_id: str = ""
    region_name: str = ""
    exit_coordinate: Optional[WorldCoordinate] = None
    to_static_room: Optional[str] = None

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.REGION_EXIT)


@dataclass
class RoomGeneratedEvent(GameEvent):
    """Event fired when a room is generated in a dynamic region."""

    region_id: str = ""
    room_id: str = ""
    coordinate: Optional[WorldCoordinate] = None
    triggered_by: Optional[EntityId] = None


# =============================================================================
# Region Runtime State
# =============================================================================


@dataclass
class RegionRuntimeState:
    """
    Runtime state for an active dynamic region.

    Tracks generated rooms, player presence, and manages cleanup.
    """

    region_id: str
    template: RegionTemplate
    state: RegionState = field(default_factory=lambda: RegionState(region_id=""))

    # Generated rooms: coordinate tuple -> (room_entity_id, RoomData)
    generated_rooms: Dict[Tuple[int, int, int], Tuple[str, RegionRoomData]] = field(
        default_factory=dict
    )

    # Players currently in region
    players_in_region: Set[str] = field(default_factory=set)

    # Skeleton path for this region (pre-planned route)
    skeleton_path: List[WorldCoordinate] = field(default_factory=list)

    # Cleanup tracking
    last_activity: datetime = field(default_factory=datetime.utcnow)
    cleanup_after: Optional[datetime] = None

    def __post_init__(self):
        self.state = RegionState(region_id=self.region_id)


# =============================================================================
# Region Manager Actor
# =============================================================================


@ray.remote
class RegionManager:
    """
    Ray actor that manages all dynamic regions.

    This actor:
    - Tracks runtime state for each active region
    - Generates rooms on-demand as players explore
    - Ensures coordinate consistency and bidirectional exits
    - Publishes events for region transitions
    - Manages room lifecycle and cleanup

    Usage:
        manager = get_region_manager()
        room_id = await manager.get_or_generate_room.remote(
            region_id, coordinate, entry_direction
        )
    """

    def __init__(self):
        self._regions: Dict[str, RegionRuntimeState] = {}
        self._registry: Optional[TemplateRegistry] = None
        self._cleanup_interval = 60.0  # Check for cleanup every minute
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._stats = {
            "rooms_generated": 0,
            "region_entries": 0,
            "region_exits": 0,
            "cleanup_runs": 0,
        }

        logger.info("RegionManager initialized")

    async def start(self) -> None:
        """Start the region manager and cleanup loop."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("RegionManager started")

    async def stop(self) -> None:
        """Stop the region manager."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("RegionManager stopped")

    def _get_registry(self) -> TemplateRegistry:
        """Get the template registry (lazy load)."""
        if self._registry is None:
            self._registry = get_template_registry()
        return self._registry

    # =========================================================================
    # Region Lifecycle
    # =========================================================================

    async def activate_region(self, region_id: str) -> Optional[RegionRuntimeState]:
        """
        Activate a region and create its runtime state.

        Returns the runtime state or None if template not found.
        """
        if region_id in self._regions:
            return self._regions[region_id]

        registry = self._get_registry()
        template = registry.get_region(region_id)
        if not template:
            logger.error(f"Region template not found: {region_id}")
            return None

        # Create runtime state
        state = RegionRuntimeState(
            region_id=region_id,
            template=template,
        )

        # Plan the skeleton path for this region
        state.skeleton_path = self._plan_skeleton_path(template)

        self._regions[region_id] = state
        logger.info(f"Activated region: {region_id} ({template.name})")
        return state

    async def deactivate_region(self, region_id: str) -> bool:
        """
        Deactivate a region and clean up its rooms.

        Only succeeds if no players are in the region.
        """
        if region_id not in self._regions:
            return False

        state = self._regions[region_id]
        if state.players_in_region:
            logger.warning(
                f"Cannot deactivate region {region_id}: "
                f"{len(state.players_in_region)} players present"
            )
            return False

        # Clean up generated rooms
        for coord, (room_id, _) in state.generated_rooms.items():
            await self._cleanup_room(room_id)

        del self._regions[region_id]
        logger.info(f"Deactivated region: {region_id}")
        return True

    # =========================================================================
    # Room Generation
    # =========================================================================

    async def get_or_generate_room(
        self,
        region_id: str,
        coordinate: WorldCoordinate,
        entry_direction: Optional[Direction] = None,
        triggered_by: Optional[EntityId] = None,
    ) -> Optional[str]:
        """
        Get or generate a room at the given coordinate in a region.

        Args:
            region_id: The region template ID
            coordinate: World coordinate for the room
            entry_direction: Direction player is coming from
            triggered_by: Entity that triggered the generation

        Returns:
            Room entity ID or None if generation failed
        """
        # Ensure region is activated
        state = await self.activate_region(region_id)
        if not state:
            return None

        coord_key = (coordinate.x, coordinate.y, coordinate.z)

        # Return existing room if already generated
        if coord_key in state.generated_rooms:
            room_id, _ = state.generated_rooms[coord_key]
            state.last_activity = datetime.utcnow()
            return room_id

        # Generate new room
        room_data = await self._generate_room(
            state, coordinate, entry_direction, triggered_by
        )
        if not room_data:
            return None

        # Create entity ID for the room
        room_id = f"region_{region_id}_{coordinate.x}_{coordinate.y}_{coordinate.z}"

        # Store in state
        state.generated_rooms[coord_key] = (room_id, room_data)
        state.state.set_room_at(coordinate, room_id)
        state.last_activity = datetime.utcnow()

        # Ensure bidirectional exits
        await self._ensure_bidirectional_exits(state, coordinate, room_id, room_data)

        # Publish event
        await self._publish_room_generated(
            region_id, room_id, coordinate, triggered_by
        )

        self._stats["rooms_generated"] += 1
        logger.debug(f"Generated room at {coordinate} in region {region_id}")

        return room_id

    async def _generate_room(
        self,
        state: RegionRuntimeState,
        coordinate: WorldCoordinate,
        entry_direction: Optional[Direction],
        triggered_by: Optional[EntityId],
    ) -> Optional[RegionRoomData]:
        """Generate a room using the LLM or fallback templates."""
        template = state.template
        theme = template.theme

        # Build context for generation
        adjacent_descriptions = self._get_adjacent_descriptions(state, coordinate)
        required_exits = self._get_required_exits(state, coordinate)
        forbidden_exits = self._get_forbidden_exits(state, coordinate)
        nearest_static, distance = self._get_nearest_static_info(state, coordinate)

        # Determine exits based on skeleton path and connectivity
        exits = self._determine_exits(state, coordinate, entry_direction)

        # Try LLM generation first
        generated_room: Optional[GeneratedRoom] = None
        if generation_engine_exists() and theme:
            try:
                engine = get_generation_engine()

                # Build context
                context = RoomContext(
                    adjacent_rooms=adjacent_descriptions,
                    depth=distance,
                    required_exits=[e.value for e in exits.keys()],
                )

                # Generate
                generated_room = await engine.generate_room.remote(
                    theme.theme_id, context
                )
            except Exception as e:
                logger.warning(f"LLM generation failed, using fallback: {e}")

        # Create room data
        if generated_room:
            room_data = RegionRoomData(
                short_description=generated_room.short_description,
                long_description=generated_room.long_description,
                sector_type=template.primary_sector_type,
                ambient_messages=generated_room.ambient_messages or [],
                region_id=state.region_id,
                coordinate=coordinate,
                generation_context=f"LLM generated for {nearest_static}",
            )
        else:
            # Fallback: simple procedural generation
            room_data = self._generate_fallback_room(
                state, coordinate, nearest_static, distance
            )

        # Set up exits
        room_data.exits = exits

        # Check if this connects to a static room
        self._check_static_connections(state, room_data, coordinate)

        return room_data

    def _generate_fallback_room(
        self,
        state: RegionRuntimeState,
        coordinate: WorldCoordinate,
        nearest_static: str,
        distance: int,
    ) -> RegionRoomData:
        """Generate a simple fallback room when LLM is unavailable."""
        template = state.template
        sector = template.primary_sector_type

        # Sector-based descriptions
        descriptions = {
            SectorType.FOREST: (
                "A Forest Path",
                "You are on a winding path through the forest. Trees loom overhead, their branches filtering the light.",
            ),
            SectorType.HILLS: (
                "Rolling Hills",
                "You traverse the rolling hills. The landscape undulates gently around you.",
            ),
            SectorType.MOUNTAIN: (
                "Mountain Trail",
                "A rocky trail winds through the mountains. The air is thin and crisp.",
            ),
            SectorType.ROAD: (
                "The Road",
                "You are on a well-traveled road. The packed earth shows signs of frequent passage.",
            ),
            SectorType.CAVE: (
                "A Cave Passage",
                "You are in a dark passage underground. The stone walls are cool and damp.",
            ),
        }

        short, long = descriptions.get(
            sector,
            ("A Path", "You are traveling through the wilderness."),
        )

        # Add variation based on distance
        if distance > 5:
            long += " The way forward seems uncertain."

        # Get ambient messages from theme
        ambient = []
        if template.theme:
            ambient = template.theme.ambient_messages[:3] if template.theme.ambient_messages else []

        return RegionRoomData(
            short_description=short,
            long_description=long,
            sector_type=sector,
            ambient_messages=ambient,
            region_id=state.region_id,
            coordinate=coordinate,
            generation_context=f"Fallback for {nearest_static}",
        )

    # =========================================================================
    # Exit Management
    # =========================================================================

    def _determine_exits(
        self,
        state: RegionRuntimeState,
        coordinate: WorldCoordinate,
        entry_direction: Optional[Direction],
    ) -> Dict[str, ExitData]:
        """
        Determine which exits this room should have.

        Uses the skeleton path and connectivity rules to ensure navigability.
        """
        exits: Dict[str, ExitData] = {}
        template = state.template

        # Always allow exit back to where we came from
        if entry_direction:
            opposite = Direction.opposite(entry_direction)
            exits[opposite.value] = ExitData(
                direction=opposite,
                target_coordinate=coordinate.neighbor(opposite),
                leads_to_region=state.region_id,
            )

        # Check skeleton path for required connectivity
        coord_tuple = (coordinate.x, coordinate.y, coordinate.z)
        if state.skeleton_path:
            idx = None
            for i, wp in enumerate(state.skeleton_path):
                if (wp.x, wp.y, wp.z) == coord_tuple:
                    idx = i
                    break

            if idx is not None:
                # Connect to previous waypoint
                if idx > 0:
                    prev_wp = state.skeleton_path[idx - 1]
                    direction = coordinate.direction_to(prev_wp)
                    if direction and direction.value not in exits:
                        exits[direction.value] = ExitData(
                            direction=direction,
                            target_coordinate=prev_wp,
                            leads_to_region=state.region_id,
                        )

                # Connect to next waypoint
                if idx < len(state.skeleton_path) - 1:
                    next_wp = state.skeleton_path[idx + 1]
                    direction = coordinate.direction_to(next_wp)
                    if direction and direction.value not in exits:
                        exits[direction.value] = ExitData(
                            direction=direction,
                            target_coordinate=next_wp,
                            leads_to_region=state.region_id,
                        )

        # Check for endpoint connections to static rooms
        for endpoint in template.endpoints:
            if endpoint.coordinate == coordinate:
                # This room connects to a static room
                exits[endpoint.direction.value] = ExitData(
                    direction=endpoint.direction,
                    target_static_room=endpoint.static_room_id,
                )

        # Add branching exits based on branch_chance
        if random.random() < template.branch_chance:
            available_directions = [
                d for d in Direction
                if d.value not in exits
                and d not in (Direction.UP, Direction.DOWN)  # No vertical branches
            ]
            if available_directions:
                branch_dir = random.choice(available_directions)
                exits[branch_dir.value] = ExitData(
                    direction=branch_dir,
                    target_coordinate=coordinate.neighbor(branch_dir),
                    leads_to_region=state.region_id,
                )

        return exits

    async def _ensure_bidirectional_exits(
        self,
        state: RegionRuntimeState,
        coordinate: WorldCoordinate,
        room_id: str,
        room_data: RegionRoomData,
    ) -> None:
        """
        Ensure all adjacent rooms have exits back to this room.

        Maintains bidirectional consistency in the region.
        """
        for direction, exit_data in room_data.exits.items():
            if not exit_data.target_coordinate:
                continue

            target_coord = exit_data.target_coordinate
            target_key = (target_coord.x, target_coord.y, target_coord.z)

            if target_key not in state.generated_rooms:
                continue

            # Get the adjacent room
            adj_room_id, adj_room_data = state.generated_rooms[target_key]

            # Check if it has an exit back to us
            opposite_dir = Direction.opposite(Direction(direction))
            if opposite_dir.value not in adj_room_data.exits:
                # Add the missing exit
                adj_room_data.exits[opposite_dir.value] = ExitData(
                    direction=opposite_dir,
                    target_coordinate=coordinate,
                    leads_to_region=state.region_id,
                )
                logger.debug(
                    f"Added bidirectional exit: {target_coord} -> {coordinate}"
                )

    def _check_static_connections(
        self,
        state: RegionRuntimeState,
        room_data: RegionRoomData,
        coordinate: WorldCoordinate,
    ) -> None:
        """Check and set up connections to static rooms."""
        for endpoint in state.template.endpoints:
            if endpoint.coordinate == coordinate:
                room_data.connects_to_static = endpoint.static_room_id
                room_data.connects_direction = endpoint.direction

    # =========================================================================
    # Path Planning
    # =========================================================================

    def _plan_skeleton_path(self, template: RegionTemplate) -> List[WorldCoordinate]:
        """
        Plan the skeleton path for a region.

        The skeleton path is the main navigable route through the region,
        connecting all endpoints through any required waypoints.
        """
        if len(template.endpoints) < 2:
            return []

        path: List[WorldCoordinate] = []

        # Start from first endpoint
        current = template.endpoints[0].coordinate
        path.append(current)

        # Include waypoints if any
        waypoints = [wp.coordinate for wp in template.waypoints if wp.is_required]

        # Add path through waypoints to second endpoint
        target = template.endpoints[1].coordinate if len(template.endpoints) > 1 else current

        # Simple path: direct route with waypoints
        for wp in waypoints:
            # Generate intermediate points to waypoint
            while current != wp:
                direction = current.direction_to(wp)
                if direction:
                    current = current.neighbor(direction)
                    path.append(current)
                else:
                    break

        # Continue to target
        while current != target:
            direction = current.direction_to(target)
            if direction:
                current = current.neighbor(direction)
                path.append(current)
            else:
                break

        logger.debug(f"Planned skeleton path with {len(path)} points")
        return path

    # =========================================================================
    # Context Helpers
    # =========================================================================

    def _get_adjacent_descriptions(
        self, state: RegionRuntimeState, coordinate: WorldCoordinate
    ) -> str:
        """Get descriptions of adjacent rooms for context."""
        descriptions = []
        for direction in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
            neighbor = coordinate.neighbor(direction)
            key = (neighbor.x, neighbor.y, neighbor.z)
            if key in state.generated_rooms:
                _, room_data = state.generated_rooms[key]
                descriptions.append(f"{direction.value}: {room_data.short_description}")
        return "; ".join(descriptions) if descriptions else "No adjacent rooms explored"

    def _get_required_exits(
        self, state: RegionRuntimeState, coordinate: WorldCoordinate
    ) -> str:
        """Get list of required exit directions."""
        required = []
        for endpoint in state.template.endpoints:
            if endpoint.coordinate == coordinate:
                required.append(endpoint.direction.value)
        return ", ".join(required) if required else "none"

    def _get_forbidden_exits(
        self, state: RegionRuntimeState, coordinate: WorldCoordinate
    ) -> str:
        """Get list of forbidden exit directions (blocked by generation limits)."""
        # Check if we've hit max rooms
        if state.state.rooms_generated >= state.template.max_rooms:
            # Only allow exits to existing rooms
            forbidden = []
            for direction in Direction:
                neighbor = coordinate.neighbor(direction)
                key = (neighbor.x, neighbor.y, neighbor.z)
                if key not in state.generated_rooms:
                    forbidden.append(direction.value)
            return ", ".join(forbidden)
        return "none"

    def _get_nearest_static_info(
        self, state: RegionRuntimeState, coordinate: WorldCoordinate
    ) -> Tuple[str, int]:
        """Get info about the nearest static room."""
        min_distance = float("inf")
        nearest = "unknown"

        for endpoint in state.template.endpoints:
            distance = coordinate.distance_to(endpoint.coordinate)
            if distance < min_distance:
                min_distance = distance
                nearest = endpoint.static_room_id

        return nearest, int(min_distance)

    # =========================================================================
    # Player Tracking
    # =========================================================================

    async def player_enter_region(
        self, region_id: str, player_id: str, coordinate: WorldCoordinate
    ) -> bool:
        """Track a player entering a region."""
        state = await self.activate_region(region_id)
        if not state:
            return False

        state.players_in_region.add(player_id)
        state.state.player_enter(player_id)
        state.cleanup_after = None  # Cancel any pending cleanup
        self._stats["region_entries"] += 1

        # Publish event
        try:
            bus = get_event_bus()
            event = RegionEnterEvent(
                event_id=generate_event_id(),
                topic=EventTopic.REGION_ENTER,
                target=EventTarget.entity(EntityId(player_id, "player")),
                source_entity=EntityId(player_id, "player"),
                region_id=region_id,
                region_name=state.template.name,
                entry_coordinate=coordinate,
            )
            await bus.publish.remote(event)
        except Exception as e:
            logger.warning(f"Failed to publish region enter event: {e}")

        return True

    async def player_exit_region(
        self, region_id: str, player_id: str, coordinate: WorldCoordinate
    ) -> bool:
        """Track a player exiting a region."""
        if region_id not in self._regions:
            return False

        state = self._regions[region_id]
        state.players_in_region.discard(player_id)
        state.state.player_leave(player_id)
        state.last_activity = datetime.utcnow()
        self._stats["region_exits"] += 1

        # Schedule cleanup if region is now empty
        if state.state.is_empty():
            state.cleanup_after = datetime.utcnow() + timedelta(minutes=5)

        # Publish event
        try:
            bus = get_event_bus()
            event = RegionExitEvent(
                event_id=generate_event_id(),
                topic=EventTopic.REGION_EXIT,
                target=EventTarget.entity(EntityId(player_id, "player")),
                source_entity=EntityId(player_id, "player"),
                region_id=region_id,
                region_name=state.template.name,
                exit_coordinate=coordinate,
            )
            await bus.publish.remote(event)
        except Exception as e:
            logger.warning(f"Failed to publish region exit event: {e}")

        return True

    # =========================================================================
    # Room Queries
    # =========================================================================

    async def get_room_at(
        self, region_id: str, coordinate: WorldCoordinate
    ) -> Optional[Tuple[str, RegionRoomData]]:
        """Get room info at a coordinate if it exists."""
        if region_id not in self._regions:
            return None

        state = self._regions[region_id]
        key = (coordinate.x, coordinate.y, coordinate.z)
        return state.generated_rooms.get(key)

    async def get_room_by_id(
        self, region_id: str, room_id: str
    ) -> Optional[RegionRoomData]:
        """Get room data by room entity ID."""
        if region_id not in self._regions:
            return None

        state = self._regions[region_id]
        for _, (rid, room_data) in state.generated_rooms.items():
            if rid == room_id:
                return room_data
        return None

    async def get_region_info(self, region_id: str) -> Optional[Dict]:
        """Get information about a region's runtime state."""
        if region_id not in self._regions:
            return None

        state = self._regions[region_id]
        return {
            "region_id": region_id,
            "name": state.template.name,
            "rooms_generated": len(state.generated_rooms),
            "max_rooms": state.template.max_rooms,
            "players_in_region": list(state.players_in_region),
            "skeleton_path_length": len(state.skeleton_path),
            "last_activity": state.last_activity.isoformat(),
        }

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def _cleanup_loop(self) -> None:
        """Background loop that cleans up empty regions."""
        while self._running:
            try:
                await self._run_cleanup()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

            await asyncio.sleep(self._cleanup_interval)

    async def _run_cleanup(self) -> None:
        """Check and clean up regions scheduled for removal."""
        now = datetime.utcnow()
        to_remove = []

        for region_id, state in self._regions.items():
            if state.cleanup_after and now > state.cleanup_after:
                if state.state.is_empty():
                    to_remove.append(region_id)
                else:
                    # Players returned, cancel cleanup
                    state.cleanup_after = None

        for region_id in to_remove:
            await self.deactivate_region(region_id)
            self._stats["cleanup_runs"] += 1

    async def _cleanup_room(self, room_id: str) -> None:
        """Clean up a room entity."""
        # TODO: Remove room entity from ECS
        logger.debug(f"Cleaned up room: {room_id}")

    # =========================================================================
    # Events
    # =========================================================================

    async def _publish_room_generated(
        self,
        region_id: str,
        room_id: str,
        coordinate: WorldCoordinate,
        triggered_by: Optional[EntityId],
    ) -> None:
        """Publish a room generated event."""
        try:
            bus = get_event_bus()
            event = RoomGeneratedEvent(
                event_id=generate_event_id(),
                topic=EventTopic.ROOM_CHANGE,
                target=EventTarget.region(region_id),
                source_entity=triggered_by,
                region_id=region_id,
                room_id=room_id,
                coordinate=coordinate,
                triggered_by=triggered_by,
            )
            await bus.publish.remote(event)
        except Exception as e:
            logger.warning(f"Failed to publish room generated event: {e}")

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> Dict:
        """Get region manager statistics."""
        return {
            **self._stats,
            "active_regions": len(self._regions),
            "total_rooms": sum(
                len(s.generated_rooms) for s in self._regions.values()
            ),
            "total_players_in_regions": sum(
                len(s.players_in_region) for s in self._regions.values()
            ),
        }


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================

REGION_MANAGER_ACTOR = "region_manager"
REGION_MANAGER_NAMESPACE = "llmmud"


def start_region_manager() -> ActorHandle:
    """Start the region manager actor."""
    actor: ActorHandle = RegionManager.options(
        name=REGION_MANAGER_ACTOR,
        namespace=REGION_MANAGER_NAMESPACE,
        lifetime="detached",
    ).remote()
    logger.info(f"Started RegionManager as {REGION_MANAGER_NAMESPACE}/{REGION_MANAGER_ACTOR}")
    return actor


def get_region_manager() -> ActorHandle:
    """Get the region manager actor."""
    return ray.get_actor(REGION_MANAGER_ACTOR, namespace=REGION_MANAGER_NAMESPACE)


def region_manager_exists() -> bool:
    """Check if the region manager exists."""
    try:
        ray.get_actor(REGION_MANAGER_ACTOR, namespace=REGION_MANAGER_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_region_manager() -> bool:
    """Stop the region manager actor."""
    try:
        actor = ray.get_actor(REGION_MANAGER_ACTOR, namespace=REGION_MANAGER_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped RegionManager")
        return True
    except ValueError:
        return False
