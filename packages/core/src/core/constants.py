"""Constants for the ECS system."""

# Ray namespace for all actors
NAMESPACE: str = "llmmud"

# Core system actor paths
TICK_COORDINATOR_ACTOR: str = "llmmud/system/tick_coordinator"
COMPONENT_ENGINE_ACTOR: str = "llmmud/system/component_engine"
ENTITY_INDEX_ACTOR: str = "llmmud/system/entity_index"

# Legacy aliases for compatibility
TICK_ENGINE_ACTOR: str = TICK_COORDINATOR_ACTOR

# Component actor path prefix
COMPONENT_ACTOR_PREFIX: str = "llmmud/components"

# System actor path prefix
SYSTEM_ACTOR_PREFIX: str = "llmmud/systems"

# Timeouts
GET_COMPONENTS_TIMEOUT_S: float = 1.0
TICK_TIMEOUT_S: float = 5.0
SNAPSHOT_TIMEOUT_S: float = 2.0
COMMIT_TIMEOUT_S: float = 3.0
