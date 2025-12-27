"""
QueryCoordinator utility for efficient cross-component queries.

Provides high-level query operations that coordinate across multiple
component actors and the EntityIndex for efficient entity lookups.
"""

import logging
from typing import Dict, List, Set, Optional, Callable

import ray
from ray import ObjectRef

from .types import EntityId, ComponentData
from .component import get_component_actor
from .entity_index import get_entity_index
from . import constants

logger = logging.getLogger(__name__)


class QueryCoordinator:
    """
    Coordinates queries across multiple component actors.

    Provides efficient methods for:
    - Finding entities with specific component combinations
    - Fetching component data for matched entities
    - Filtered queries with predicates
    """

    def __init__(self, use_entity_index: bool = True):
        """
        Initialize the query coordinator.

        Args:
            use_entity_index: If True, use EntityIndex for faster joins.
                             If False, query component actors directly.
        """
        self._use_entity_index = use_entity_index

    async def get_entities_with_components(self, component_types: List[str]) -> Set[EntityId]:
        """
        Find entities that have ALL specified components.

        Uses EntityIndex if available, otherwise queries component actors.
        """
        if not component_types:
            return set()

        if self._use_entity_index:
            try:
                entity_index = get_entity_index()
                return await entity_index.query_join.remote(component_types)
            except Exception as e:
                logger.warning(f"EntityIndex query failed, falling back: {e}")

        # Fallback: query component actors directly
        return await self._query_components_directly(component_types)

    async def _query_components_directly(self, component_types: List[str]) -> Set[EntityId]:
        """Query component actors directly for entity sets."""
        refs: List[ObjectRef] = []
        for component_type in component_types:
            try:
                actor = get_component_actor(component_type)
                refs.append(actor.get_entities.remote())
            except Exception as e:
                logger.error(f"Error getting actor for {component_type}: {e}")
                return set()

        entity_sets: List[Set[EntityId]] = ray.get(refs)

        if not entity_sets:
            return set()

        result = entity_sets[0]
        for entity_set in entity_sets[1:]:
            result &= entity_set

        return result

    async def query(
        self,
        component_types: List[str],
        filters: Optional[Dict[str, Callable[[ComponentData], bool]]] = None,
    ) -> Dict[EntityId, Dict[str, ComponentData]]:
        """
        Full query: get entities with all components, optionally filtered.

        Args:
            component_types: Component types the entity must have
            filters: Optional dict of {component_type: predicate} for filtering

        Returns:
            Dict of {entity_id: {component_type: component_data}}
        """
        if not component_types:
            return {}

        # Step 1: Find matching entities
        if filters:
            entities = await self._query_with_filters(component_types, filters)
        else:
            entities = await self.get_entities_with_components(component_types)

        if not entities:
            return {}

        # Step 2: Fetch component data for matched entities
        entity_list = list(entities)
        return await self.fetch_components_for_entities(entity_list, component_types)

    async def _query_with_filters(
        self,
        component_types: List[str],
        filters: Dict[str, Callable[[ComponentData], bool]],
    ) -> Set[EntityId]:
        """Query with predicate filters on specific components."""
        filtered_entity_sets: List[Set[EntityId]] = []

        for component_type in component_types:
            actor = get_component_actor(component_type)

            if component_type in filters:
                # Apply filter remotely
                ref = actor.get_entities_where.remote(filters[component_type])
            else:
                ref = actor.get_entities.remote()

            filtered_entity_sets.append(ray.get(ref))  # type: ignore[call-overload]

        if not filtered_entity_sets:
            return set()

        # Intersect all sets
        return set.intersection(*filtered_entity_sets)

    async def fetch_components_for_entities(
        self, entities: List[EntityId], component_types: List[str]
    ) -> Dict[EntityId, Dict[str, ComponentData]]:
        """
        Fetch component data for specific entities.

        Args:
            entities: List of entity IDs to fetch
            component_types: Component types to fetch

        Returns:
            Dict of {entity_id: {component_type: component_data}}
        """
        if not entities or not component_types:
            return {}

        # Batch fetch from each component actor
        refs: List[tuple[str, ObjectRef]] = []
        for component_type in component_types:
            try:
                actor = get_component_actor(component_type)
                refs.append((component_type, actor.get_many.remote(entities)))
            except Exception as e:
                logger.error(f"Error fetching {component_type}: {e}")

        # Assemble results
        results: Dict[EntityId, Dict[str, ComponentData]] = {}

        for component_type, ref in refs:
            try:
                data = ray.get(ref, timeout=constants.GET_COMPONENTS_TIMEOUT_S)
                for entity_id, component_data in data.items():
                    if entity_id not in results:
                        results[entity_id] = {}
                    results[entity_id][component_type] = component_data
            except Exception as e:
                logger.error(f"Error getting data for {component_type}: {e}")

        return results

    async def get_single_entity(
        self, entity: EntityId, component_types: List[str]
    ) -> Optional[Dict[str, ComponentData]]:
        """
        Get all requested components for a single entity.

        Returns None if entity doesn't have all required components.
        """
        refs: List[tuple[str, ObjectRef]] = []

        for component_type in component_types:
            try:
                actor = get_component_actor(component_type)
                refs.append((component_type, actor.get.remote(entity)))
            except Exception as e:
                logger.error(f"Error getting {component_type}: {e}")
                return None

        result: Dict[str, ComponentData] = {}

        for component_type, ref in refs:
            try:
                data = ray.get(ref, timeout=constants.GET_COMPONENTS_TIMEOUT_S)
                if data is None:
                    return None  # Missing required component
                result[component_type] = data
            except Exception as e:
                logger.error(f"Error getting {component_type}: {e}")
                return None

        return result

    async def count_entities_with_components(self, component_types: List[str]) -> int:
        """Count entities that have all specified components."""
        entities = await self.get_entities_with_components(component_types)
        return len(entities)

    async def get_entities_by_type(
        self, entity_type: str, component_types: Optional[List[str]] = None
    ) -> Set[EntityId]:
        """
        Get entities of a specific type, optionally with component filter.
        """
        if self._use_entity_index:
            try:
                entity_index = get_entity_index()
                return await entity_index.query_by_entity_type.remote(entity_type, component_types)
            except Exception as e:
                logger.warning(f"EntityIndex query failed: {e}")

        # Fallback: get all entities with components and filter by type
        if component_types:
            entities = await self.get_entities_with_components(component_types)
        else:
            entity_index = get_entity_index()
            entities = await entity_index.get_all_entities.remote()

        return {e for e in entities if e.entity_type == entity_type}


