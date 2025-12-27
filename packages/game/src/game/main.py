"""
Main Entry Point

Starts all game actors and systems.

Supports two modes:
- Legacy: Uses local TemplateRegistry and CommandRegistry (single process)
- Distributed: Uses Ray actors for registries (multi-process, pluggable)
"""

import asyncio
import logging

import ray

logger = logging.getLogger(__name__)


# =============================================================================
# Distributed Mode Functions
# =============================================================================


async def start_registries() -> None:
    """
    Start the distributed registry actors.

    Should be called once during server initialization, before loading content.
    """
    from .world.template_actor import start_template_registry, template_registry_exists
    from .commands.command_actor import start_command_registry, command_registry_exists

    if not template_registry_exists():
        start_template_registry()
        logger.info("Started TemplateRegistryActor")
    else:
        logger.info("TemplateRegistryActor already exists")

    if not command_registry_exists():
        start_command_registry()
        logger.info("Started CommandRegistryActor")
    else:
        logger.info("CommandRegistryActor already exists")


async def register_builtin_commands_distributed() -> int:
    """
    Register built-in commands to the distributed registry.

    Returns the number of commands registered.
    """
    from .commands.command_actor import (
        get_command_registry_actor,
        DistributedCommandDefinition,
        CommandCategory,
    )
    from .components.position import Position

    registry = get_command_registry_actor()

    # Define all built-in commands with their handler references
    commands = [
        # Movement commands
        DistributedCommandDefinition(
            name="north",
            handler_module="game.commands.movement",
            handler_name="cmd_north",
            aliases=["n"],
            category=CommandCategory.MOVEMENT,
            help_text="Move north.",
            usage="north",
        ),
        DistributedCommandDefinition(
            name="south",
            handler_module="game.commands.movement",
            handler_name="cmd_south",
            aliases=["s"],
            category=CommandCategory.MOVEMENT,
            help_text="Move south.",
            usage="south",
        ),
        DistributedCommandDefinition(
            name="east",
            handler_module="game.commands.movement",
            handler_name="cmd_east",
            aliases=["e"],
            category=CommandCategory.MOVEMENT,
            help_text="Move east.",
            usage="east",
        ),
        DistributedCommandDefinition(
            name="west",
            handler_module="game.commands.movement",
            handler_name="cmd_west",
            aliases=["w"],
            category=CommandCategory.MOVEMENT,
            help_text="Move west.",
            usage="west",
        ),
        DistributedCommandDefinition(
            name="up",
            handler_module="game.commands.movement",
            handler_name="cmd_up",
            aliases=["u"],
            category=CommandCategory.MOVEMENT,
            help_text="Move up.",
            usage="up",
        ),
        DistributedCommandDefinition(
            name="down",
            handler_module="game.commands.movement",
            handler_name="cmd_down",
            aliases=["d"],
            category=CommandCategory.MOVEMENT,
            help_text="Move down.",
            usage="down",
        ),
        DistributedCommandDefinition(
            name="exits",
            handler_module="game.commands.movement",
            handler_name="cmd_exits",
            aliases=["ex"],
            category=CommandCategory.MOVEMENT,
            min_position=Position.RESTING,
            help_text="List exits from current room.",
            usage="exits",
        ),
        DistributedCommandDefinition(
            name="recall",
            handler_module="game.commands.movement",
            handler_name="cmd_recall",
            aliases=[],
            category=CommandCategory.MOVEMENT,
            in_combat=False,
            help_text="Return to the starting room.",
            usage="recall",
        ),
        # Information commands
        DistributedCommandDefinition(
            name="look",
            handler_module="game.commands.info",
            handler_name="cmd_look",
            aliases=["l"],
            category=CommandCategory.INFORMATION,
            min_position=Position.RESTING,
            help_text="Look at your surroundings or an object.",
            usage="look [target]",
        ),
        DistributedCommandDefinition(
            name="score",
            handler_module="game.commands.info",
            handler_name="cmd_score",
            aliases=["sc"],
            category=CommandCategory.INFORMATION,
            min_position=Position.RESTING,
            help_text="View your character statistics.",
            usage="score",
        ),
        DistributedCommandDefinition(
            name="inventory",
            handler_module="game.commands.info",
            handler_name="cmd_inventory",
            aliases=["i", "inv"],
            category=CommandCategory.INFORMATION,
            min_position=Position.RESTING,
            help_text="View your inventory.",
            usage="inventory",
        ),
        DistributedCommandDefinition(
            name="equipment",
            handler_module="game.commands.info",
            handler_name="cmd_equipment",
            aliases=["eq", "worn"],
            category=CommandCategory.INFORMATION,
            min_position=Position.RESTING,
            help_text="View equipped items.",
            usage="equipment",
        ),
        DistributedCommandDefinition(
            name="who",
            handler_module="game.commands.info",
            handler_name="cmd_who",
            aliases=[],
            category=CommandCategory.INFORMATION,
            min_position=Position.RESTING,
            help_text="List online players.",
            usage="who",
        ),
        DistributedCommandDefinition(
            name="help",
            handler_module="game.commands.info",
            handler_name="cmd_help",
            aliases=["?"],
            category=CommandCategory.INFORMATION,
            min_position=Position.DEAD,
            help_text="Get help on commands.",
            usage="help [command]",
        ),
        # Combat commands
        DistributedCommandDefinition(
            name="kill",
            handler_module="game.commands.combat",
            handler_name="cmd_kill",
            aliases=["k", "attack"],
            category=CommandCategory.COMBAT,
            help_text="Attack a target.",
            usage="kill <target>",
        ),
        DistributedCommandDefinition(
            name="flee",
            handler_module="game.commands.combat",
            handler_name="cmd_flee",
            aliases=[],
            category=CommandCategory.COMBAT,
            in_combat=True,
            help_text="Flee from combat.",
            usage="flee",
        ),
        DistributedCommandDefinition(
            name="consider",
            handler_module="game.commands.combat",
            handler_name="cmd_consider",
            aliases=["con"],
            category=CommandCategory.COMBAT,
            help_text="Evaluate a potential target.",
            usage="consider <target>",
        ),
        # Communication commands
        DistributedCommandDefinition(
            name="say",
            handler_module="game.commands.communication",
            handler_name="cmd_say",
            aliases=["'"],
            category=CommandCategory.COMMUNICATION,
            min_position=Position.RESTING,
            help_text="Say something to the room.",
            usage="say <message>",
        ),
        DistributedCommandDefinition(
            name="shout",
            handler_module="game.commands.communication",
            handler_name="cmd_shout",
            aliases=["yell"],
            category=CommandCategory.COMMUNICATION,
            min_position=Position.RESTING,
            help_text="Shout to the area.",
            usage="shout <message>",
        ),
        DistributedCommandDefinition(
            name="tell",
            handler_module="game.commands.communication",
            handler_name="cmd_tell",
            aliases=["whisper"],
            category=CommandCategory.COMMUNICATION,
            min_position=Position.RESTING,
            help_text="Send a private message.",
            usage="tell <player> <message>",
        ),
        DistributedCommandDefinition(
            name="emote",
            handler_module="game.commands.communication",
            handler_name="cmd_emote",
            aliases=["em"],
            category=CommandCategory.COMMUNICATION,
            min_position=Position.RESTING,
            help_text="Perform an emote.",
            usage="emote <action>",
        ),
    ]

    count = await registry.register_batch.remote(commands)
    logger.info(f"Registered {count} built-in commands to distributed registry")
    return count


