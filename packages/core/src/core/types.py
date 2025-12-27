"""Core type definitions for the ECS system."""

from dataclasses import dataclass, field
from collections import namedtuple


# Simple entity identifier - hashable and immutable
EntityId = namedtuple("EntityId", ["id", "entity_type"])


@dataclass
class ComponentData:
    """
    Base class for all component data.
    Components store the data for entities - systems operate on this data.
    """

    owner: EntityId

    def __post_init__(self):
        # Ensure owner is set
        if self.owner is None:
            raise ValueError("ComponentData requires an owner EntityId")


@dataclass
class SnapshotMetadata:
    """Metadata about a component snapshot."""

    tick_id: int
    component_type: str
    entity_count: int
    timestamp: float = field(default_factory=lambda: __import__("time").time())
