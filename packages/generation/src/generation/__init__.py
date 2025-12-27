"""
LLM-MUD Dynamic Content Generation Package

Provides Ray actors for managing LLM-generated content pools,
rate limiting, on-demand generation, and instance management.
"""

from .pool import ContentPool, ContentPoolManager, ContentType, PoolConfig
from .engine import GenerationEngine, GenerationEngineConfig
from .rate_limiter import RateLimiter, RateLimitConfig
from .instance import InstanceManager, Instance, InstanceRoom, InstanceConfig
from .personality import PersonalityEngine, CombatDecision, CombatContext, CombatAction, DialogueIntent
from .region import (
    RegionManager,
    RegionRuntimeState,
    RegionEnterEvent,
    RegionExitEvent,
    RoomGeneratedEvent,
    start_region_manager,
    get_region_manager,
    region_manager_exists,
    stop_region_manager,
)
from .quest import (
    QuestGenerator,
    QuestPoolConfig,
    PooledQuest,
    start_quest_generator,
    get_quest_generator,
    quest_generator_exists,
    stop_quest_generator,
)
from .crafting import (
    CraftingEngine,
    CraftingRecipe,
    CraftingAttempt,
    calculate_quality_modifier,
    determine_output_rarity,
    infer_item_type,
    start_crafting_engine,
    get_crafting_engine,
    crafting_engine_exists,
    stop_crafting_engine,
)

__all__ = [
    # Pool
    "ContentPool",
    "ContentPoolManager",
    "ContentType",
    "PoolConfig",
    # Engine
    "GenerationEngine",
    "GenerationEngineConfig",
    # Rate Limiter
    "RateLimiter",
    "RateLimitConfig",
    # Instance
    "InstanceManager",
    "Instance",
    "InstanceRoom",
    "InstanceConfig",
    # Personality
    "PersonalityEngine",
    "CombatDecision",
    "CombatContext",
    "CombatAction",
    "DialogueIntent",
    # Region
    "RegionManager",
    "RegionRuntimeState",
    "RegionEnterEvent",
    "RegionExitEvent",
    "RoomGeneratedEvent",
    "start_region_manager",
    "get_region_manager",
    "region_manager_exists",
    "stop_region_manager",
    # Quest
    "QuestGenerator",
    "QuestPoolConfig",
    "PooledQuest",
    "start_quest_generator",
    "get_quest_generator",
    "quest_generator_exists",
    "stop_quest_generator",
    # Crafting
    "CraftingEngine",
    "CraftingRecipe",
    "CraftingAttempt",
    "calculate_quality_modifier",
    "determine_output_rarity",
    "infer_item_type",
    "start_crafting_engine",
    "get_crafting_engine",
    "crafting_engine_exists",
    "stop_crafting_engine",
]