async def _start_game_systems() -> None:
    """
    Start game systems (tick-based and utility actors).

    This starts:
    - LevelingSystem: Processes level-up requests each tick
    - GuildAccessSystem: Validates guild room access (utility, not tick-based)
    """
    from core import get_tick_coordinator
    from core.tick import SystemDefinition

    from .systems.leveling import (
        start_leveling_system,
        leveling_system_exists,
        ACTOR_NAME as LEVELING_ACTOR_NAME,
        ACTOR_NAMESPACE as LEVELING_NAMESPACE,
    )
    from .systems.guild_access import (
        start_guild_access_system,
        guild_access_system_exists,
    )

    # Start GuildAccessSystem (utility actor, not tick-based)
    if not guild_access_system_exists():
        await start_guild_access_system()
        logger.info("Started GuildAccessSystem")
    else:
        logger.info("GuildAccessSystem already exists")

    # Start LevelingSystem (tick-based)
    if not leveling_system_exists():
        await start_leveling_system()
        logger.info("Started LevelingSystem")

        # Register with TickCoordinator
        coordinator = get_tick_coordinator()
        leveling_def = SystemDefinition(
            name="LevelingSystem",
            actor_path=LEVELING_ACTOR_NAME,
            required_components=["LevelUpQueue"],
            optional_components=["Leveling", "Player", "Stats"],
            dependencies=[],
            priority=5,
        )
        await coordinator.register_system.remote(leveling_def)
        logger.info("Registered LevelingSystem with TickCoordinator")
    else:
        logger.info("LevelingSystem already exists")


