"""
LLM Response Cache

Provides caching for agent results to reduce API calls and latency.
Supports both in-memory and Redis backends.
"""

import asyncio
import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# =============================================================================
# Cache Interface
# =============================================================================


class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int = 0) -> None:
        """Set a value with optional TTL."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a key."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all cached values."""
        pass


# =============================================================================
# In-Memory Cache Backend
# =============================================================================


@dataclass
class CacheEntry:
    """An entry in the memory cache."""

    value: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 0

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return datetime.utcnow() - self.created_at > timedelta(seconds=self.ttl_seconds)


class MemoryCacheBackend(CacheBackend):
    """In-memory cache with TTL support."""

    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._cache[key]
                return None
            return entry.value

    async def set(self, key: str, value: str, ttl_seconds: int = 0) -> None:
        async with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self._max_size:
                await self._evict_expired()
                if len(self._cache) >= self._max_size:
                    # Remove oldest entry
                    oldest = min(self._cache.items(), key=lambda x: x[1].created_at)
                    del self._cache[oldest[0]]

            self._cache[key] = CacheEntry(
                value=value,
                ttl_seconds=ttl_seconds,
            )

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def _evict_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        expired = [k for k, v in self._cache.items() if v.is_expired]
        for key in expired:
            del self._cache[key]
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._cache)


# =============================================================================
# Redis Cache Backend (optional)
# =============================================================================


class RedisCacheBackend(CacheBackend):
    """
    Redis cache backend.

    Requires redis package: pip install redis
    """

    def __init__(self, url: Optional[str] = None):
        self._url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._client = None
        self._prefix = "llm_cache:"

    async def _get_client(self):
        """Lazy initialize Redis client."""
        if self._client is None:
            try:
                import redis.asyncio as redis

                self._client = redis.from_url(self._url)
            except ImportError:
                logger.warning("redis package not installed, falling back to memory cache")
                raise
        return self._client

    async def get(self, key: str) -> Optional[str]:
        try:
            client = await self._get_client()
            value = await client.get(self._prefix + key)
            return value.decode() if value else None
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    async def set(self, key: str, value: str, ttl_seconds: int = 0) -> None:
        try:
            client = await self._get_client()
            if ttl_seconds > 0:
                await client.setex(self._prefix + key, ttl_seconds, value)
            else:
                await client.set(self._prefix + key, value)
        except Exception as e:
            logger.warning(f"Redis set error: {e}")

    async def delete(self, key: str) -> bool:
        try:
            client = await self._get_client()
            result = await client.delete(self._prefix + key)
            return result > 0
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
            return False

    async def clear(self) -> None:
        try:
            client = await self._get_client()
            keys = await client.keys(self._prefix + "*")
            if keys:
                await client.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")


# =============================================================================
# Cached Agent Wrapper
# =============================================================================


class CachedAgent(Generic[T]):
    """
    Wrapper that caches agent results.

    Usage:
        cached_room_agent = CachedAgent(room_agent, cache_backend)
        result = await cached_room_agent.run("Generate a room", deps=context)
    """

    def __init__(
        self,
        agent: Agent,
        cache: CacheBackend,
        ttl_seconds: int = 3600,
        cache_enabled: bool = True,
    ):
        self.agent = agent
        self.cache = cache
        self.ttl_seconds = ttl_seconds
        self.cache_enabled = cache_enabled
        self._stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
        }

    def _make_cache_key(self, prompt: str, deps: Any) -> str:
        """Generate a cache key from prompt and deps."""
        # Serialize deps to JSON for hashing
        if hasattr(deps, "model_dump"):
            deps_str = json.dumps(deps.model_dump(), sort_keys=True)
        elif hasattr(deps, "__dict__"):
            deps_str = json.dumps(vars(deps), sort_keys=True, default=str)
        else:
            deps_str = str(deps)

        combined = f"{prompt}:{deps_str}"
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    async def run(self, prompt: str, deps: Any = None) -> T:
        """
        Run the agent with caching.

        Args:
            prompt: The prompt to send to the agent
            deps: Dependencies/context for the agent

        Returns:
            The agent's result (from cache or fresh generation)
        """
        if not self.cache_enabled:
            result = await self.agent.run(prompt, deps=deps)
            return result.data

        cache_key = self._make_cache_key(prompt, deps)

        # Try cache first
        cached = await self.cache.get(cache_key)
        if cached:
            try:
                # Parse cached JSON back to model
                result_type = self.agent.result_type
                if hasattr(result_type, "model_validate_json"):
                    self._stats["hits"] += 1
                    return result_type.model_validate_json(cached)
            except Exception as e:
                logger.warning(f"Cache parse error: {e}")
                await self.cache.delete(cache_key)

        # Cache miss - generate fresh
        self._stats["misses"] += 1
        try:
            result = await self.agent.run(prompt, deps=deps)
            data = result.data

            # Cache the result
            if hasattr(data, "model_dump_json"):
                await self.cache.set(
                    cache_key,
                    data.model_dump_json(),
                    self.ttl_seconds,
                )

            return data
        except Exception:
            self._stats["errors"] += 1
            raise

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return self._stats.copy()


# =============================================================================
# Cache Factory
# =============================================================================


def get_cache_backend() -> CacheBackend:
    """
    Get the appropriate cache backend based on environment.

    Uses Redis if REDIS_URL is set, otherwise falls back to memory.
    """
    redis_url = os.environ.get("REDIS_URL")

    if redis_url:
        try:
            import redis.asyncio  # noqa: F401

            logger.info(f"Using Redis cache backend: {redis_url}")
            return RedisCacheBackend(redis_url)
        except ImportError:
            logger.warning("Redis URL set but redis package not installed")

    logger.info("Using in-memory cache backend")
    return MemoryCacheBackend()


# Global cache instance
_cache_backend: Optional[CacheBackend] = None


def get_cache() -> CacheBackend:
    """Get or create the global cache backend."""
    global _cache_backend
    if _cache_backend is None:
        _cache_backend = get_cache_backend()
    return _cache_backend


def create_cached_agent(
    agent: Agent,
    ttl_seconds: int = 3600,
    cache_enabled: bool = True,
) -> CachedAgent:
    """Create a cached wrapper for an agent."""
    return CachedAgent(
        agent=agent,
        cache=get_cache(),
        ttl_seconds=ttl_seconds,
        cache_enabled=cache_enabled,
    )


__all__ = [
    "CacheBackend",
    "MemoryCacheBackend",
    "RedisCacheBackend",
    "CachedAgent",
    "get_cache_backend",
    "get_cache",
    "create_cached_agent",
]
