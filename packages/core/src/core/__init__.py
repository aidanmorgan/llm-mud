"""
LLM-MUD Core Package

Entity-Component-System (ECS) implementation built on Ray actors.

Key concepts:
- Components: Data containers (Ray actors per component type)
- Entities: Unique IDs with component associations
- Systems: Logic that processes entities with specific components
- Ticks: Coordinated processing cycles with snapshot/process/commit phases

Architecture:
    TickCoordinator
        │ 1. Take snapshots from Component actors
        │ 2. Execute Systems in dependency order
        │ 3. Commit WriteBuffer to Component actors
        ▼
    ┌─────────────┬─────────────┬─────────────┐
    │ Component A │ Component B │ Component C │
    └─────────────┴─────────────┴─────────────┘
                      │
                      ▼
                 EntityIndex
            (entity→components map)
"""

import logging
import threading
from typing import Optional

import ray
from ray.actor import ActorHandle

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Type exports
from .types import EntityId, ComponentData, SnapshotMetadata  # noqa: E402

# Constants
from .constants import (  # noqa: E402
    NAMESPACE,
    TICK_COORDINATOR_ACTOR,
    TICK_ENGINE_ACTOR,
    COMPONENT_ENGINE_ACTOR,
    ENTITY_INDEX_ACTOR,
    COMPONENT_ACTOR_PREFIX,
    SYSTEM_ACTOR_PREFIX,
    GET_COMPONENTS_TIMEOUT_S,
    TICK_TIMEOUT_S,
    SNAPSHOT_TIMEOUT_S,
    COMMIT_TIMEOUT_S,
)

# Component system
from .component import (  # noqa: E402
    Component,
    ComponentEngine,
    component_actor_path,
    get_component_actor,
)

# Entity index
from .entity_index import (  # noqa: E402
    EntityIndex,
    get_entity_index,
)

# Write buffer
from .write_buffer import (  # noqa: E402
    WriteBuffer,
    WriteOperation,
    create_write_buffer,
    destroy_write_buffer,
)

# Tick coordination
from .tick import (  # noqa: E402
    TickCoordinator,
    TickEngine,  # Legacy alias
    SystemDefinition,
    TickResult,
    get_tick_coordinator,
)

# System base class
from .system import (  # noqa: E402
    System,
    TickableMixin,
)

# Query utilities
from .query import (  # noqa: E402
    QueryCoordinator,
    get_entities_in_room,
    get_entities_with_target,
    get_low_health_entities,
)

# Extension API
from .extension import (  # noqa: E402
    Extension,
    ExtensionInfo,
)

# Event system
from .events import (  # noqa: E402
    EventBus,
    EventRouter,
    EventScope,
    EventTopic,
    EventPriority,
    EventTarget,
    GameEvent,
    CombatEvent,
    MovementEvent,
    ChatEvent,
    ItemEvent,
    SkillEvent,
    SystemEvent,
    Subscription,
    EventHandler,
    get_event_bus,
    publish_event,
    subscribe,
    generate_event_id,
    create_combat_event,
    create_movement_event,
    create_chat_event,
    create_channel_event,
    create_system_event,
)

# Keep legacy definition exports
from .definitions import (  # noqa: E402
    SystemDefinition as LegacySystemDefinition,
    EntityDefinition,
    ComponentDefinition,
)

# Global actor references (initialized lazily)
# Thread-safe access via _actor_lock
_actor_lock = threading.Lock()
_tick_coordinator: Optional[ActorHandle] = None
_component_engine: Optional[ActorHandle] = None
_entity_index: Optional[ActorHandle] = None


def _register_tick_coordinator() -> ActorHandle:
    """Create or get the TickCoordinator actor (detached for resilience)."""
    actor: ActorHandle = TickCoordinator.options(
        name=TICK_COORDINATOR_ACTOR,
        namespace=NAMESPACE,
        lifetime="detached",
        get_if_exists=True,
    ).remote()  # type: ignore[assignment]
    return actor


def _register_component_engine() -> ActorHandle:
    """Create or get the ComponentEngine actor (detached for resilience)."""
    actor: ActorHandle = ComponentEngine.options(
        name=COMPONENT_ENGINE_ACTOR,
        namespace=NAMESPACE,
        lifetime="detached",
        get_if_exists=True,
    ).remote()  # type: ignore[assignment]
    return actor


def _register_entity_index() -> ActorHandle:
    """Create or get the EntityIndex actor (detached for resilience)."""
    actor: ActorHandle = EntityIndex.options(
        name=ENTITY_INDEX_ACTOR,
        namespace=NAMESPACE,
        lifetime="detached",
        get_if_exists=True,
    ).remote()  # type: ignore[assignment]
    return actor


def core_tick_coordinator() -> ActorHandle:
    """Get the global TickCoordinator actor (thread-safe)."""
    global _tick_coordinator
    with _actor_lock:
        if _tick_coordinator is None:
            _tick_coordinator = _register_tick_coordinator()
        return _tick_coordinator


def core_tick_engine() -> ActorHandle:
    """Legacy alias for core_tick_coordinator."""
    return core_tick_coordinator()


def core_component_engine() -> ActorHandle:
    """Get the global ComponentEngine actor (thread-safe)."""
    global _component_engine
    with _actor_lock:
        if _component_engine is None:
            _component_engine = _register_component_engine()
        return _component_engine


