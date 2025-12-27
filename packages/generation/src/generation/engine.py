"""
Generation Engine

Central orchestrator for content generation. Manages the LLM provider,
content pools, and rate limiting to provide both pooled and on-demand content.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Type, TypeVar

import ray
from ray.actor import ActorHandle
from pydantic import BaseModel

from llm import (
    LLMProvider,
    GenerationResult,
    GenerationError,
    GeneratedRoom,
    GeneratedMob,
    GeneratedItem,
    GeneratedDialogue,
    Theme,
)
from llm.prompts import (
    RoomPromptBuilder,
    MobPromptBuilder,
    ItemPromptBuilder,
    DialoguePromptBuilder,
    RoomContext,
    MobContext,
    ItemContext,
    DialogueContext,
)
from llm.providers import AnthropicProvider
from llm.provider import ProviderConfig

from .pool import (
    ContentType,
    PoolConfig,
    PooledContent,
    get_pool_manager,
    pool_manager_exists,
)
from .rate_limiter import get_rate_limiter, rate_limiter_exists

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class GenerationEngineConfig:
    """Configuration for the generation engine."""

    # LLM provider configuration
    api_key: str
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    # Pool settings
    enable_pooling: bool = True
    fallback_to_generation: bool = True

    # Replenishment settings
    replenishment_enabled: bool = True
    replenishment_interval_s: float = 30.0
    replenishment_batch_size: int = 3

    # Default pool configs per content type
    default_pool_min: int = 5
    default_pool_target: int = 10
    default_pool_max: int = 20


@ray.remote
class GenerationEngine:
    """
    Ray actor that orchestrates content generation.

    Provides a unified interface for getting content - either from pools
    (for instant delivery) or generated on-demand (for unique/boss content).

    The engine automatically manages:
    - LLM provider lifecycle
    - Rate limiting
    - Pool replenishment
    - Fallback from pool to on-demand generation

    Usage:
        engine = get_generation_engine()

        # Get content (from pool if available, else generate)
        room = await engine.get_room.remote(theme, context)

        # Force generation (bypass pool)
        boss = await engine.generate_mob.remote(theme, context, force_generate=True)

        # Start background replenishment
        await engine.start_replenishment.remote()
    """

    def __init__(self, config: GenerationEngineConfig):
        self._config = config
        self._provider: Optional[LLMProvider] = None
        self._replenishment_task: Optional[asyncio.Task] = None
        self._themes: dict[str, Theme] = {}
        self._running = False

        # Statistics
        self._stats = {
            "pool_hits": 0,
            "pool_misses": 0,
            "generations": 0,
            "errors": 0,
        }

        self._init_provider()
        logger.info("GenerationEngine initialized")

    def _init_provider(self) -> None:
        """Initialize the LLM provider."""
        provider_config = ProviderConfig(
            api_key=self._config.api_key,
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        self._provider = AnthropicProvider(provider_config)
        logger.info(f"LLM provider initialized: {self._provider.provider_name}")

    # =========================================================================
    # Theme Management
    # =========================================================================

    async def register_theme(self, theme: Theme) -> None:
        """Register a theme for content generation."""
        self._themes[theme.theme_id] = theme
        logger.info(f"Registered theme: {theme.theme_id}")

        # Create pools for this theme if pooling is enabled
        if self._config.enable_pooling and pool_manager_exists():
            manager = get_pool_manager()
            for content_type in [ContentType.ROOM, ContentType.MOB, ContentType.ITEM]:
                pool_config = PoolConfig(
                    theme_id=theme.theme_id,
                    content_type=content_type,
                    min_size=self._config.default_pool_min,
                    target_size=self._config.default_pool_target,
                    max_size=self._config.default_pool_max,
                )
                await manager.create_pool.remote(pool_config)

    async def get_theme(self, theme_id: str) -> Optional[Theme]:
        """Get a registered theme."""
        return self._themes.get(theme_id)

    # =========================================================================
    # Content Generation - Rooms
    # =========================================================================

    async def get_room(
        self,
        theme_id: str,
        context: Optional[RoomContext] = None,
        force_generate: bool = False,
    ) -> Optional[GeneratedRoom]:
        """
        Get a room - from pool if available, else generate.

        Args:
            theme_id: Theme to use for generation
            context: Room generation context
            force_generate: If True, bypass pool and always generate

        Returns:
            GeneratedRoom or None if generation failed
        """
        # Try pool first
        if not force_generate and self._config.enable_pooling:
            content = await self._try_pool(theme_id, ContentType.ROOM)
            if content:
                self._stats["pool_hits"] += 1
                return content.content

            self._stats["pool_misses"] += 1
            if not self._config.fallback_to_generation:
                return None

        # Generate on-demand
        return await self.generate_room(theme_id, context)

    async def generate_room(
        self, theme_id: str, context: Optional[RoomContext] = None
    ) -> Optional[GeneratedRoom]:
        """Generate a room on-demand (always generates, never uses pool)."""
        theme = self._themes.get(theme_id)
        if not theme:
            logger.error(f"Theme not found: {theme_id}")
            return None

        return await self._generate(
            theme=theme,
            schema=GeneratedRoom,
            prompt_builder=RoomPromptBuilder(theme),
            context=context,
        )

    # =========================================================================
    # Content Generation - Mobs
    # =========================================================================

    async def get_mob(
        self,
        theme_id: str,
        context: Optional[MobContext] = None,
        force_generate: bool = False,
    ) -> Optional[GeneratedMob]:
        """Get a mob - from pool if available, else generate."""
        if not force_generate and self._config.enable_pooling:
            content = await self._try_pool(theme_id, ContentType.MOB)
            if content:
                self._stats["pool_hits"] += 1
                return content.content

            self._stats["pool_misses"] += 1
            if not self._config.fallback_to_generation:
                return None

        return await self.generate_mob(theme_id, context)

    async def generate_mob(
        self, theme_id: str, context: Optional[MobContext] = None
    ) -> Optional[GeneratedMob]:
        """Generate a mob on-demand."""
        theme = self._themes.get(theme_id)
        if not theme:
            logger.error(f"Theme not found: {theme_id}")
            return None

        return await self._generate(
            theme=theme,
            schema=GeneratedMob,
            prompt_builder=MobPromptBuilder(theme),
            context=context,
        )

    # =========================================================================
    # Content Generation - Items
    # =========================================================================

    async def get_item(
        self,
        theme_id: str,
        context: Optional[ItemContext] = None,
        force_generate: bool = False,
    ) -> Optional[GeneratedItem]:
        """Get an item - from pool if available, else generate."""
        if not force_generate and self._config.enable_pooling:
            content = await self._try_pool(theme_id, ContentType.ITEM)
            if content:
                self._stats["pool_hits"] += 1
                return content.content

            self._stats["pool_misses"] += 1
            if not self._config.fallback_to_generation:
                return None

        return await self.generate_item(theme_id, context)

    async def generate_item(
        self, theme_id: str, context: Optional[ItemContext] = None
    ) -> Optional[GeneratedItem]:
        """Generate an item on-demand."""
        theme = self._themes.get(theme_id)
        if not theme:
            logger.error(f"Theme not found: {theme_id}")
            return None

        return await self._generate(
            theme=theme,
            schema=GeneratedItem,
            prompt_builder=ItemPromptBuilder(theme),
            context=context,
        )

    # =========================================================================
    # Content Generation - Dialogue
    # =========================================================================

    async def generate_dialogue(
        self, theme_id: str, context: DialogueContext
    ) -> Optional[GeneratedDialogue]:
        """Generate dialogue for a mob. Always generates fresh (no pooling)."""
        theme = self._themes.get(theme_id)
        if not theme:
            logger.error(f"Theme not found: {theme_id}")
            return None

        prompt = DialoguePromptBuilder(theme).build(context)
        return await self._generate_raw(theme, GeneratedDialogue, prompt)

    # =========================================================================
    # Internal Generation Methods
    # =========================================================================

    async def _try_pool(self, theme_id: str, content_type: ContentType) -> Optional[PooledContent]:
        """Try to get content from pool."""
        if not pool_manager_exists():
            return None

        manager = get_pool_manager()
        return await manager.get_content.remote(theme_id, content_type)

    async def _generate(
        self,
        theme: Theme,
        schema: Type[T],
        prompt_builder: RoomPromptBuilder | MobPromptBuilder | ItemPromptBuilder,
        context: Optional[RoomContext | MobContext | ItemContext] = None,
    ) -> Optional[T]:
        """Generate content using the LLM provider."""
        if not self._provider:
            logger.error("Provider not initialized")
            return None

        # Rate limit
        if rate_limiter_exists():
            limiter = get_rate_limiter()
            if not await limiter.acquire.remote():
                logger.warning("Rate limit or budget exceeded")
                return None

        # Build prompt
        prompt = prompt_builder.build(context)
        system_prompt = theme.build_system_prompt()

        try:
            result: GenerationResult[T] = await self._provider.generate_structured(
                prompt=prompt,
                schema=schema,
                system=system_prompt,
                temperature=theme.temperature,
            )

            # Record usage
            if rate_limiter_exists():
                limiter = get_rate_limiter()
                await limiter.record_usage.remote(
                    result.usage.input_tokens, result.usage.output_tokens
                )

            self._stats["generations"] += 1
            logger.debug(
                f"Generated {schema.__name__} for {theme.theme_id} "
                f"({result.latency_ms:.0f}ms, {result.usage.total_tokens} tokens)"
            )
            return result.content

        except GenerationError as e:
            self._stats["errors"] += 1
            logger.error(f"Generation error: {e}")
            return None

    async def _generate_raw(self, theme: Theme, schema: Type[T], prompt: str) -> Optional[T]:
        """Generate content with a raw prompt."""
        if not self._provider:
            return None

        if rate_limiter_exists():
            limiter = get_rate_limiter()
            if not await limiter.acquire.remote():
                return None

        system_prompt = theme.build_system_prompt()

        try:
            result: GenerationResult[T] = await self._provider.generate_structured(
                prompt=prompt,
                schema=schema,
                system=system_prompt,
            )

            if rate_limiter_exists():
                limiter = get_rate_limiter()
                await limiter.record_usage.remote(
                    result.usage.input_tokens, result.usage.output_tokens
                )

            self._stats["generations"] += 1
            return result.content

        except GenerationError as e:
            self._stats["errors"] += 1
            logger.error(f"Generation error: {e}")
            return None

    # =========================================================================
    # Replenishment Loop
    # =========================================================================

    async def start_replenishment(self) -> None:
        """Start the background replenishment loop."""
        if self._running:
            logger.warning("Replenishment already running")
            return

        if not self._config.replenishment_enabled:
            logger.info("Replenishment disabled")
            return

        self._running = True
        self._replenishment_task = asyncio.create_task(self._replenishment_loop())
        logger.info("Started replenishment loop")

    async def stop_replenishment(self) -> None:
        """Stop the background replenishment loop."""
        self._running = False
        if self._replenishment_task:
            self._replenishment_task.cancel()
            try:
                await self._replenishment_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped replenishment loop")

    async def _replenishment_loop(self) -> None:
        """Background loop that replenishes pools."""
        while self._running:
            try:
                await self._replenish_pools()
            except Exception as e:
                logger.error(f"Error in replenishment: {e}")

            await asyncio.sleep(self._config.replenishment_interval_s)

    async def _replenish_pools(self) -> None:
        """Check and replenish pools that need content."""
        if not pool_manager_exists():
            return

        manager = get_pool_manager()
        needs = await manager.get_pools_needing_replenishment.remote()

        for theme_id, content_type, count in needs:
            if not self._running:
                break

            # Generate batch for this pool
            batch_size = min(count, self._config.replenishment_batch_size)
            logger.debug(f"Replenishing {theme_id}/{content_type.value}: {batch_size} items")

            for _ in range(batch_size):
                if not self._running:
                    break

                content = await self._generate_for_pool(theme_id, content_type)
                if content:
                    await manager.add_content.remote(theme_id, content_type, content)

    async def _generate_for_pool(
        self, theme_id: str, content_type: ContentType
    ) -> Optional[BaseModel]:
        """Generate content for adding to a pool."""
        if content_type == ContentType.ROOM:
            return await self.generate_room(theme_id)
        elif content_type == ContentType.MOB:
            return await self.generate_mob(theme_id)
        elif content_type == ContentType.ITEM:
            return await self.generate_item(theme_id)
        return None

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict:
        """Get engine statistics."""
        provider_stats = self._provider.get_stats() if self._provider else {}
        return {
            "engine": self._stats,
            "provider": provider_stats,
            "themes": list(self._themes.keys()),
            "replenishment_running": self._running,
        }


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================

ENGINE_ACTOR_NAME = "generation_engine"
ENGINE_NAMESPACE = "llmmud"


def start_generation_engine(config: GenerationEngineConfig) -> ActorHandle:
    """Start the generation engine actor."""
    actor: ActorHandle = GenerationEngine.options(
        name=ENGINE_ACTOR_NAME,
        namespace=ENGINE_NAMESPACE,
        lifetime="detached",
    ).remote(
        config
    )  # type: ignore[assignment]
    logger.info(f"Started GenerationEngine as {ENGINE_NAMESPACE}/{ENGINE_ACTOR_NAME}")
    return actor


def get_generation_engine() -> ActorHandle:
    """Get the generation engine actor."""
    return ray.get_actor(ENGINE_ACTOR_NAME, namespace=ENGINE_NAMESPACE)


def generation_engine_exists() -> bool:
    """Check if the generation engine exists."""
    try:
        ray.get_actor(ENGINE_ACTOR_NAME, namespace=ENGINE_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_generation_engine() -> bool:
    """Stop the generation engine actor."""
    try:
        actor = ray.get_actor(ENGINE_ACTOR_NAME, namespace=ENGINE_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped GenerationEngine")
        return True
    except ValueError:
        return False
