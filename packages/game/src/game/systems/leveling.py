"""
Leveling System

Processes level-up requests queued by the level command.
Runs each tick to handle pending level-ups at guild masters.

Level-up flow:
1. Player uses 'level' command at guild master
2. Command validates requirements and creates LevelUpQueueData
3. LevelingSystem processes the queue each tick
4. Updates LevelingData, grants rewards, clears queue
"""

import logging
import time
from typing import Dict, List, Optional, Any

import ray
from ray.actor import ActorHandle

from core import EntityId, ComponentData, System
from core.component import get_component_actor

from ..components.leveling import (
    LevelingData,
    LevelUpQueueData,
    LevelRequirement,
    get_default_title,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Leveling System
# =============================================================================


@ray.remote
class LevelingSystem(System):
    """
    Processes pending level-up requests.

    Required components:
    - LevelUpQueue: Entities with pending level-up requests

    Optional components:
    - Leveling: Current leveling state (required for actual level-up)

    The system:
    1. Finds all entities with LevelUpQueueData
    2. Validates the queue is marked as validated
    3. Gets class definition for level requirements
    4. Updates LevelingData with new level/title
    5. Grants rewards (gold, items, skills)
    6. Removes the queue component
    """

    def __init__(self):
        super().__init__(
            system_type="LevelingSystem",
            required_components=["LevelUpQueue"],
            optional_components=["Leveling", "Player", "Stats"],
            dependencies=[],  # Run early, no combat dependencies
            priority=5,
        )
        self._level_up_events: List[Dict[str, Any]] = []
        self._class_registry = None

    def _get_class_registry(self) -> ActorHandle:
        """Get the class registry actor lazily."""
        if self._class_registry is None:
            from ..world.class_registry import get_class_registry
            self._class_registry = get_class_registry()
        return self._class_registry

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Process all pending level-up requests.

        Returns the number of level-ups processed.
        """
        processed = 0
        self._level_up_events.clear()

        for entity_id, components in entities.items():
            queue_data: LevelUpQueueData = components["LevelUpQueue"]
            leveling_data: Optional[LevelingData] = components.get("Leveling")

            # Skip if not validated
            if not queue_data.validated:
                logger.debug(f"Skipping unvalidated level-up for {entity_id}")
                continue

            # Skip if no leveling data
            if not leveling_data:
                logger.warning(f"Entity {entity_id} has LevelUpQueue but no Leveling")
                await self._remove_queue(write_buffer, entity_id)
                continue

            # Skip if queue is stale (> 30 seconds old)
            if time.time() - queue_data.created_at > 30.0:
                logger.info(f"Level-up request for {entity_id} timed out")
                await self._remove_queue(write_buffer, entity_id)
                continue

            # Process the level-up
            try:
                await self._process_level_up(
                    entity_id,
                    leveling_data,
                    queue_data,
                    components,
                    write_buffer,
                )
                processed += 1
            except Exception as e:
                logger.error(f"Error processing level-up for {entity_id}: {e}")
                await self._remove_queue(write_buffer, entity_id)

        return processed

    async def _process_level_up(
        self,
        entity_id: EntityId,
        leveling: LevelingData,
        queue: LevelUpQueueData,
        components: Dict[str, ComponentData],
        write_buffer: ActorHandle,
    ) -> None:
        """Process a single level-up."""
        target_level = queue.target_level
        class_id = leveling.class_id

        # Get level requirements from class registry
        registry = self._get_class_registry()
        requirements = await registry.get_level_requirements.remote(
            class_id, target_level
        )

        if not requirements:
            # Use default if registry doesn't have it
            xp_to_next = (target_level + 1) * (target_level + 1) * 1000
            new_title = get_default_title(class_id, target_level)
        else:
            # Calculate XP for the next level
            next_req = await registry.get_level_requirements.remote(
                class_id, target_level + 1
            )
            xp_to_next = next_req.xp_required if next_req else (target_level + 1) ** 2 * 1000
            new_title = requirements.title

        # Consume gold if required
        if queue.gold_to_consume > 0:
            await self._consume_gold(entity_id, queue.gold_to_consume, write_buffer)

        # Consume items if required
        for item_id in queue.items_to_consume:
            await self._consume_item(item_id, write_buffer)

        # Update leveling data
        await self._apply_level_up(
            entity_id,
            target_level,
            xp_to_next,
            new_title,
            write_buffer,
        )

        # Update stats (health/mana increase)
        if "Stats" in components:
            await self._update_stats_for_level(
                entity_id,
                class_id,
                target_level,
                write_buffer,
            )

        # Grant rewards
        if requirements and requirements.rewards:
            await self._grant_rewards(
                entity_id,
                requirements.rewards,
                write_buffer,
            )

        # Record event
        self._level_up_events.append({
            "entity_id": entity_id,
            "new_level": target_level,
            "new_title": new_title,
            "class_id": class_id,
            "timestamp": time.time(),
        })

        logger.info(f"Entity {entity_id} leveled up to {target_level} ({new_title})")

        # Remove the queue component
        await self._remove_queue(write_buffer, entity_id)

    async def _apply_level_up(
        self,
        entity_id: EntityId,
        new_level: int,
        xp_to_next: int,
        new_title: str,
        write_buffer: ActorHandle,
    ) -> None:
        """Apply level-up to LevelingData."""

        def update_leveling(leveling: LevelingData) -> LevelingData:
            leveling.current_level = new_level
            leveling.xp_to_next = xp_to_next
            leveling.class_title = new_title
            leveling.pending_level_up = False
            leveling.last_level_up_at = time.time()
            leveling.total_levels_gained += 1
            leveling.levels_gained_session += 1
            return leveling

        await write_buffer.mutate.remote("Leveling", entity_id, update_leveling)

    async def _update_stats_for_level(
        self,
        entity_id: EntityId,
        class_id: str,
        new_level: int,
        write_buffer: ActorHandle,
    ) -> None:
        """Update player stats for the new level (health/mana increase)."""
        registry = self._get_class_registry()
        class_def = await registry.get_class.remote(class_id)

        if not class_def:
            # Default gains
            health_gain = 10
            mana_gain = 5
        else:
            health_gain = class_def.health_per_level
            mana_gain = class_def.mana_per_level

        def update_stats(stats) -> None:
            stats.max_health = stats.max_health + health_gain
            stats.current_health = min(
                stats.current_health + health_gain, stats.max_health
            )
            stats.max_mana = stats.max_mana + mana_gain
            stats.current_mana = min(
                stats.current_mana + mana_gain, stats.max_mana
            )
            return stats

        await write_buffer.mutate.remote("Stats", entity_id, update_stats)

    async def _consume_gold(
        self,
        entity_id: EntityId,
        amount: int,
        write_buffer: ActorHandle,
    ) -> None:
        """Consume gold from player."""

        def deduct_gold(player) -> None:
            player.gold = max(0, player.gold - amount)
            return player

        await write_buffer.mutate.remote("Player", entity_id, deduct_gold)

    async def _consume_item(
        self,
        item_id: EntityId,
        write_buffer: ActorHandle,
    ) -> None:
        """Mark an item for deletion."""
        # For now, we mark the item as consumed by setting quantity to 0
        # The actual cleanup can be handled by an inventory cleanup system
        try:
            def consume(item) -> None:
                item.quantity = 0
                return item

            await write_buffer.mutate.remote("Item", item_id, consume)
        except Exception as e:
            logger.warning(f"Failed to consume item {item_id}: {e}")

    async def _grant_rewards(
        self,
        entity_id: EntityId,
        rewards,  # LevelReward
        write_buffer: ActorHandle,
    ) -> None:
        """Grant level-up rewards to the player."""
        # Grant gold
        if rewards.gold > 0:
            def add_gold(player) -> None:
                player.gold = player.gold + rewards.gold
                return player

            await write_buffer.mutate.remote("Player", entity_id, add_gold)

        # Items and skills would be granted through item/skill systems
        # For now, log what should be granted
        if rewards.items:
            logger.info(f"Should grant items to {entity_id}: {rewards.items}")

        if rewards.skills:
            logger.info(f"Should grant skills to {entity_id}: {rewards.skills}")

    async def _remove_queue(
        self,
        write_buffer: ActorHandle,
        entity_id: EntityId,
    ) -> None:
        """Remove the LevelUpQueue component from an entity."""
        try:
            # Set validated to false and clear it - component cleanup will handle removal
            def clear_queue(queue: LevelUpQueueData) -> LevelUpQueueData:
                queue.validated = False
                queue.target_level = 0
                return queue

            await write_buffer.mutate.remote("LevelUpQueue", entity_id, clear_queue)
        except Exception as e:
            logger.warning(f"Failed to remove queue for {entity_id}: {e}")

    async def get_level_up_events(self) -> List[Dict[str, Any]]:
        """Get level-up events from the last tick (for messaging)."""
        return list(self._level_up_events)


# =============================================================================
# Actor Management
# =============================================================================

ACTOR_NAME = "leveling_system"
ACTOR_NAMESPACE = "llmmud"

_leveling_system: Optional[ActorHandle] = None


def get_leveling_system() -> ActorHandle:
    """Get the leveling system actor."""
    global _leveling_system
    if _leveling_system is None:
        _leveling_system = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
    return _leveling_system


async def start_leveling_system() -> ActorHandle:
    """Start the leveling system actor."""
    global _leveling_system

    system: ActorHandle = LevelingSystem.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote()

    _leveling_system = system
    logger.info("Started LevelingSystem actor")
    return system


def leveling_system_exists() -> bool:
    """Check if leveling system actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False