async def start_game_distributed(world_path: str = None, host: str = "0.0.0.0", port: int = 4000):
    """
    Start the game server in distributed mode.

    Uses Ray actors for template and command registries, enabling
    multi-process deployments and runtime extensions.

    Args:
        world_path: Path to world data directory
        host: WebSocket server host
        port: WebSocket server port
    """
    # Initialize Ray if not already
    if not ray.is_initialized():
        ray.init(namespace="llmmud")

    logger.info("Starting LLM-MUD server (distributed mode)...")

    # Initialize core ECS actors
    from core import initialise_core

    await initialise_core()
    logger.info("Core ECS actors initialized")

    # Start distributed registries
    await start_registries()
    logger.info("Distributed registries started")

    # Register game components
    await _register_components()
    logger.info("Game components registered")

    # Register built-in commands to distributed registry
    await register_builtin_commands_distributed()

    # Load world data into distributed registry
    if world_path:
        from .world.loader import load_world_distributed

        stats = await load_world_distributed(world_path)
        logger.info(
            f"World loaded (distributed): {stats['rooms']} rooms, "
            f"{stats['mobs']} mobs, {stats['items']} items"
        )

        # Create room entities from distributed templates
        await _instantiate_world_distributed()
        logger.info("World entities instantiated")

    # Start distributed command handler
    from .commands.handler import start_distributed_command_handler

    await start_distributed_command_handler()
    logger.info("Distributed command handler started")

    # Start gateway (use distributed handler)
    from network import start_gateway

    gateway = await start_gateway(
        host=host, port=port, command_handler_name="distributed_command_handler"
    )
    logger.info(f"Gateway listening on ws://{host}:{port}")

    # Start game systems
    await _start_game_systems()
    logger.info("Game systems started")

    # Start tick coordinator loop
    from core import get_tick_coordinator

    coordinator = get_tick_coordinator()
    await coordinator.start.remote()
    logger.info("Tick coordinator started")

    logger.info("LLM-MUD server is running (distributed mode)!")

    return gateway


async def _instantiate_world_distributed():
    """Create entity instances from distributed templates."""
    from .world.factory import get_distributed_entity_factory
    from .world.template_actor import get_template_registry_actor

    factory = get_distributed_entity_factory()
    registry = get_template_registry_actor()

    # Create all rooms
    room_templates = await registry.get_all_rooms.remote()
    for template_id in room_templates:
        await factory.create_room(template_id, instance_id=template_id)

    # Resolve room exits (convert template IDs to entity IDs)
    from core.component import get_component_actor
    from core import EntityId

    room_actor = get_component_actor("Room")
    all_rooms = await room_actor.get_all.remote()

    for room_id, room_data in all_rooms.items():
        template = await registry.get_room.remote(room_id.id)
        if not template:
            continue

        # Build exits from template
        from .components.spatial import ExitData, Direction

        exits = {}
        for direction, dest_template_id in template.exits.items():
            dest_entity_id = EntityId(id=dest_template_id, entity_type="room")
            exits[direction] = ExitData(
                direction=Direction.from_string(direction) or Direction.NORTH,
                destination_id=dest_entity_id,
            )

        # Update room with resolved exits
        def set_exits(r):
            r.exits = exits

        await room_actor.mutate.remote(room_id, set_exits)


