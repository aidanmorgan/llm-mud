"""
WriteBuffer actor for transactional writes during tick processing.

Collects all component modifications during a tick, then commits them
atomically at the end. This ensures:
- Read isolation: systems read from snapshot, not affected by other systems' writes
- Write ordering: all writes applied after all systems complete
- Atomicity: partial failures can be detected and handled
"""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Set, Any, Optional, Tuple

import ray
from ray import ObjectRef
from ray.actor import ActorHandle

from .types import EntityId, ComponentData
from .component import get_component_actor
from .entity_index import get_entity_index
from . import constants

logger = logging.getLogger(__name__)


@dataclass
class WriteOperation:
    """Represents a pending write operation."""

    operation_type: str  # 'create', 'write', 'mutate', 'delete'
    entity: EntityId
    component_type: str
    data: Optional[ComponentData] = None
    mutation: Optional[Callable[[ComponentData], None]] = None


@ray.remote
class WriteBuffer:
    """
    Collects writes during a tick, then commits atomically.

    Provides isolation: systems see consistent reads from snapshot,
    writes don't interfere with each other during tick processing.

    Usage:
        buffer = WriteBuffer.remote(tick_id)
        await buffer.write.remote("Health", entity, new_health_data)
        await buffer.mutate.remote("Combat", entity, lambda c: c.target = None)
        await buffer.commit.remote()
    """

    def __init__(self, tick_id: int):
        self._tick_id = tick_id
        self._committed = False

        # Pending writes by component type
        # component_type -> entity_id -> ComponentData
        self._pending_writes: Dict[str, Dict[EntityId, ComponentData]] = defaultdict(dict)

        # Pending mutations by component type
        # component_type -> entity_id -> list of mutations
        self._pending_mutations: Dict[str, Dict[EntityId, List[Callable]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Pending deletes by component type
        # component_type -> set of entity_ids
        self._pending_deletes: Dict[str, Set[EntityId]] = defaultdict(set)

        # Pending creates (new entities with components)
        # component_type -> entity_id -> ComponentData
        self._pending_creates: Dict[str, Dict[EntityId, ComponentData]] = defaultdict(dict)

        # Track new entities for EntityIndex updates
        self._new_entity_components: Dict[EntityId, Set[str]] = defaultdict(set)

        # Track deleted entity-component pairs for EntityIndex updates
        self._deleted_entity_components: List[Tuple[EntityId, str]] = []

        logger.debug(f"WriteBuffer created for tick {tick_id}")

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def create(self, component_type: str, entity: EntityId, data: ComponentData) -> None:
        """
        Queue creation of a new component.
        Use when adding a component to an entity that doesn't have it.
        """
        if self._committed:
            raise RuntimeError("Cannot write to committed buffer")

        self._pending_creates[component_type][entity] = data
        self._new_entity_components[entity].add(component_type)

    async def write(self, component_type: str, entity: EntityId, data: ComponentData) -> None:
        """
        Queue a complete write (overwrites existing).
        Use when you have the full component data to write.
        """
        if self._committed:
            raise RuntimeError("Cannot write to committed buffer")

        self._pending_writes[component_type][entity] = data

    async def mutate(
        self,
        component_type: str,
        entity: EntityId,
        mutation: Callable[[ComponentData], None],
    ) -> None:
        """
        Queue a mutation to be applied at commit time.
        Use when you want to modify specific fields without full data.

        Note: Multiple mutations to the same entity are applied in order.
        """
        if self._committed:
            raise RuntimeError("Cannot write to committed buffer")

        self._pending_mutations[component_type][entity].append(mutation)

    async def delete(self, component_type: str, entity: EntityId) -> None:
        """
        Queue a component deletion.
        """
        if self._committed:
            raise RuntimeError("Cannot write to committed buffer")

        self._pending_deletes[component_type].add(entity)
        self._deleted_entity_components.append((entity, component_type))

    async def delete_entity(self, entity: EntityId, component_types: List[str]) -> None:
        """
        Queue deletion of all specified components for an entity.
        Use when removing an entity entirely.
        """
        for component_type in component_types:
            await self.delete(component_type, entity)

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def create_batch(
        self, component_type: str, entities_data: Dict[EntityId, ComponentData]
    ) -> None:
        """Queue multiple component creations."""
        for entity, data in entities_data.items():
            await self.create(component_type, entity, data)

    async def write_batch(
        self, component_type: str, entities_data: Dict[EntityId, ComponentData]
    ) -> None:
        """Queue multiple writes."""
        for entity, data in entities_data.items():
            await self.write(component_type, entity, data)

    async def mutate_batch(
        self,
        component_type: str,
        entities_mutations: List[Tuple[EntityId, Callable[[ComponentData], None]]],
    ) -> None:
        """Queue multiple mutations."""
        for entity, mutation in entities_mutations:
            await self.mutate(component_type, entity, mutation)

    async def delete_batch(self, component_type: str, entities: List[EntityId]) -> None:
        """Queue multiple deletions."""
        for entity in entities:
            await self.delete(component_type, entity)

    # =========================================================================
    # Query Pending State
    # =========================================================================

    async def has_pending_write(self, component_type: str, entity: EntityId) -> bool:
        """Check if there's a pending write for this entity-component."""
        return (
            entity in self._pending_writes.get(component_type, {})
            or entity in self._pending_creates.get(component_type, {})
            or entity in self._pending_mutations.get(component_type, {})
        )

    async def is_pending_delete(self, component_type: str, entity: EntityId) -> bool:
        """Check if this entity-component is marked for deletion."""
        return entity in self._pending_deletes.get(component_type, set())

    async def get_pending_stats(self) -> Dict[str, Any]:
        """Get statistics about pending operations."""
        return {
            "tick_id": self._tick_id,
            "committed": self._committed,
            "pending_creates": sum(len(d) for d in self._pending_creates.values()),
            "pending_writes": sum(len(d) for d in self._pending_writes.values()),
            "pending_mutations": sum(
                sum(len(m) for m in d.values()) for d in self._pending_mutations.values()
            ),
            "pending_deletes": sum(len(s) for s in self._pending_deletes.values()),
            "new_entities": len(self._new_entity_components),
        }

    # =========================================================================
    # Commit
    # =========================================================================

    async def commit(self) -> Dict[str, Dict[str, int]]:
        """
        Commit all pending operations to component actors.

        Returns stats: {component_type: {operation: count}}
        """
        if self._committed:
            raise RuntimeError("Buffer already committed")

        self._committed = True
        stats: Dict[str, Dict[str, int]] = {}

        # Collect all unique component types
        all_types: Set[str] = set()
        all_types.update(self._pending_creates.keys())
        all_types.update(self._pending_writes.keys())
        all_types.update(self._pending_mutations.keys())
        all_types.update(self._pending_deletes.keys())

        # Commit to each component actor
        commit_refs: List[Tuple[str, ObjectRef]] = []

        for component_type in all_types:
            operations = {
                "creates": self._pending_creates.get(component_type, {}),
                "writes": self._pending_writes.get(component_type, {}),
                "mutations": dict(self._pending_mutations.get(component_type, {})),
                "deletes": self._pending_deletes.get(component_type, set()),
            }

            try:
                actor = get_component_actor(component_type)
                ref = actor.apply_commit.remote(operations)
                commit_refs.append((component_type, ref))
            except Exception as e:
                logger.error(f"Error getting actor for {component_type}: {e}")
                stats[component_type] = {"error": 1}

        # Wait for all commits
        for component_type, ref in commit_refs:
            try:
                result = ray.get(ref, timeout=constants.COMMIT_TIMEOUT_S)
                stats[component_type] = result
            except Exception as e:
                logger.error(f"Error committing {component_type}: {e}")
                stats[component_type] = {"error": 1}

        # Update EntityIndex
        await self._update_entity_index()

        logger.debug(f"WriteBuffer committed for tick {self._tick_id}: {stats}")
        return stats

    async def _update_entity_index(self) -> None:
        """Update the EntityIndex with new and deleted entity-component pairs."""
        try:
            entity_index = get_entity_index()

            # Register new entity-component pairs
            if self._new_entity_components:
                registrations = [
                    (entity, component_type)
                    for entity, component_types in self._new_entity_components.items()
                    for component_type in component_types
                ]
                if registrations:
                    await entity_index.register_many.remote(registrations)

            # Unregister deleted pairs
            for entity, component_type in self._deleted_entity_components:
                await entity_index.unregister.remote(entity, component_type)

        except Exception as e:
            logger.error(f"Error updating EntityIndex: {e}")

    # =========================================================================
    # Rollback (for error handling)
    # =========================================================================

    async def discard(self) -> None:
        """
        Discard all pending operations without committing.
        Use when an error occurs and you want to abort the tick.
        """
        if self._committed:
            raise RuntimeError("Cannot discard committed buffer")

        self._pending_creates.clear()
        self._pending_writes.clear()
        self._pending_mutations.clear()
        self._pending_deletes.clear()
        self._new_entity_components.clear()
        self._deleted_entity_components.clear()

        logger.debug(f"WriteBuffer discarded for tick {self._tick_id}")


def create_write_buffer(tick_id: int) -> ActorHandle:
    """
    Create a new WriteBuffer actor for a tick.

    Uses UUID in the name to prevent race conditions if the same tick_id
    is somehow used concurrently (defensive programming).
    """
    buffer_id = uuid.uuid4().hex[:8]
    name = f"llmmud/write_buffer/{tick_id}_{buffer_id}"
    actor: ActorHandle = WriteBuffer.options(
        name=name, namespace=constants.NAMESPACE, get_if_exists=False
    ).remote(
        tick_id
    )  # type: ignore[assignment]
    return actor


def destroy_write_buffer(buffer: ActorHandle) -> None:
    """Destroy a WriteBuffer actor after use."""
    try:
        ray.kill(buffer)
    except Exception as e:
        logger.warning(f"Error destroying write buffer: {e}")
