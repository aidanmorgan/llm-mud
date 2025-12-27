"""
EntityIndex actor for O(1) entity-component lookups.

Maintains a bidirectional index:
- entity -> set of component types it has
- component_type -> set of entity IDs

This enables efficient join queries without querying all component actors.
"""

import logging
from collections import defaultdict
from typing import Dict, Set, List, Optional, Any

import ray
from ray.actor import ActorHandle

from .types import EntityId
from . import constants

logger = logging.getLogger(__name__)


@ray.remote
class EntityIndex:
    """
    Central index mapping entities to their components.

    This actor enables O(1) lookups for:
    - Which components does entity X have?
    - Which entities have component type Y?
    - Which entities have ALL of components [A, B, C]?
    - Which entities have ANY of components [A, B, C]?
    """

    def __init__(self):
        # entity_id -> set of component types it has
        self._entity_components: Dict[EntityId, Set[str]] = defaultdict(set)

        # component_type -> set of entity_ids
        self._component_entities: Dict[str, Set[EntityId]] = defaultdict(set)

        # Track entity metadata
        self._entity_types: Dict[EntityId, str] = {}

        logger.info("EntityIndex initialized")

    # =========================================================================
    # Registration / Deregistration
    # =========================================================================

    async def register(self, entity: EntityId, component_type: str) -> None:
        """Register that an entity has a component."""
        self._entity_components[entity].add(component_type)
        self._component_entities[component_type].add(entity)
        self._entity_types[entity] = entity.entity_type

    async def register_many(self, registrations: List[tuple[EntityId, str]]) -> int:
        """Batch register entity-component associations."""
        for entity, component_type in registrations:
            self._entity_components[entity].add(component_type)
            self._component_entities[component_type].add(entity)
            self._entity_types[entity] = entity.entity_type
        return len(registrations)

    async def unregister(self, entity: EntityId, component_type: str) -> bool:
        """Unregister a component from an entity."""
        if entity in self._entity_components:
            self._entity_components[entity].discard(component_type)

            # Clean up empty entries
            if not self._entity_components[entity]:
                del self._entity_components[entity]
                if entity in self._entity_types:
                    del self._entity_types[entity]

        if component_type in self._component_entities:
            self._component_entities[component_type].discard(entity)
            return True

        return False

    async def unregister_entity(self, entity: EntityId) -> Set[str]:
        """
        Remove an entity from the index entirely.
        Returns the set of component types it had.
        """
        if entity not in self._entity_components:
            return set()

        component_types = self._entity_components.pop(entity)

        for component_type in component_types:
            self._component_entities[component_type].discard(entity)

        if entity in self._entity_types:
            del self._entity_types[entity]

        return component_types

    async def unregister_many_entities(self, entities: List[EntityId]) -> int:
        """Batch unregister entities."""
        count = 0
        for entity in entities:
            if entity in self._entity_components:
                await self.unregister_entity(entity)
                count += 1
        return count

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def get_components_for_entity(self, entity: EntityId) -> Set[str]:
        """Get all component types an entity has."""
        return self._entity_components.get(entity, set()).copy()

    async def get_entities_with_component(self, component_type: str) -> Set[EntityId]:
        """Get all entities that have a specific component type."""
        return self._component_entities.get(component_type, set()).copy()

    async def query_join(self, component_types: List[str]) -> Set[EntityId]:
        """
        Find entities that have ALL specified components (AND query).
        This is the core join operation for ECS systems.
        """
        if not component_types:
            return set()

        # Start with first component's entities
        result = self._component_entities.get(component_types[0], set()).copy()

        # Intersect with remaining component sets
        for component_type in component_types[1:]:
            result &= self._component_entities.get(component_type, set())

            # Early exit if no matches
            if not result:
                return set()

        return result

    async def query_any(self, component_types: List[str]) -> Set[EntityId]:
        """
        Find entities that have ANY of the specified components (OR query).
        """
        result: Set[EntityId] = set()
        for component_type in component_types:
            result |= self._component_entities.get(component_type, set())
        return result

    async def query_exactly(self, component_types: List[str]) -> Set[EntityId]:
        """
        Find entities that have EXACTLY the specified components (no more, no less).
        """
        required = set(component_types)
        return {
            entity
            for entity, components in self._entity_components.items()
            if components == required
        }

    async def query_without(self, required: List[str], excluded: List[str]) -> Set[EntityId]:
        """
        Find entities that have all required components but none of the excluded.
        Useful for queries like "all entities with Position but not Dead".
        """
        # Get entities with required components
        result = await self.query_join(required)

        # Remove entities with excluded components
        for component_type in excluded:
            result -= self._component_entities.get(component_type, set())

        return result

    async def query_by_entity_type(
        self, entity_type: str, component_types: Optional[List[str]] = None
    ) -> Set[EntityId]:
        """
        Find entities of a specific type, optionally filtered by components.
        """
        # Get all entities of this type
        result = {entity for entity, etype in self._entity_types.items() if etype == entity_type}

        # Filter by components if specified
        if component_types:
            required_entities = await self.query_join(component_types)
            result &= required_entities

        return result

    async def has_component(self, entity: EntityId, component_type: str) -> bool:
        """Check if an entity has a specific component."""
        return component_type in self._entity_components.get(entity, set())

    async def has_all_components(self, entity: EntityId, component_types: List[str]) -> bool:
        """Check if an entity has all specified components."""
        entity_components = self._entity_components.get(entity, set())
        return all(ct in entity_components for ct in component_types)

    async def entity_exists(self, entity: EntityId) -> bool:
        """Check if an entity is in the index."""
        return entity in self._entity_components

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    async def get_all_entities(self) -> Set[EntityId]:
        """Get all known entities."""
        return set(self._entity_components.keys())

    async def get_all_component_types(self) -> Set[str]:
        """Get all known component types."""
        return set(self._component_entities.keys())

    async def clear(self) -> None:
        """Clear the entire index."""
        self._entity_components.clear()
        self._component_entities.clear()
        self._entity_types.clear()
        logger.info("EntityIndex cleared")

    # =========================================================================
    # Synchronization with Component Actors
    # =========================================================================

    async def sync_from_component_actors(self, component_engine: ActorHandle) -> Dict[str, int]:
        """
        Rebuild the index by querying all component actors.
        Useful for recovery or initialization.
        """
        from .component import get_component_actor

        # Clear current state
        await self.clear()

        stats: Dict[str, int] = {}

        # Get all registered components
        component_types = await component_engine.get_registered_components.remote()

        for component_type in component_types:
            try:
                actor = get_component_actor(component_type)
                entities = await actor.get_entities.remote()

                for entity in entities:
                    self._entity_components[entity].add(component_type)
                    self._component_entities[component_type].add(entity)
                    self._entity_types[entity] = entity.entity_type

                stats[component_type] = len(entities)

            except Exception as e:
                logger.error(f"Error syncing component {component_type}: {e}")
                stats[component_type] = -1

        logger.info(f"EntityIndex synced: {sum(v for v in stats.values() if v > 0)} total entries")
        return stats

    # =========================================================================
    # Diagnostics
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the index."""
        return {
            "total_entities": len(self._entity_components),
            "total_component_types": len(self._component_entities),
            "entities_per_component": {
                ct: len(entities) for ct, entities in self._component_entities.items()
            },
            "entity_types": dict(
                sorted(
                    [
                        (et, sum(1 for e in self._entity_types.values() if e == et))
                        for et in set(self._entity_types.values())
                    ],
                    key=lambda x: -x[1],
                )
            ),
        }


def get_entity_index() -> ActorHandle:
    """Get the EntityIndex actor."""
    return ray.get_actor(constants.ENTITY_INDEX_ACTOR, namespace=constants.NAMESPACE)