# =============================================================================
# Legacy Mode Functions (single-process, local registries)
# =============================================================================


async def start_game(world_path: str = None, host: str = "0.0.0.0", port: int = 4000):
    """
    Start the game server.

    Args:
        world_path: Path to world data directory
        host: WebSocket server host
        port: WebSocket server port
    """
    # Initialize Ray if not already
    if not ray.is_initialized():
        ray.init(namespace="llmmud")

    logger.info("Starting LLM-MUD server...")

    # Initialize core ECS actors
    from core import initialise_core

    await initialise_core()
    logger.info("Core ECS actors initialized")

    # Register game components
    await _register_components()
    logger.info("Game components registered")

    # Load world data
    if world_path:
        from .world import load_world

        stats = load_world(world_path)
        logger.info(
            f"World loaded: {stats['rooms']} rooms, {stats['mobs']} mobs, "
            f"{stats['items']} items"
        )

        # Create room entities from templates
        await _instantiate_world()
        logger.info("World entities instantiated")

    # Start command handler
    from .commands.handler import start_command_handler

    await start_command_handler()
    logger.info("Command handler started")

    # Start gateway
    from network import start_gateway

    gateway = await start_gateway(
        host=host, port=port, command_handler_name="command_handler"
    )
    logger.info(f"Gateway listening on ws://{host}:{port}")

    # Start tick coordinator loop
    from core import get_tick_coordinator

    coordinator = get_tick_coordinator()
    await coordinator.start.remote()
    logger.info("Tick coordinator started")

    logger.info("LLM-MUD server is running!")

    return gateway


async def _register_components():
    """Register all game component types."""
    from core import core_component_engine

    engine = core_component_engine()

    # Import all component data classes
    from .components import (
        StaticIdentityData,
        DynamicIdentityData,
        LocationData,
        StaticRoomData,
        DynamicRoomData,
        PlayerStatsData,
        MobStatsData,
        CombatData,
        ContainerData,
        EquipmentSlotsData,
        ItemData,
        WeaponData,
        ArmorData,
        ConsumableData,
        StaticAIData,
        DynamicAIData,
        DialogueData,
        PlayerConnectionData,
        PlayerProgressData,
        QuestLogData,
        PortalData,
        InstanceData,
        ClassData,
        RaceData,
        CharacterCreationData,
    )
    from .systems import MovementRequestData, AttackRequestData

    # Map component types to their data classes
    components = {
        "Identity": StaticIdentityData,
        "DynamicIdentity": DynamicIdentityData,
        "Location": LocationData,
        "Room": StaticRoomData,
        "DynamicRoom": DynamicRoomData,
        "Stats": PlayerStatsData,
        "MobStats": MobStatsData,
        "Combat": CombatData,
        "Container": ContainerData,
        "Equipment": EquipmentSlotsData,
        "Item": ItemData,
        "Weapon": WeaponData,
        "Armor": ArmorData,
        "Consumable": ConsumableData,
        "AI": StaticAIData,
        "DynamicAI": DynamicAIData,
        "Dialogue": DialogueData,
        "Connection": PlayerConnectionData,
        "Progress": PlayerProgressData,
        "QuestLog": QuestLogData,
        "Portal": PortalData,
        "Instance": InstanceData,
        "MovementRequest": MovementRequestData,
        "AttackRequest": AttackRequestData,
        "Class": ClassData,
        "Race": RaceData,
        "CharacterCreation": CharacterCreationData,
    }

    # Register each component type with a factory function
    # The factory takes an EntityId and returns a new instance of the data class
    def make_factory(cls):
        """Create a factory function for a component data class."""
        return lambda entity_id: cls()

    for component_type, data_class in components.items():
        factory = make_factory(data_class)
        await engine.register_component.remote(component_type, factory)


