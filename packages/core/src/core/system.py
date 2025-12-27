"""
System base class for ECS game systems.

Systems process entities that have specific component combinations.
They read from snapshots (for consistency) and write to WriteBuffer
(for atomic commits).

Example:
    @ray.remote
    class CombatSystem(System):
        def __init__(self):
            super().__init__(
                "CombatSystem",
                required_components=["Combat", "Health", "Position"],
                optional_components=["Buff", "Equipment"]
            )

        async def process_entities(self, entities, write_buffer):
            for entity_id, components in entities.items():
                # Process combat logic
                combat = components["Combat"]
                health = components["Health"]
                # ...
                await write_buffer.mutate.remote(
                    "Health", entity_id,
                    lambda h: setattr(h, 'current_hp', h.current_hp - damage)
                )
"""

import abc
import logging
from typing import Dict, List, Optional, Any

import ray
from ray import ObjectRef
from ray.actor import ActorHandle

from .types import EntityId, ComponentData
from .tick import get_tick_coordinator, SystemDefinition

logger = logging.getLogger(__name__)


class System(abc.ABC):
    """
    Base class for ECS systems.

    Systems are the "S" in ECS - they contain the logic that operates
    on entities with specific component combinations.

    Subclasses must implement:
    - process_entities(): The main logic that processes matched entities

    The base class handles:
    - Querying entities from snapshots based on required components
    - Adding optional components when available
    - Integration with TickCoordinator
    """

    def __init__(
        self,
        system_type: str,
        required_components: List[str],
        optional_components: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        priority: int = 0,
    ):
        """
        Initialize the system.

        Args:
            system_type: Unique identifier for this system
            required_components: Components an entity MUST have to be processed
            optional_components: Components to include if present (not required)
            dependencies: Other systems that must run before this one
            priority: Execution priority within same dependency level (lower = earlier)
        """
        self._system_type = system_type
        self._required_components = required_components
        self._optional_components = optional_components or []
        self._dependencies = dependencies or []
        self._priority = priority

        # Stats
        self._ticks_processed: int = 0
        self._entities_processed: int = 0
        self._total_time_ms: float = 0

    @property
    def system_type(self) -> str:
        return self._system_type

    @property
    def required_components(self) -> List[str]:
        return self._required_components

    @property
    def optional_components(self) -> List[str]:
        return self._optional_components

    # =========================================================================
    # Abstract Methods
    # =========================================================================

    @abc.abstractmethod
    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Process all matched entities for this tick.

        Args:
            entities: Dict of entity_id -> {component_type: component_data}
            write_buffer: WriteBuffer actor for queuing writes

        Returns:
            Number of entities processed
        """
        pass

    # =========================================================================
    # Tick Processing
    # =========================================================================

    async def process_tick(
        self, tick_id: int, snapshot_ref: ObjectRef, write_buffer: ActorHandle
    ) -> int:
        """
        Called by TickCoordinator each tick.

        This method:
        1. Retrieves the snapshot from object store
        2. Queries for entities matching required components
        3. Adds optional components if present
        4. Calls process_entities() with the matched entities

        Returns:
            Number of entities processed
        """
        import time

        start = time.time()

        try:
            # Get snapshot from object store (zero-copy on same node)
            snapshots: Dict[str, Dict[EntityId, ComponentData]] = ray.get(snapshot_ref)

            # Query for matching entities from snapshot
            entities = self._query_from_snapshot(snapshots, self._required_components)

            if not entities:
                return 0

            # Add optional components if present
            for entity_id, components in entities.items():
                for opt_type in self._optional_components:
                    if opt_type in snapshots and entity_id in snapshots[opt_type]:
                        components[opt_type] = snapshots[opt_type][entity_id]

            # Let subclass process
            count = await self.process_entities(entities, write_buffer)

            # Update stats
            self._ticks_processed += 1
            self._entities_processed += count
            self._total_time_ms += (time.time() - start) * 1000

            return count

        except Exception as e:
            logger.error(f"Error in {self._system_type}.process_tick: {e}")
            raise

    def _query_from_snapshot(
        self, snapshots: Dict[str, Dict[EntityId, ComponentData]], required: List[str]
    ) -> Dict[EntityId, Dict[str, ComponentData]]:
        """
        Query entities from snapshot data (local operation).

        Finds entities that have ALL required components.
        """
        if not required:
            return {}

        # Check all required components exist in snapshot
        for component_type in required:
            if component_type not in snapshots:
                logger.warning(f"Required component {component_type} not in snapshot")
                return {}

        # Get entities that have all required components
        entity_sets = [set(snapshots[component_type].keys()) for component_type in required]

        # Intersect to find entities with ALL components
        if not entity_sets:
            return {}

        matched_entities = entity_sets[0]
        for entity_set in entity_sets[1:]:
            matched_entities &= entity_set

        # Build result with component data
        result: Dict[EntityId, Dict[str, ComponentData]] = {}
        for entity_id in matched_entities:
            result[entity_id] = {
                component_type: snapshots[component_type][entity_id] for component_type in required
            }

        return result

    # =========================================================================
    # Registration
    # =========================================================================

    def get_definition(self, actor_path: str) -> SystemDefinition:
        """Get a SystemDefinition for registering with TickCoordinator."""
        return SystemDefinition(
            name=self._system_type,
            actor_path=actor_path,
            required_components=self._required_components,
            optional_components=self._optional_components,
            dependencies=self._dependencies,
            priority=self._priority,
        )

    async def register_with_coordinator(self, actor_path: str) -> None:
        """Register this system with the TickCoordinator."""
        coordinator = get_tick_coordinator()
        definition = self.get_definition(actor_path)
        await coordinator.register_system.remote(definition)
        logger.info(f"System {self._system_type} registered at {actor_path}")

    async def unregister_from_coordinator(self) -> None:
        """Unregister this system from the TickCoordinator."""
        coordinator = get_tick_coordinator()
        await coordinator.unregister_system.remote(self._system_type)
        logger.info(f"System {self._system_type} unregistered")

    # =========================================================================
    # Diagnostics
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about this system."""
        return {
            "system_type": self._system_type,
            "required_components": self._required_components,
            "optional_components": self._optional_components,
            "dependencies": self._dependencies,
            "priority": self._priority,
            "ticks_processed": self._ticks_processed,
            "entities_processed": self._entities_processed,
            "total_time_ms": self._total_time_ms,
            "avg_time_ms": (
                self._total_time_ms / self._ticks_processed if self._ticks_processed > 0 else 0
            ),
            "avg_entities": (
                self._entities_processed / self._ticks_processed if self._ticks_processed > 0 else 0
            ),
        }


class TickableMixin(abc.ABC):
    """
    Mixin for actors that need tick notifications.
    Legacy compatibility - prefer using System base class.
    """

    @abc.abstractmethod
    async def tick(self) -> None:
        """Called each tick."""
        pass

    @abc.abstractmethod
    def actor_path(self) -> str:
        """Return the actor's path for registration."""
        pass

    async def subscribe(self) -> None:
        """Subscribe to tick notifications."""
        path = self.actor_path()
        coordinator = get_tick_coordinator()
        await coordinator.register.remote(path)

    async def unsubscribe(self) -> None:
        """Unsubscribe from tick notifications."""
        path = self.actor_path()
        coordinator = get_tick_coordinator()
        await coordinator.unregister.remote(path)
