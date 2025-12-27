"""
Zone Worker Entrypoint

Runs in a separate container/process and connects to the Ray cluster.
Each zone worker is responsible for:
- Loading zone-specific content (rooms, mobs, items)
- Running zone-specific actors (mob AI, respawns)
- Handling cross-zone communication via Ray

Usage:
    ZONE_TYPE=core python -m game.zone   # Core ECS actors
    ZONE_ID=ravenmoor python -m game.zone  # Zone-specific content
"""

import asyncio
import logging
import os
import signal
import sys

import ray

logger = logging.getLogger(__name__)

# Shutdown flag
_shutdown_requested = False


def handle_signal(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating shutdown...")
    _shutdown_requested = True


async def start_core_workers():
    """
    Start core ECS infrastructure actors.

    This should run in exactly one container. Other containers
    connect to these existing actors.
    """
    from core import initialise_core

    logger.info("Starting core ECS actors...")
    await initialise_core()
    logger.info("Core ECS actors initialized")

    # Start distributed registries
    from .main import start_registries

    await start_registries()
    logger.info("Distributed registries started")

    # Register game components
    from .main import _register_components

    await _register_components()
    logger.info("Game components registered")


async def start_zone_worker(zone_id: str, world_path: str):
    """
    Start a zone-specific worker.

    Loads zone content and starts zone-specific systems.

    Args:
        zone_id: Zone identifier (e.g., "ravenmoor", "ironvein")
        world_path: Path to world data directory
    """
    logger.info(f"Starting zone worker for: {zone_id}")

    # Load zone-specific content into distributed registry
    from .world.loader import load_zone_distributed

    stats = await load_zone_distributed(world_path, zone_id)
    logger.info(
        f"Zone {zone_id} loaded: {stats.get('rooms', 0)} rooms, "
        f"{stats.get('mobs', 0)} mobs, {stats.get('items', 0)} items"
    )

    # Instantiate zone entities (rooms, mobs)
    from .main import _instantiate_world_distributed

    await _instantiate_world_distributed()
    logger.info(f"Zone {zone_id} entities instantiated")

    # Start zone-specific systems
    await start_zone_systems(zone_id)
    logger.info(f"Zone {zone_id} systems started")


async def start_zone_systems(zone_id: str):
    """
    Start systems specific to this zone.

    For now, this is a placeholder. In a full implementation,
    this would start:
    - Mob AI actors for mobs in this zone
    - Respawn timers for this zone
    - Any zone-specific event handlers
    """
    # TODO: Implement zone-specific system startup
    # This would involve:
    # 1. Getting all mobs in this zone
    # 2. Starting AI decision loops for each
    # 3. Setting up respawn schedules
    logger.info(f"Zone {zone_id} systems initialized (placeholder)")


async def start_gateway_worker(host: str = "0.0.0.0", port: int = 4000):
    """
    Start the gateway worker.

    Handles WebSocket connections and routes commands.
    """
    logger.info(f"Starting gateway on {host}:{port}")

    # Register built-in commands
    from .main import register_builtin_commands_distributed

    await register_builtin_commands_distributed()
    logger.info("Built-in commands registered")

    # Start distributed command handler
    from .commands.handler import start_distributed_command_handler

    await start_distributed_command_handler()
    logger.info("Distributed command handler started")

    # Start gateway
    from network import start_gateway

    await start_gateway(
        host=host,
        port=port,
        command_handler_name="distributed_command_handler",
    )
    logger.info(f"Gateway listening on ws://{host}:{port}")


async def run_worker():
    """Main worker loop."""
    global _shutdown_requested

    # Get configuration from environment
    ray_address = os.environ.get("RAY_ADDRESS", "auto")
    zone_type = os.environ.get("ZONE_TYPE", "zone")
    zone_id = os.environ.get("ZONE_ID", "")
    world_path = os.environ.get("WORLD_PATH", "/app/world")
    gateway_host = os.environ.get("GATEWAY_HOST", "0.0.0.0")
    gateway_port = int(os.environ.get("GATEWAY_PORT", "4000"))

    # Connect to Ray cluster via local raylet (started by entrypoint script)
    logger.info(f"Connecting to Ray cluster (RAY_ADDRESS={ray_address})...")
    ray.init(address="auto", namespace="llmmud", ignore_reinit_error=True)
    logger.info("Connected to Ray cluster")

    try:
        if zone_type == "core":
            # Core worker: start ECS infrastructure
            await start_core_workers()

        elif zone_type == "gateway":
            # Gateway worker: handle connections
            await start_gateway_worker(gateway_host, gateway_port)

        elif zone_type == "zone" and zone_id:
            # Zone worker: load zone content
            await start_zone_worker(zone_id, world_path)

        else:
            logger.error(f"Invalid configuration: ZONE_TYPE={zone_type}, ZONE_ID={zone_id}")
            sys.exit(1)

        logger.info(f"Worker started successfully (type={zone_type}, id={zone_id or 'N/A'})")

        # Keep running until shutdown requested
        while not _shutdown_requested:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Worker error: {e}", exc_info=True)
        raise

    finally:
        logger.info("Worker shutting down...")


def main():
    """Entry point for zone worker."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Set up signal handlers
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Run the worker
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
