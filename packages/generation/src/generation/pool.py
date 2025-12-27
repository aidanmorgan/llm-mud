"""
Content Pool for Pre-Generated Content

Maintains pools of pre-generated content (rooms, mobs, items) for each theme,
enabling instant content delivery without waiting for LLM generation.
"""

import logging
import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Deque

import ray
from ray.actor import ActorHandle

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """Types of content that can be pooled."""

    ROOM = "room"
    MOB = "mob"
    ITEM = "item"
    DIALOGUE = "dialogue"


@dataclass
class PoolConfig:
    """Configuration for a content pool."""

    theme_id: str
    content_type: ContentType

    # Pool size limits
    min_size: int = 5
    target_size: int = 10
    max_size: int = 20

    # Replenishment settings
    replenish_batch_size: int = 3
    replenish_interval_s: float = 60.0

    # TTL for content (0 = no expiry)
    content_ttl_s: float = 0


@dataclass
class PooledContent:
    """A piece of content stored in the pool."""

    content: Any  # The actual content (GeneratedRoom, GeneratedMob, etc.)
    created_at: float
    theme_id: str
    content_type: ContentType
    metadata: dict = field(default_factory=dict)


@ray.remote
class ContentPool:
    """
    Ray actor managing a pool of pre-generated content for a specific theme/type.

    Each pool stores content of a single type (room, mob, item) for a single theme.
    The pool automatically replenishes when it drops below the minimum size.

    Usage:
        pool = ContentPool.remote(config)
        content = await pool.get.remote()  # Get content from pool
        await pool.add.remote(generated_content)  # Add new content
    """

    def __init__(self, config: PoolConfig):
        self._config = config
        self._pool: Deque[PooledContent] = deque()
        self._replenishing = False
        self._total_served = 0
        self._total_added = 0

        logger.info(
            f"ContentPool created: {config.theme_id}/{config.content_type.value} "
            f"(target: {config.target_size})"
        )

    async def get(self) -> Optional[PooledContent]:
        """
        Get content from the pool.

        Returns None if pool is empty. Caller should handle this by
        either waiting for replenishment or generating on-demand.
        """
        import time

        if not self._pool:
            logger.debug(f"Pool {self._config.theme_id}/{self._config.content_type.value} empty")
            return None

        # Get oldest content (FIFO)
        content = self._pool.popleft()

        # Check TTL if configured
        if self._config.content_ttl_s > 0:
            age = time.time() - content.created_at
            if age > self._config.content_ttl_s:
                logger.debug(f"Content expired (age: {age:.0f}s)")
                # Try to get fresh content
                return await self.get()

        self._total_served += 1
        logger.debug(
            f"Served from pool {self._config.theme_id}/{self._config.content_type.value} "
            f"(remaining: {len(self._pool)})"
        )
        return content

    async def get_random(self) -> Optional[PooledContent]:
        """Get random content from the pool (doesn't remove it)."""
        if not self._pool:
            return None

        return random.choice(list(self._pool))

    async def add(self, content: Any, metadata: Optional[dict] = None) -> bool:
        """
        Add content to the pool.

        Returns False if pool is at max capacity.
        """
        import time

        if len(self._pool) >= self._config.max_size:
            logger.warning(
                f"Pool {self._config.theme_id}/{self._config.content_type.value} at max capacity"
            )
            return False

        pooled = PooledContent(
            content=content,
            created_at=time.time(),
            theme_id=self._config.theme_id,
            content_type=self._config.content_type,
            metadata=metadata or {},
        )

        self._pool.append(pooled)
        self._total_added += 1
        logger.debug(
            f"Added to pool {self._config.theme_id}/{self._config.content_type.value} "
            f"(size: {len(self._pool)})"
        )
        return True

    async def add_batch(self, contents: list[Any]) -> int:
        """Add multiple content items. Returns count added."""
        added = 0
        for content in contents:
            if await self.add(content):
                added += 1
            else:
                break  # Pool full
        return added

    async def needs_replenishment(self) -> bool:
        """Check if pool needs replenishment."""
        return len(self._pool) < self._config.min_size

    async def get_replenish_count(self) -> int:
        """Get number of items needed to reach target size."""
        return max(0, self._config.target_size - len(self._pool))

    async def get_size(self) -> int:
        """Get current pool size."""
        return len(self._pool)

    async def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "theme_id": self._config.theme_id,
            "content_type": self._config.content_type.value,
            "current_size": len(self._pool),
            "min_size": self._config.min_size,
            "target_size": self._config.target_size,
            "max_size": self._config.max_size,
            "total_served": self._total_served,
            "total_added": self._total_added,
            "needs_replenishment": len(self._pool) < self._config.min_size,
        }

    async def clear(self) -> int:
        """Clear the pool. Returns count of items cleared."""
        count = len(self._pool)
        self._pool.clear()
        logger.info(f"Cleared pool {self._config.theme_id}/{self._config.content_type.value}")
        return count