async def _instantiate_world():
    """Create entity instances from loaded templates."""
    from .world import get_entity_factory
    from .world.templates import get_template_registry

    factory = get_entity_factory()
    registry = get_template_registry()

    # Create all rooms
    room_templates = registry.get_all_rooms()
    for template_id in room_templates:
        await factory.create_room(template_id, instance_id=template_id)

    # Resolve room exits (convert template IDs to entity IDs)
    from core.component import get_component_actor
    from core import EntityId

    room_actor = get_component_actor("Room")
    all_rooms = await room_actor.get_all.remote()

    for room_id, room_data in all_rooms.items():
        template = registry.get_room(room_id.id)
        if not template:
            continue

        # Build exits from template
        from .components.spatial import ExitData, Direction

        exits = {}
        for direction, dest_template_id in template.exits.items():
            dest_entity_id = EntityId(id=dest_template_id, entity_type="room")
            exits[direction] = ExitData(
                direction=Direction.from_string(direction) or Direction.NORTH,
                destination_id=dest_entity_id,
            )

        # Update room with resolved exits
        def set_exits(r):
            r.exits = exits

        await room_actor.mutate.remote(room_id, set_exits)


def run(
    world_path: str = None,
    host: str = "0.0.0.0",
    port: int = 4000,
    distributed: bool = False,
):
    """
    Run the game server (blocking).

    Args:
        world_path: Path to world data directory
        host: WebSocket server host
        port: WebSocket server port
        distributed: Use distributed mode for multi-process support
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    asyncio.run(_run_server(world_path, host, port, distributed))


async def shutdown_game(distributed: bool = False, kill_all: bool = False) -> None:
    """
    Shutdown the game server and clean up actors.

    Args:
        distributed: Whether running in distributed mode
        kill_all: If True, kill all detached actors (for full cluster cleanup)
    """
    logger.info("Shutting down game server...")

    # Stop the gateway first (no new connections)
    try:
        from network.gateway import get_gateway

        gateway = get_gateway()
        await gateway.stop.remote()
        if kill_all:
            ray.kill(gateway)
        logger.info("Gateway stopped")
    except Exception as e:
        logger.warning(f"Error stopping gateway: {e}")

    # Stop command handlers
    try:
        from .commands.handler import get_command_handler, get_distributed_command_handler

        if distributed:
            handler = get_distributed_command_handler()
        else:
            handler = get_command_handler()
        if kill_all:
            ray.kill(handler)
            logger.info("Command handler killed")
    except Exception as e:
        logger.warning(f"Error stopping command handler: {e}")

    # Stop distributed registries if requested
    if distributed and kill_all:
        from .world.template_actor import stop_template_registry
        from .commands.command_actor import stop_command_registry

        stop_template_registry()
        stop_command_registry()

    # Shutdown core ECS infrastructure
    from core import shutdown_core

    await shutdown_core(kill_actors=kill_all)

    logger.info("Game server shutdown complete")


async def _run_server(world_path: str, host: str, port: int, distributed: bool = False):
    """Run the server and keep it running."""
    if distributed:
        await start_game_distributed(world_path, host, port)
    else:
        await start_game(world_path, host, port)

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await shutdown_game(distributed=distributed, kill_all=False)


if __name__ == "__main__":
    import sys

    # Parse command line arguments
    world_path = None
    distributed = False

    for arg in sys.argv[1:]:
        if arg == "--distributed":
            distributed = True
        elif not arg.startswith("--"):
            world_path = arg

    run(world_path=world_path, distributed=distributed)
