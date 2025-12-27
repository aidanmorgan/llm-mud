"""
Quest Instance Components

Tracks player-visible-only quest entities (instanced spawns).
Used for dynamically generated quest targets that are only visible
to the quest holder or their group.
"""

from dataclasses import dataclass, field
from typing import Set, Optional
import time

from core import ComponentData, EntityId


@dataclass
class QuestInstanceData(ComponentData):
    """
    Marks an entity as instanced for a specific quest/player.

    Instanced entities are only visible to specific players, ensuring
    quest fairness (e.g., a named boss won't be killed by others).

    Used on: mobs, items, NPCs spawned specifically for a quest.
    """

    # The quest this entity belongs to
    quest_id: str = ""

    # Player IDs who can see and interact with this entity
    visible_to: Set[str] = field(default_factory=set)

    # If True, entity is visible to players in the same group as visible_to
    group_visible: bool = True

    # Despawn behavior
    despawn_on_quest_complete: bool = True
    despawn_on_quest_abandon: bool = True
    despawn_on_quest_fail: bool = True

    # Cleanup after time (seconds) even if quest not resolved (0 = never)
    max_lifetime_s: float = 3600.0  # 1 hour default

    # Spawn tracking
    spawned_at: float = field(default_factory=time.time)
    spawned_by: str = ""  # Player ID who triggered spawn
    spawned_from_objective: str = ""  # Objective ID that created this

    # For quest target tracking
    is_quest_target: bool = True  # If True, killing/collecting completes objective
    objective_contribution: int = 1  # How much progress this contributes

    @property
    def age_seconds(self) -> float:
        """Get how long this entity has existed."""
        return time.time() - self.spawned_at

    @property
    def is_expired(self) -> bool:
        """Check if entity has exceeded max lifetime."""
        if self.max_lifetime_s <= 0:
            return False
        return self.age_seconds > self.max_lifetime_s


def is_visible_to_player(
    instance_data: QuestInstanceData,
    player_id: str,
    group_member_ids: Optional[Set[str]] = None,
) -> bool:
    """
    Check if a quest-instanced entity is visible to a specific player.

    Args:
        instance_data: The QuestInstanceData component
        player_id: The player checking visibility
        group_member_ids: Set of player IDs in the same group (optional)

    Returns:
        True if the player can see and interact with this entity
    """
    # Direct visibility check
    if player_id in instance_data.visible_to:
        return True

    # Group visibility check
    if instance_data.group_visible and group_member_ids:
        # If any visible_to player is in the same group, allow
        return bool(instance_data.visible_to & group_member_ids)

    return False


@dataclass
class QuestSpawnedEntityData(ComponentData):
    """
    Tracks entities that were spawned for a player's quest.

    Attached to the PLAYER to track what entities were created for their quests.
    Used for cleanup when quest is completed/abandoned/failed.
    """

    # quest_id -> list of spawned entity IDs
    spawned_entities: dict[str, list[str]] = field(default_factory=dict)

    def add_spawned(self, quest_id: str, entity_id: str) -> None:
        """Record a spawned entity for a quest."""
        if quest_id not in self.spawned_entities:
            self.spawned_entities[quest_id] = []
        if entity_id not in self.spawned_entities[quest_id]:
            self.spawned_entities[quest_id].append(entity_id)

    def get_spawned(self, quest_id: str) -> list[str]:
        """Get all entities spawned for a quest."""
        return self.spawned_entities.get(quest_id, [])

    def remove_spawned(self, quest_id: str) -> list[str]:
        """Remove and return all entities for a quest (for cleanup)."""
        return self.spawned_entities.pop(quest_id, [])

    def remove_entity(self, quest_id: str, entity_id: str) -> None:
        """Remove a specific entity from tracking."""
        if quest_id in self.spawned_entities:
            if entity_id in self.spawned_entities[quest_id]:
                self.spawned_entities[quest_id].remove(entity_id)


@dataclass
class GeneratedQuestData(ComponentData):
    """
    Tracks a dynamically generated quest attached to a player.

    This stores the raw generated quest data before/after conversion
    to QuestDefinition, for potential regeneration or analysis.
    """

    # Original generation context (serialized)
    generation_context: dict = field(default_factory=dict)

    # The raw generated quest data from LLM
    generated_quest_data: dict = field(default_factory=dict)

    # When this quest was generated
    generated_at: float = field(default_factory=time.time)

    # Generator version/model for reproducibility
    generator_version: str = ""

    # Was this from pool (cached) or on-demand?
    from_pool: bool = False

    # Zone this quest was generated for
    source_zone: str = ""
