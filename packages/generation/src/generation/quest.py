"""
Quest Generator Actor

Ray actor for dynamic quest generation with pooling, caching, and static fallback.
Generates level-appropriate quests personalized to player context.
"""

import logging
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

import ray
from ray.actor import ActorHandle

from llm.agents import quest_agent
from llm.cache import create_cached_agent, CachedAgent
from llm.schemas import (
    GeneratedQuest,
    QuestGenerationContext,
    QuestArchetype,
    ZoneQuestTheme,
    ZoneType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

ACTOR_NAME = "quest_generator"
ACTOR_NAMESPACE = "llmmud"


@dataclass
class QuestPoolConfig:
    """Configuration for per-zone quest pooling."""

    zone_id: str
    min_size: int = 3
    target_size: int = 5
    max_size: int = 10
    replenish_batch_size: int = 2


@dataclass
class PooledQuest:
    """A quest stored in the pool."""

    quest: GeneratedQuest
    created_at: float
    zone_id: str
    archetype: QuestArchetype
    level_range: tuple[int, int] = (1, 50)  # Min/max player level this suits

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


# =============================================================================
# Quest Generator Actor
# =============================================================================


@ray.remote
class QuestGenerator:
    """
    Ray actor for dynamic quest generation with pooling and fallback.

    Features:
    - Pre-generation pool per zone (configurable size)
    - On-demand generation with caching
    - Fallback to static quests when LLM fails
    - Variety enforcement (avoid repeating archetypes)
    - Level-appropriate quest scaling

    Usage:
        generator = get_quest_generator()
        context = QuestGenerationContext(...)
        quest = await generator.get_quest.remote(context)
    """

    def __init__(self, cache_ttl: int = 1800):
        """
        Initialize the quest generator.

        Args:
            cache_ttl: TTL for cached quests in seconds (default 30 min)
        """
        self._cached_agent: CachedAgent = create_cached_agent(
            quest_agent, ttl_seconds=cache_ttl
        )
        self._pools: Dict[str, Deque[PooledQuest]] = {}
        self._pool_configs: Dict[str, QuestPoolConfig] = {}
        self._static_fallbacks: Dict[str, List[Dict[str, Any]]] = {}
        self._replenishment_running = False

        # Statistics
        self._stats = {
            "pool_hits": 0,
            "generations": 0,
            "fallbacks": 0,
            "errors": 0,
            "cache_hits": 0,
        }

        logger.info(f"QuestGenerator initialized with cache TTL {cache_ttl}s")

    async def get_quest(
        self,
        context: QuestGenerationContext,
        force_generate: bool = False,
    ) -> Optional[GeneratedQuest]:
        """
        Get a quest for the given context.

        Tries in order:
        1. Pool (if available and matches level)
        2. On-demand generation (with caching)
        3. Static fallback quests

        Args:
            context: Quest generation context with player/zone info
            force_generate: Skip pool, always generate fresh

        Returns:
            Generated quest or None if all methods fail
        """
        zone_id = context.target_zone_id

        # 1. Try pool first (unless forced)
        if not force_generate:
            pooled = await self._get_from_pool(zone_id, context.player_level)
            if pooled:
                self._stats["pool_hits"] += 1
                logger.debug(f"Quest from pool for {zone_id}")
                return pooled.quest

        # 2. Generate on-demand
        try:
            quest = await self._cached_agent.run(
                "Generate a quest for this player and zone.",
                deps=context,
            )
            self._stats["generations"] += 1
            logger.debug(f"Generated quest: {quest.name}")
            return quest
        except Exception as e:
            logger.warning(f"Quest generation failed: {e}")
            self._stats["errors"] += 1

        # 3. Fallback to static quests
        static = await self._get_static_fallback(zone_id, context.player_level)
        if static:
            self._stats["fallbacks"] += 1
            logger.debug(f"Using static fallback quest for {zone_id}")
            return static

        logger.error(f"No quest available for {zone_id}")
        return None

    async def _get_from_pool(
        self, zone_id: str, player_level: int
    ) -> Optional[PooledQuest]:
        """Get a level-appropriate quest from the zone's pool."""
        if zone_id not in self._pools:
            return None

        pool = self._pools[zone_id]
        if not pool:
            return None

        # Find best match for player level
        for i, pooled in enumerate(pool):
            min_level, max_level = pooled.level_range
            if min_level <= player_level <= max_level:
                # Remove and return this quest
                pool.remove(pooled)
                return pooled

        # No level-appropriate quest, take oldest
        return pool.popleft() if pool else None

    async def _get_static_fallback(
        self, zone_id: str, player_level: int
    ) -> Optional[GeneratedQuest]:
        """Get a static fallback quest, converted to GeneratedQuest."""
        fallbacks = self._static_fallbacks.get(zone_id, [])
        if not fallbacks:
            return None

        # Filter by level if possible
        suitable = [
            q for q in fallbacks
            if q.get("min_level", 1) <= player_level <= q.get("max_level", 50)
        ]

        if not suitable:
            suitable = fallbacks

        # Pick random from suitable
        static = random.choice(suitable)
        return self._convert_static_to_generated(static)

    def _convert_static_to_generated(
        self, static: Dict[str, Any]
    ) -> GeneratedQuest:
        """Convert static quest dict to GeneratedQuest."""
        from llm.schemas import GeneratedObjective, GeneratedReward, ItemRarity

        objectives = []
        for obj_data in static.get("objectives", []):
            objectives.append(GeneratedObjective(
                objective_type=obj_data.get("type", "kill"),
                description=obj_data.get("description", "Complete objective"),
                target_description=obj_data.get("target", "target"),
                target_type_hint=obj_data.get("target_hint", "enemy"),
                required_count=obj_data.get("count", 1),
                location_hint=obj_data.get("location"),
            ))

        rewards_data = static.get("rewards", {})
        rewards = GeneratedReward(
            experience=rewards_data.get("experience", 100),
            gold=rewards_data.get("gold", 10),
            item_hints=rewards_data.get("items", []),
        )

        return GeneratedQuest(
            name=static.get("name", "Unnamed Quest"),
            description=static.get("description", "A quest."),
            archetype=QuestArchetype(static.get("archetype", "combat")),
            rarity=ItemRarity(static.get("rarity", "common")),
            objectives=objectives if objectives else [
                GeneratedObjective(
                    objective_type="talk",
                    description="Speak to the quest giver",
                    target_description="quest giver",
                    target_type_hint="npc",
                )
            ],
            rewards=rewards,
            intro_text=static.get("intro_text", "Will you help?"),
            progress_text=static.get("progress_text", "Come back when done."),
            complete_text=static.get("complete_text", "Thank you, adventurer!"),
        )

    async def register_zone(self, zone_id: str, config: QuestPoolConfig) -> None:
        """Register a zone for quest pooling."""
        self._pool_configs[zone_id] = config
        self._pools[zone_id] = deque(maxlen=config.max_size)
        logger.info(f"Registered zone {zone_id} for quest pooling")

    async def register_static_quests(
        self, zone_id: str, quests: List[Dict[str, Any]]
    ) -> int:
        """
        Register static quests as fallback for a zone.

        Args:
            zone_id: Zone identifier
            quests: List of quest dicts in simplified format

        Returns:
            Number of quests registered
        """
        self._static_fallbacks[zone_id] = quests
        logger.info(f"Registered {len(quests)} static fallback quests for {zone_id}")
        return len(quests)

    async def replenish_pool(
        self,
        zone_id: str,
        context: QuestGenerationContext,
        count: Optional[int] = None,
    ) -> int:
        """
        Replenish quest pool for a zone.

        Args:
            zone_id: Zone to replenish
            context: Generation context template
            count: Number to generate (default: to target size)

        Returns:
            Number of quests added to pool
        """
        if zone_id not in self._pool_configs:
            await self.register_zone(zone_id, QuestPoolConfig(zone_id=zone_id))

        config = self._pool_configs[zone_id]
        pool = self._pools[zone_id]

        if count is None:
            count = max(0, config.target_size - len(pool))

        if count <= 0:
            return 0

        added = 0
        for _ in range(count):
            if len(pool) >= config.max_size:
                break

            try:
                quest = await self._cached_agent.run(
                    "Generate a quest for this zone.",
                    deps=context,
                )

                # Determine level range based on difficulty
                level = context.player_level
                level_range = (max(1, level - 3), min(50, level + 5))

                pooled = PooledQuest(
                    quest=quest,
                    created_at=time.time(),
                    zone_id=zone_id,
                    archetype=quest.archetype,
                    level_range=level_range,
                )
                pool.append(pooled)
                added += 1
            except Exception as e:
                logger.warning(f"Failed to generate quest for pool: {e}")
                break

        logger.info(f"Replenished {added} quests for {zone_id}")
        return added

    async def needs_replenishment(self, zone_id: str) -> bool:
        """Check if a zone's pool needs replenishment."""
        if zone_id not in self._pool_configs:
            return False
        config = self._pool_configs[zone_id]
        pool = self._pools.get(zone_id, deque())
        return len(pool) < config.min_size

    async def get_stats(self) -> Dict[str, Any]:
        """Get generation statistics."""
        agent_stats = self._cached_agent.get_stats()
        return {
            **self._stats,
            "cache_stats": agent_stats,
            "pools": {
                zone_id: len(pool)
                for zone_id, pool in self._pools.items()
            },
            "fallback_zones": list(self._static_fallbacks.keys()),
            "registered_zones": list(self._pool_configs.keys()),
        }

    async def clear_pool(self, zone_id: str) -> int:
        """Clear a zone's quest pool. Returns count cleared."""
        if zone_id not in self._pools:
            return 0
        count = len(self._pools[zone_id])
        self._pools[zone_id].clear()
        return count

    async def get_pool_size(self, zone_id: str) -> int:
        """Get current pool size for a zone."""
        return len(self._pools.get(zone_id, []))


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_quest_generator(cache_ttl: int = 1800) -> ActorHandle:
    """Start the quest generator actor."""
    actor: ActorHandle = QuestGenerator.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote(cache_ttl)
    logger.info(f"Started QuestGenerator as {ACTOR_NAMESPACE}/{ACTOR_NAME}")
    return actor


def get_quest_generator() -> ActorHandle:
    """Get the quest generator actor."""
    return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)


def quest_generator_exists() -> bool:
    """Check if the quest generator exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_quest_generator() -> bool:
    """Stop the quest generator."""
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped QuestGenerator")
        return True
    except ValueError:
        return False


__all__ = [
    "QuestGenerator",
    "QuestPoolConfig",
    "PooledQuest",
    "start_quest_generator",
    "get_quest_generator",
    "quest_generator_exists",
    "stop_quest_generator",
]
