"""
Sample Extension

Demonstrates how to create an extension that registers content
with the LLM-MUD server.

This extension can be:
1. Loaded as a module by the main server
2. Run as a separate process that connects to the Ray cluster

Usage (as separate process):
    python -m extensions.sample_extension

Usage (loaded by server):
    from extensions.sample_extension import SampleExtension
    ext = SampleExtension()
    await ext.connect()
    await ext.load()
"""

import asyncio
import logging
from typing import List

# Import the Extension base class from core
from core import Extension

# Import template types (only needed for type hints in separate process)
# The actual types are serialized via Ray, so imports are optional
try:
    from game.world.templates import RoomTemplate, MobTemplate, ItemTemplate
except ImportError:
    # Running as separate process without game package
    RoomTemplate = None
    MobTemplate = None
    ItemTemplate = None

logger = logging.getLogger(__name__)


# =============================================================================
# Sample Command Handler
# =============================================================================


async def cmd_sample(player_id, args: List[str]) -> str:
    """
    Sample command added by extension.

    This demonstrates adding a new command via the extension API.
    """
    return "This is a sample command added by an extension!"


async def cmd_ping(player_id, args: List[str]) -> str:
    """Simple ping command."""
    return "Pong!"


# =============================================================================
# Sample Extension
# =============================================================================


class SampleExtension(Extension):
    """
    A sample extension that adds a test zone with rooms and commands.

    This demonstrates the Extension API for:
    - Registering room templates
    - Registering mob templates
    - Registering item templates
    - Registering commands
    """

    def __init__(self):
        super().__init__(
            name="sample_extension",
            version="1.0.0",
            author="LLM-MUD Team",
            description="A sample extension demonstrating the Extension API",
        )

    async def on_load(self) -> None:
        """
        Called when the extension is loaded.

        Registers all content with the distributed registries.
        """
        logger.info(f"Loading {self.name}...")

        # Register rooms
        await self._register_sample_rooms()

        # Register mobs
        await self._register_sample_mobs()

        # Register items
        await self._register_sample_items()

        # Register commands
        await self._register_sample_commands()

        logger.info(f"{self.name} loaded successfully!")

    async def on_unload(self) -> None:
        """Called when the extension is unloaded."""
        logger.info(f"Unloading {self.name}...")
        # Could clean up zone here if needed

    async def _register_sample_rooms(self) -> None:
        """Register sample room templates."""
        # Import here to avoid issues when running standalone
        from game.world.templates import RoomTemplate

        rooms = [
            RoomTemplate(
                template_id="sample_zone_entrance",
                zone_id="sample_zone",
                vnum=9000,
                name="Sample Zone Entrance",
                short_description="The entrance to a sample zone",
                long_description=(
                    "You stand at the entrance to a sample zone created by "
                    "an extension. The area demonstrates how extensions can "
                    "add new content to the game world at runtime."
                ),
                exits={"north": "sample_zone_hall"},
                sector_type="inside",
                flags=["safe"],
            ),
            RoomTemplate(
                template_id="sample_zone_hall",
                zone_id="sample_zone",
                vnum=9001,
                name="Sample Hall",
                short_description="A hall in the sample zone",
                long_description=(
                    "This hall connects various parts of the sample zone. "
                    "It's a bit empty, but demonstrates room connectivity."
                ),
                exits={
                    "south": "sample_zone_entrance",
                    "east": "sample_zone_chamber",
                },
                sector_type="inside",
            ),
            RoomTemplate(
                template_id="sample_zone_chamber",
                zone_id="sample_zone",
                vnum=9002,
                name="Sample Chamber",
                short_description="A mysterious chamber",
                long_description=(
                    "This chamber contains a strange energy. Perhaps "
                    "something important resides here."
                ),
                exits={"west": "sample_zone_hall"},
                sector_type="inside",
                mob_spawns=[{"template_id": "sample_mob"}],
            ),
        ]

        count = await self.register_rooms(rooms)
        logger.info(f"Registered {count} sample rooms")

    async def _register_sample_mobs(self) -> None:
        """Register sample mob templates."""
        from game.world.templates import MobTemplate

        mobs = [
            MobTemplate(
                template_id="sample_mob",
                zone_id="sample_zone",
                vnum=9100,
                name="a sample creature",
                keywords=["creature", "sample"],
                short_description="A sample creature lurks here.",
                long_description=(
                    "This creature was created by an extension. It seems "
                    "mostly harmless but curious about new visitors."
                ),
                level=2,
                health=50,
                mana=20,
                behavior_type="passive",
                experience_value=50,
                dialogue={
                    "greeting": "Hello, adventurer! I'm from an extension.",
                    "farewell": "Safe travels!",
                },
            ),
        ]

        count = await self.register_mobs(mobs)
        logger.info(f"Registered {count} sample mobs")

    async def _register_sample_items(self) -> None:
        """Register sample item templates."""
        from game.world.templates import ItemTemplate

        items = [
            ItemTemplate(
                template_id="sample_token",
                zone_id="sample_zone",
                vnum=9200,
                name="a sample token",
                keywords=["token", "sample"],
                short_description="A small token lies here.",
                long_description=(
                    "This token was created by an extension. It serves "
                    "as proof that the extension system is working."
                ),
                item_type="misc",
                rarity="uncommon",
                weight=0.1,
                value=100,
            ),
        ]

        count = await self.register_items(items)
        logger.info(f"Registered {count} sample items")

    async def _register_sample_commands(self) -> None:
        """Register sample commands."""
        # Register the sample command
        await self.register_command(
            name="sample",
            handler_module="extensions.sample_extension",
            handler_name="cmd_sample",
            aliases=["samp"],
            category="information",
            help_text="A sample command from an extension.",
            usage="sample",
        )

        # Register ping command
        await self.register_command(
            name="ping",
            handler_module="extensions.sample_extension",
            handler_name="cmd_ping",
            aliases=[],
            category="information",
            help_text="Simple ping/pong command.",
            usage="ping",
        )

        logger.info("Registered sample commands")


# =============================================================================
# Standalone Execution
# =============================================================================


async def main():
    """Run the extension as a standalone process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ext = SampleExtension()

    # Connect to existing Ray cluster
    await ext.connect(ray_address="auto")

    # Load the extension
    await ext.load()

    # Print stats
    template_stats = await ext.get_template_stats()
    command_stats = await ext.get_command_stats()
    print(f"Template registry stats: {template_stats}")
    print(f"Command registry stats: {command_stats}")

    print("\nExtension loaded! Press Ctrl+C to exit.")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await ext.unload()
        await ext.disconnect()
        print("Extension unloaded.")


if __name__ == "__main__":
    asyncio.run(main())