# Convenience functions for common queries


async def get_entities_in_room(
    room_id: EntityId, component_types: Optional[List[str]] = None
) -> Set[EntityId]:
    """
    Get all entities in a specific room.

    Requires entities to have a "Location" component with room_id field.
    """
    location_actor = get_component_actor("Location")

    # Get all entities with Location component where room matches
    entities = await location_actor.get_entities_where.remote(
        lambda loc: getattr(loc, "room_id", None) == room_id
    )

    # Filter by additional components if specified
    if component_types:
        coordinator = QueryCoordinator()
        component_entities = await coordinator.get_entities_with_components(component_types)
        entities &= component_entities

    return entities


async def get_entities_with_target(
    target_id: EntityId, component_type: str = "Combat"
) -> Set[EntityId]:
    """
    Get all entities targeting a specific entity.

    Requires entities to have a component with a 'target' field.
    """
    actor = get_component_actor(component_type)

    return await actor.get_entities_where.remote(lambda c: getattr(c, "target", None) == target_id)


async def get_low_health_entities(
    threshold: float = 0.3, component_types: Optional[List[str]] = None
) -> Set[EntityId]:
    """
    Get entities with health below a threshold percentage.

    Requires entities to have a "Health" component with current_hp and max_hp fields.
    """
    health_actor = get_component_actor("Health")

    entities = await health_actor.get_entities_where.remote(
        lambda h: getattr(h, "current_hp", 0) / max(getattr(h, "max_hp", 1), 1) < threshold
    )

    if component_types:
        coordinator = QueryCoordinator()
        component_entities = await coordinator.get_entities_with_components(component_types)
        entities &= component_entities

    return entities