@ray.remote
class ContentPoolManager:
    """
    Ray actor managing multiple content pools.

    Provides a central interface for getting content from the appropriate pool
    and triggering replenishment across all pools.

    Usage:
        manager = get_pool_manager()
        content = await manager.get_content.remote("dark_cave", ContentType.ROOM)
        await manager.trigger_replenishment.remote()
    """

    def __init__(self):
        self._pools: dict[str, ActorHandle] = {}  # "theme_id/content_type" -> pool actor
        self._replenishment_running = False
        logger.info("ContentPoolManager initialized")

    def _pool_key(self, theme_id: str, content_type: ContentType) -> str:
        """Generate key for pool lookup."""
        return f"{theme_id}/{content_type.value}"

    async def create_pool(self, config: PoolConfig) -> ActorHandle:
        """Create a new content pool."""
        key = self._pool_key(config.theme_id, config.content_type)

        if key in self._pools:
            logger.warning(f"Pool {key} already exists")
            return self._pools[key]

        pool: ActorHandle = ContentPool.options(
            name=f"content_pool/{key}",
            namespace="llmmud",
        ).remote(
            config
        )  # type: ignore[assignment]

        self._pools[key] = pool
        logger.info(f"Created pool: {key}")
        return pool

    async def get_pool(self, theme_id: str, content_type: ContentType) -> Optional[ActorHandle]:
        """Get a pool by theme and content type."""
        key = self._pool_key(theme_id, content_type)
        return self._pools.get(key)

    async def get_content(
        self, theme_id: str, content_type: ContentType
    ) -> Optional[PooledContent]:
        """Get content from the appropriate pool."""
        pool = await self.get_pool(theme_id, content_type)
        if not pool:
            logger.warning(f"No pool for {theme_id}/{content_type.value}")
            return None

        return await pool.get.remote()

    async def add_content(self, theme_id: str, content_type: ContentType, content: Any) -> bool:
        """Add content to the appropriate pool."""
        pool = await self.get_pool(theme_id, content_type)
        if not pool:
            return False

        return await pool.add.remote(content)

    async def get_pools_needing_replenishment(self) -> list[tuple[str, ContentType, int]]:
        """
        Get list of pools needing replenishment.

        Returns list of (theme_id, content_type, count_needed) tuples.
        """
        needs = []
        for key, pool in self._pools.items():
            if await pool.needs_replenishment.remote():
                theme_id, content_type = key.rsplit("/", 1)
                count = await pool.get_replenish_count.remote()
                needs.append((theme_id, ContentType(content_type), count))
        return needs

    async def get_all_stats(self) -> list[dict]:
        """Get stats for all pools."""
        stats = []
        for pool in self._pools.values():
            pool_stats = await pool.get_stats.remote()
            stats.append(pool_stats)
        return stats

    async def clear_theme(self, theme_id: str) -> int:
        """Clear all pools for a theme. Returns total items cleared."""
        total = 0
        for key, pool in list(self._pools.items()):
            if key.startswith(f"{theme_id}/"):
                total += await pool.clear.remote()
        return total

    async def remove_pool(self, theme_id: str, content_type: ContentType) -> bool:
        """Remove a pool entirely."""
        key = self._pool_key(theme_id, content_type)
        if key in self._pools:
            pool = self._pools.pop(key)
            ray.kill(pool)
            logger.info(f"Removed pool: {key}")
            return True
        return False


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================

MANAGER_ACTOR_NAME = "content_pool_manager"
MANAGER_NAMESPACE = "llmmud"


def start_pool_manager() -> ActorHandle:
    """Start the content pool manager actor."""
    actor: ActorHandle = ContentPoolManager.options(
        name=MANAGER_ACTOR_NAME,
        namespace=MANAGER_NAMESPACE,
        lifetime="detached",
    ).remote()  # type: ignore[assignment]
    logger.info(f"Started ContentPoolManager as {MANAGER_NAMESPACE}/{MANAGER_ACTOR_NAME}")
    return actor


def get_pool_manager() -> ActorHandle:
    """Get the content pool manager actor."""
    return ray.get_actor(MANAGER_ACTOR_NAME, namespace=MANAGER_NAMESPACE)


def pool_manager_exists() -> bool:
    """Check if the pool manager exists."""
    try:
        ray.get_actor(MANAGER_ACTOR_NAME, namespace=MANAGER_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_pool_manager() -> bool:
    """Stop the pool manager and all pools."""
    try:
        actor = ray.get_actor(MANAGER_ACTOR_NAME, namespace=MANAGER_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped ContentPoolManager")
        return True
    except ValueError:
        return False
