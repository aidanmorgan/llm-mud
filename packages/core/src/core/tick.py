"""
TickCoordinator actor for orchestrating ECS tick processing.

Implements the two-phase tick cycle:
1. SNAPSHOT: Take consistent snapshots from all component actors
2. PROCESS: Execute systems in dependency order, writing to buffer
3. COMMIT: Apply all buffered writes atomically

This ensures:
- Read isolation: systems read from tick-start snapshot
- Write ordering: all writes applied after all systems complete
- System dependencies: groups execute sequentially
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import ray
from ray import ObjectRef
from ray.actor import ActorHandle

from .types import EntityId, ComponentData
from .write_buffer import create_write_buffer, destroy_write_buffer
from . import constants

logger = logging.getLogger(__name__)


@dataclass
class SystemDefinition:
    """Definition of a system for registration."""

    name: str
    actor_path: str
    required_components: List[str]
    optional_components: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0  # Lower = earlier within same dependency level


@dataclass
class TickResult:
    """Result of a tick cycle."""

    tick_id: int
    duration_ms: float
    snapshot_ms: float
    process_ms: float
    commit_ms: float
    systems_executed: List[str]
    entities_processed: int
    writes_committed: Dict[str, int]
    errors: List[str]


@ray.remote
class TickCoordinator:
    """
    Orchestrates tick execution with consistency guarantees.

    Manages:
    - System registration and dependency ordering
    - Tick lifecycle (snapshot → process → commit)
    - Multiple tick rates (combat, pulse, area)
    """

    # Tick rate constants (milliseconds)
    COMBAT_TICK_MS = 1000  # Fast combat actions
    PULSE_TICK_MS = 4000  # Combat rounds, regeneration
    AREA_TICK_MS = 60000  # Mob respawn, weather

    def __init__(self):
        self._tick_id: int = 0
        self._running: bool = False

        # System registry
        self._systems: Dict[str, SystemDefinition] = {}
        self._system_groups: Optional[List[List[str]]] = None

        # Component engine reference
        self._component_engine: Optional[ActorHandle] = None

        # Tick tasks
        self._tick_tasks: List[asyncio.Task] = []

        # Stats
        self._total_ticks: int = 0
        self._total_time_ms: float = 0

        logger.info("TickCoordinator initialized")

    # =========================================================================
    # Configuration
    # =========================================================================

    async def set_component_engine(self, engine: ActorHandle) -> None:
        """Set the component engine reference."""
        self._component_engine = engine

    async def register_system(self, system: SystemDefinition) -> None:
        """
        Register a system for tick processing.
        Systems are executed in dependency order each tick.
        """
        self._systems[system.name] = system
        self._system_groups = None  # Invalidate cached ordering
        logger.info(f"Registered system: {system.name}")

    async def unregister_system(self, name: str) -> bool:
        """Unregister a system."""
        if name in self._systems:
            del self._systems[name]
            self._system_groups = None
            return True
        return False

    async def get_registered_systems(self) -> List[str]:
        """Get list of registered system names."""
        return list(self._systems.keys())

    # =========================================================================
    # System Ordering
    # =========================================================================

    def _compute_system_groups(self) -> List[List[str]]:
        """
        Topological sort systems into execution groups.
        Systems in the same group have no dependencies on each other
        and can run in parallel.
        """
        if not self._systems:
            return []

        # Build dependency graph
        in_degree: Dict[str, int] = {name: 0 for name in self._systems}
        dependents: Dict[str, List[str]] = {name: [] for name in self._systems}

        for name, system in self._systems.items():
            for dep in system.dependencies:
                if dep in self._systems:
                    in_degree[name] += 1
                    dependents[dep].append(name)
                else:
                    logger.warning(f"System {name} depends on unknown system {dep}")

        # Kahn's algorithm with grouping
        groups: List[List[str]] = []
        current_group = [name for name, degree in in_degree.items() if degree == 0]

        while current_group:
            # Sort current group by priority
            current_group.sort(key=lambda n: self._systems[n].priority)
            groups.append(current_group)

            next_group = []
            for name in current_group:
                for dependent in dependents[name]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_group.append(dependent)

            current_group = next_group

        # Check for cycles
        if sum(len(g) for g in groups) != len(self._systems):
            logger.error("Circular dependency detected in systems!")
            # Return what we have, some systems won't run

        return groups

    async def get_system_groups(self) -> List[List[str]]:
        """Get the current system execution groups."""
        if self._system_groups is None:
            self._system_groups = self._compute_system_groups()
        return self._system_groups

    # =========================================================================
    # Tick Execution
    # =========================================================================

    async def execute_tick(self) -> TickResult:
        """
        Execute a complete tick cycle.

        1. SNAPSHOT: Get consistent state from all components
        2. PROCESS: Run systems in order, writing to buffer
        3. COMMIT: Apply all buffered writes
        """
        tick_start = time.time()
        self._tick_id += 1
        tick_id = self._tick_id

        errors: List[str] = []
        systems_executed: List[str] = []
        entities_processed = 0
        writes_committed: Dict[str, int] = {}

        logger.debug(f"Starting tick {tick_id}")

        # =====================================================================
        # Phase 1: SNAPSHOT
        # =====================================================================
        snapshot_start = time.time()

        try:
            # Get all component snapshots
            if self._component_engine is None:
                raise RuntimeError("Component engine not set")

            snapshot_refs = await self._component_engine.get_all_snapshots.remote(tick_id)
            snapshots: Dict[str, Dict[EntityId, ComponentData]] = {}

            for component_type, ref in snapshot_refs.items():
                try:
                    metadata, data = ray.get(ref, timeout=constants.SNAPSHOT_TIMEOUT_S)
                    snapshots[component_type] = data
                except Exception as e:
                    errors.append(f"Snapshot error for {component_type}: {e}")
                    snapshots[component_type] = {}

            # Put snapshots in object store for systems to read (zero-copy)
            snapshot_ref = ray.put(snapshots)

        except Exception as e:
            errors.append(f"Snapshot phase error: {e}")
            snapshot_ref = ray.put({})

        snapshot_ms = (time.time() - snapshot_start) * 1000

        # =====================================================================
        # Phase 2: PROCESS
        # =====================================================================
        process_start = time.time()

        # Create write buffer for this tick
        write_buffer = create_write_buffer(tick_id)

        try:
            # Ensure we have system groups
            if self._system_groups is None:
                self._system_groups = self._compute_system_groups()

            # Execute system groups in order
            for group in self._system_groups:
                # Systems within a group run in parallel
                system_refs: List[tuple[str, ObjectRef]] = []

                for system_name in group:
                    system = self._systems[system_name]
                    try:
                        system_actor = ray.get_actor(
                            system.actor_path, namespace=constants.NAMESPACE
                        )
                        ref = system_actor.process_tick.remote(tick_id, snapshot_ref, write_buffer)
                        system_refs.append((system_name, ref))
                    except Exception as e:
                        errors.append(f"Error invoking system {system_name}: {e}")

                # Wait for group to complete
                for system_name, ref in system_refs:
                    try:
                        result = ray.get(ref, timeout=constants.TICK_TIMEOUT_S)
                        systems_executed.append(system_name)
                        if isinstance(result, int):
                            entities_processed += result
                    except Exception as e:
                        errors.append(f"Error in system {system_name}: {e}")

        except Exception as e:
            errors.append(f"Process phase error: {e}")

        process_ms = (time.time() - process_start) * 1000

        # =====================================================================
        # Phase 3: COMMIT
        # =====================================================================
        commit_start = time.time()

        try:
            commit_result = ray.get(
                write_buffer.commit.remote(), timeout=constants.COMMIT_TIMEOUT_S
            )  # type: ignore[call-overload]
            for component_type, stats in commit_result.items():
                total = sum(v for v in stats.values() if isinstance(v, int))
                writes_committed[component_type] = total

        except Exception as e:
            errors.append(f"Commit phase error: {e}")
            # Try to discard the buffer
            try:
                ray.get(write_buffer.discard.remote())  # type: ignore[call-overload]
            except Exception:
                pass

        commit_ms = (time.time() - commit_start) * 1000

        # Cleanup
        destroy_write_buffer(write_buffer)

        # Calculate total duration
        total_ms = (time.time() - tick_start) * 1000

        # Update stats
        self._total_ticks += 1
        self._total_time_ms += total_ms

        result = TickResult(
            tick_id=tick_id,
            duration_ms=total_ms,
            snapshot_ms=snapshot_ms,
            process_ms=process_ms,
            commit_ms=commit_ms,
            systems_executed=systems_executed,
            entities_processed=entities_processed,
            writes_committed=writes_committed,
            errors=errors,
        )

        if errors:
            logger.warning(f"Tick {tick_id} completed with errors: {errors}")
        else:
            logger.debug(f"Tick {tick_id} completed in {total_ms:.1f}ms")

        return result

    # =========================================================================
    # Tick Loops
    # =========================================================================

    async def start(self) -> None:
        """Start the tick loops."""
        if self._running:
            logger.warning("TickCoordinator already running")
            return

        self._running = True

        # Start tick loops as background tasks
        self._tick_tasks = [
            asyncio.create_task(self._tick_loop("combat", self.COMBAT_TICK_MS)),
            asyncio.create_task(self._tick_loop("pulse", self.PULSE_TICK_MS)),
            asyncio.create_task(self._tick_loop("area", self.AREA_TICK_MS)),
        ]

        logger.info("TickCoordinator started with combat/pulse/area loops")

    async def stop(self) -> None:
        """Stop the tick loops."""
        self._running = False

        for task in self._tick_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tick_tasks = []
        logger.info("TickCoordinator stopped")

    async def _tick_loop(self, name: str, interval_ms: int) -> None:
        """Run a tick loop at the specified interval."""
        interval_s = interval_ms / 1000.0

        while self._running:
            start = time.time()

            try:
                await self.execute_tick()
            except Exception as e:
                logger.error(f"Error in {name} tick loop: {e}")

            elapsed = time.time() - start
            sleep_time = max(0, interval_s - elapsed)

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                logger.warning(
                    f"{name} tick took {elapsed*1000:.1f}ms, exceeding interval of {interval_ms}ms"
                )

    async def execute_single_tick(self) -> TickResult:
        """Execute a single tick (for testing or manual triggering)."""
        return await self.execute_tick()

    # =========================================================================
    # Legacy Compatibility
    # =========================================================================

    async def register(self, actor_path: str) -> None:
        """
        Legacy method for registering tickable actors.
        Creates a minimal system definition.
        """
        name = actor_path.split("/")[-1]
        await self.register_system(
            SystemDefinition(name=name, actor_path=actor_path, required_components=[])
        )

    async def unregister(self, actor_path: str) -> None:
        """Legacy method for unregistering."""
        name = actor_path.split("/")[-1]
        await self.unregister_system(name)

    # =========================================================================
    # Diagnostics
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get statistics about tick processing."""
        return {
            "current_tick_id": self._tick_id,
            "total_ticks": self._total_ticks,
            "total_time_ms": self._total_time_ms,
            "avg_tick_ms": (
                self._total_time_ms / self._total_ticks if self._total_ticks > 0 else 0
            ),
            "running": self._running,
            "registered_systems": list(self._systems.keys()),
            "system_groups": self._system_groups,
        }

    async def get_tick_id(self) -> int:
        """Get the current tick ID."""
        return self._tick_id


# Legacy alias
TickEngine = TickCoordinator


def get_tick_coordinator() -> ActorHandle:
    """Get the TickCoordinator actor."""
    return ray.get_actor(constants.TICK_COORDINATOR_ACTOR, namespace=constants.NAMESPACE)
