"""
Component actors for the ECS system.

Each component type is its own Ray actor, storing all instances of that component.
This enables distributed storage while maintaining efficient batch operations.
"""

import copy
import logging
from typing import Callable, Dict, List, Optional, Set, Any, Tuple

import ray
from ray import ObjectRef
from ray.actor import ActorHandle

from .types import EntityId, ComponentData, SnapshotMetadata
from . import constants

logger = logging.getLogger(__name__)


def component_actor_path(component_type: str) -> str:
    """Get the actor path for a component type."""
    return f"{constants.COMPONENT_ACTOR_PREFIX}/{component_type}"


def get_component_actor(component_type: str) -> ActorHandle:
    """Get the actor handle for a component type."""
    path = component_actor_path(component_type)
    return ray.get_actor(path, namespace=constants.NAMESPACE)


@ray.remote
class Component:
    """
    Ray actor storing all instances of a single component type.

    Features:
    - Batch queries for efficient cross-entity operations
    - Snapshots for consistent reads during tick processing
    - Filtered queries with predicates
    - Atomic batch updates
    """

    def __init__(self, component_type: str, factory: Callable[[EntityId], ComponentData]):
        self.component_type = component_type
        self.factory = factory
        self.components: Dict[EntityId, ComponentData] = {}

        # Track the last tick_id for versioning
        self._last_tick_id: int = 0

        logger.info(f"Component actor created for type: {component_type}")

    # =========================================================================
    # CRUD Operations (existing functionality)
    # =========================================================================

    async def create(
        self, entity: EntityId, callback: Optional[Callable[[ComponentData], None]] = None
    ) -> EntityId:
        """Create a new component instance for an entity."""
        if entity in self.components:
            raise ValueError(f"Entity {entity} already has component {self.component_type}")

        inst: ComponentData = self.factory(entity)

        if callback:
            callback(inst)

        self.components[entity] = inst
        return entity

    async def get(self, entity: EntityId) -> Optional[ComponentData]:
        """Get a single component by entity ID."""
        return self.components.get(entity)

    async def get_all(self) -> Dict[EntityId, ComponentData]:
        """Get all components (deep copy for safety)."""
        return copy.deepcopy(self.components)

    async def delete(self, entity: EntityId) -> bool:
        """Delete a component. Returns True if it existed."""
        if entity in self.components:
            del self.components[entity]
            return True
        return False

    async def apply(
        self, entity: EntityId, callback: Callable[[ComponentData], None]
    ) -> Optional[EntityId]:
        """Apply a mutation to a single entity's component."""
        if entity in self.components:
            callback(self.components[entity])
            return entity
        return None

    async def apply_all(
        self, entities: List[EntityId], callback: Callable[[ComponentData], None]
    ) -> List[EntityId]:
        """Apply a mutation to multiple entities."""
        # If no entities specified, apply to all
        target_entities = entities if entities else list(self.components.keys())

        updated: List[EntityId] = []
        for entity in target_entities:
            if entity in self.components:
                callback(self.components[entity])
                updated.append(entity)

        return updated

    async def get_entities(self) -> Set[EntityId]:
        """
        Get all entity IDs that have this component.
        Useful for join operations - returns just IDs, not data.
        """
        return set(self.components.keys())

    async def get_many(self, entities: List[EntityId]) -> Dict[EntityId, ComponentData]:
        """
        Batch get - retrieve multiple components in one call.
        More efficient than multiple get() calls.
        """
        return {
            entity: copy.deepcopy(self.components[entity])
            for entity in entities
            if entity in self.components
        }

    async def get_where(
        self, predicate: Callable[[ComponentData], bool]
    ) -> Dict[EntityId, ComponentData]:
        """
        Filter components by predicate.
        Example: get all entities where health < max_health * 0.5

        Note: Predicate is serialized via cloudpickle - keep simple!
        """
        return {
            entity: copy.deepcopy(component)
            for entity, component in self.components.items()
            if predicate(component)
        }

    async def get_entities_where(self, predicate: Callable[[ComponentData], bool]) -> Set[EntityId]:
        """
        Get only entity IDs matching predicate (smaller payload).
        Use when you only need to know which entities match, not their data.
        """
        return {entity for entity, component in self.components.items() if predicate(component)}

    async def count(self) -> int:
        """Get the number of component instances."""
        return len(self.components)

    async def exists(self, entity: EntityId) -> bool:
        """Check if an entity has this component."""
        return entity in self.components

    async def exists_many(self, entities: List[EntityId]) -> Dict[EntityId, bool]:
        """Check existence for multiple entities."""
        return {entity: entity in self.components for entity in entities}

    # =========================================================================
    # Snapshot Operations (for tick consistency)
    # =========================================================================

    async def get_snapshot(
        self, tick_id: int
    ) -> Tuple[SnapshotMetadata, Dict[EntityId, ComponentData]]:
        """
        Return a versioned snapshot of all components.
        Used for read consistency during a tick - systems read from this snapshot.

        Returns:
            Tuple of (metadata, deep_copy of components)
        """
        self._last_tick_id = tick_id

        metadata = SnapshotMetadata(
            tick_id=tick_id,
            component_type=self.component_type,
            entity_count=len(self.components),
        )

        # Deep copy to ensure immutability of snapshot
        snapshot = copy.deepcopy(self.components)

        return (metadata, snapshot)

    async def get_snapshot_for_entities(
        self, tick_id: int, entities: List[EntityId]
    ) -> Tuple[SnapshotMetadata, Dict[EntityId, ComponentData]]:
        """
        Get a snapshot for specific entities only.
        More efficient when you know which entities you need.
        """
        self._last_tick_id = tick_id

        snapshot = {
            entity: copy.deepcopy(self.components[entity])
            for entity in entities
            if entity in self.components
        }

        metadata = SnapshotMetadata(
            tick_id=tick_id,
            component_type=self.component_type,
            entity_count=len(snapshot),
        )

        return (metadata, snapshot)

    # =========================================================================
    # Batch Write Operations (for WriteBuffer commits)
    # =========================================================================

    async def apply_batch(
        self, updates: List[Tuple[EntityId, Callable[[ComponentData], None]]]
    ) -> List[EntityId]:
        """
        Apply multiple mutations in a single actor call.
        More efficient than multiple apply() calls.
        """
        updated = []
        for entity, callback in updates:
            if entity in self.components:
                callback(self.components[entity])
                updated.append(entity)
        return updated

    async def set_many(self, data: Dict[EntityId, ComponentData]) -> int:
        """
        Bulk set - used for WriteBuffer commits.
        Overwrites existing components.
        """
        self.components.update(data)
        return len(data)

    async def delete_many(self, entities: List[EntityId]) -> int:
        """Delete multiple components at once."""
        deleted = 0
        for entity in entities:
            if entity in self.components:
                del self.components[entity]
                deleted += 1
        return deleted

    async def apply_commit(self, operations: Dict[str, Any]) -> Dict[str, int]:
        """
        Apply a batch of operations from WriteBuffer.

        Operations dict contains:
        - 'creates': Dict[EntityId, ComponentData] - new components
        - 'writes': Dict[EntityId, ComponentData] - overwrites
        - 'mutations': Dict[EntityId, List[Callable]] - callbacks to apply
        - 'deletes': Set[EntityId] - components to remove

        Returns stats about what was applied.
        """
        stats = {"creates": 0, "writes": 0, "mutations": 0, "deletes": 0}

        # Process creates first
        creates = operations.get("creates", {})
        for entity, data in creates.items():
            if entity not in self.components:
                self.components[entity] = data
                stats["creates"] += 1

        # Process writes (overwrites)
        writes = operations.get("writes", {})
        for entity, data in writes.items():
            self.components[entity] = data
            stats["writes"] += 1

        # Process mutations
        mutations = operations.get("mutations", {})
        for entity, callbacks in mutations.items():
            if entity in self.components:
                for callback in callbacks:
                    callback(self.components[entity])
                stats["mutations"] += 1

        # Process deletes last
        deletes = operations.get("deletes", set())
        for entity in deletes:
            if entity in self.components:
                del self.components[entity]
                stats["deletes"] += 1

        return stats

    # =========================================================================
    # Diagnostics
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about this component actor."""
        return {
            "component_type": self.component_type,
            "entity_count": len(self.components),
            "last_tick_id": self._last_tick_id,
        }


@ray.remote
class ComponentEngine:
    """
    Registry and factory for component actors.

    Manages the lifecycle of Component actors and provides
    convenience methods for operations across components.
    """

    def __init__(self):
        # component_type -> actor_path
        self.components: Dict[str, str] = {}
        logger.info("ComponentEngine initialized")

    async def register_component(
        self, component_type: str, factory: Callable[[EntityId], ComponentData]
    ) -> str:
        """
        Register a new component type, creating its actor.

        Returns the actor path.
        """
        path = component_actor_path(component_type)

        if component_type in self.components:
            logger.warning(f"Component {component_type} already registered, returning existing")
            return path

        # Create the component actor
        Component.options(name=path, namespace=constants.NAMESPACE, get_if_exists=True).remote(
            component_type, factory
        )

        self.components[component_type] = path
        logger.info(f"Registered component: {component_type} at {path}")

        return path

    async def unregister_component(self, component_type: str) -> bool:
        """Unregister and kill a component actor."""
        if component_type not in self.components:
            return False

        try:
            actor = get_component_actor(component_type)
            ray.kill(actor)
        except Exception as e:
            logger.warning(f"Error killing component actor {component_type}: {e}")

        del self.components[component_type]
        return True

    async def get_registered_components(self) -> List[str]:
        """Get list of all registered component types."""
        return list(self.components.keys())

    async def get_component_actor_path(self, component_type: str) -> Optional[str]:
        """Get the actor path for a component type."""
        return self.components.get(component_type)

    # =========================================================================
    # Convenience methods that delegate to component actors
    # =========================================================================

    async def create(
        self,
        component_type: str,
        entity: EntityId,
        callback: Optional[Callable[[ComponentData], None]] = None,
    ) -> ObjectRef:
        """Create a component instance."""
        actor = get_component_actor(component_type)
        return actor.create.remote(entity, callback)  # type: ignore[return-value]

    async def get(self, component_type: str, entity: EntityId) -> ObjectRef:
        """Get a component instance."""
        actor = get_component_actor(component_type)
        return actor.get.remote(entity)  # type: ignore[return-value]

    async def delete(self, component_type: str, entity: EntityId) -> ObjectRef:
        """Delete a component instance."""
        actor = get_component_actor(component_type)
        return actor.delete.remote(entity)  # type: ignore[return-value]

    async def get_all_snapshots(self, tick_id: int) -> Dict[str, ObjectRef]:
        """
        Get snapshots from all registered components.
        Returns dict of component_type -> ObjectRef of snapshot.
        """
        refs = {}
        for component_type in self.components:
            actor = get_component_actor(component_type)
            refs[component_type] = actor.get_snapshot.remote(tick_id)
        return refs

    async def get_stats(self) -> Dict[str, Any]:
        """Get stats from all component actors."""
        stats = {
            "registered_components": list(self.components.keys()),
            "component_count": len(self.components),
        }
        return stats