def core_entity_index() -> ActorHandle:
    """Get the global EntityIndex actor (thread-safe)."""
    global _entity_index
    with _actor_lock:
        if _entity_index is None:
            _entity_index = _register_entity_index()
        return _entity_index


async def initialise_core() -> None:
    """
    Initialize the core ECS infrastructure.

    Creates and configures:
    - TickCoordinator: Orchestrates tick processing
    - ComponentEngine: Registry for component types
    - EntityIndex: Maps entities to components
    """
    global _tick_coordinator, _component_engine, _entity_index

    _tick_coordinator = _register_tick_coordinator()
    _component_engine = _register_component_engine()
    _entity_index = _register_entity_index()

    # Connect the tick coordinator to the component engine
    await _tick_coordinator.set_component_engine.remote(_component_engine)

    logger.info(f"Registered TickCoordinator at: {TICK_COORDINATOR_ACTOR}")
    logger.info(f"Registered ComponentEngine at: {COMPONENT_ENGINE_ACTOR}")
    logger.info(f"Registered EntityIndex at: {ENTITY_INDEX_ACTOR}")

    # NOTE: Do NOT start the tick coordinator here. Components must be
    # registered first. Call start_tick_loop() after component registration.

    logger.info("Core ECS infrastructure initialized")


async def start_tick_loop() -> None:
    """
    Start the tick coordinator's processing loop.

    Call this AFTER all components have been registered with the ComponentEngine.
    This ensures the tick loop doesn't try to process components that don't exist yet.
    """
    global _tick_coordinator
    if _tick_coordinator is not None:
        await _tick_coordinator.start.remote()
        logger.info("Tick loop started")
    else:
        logger.warning("Cannot start tick loop: TickCoordinator not initialized")


async def shutdown_core(kill_actors: bool = False) -> None:
    """
    Shutdown the core ECS infrastructure.

    Args:
        kill_actors: If True, also kill the detached actors (use when fully
                    shutting down the cluster). If False, just stop processing
                    but leave actors alive for potential reconnection.
    """
    global _tick_coordinator, _component_engine, _entity_index

    # Stop the tick coordinator first
    if _tick_coordinator is not None:
        try:
            await _tick_coordinator.stop.remote()
            logger.info("TickCoordinator stopped")
        except Exception as e:
            logger.error(f"Error stopping TickCoordinator: {e}")

    # Kill actors if requested (for full shutdown)
    if kill_actors:
        actors_to_kill = [
            (_tick_coordinator, "TickCoordinator"),
            (_component_engine, "ComponentEngine"),
            (_entity_index, "EntityIndex"),
        ]
        for actor, name in actors_to_kill:
            if actor is not None:
                try:
                    ray.kill(actor)
                    logger.info(f"{name} actor killed")
                except Exception as e:
                    logger.warning(f"Error killing {name} actor: {e}")

    # Clear global references
    with _actor_lock:
        _tick_coordinator = None
        _component_engine = None
        _entity_index = None

    logger.info("Core ECS infrastructure shutdown complete")


# Public API
__all__ = [
    # Types
    "EntityId",
    "ComponentData",
    "SnapshotMetadata",
    # Constants
    "NAMESPACE",
    "TICK_COORDINATOR_ACTOR",
    "TICK_ENGINE_ACTOR",
    "COMPONENT_ENGINE_ACTOR",
    "ENTITY_INDEX_ACTOR",
    # Component system
    "Component",
    "ComponentEngine",
    "component_actor_path",
    "get_component_actor",
    # Entity index
    "EntityIndex",
    "get_entity_index",
    # Write buffer
    "WriteBuffer",
    "WriteOperation",
    "create_write_buffer",
    "destroy_write_buffer",
    # Tick coordination
    "TickCoordinator",
    "TickEngine",
    "SystemDefinition",
    "TickResult",
    "get_tick_coordinator",
    # System base class
    "System",
    "TickableMixin",
    # Query utilities
    "QueryCoordinator",
    "get_entities_in_room",
    "get_entities_with_target",
    "get_low_health_entities",
    # Global accessors
    "core_tick_coordinator",
    "core_tick_engine",
    "core_component_engine",
    "core_entity_index",
    "initialise_core",
    "shutdown_core",
    # Extension API
    "Extension",
    "ExtensionInfo",
    # Event system
    "EventBus",
    "EventRouter",
    "EventScope",
    "EventTopic",
    "EventPriority",
    "EventTarget",
    "GameEvent",
    "CombatEvent",
    "MovementEvent",
    "ChatEvent",
    "ItemEvent",
    "SkillEvent",
    "SystemEvent",
    "Subscription",
    "EventHandler",
    "get_event_bus",
    "publish_event",
    "subscribe",
    "generate_event_id",
    "create_combat_event",
    "create_movement_event",
    "create_chat_event",
    "create_channel_event",
    "create_system_event",
    # Legacy
    "EntityDefinition",
    "ComponentDefinition",
    # Re-exported constants for public use
    "COMPONENT_ACTOR_PREFIX",
    "SYSTEM_ACTOR_PREFIX",
    "GET_COMPONENTS_TIMEOUT_S",
    "TICK_TIMEOUT_S",
    "SNAPSHOT_TIMEOUT_S",
    "COMMIT_TIMEOUT_S",
    "LegacySystemDefinition",
]
