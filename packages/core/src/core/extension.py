"""
Extension Base Class and API

Provides the foundation for creating pluggable extensions that can
register content (rooms, mobs, items, commands) with the LLM-MUD server.

Extensions can be:
- Dynamic modules: Imported and loaded at server startup
- Separate processes: Third-party extensions connecting at runtime

Usage:
    class MyExtension(Extension):
        async def on_load(self) -> None:
            await self.register_rooms([...])
            await self.register_command(...)

        async def on_unload(self) -> None:
            pass  # cleanup if needed

    # To run:
    ext = MyExtension("my_extension")
    await ext.connect()
    await ext.load()
"""

import asyncio
import ray
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Any, Dict, Optional
import logging

from .constants import NAMESPACE

logger = logging.getLogger(__name__)


# Default timeout for waiting on registries (seconds)
DEFAULT_REGISTRY_TIMEOUT = 30.0
REGISTRY_POLL_INTERVAL = 0.5


@dataclass
class ExtensionInfo:
    """Metadata about an extension."""

    name: str
    version: str = "1.0.0"
    author: str = ""
    description: str = ""


class Extension(ABC):
    """
    Base class for LLM-MUD extensions.

    Extensions provide a clean API for registering content with the
    distributed registry actors. They can run in the same process as
    the main server (dynamic modules) or in separate processes.
    """

    def __init__(self, name: str, version: str = "1.0.0", author: str = "", description: str = ""):
        self.info = ExtensionInfo(
            name=name,
            version=version,
            author=author,
            description=description,
        )
        self._connected = False
        self._loaded = False
        self._template_registry = None
        self._command_registry = None

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(
        self,
        ray_address: str = "auto",
        wait_for_registries: bool = False,
        timeout: float = DEFAULT_REGISTRY_TIMEOUT,
    ) -> None:
        """
        Connect to the Ray cluster.

        Args:
            ray_address: Ray cluster address. Use "auto" for local cluster.
            wait_for_registries: If True, wait until registries are available.
            timeout: Maximum time to wait for registries (seconds).

        Raises:
            TimeoutError: If wait_for_registries is True and timeout expires.
        """
        if self._connected:
            logger.warning(f"Extension {self.name} already connected")
            return

        # Initialize Ray if not already
        if not ray.is_initialized():
            ray.init(address=ray_address, namespace=NAMESPACE)
            logger.info(f"Extension {self.name} initialized Ray connection")
        else:
            logger.info(f"Extension {self.name} using existing Ray connection")

        # Get registry actors (with optional retry)
        if wait_for_registries:
            await self._wait_for_registries(timeout)
        else:
            self._try_connect_registries()

        self._connected = True
        logger.info(f"Extension {self.name} connected to Ray cluster")

    def _try_connect_registries(self) -> None:
        """Attempt to connect to registries (non-blocking)."""
        try:
            self._template_registry = ray.get_actor("template_registry", namespace=NAMESPACE)
            logger.debug(f"Extension {self.name} connected to template registry")
        except ValueError:
            logger.warning(
                f"Template registry not found - extension {self.name} cannot register templates"
            )

        try:
            self._command_registry = ray.get_actor("command_registry", namespace=NAMESPACE)
            logger.debug(f"Extension {self.name} connected to command registry")
        except ValueError:
            logger.warning(
                f"Command registry not found - extension {self.name} cannot register commands"
            )

    async def _wait_for_registries(self, timeout: float) -> None:
        """
        Wait for both registries to become available.

        Args:
            timeout: Maximum time to wait (seconds).

        Raises:
            TimeoutError: If registries don't become available within timeout.
        """
        elapsed = 0.0
        template_found = False
        command_found = False

        logger.info(f"Extension {self.name} waiting for registries (timeout: {timeout}s)")

        while elapsed < timeout:
            if not template_found:
                try:
                    self._template_registry = ray.get_actor(
                        "template_registry", namespace=NAMESPACE
                    )
                    template_found = True
                    logger.debug(f"Extension {self.name} connected to template registry")
                except ValueError:
                    pass

            if not command_found:
                try:
                    self._command_registry = ray.get_actor(
                        "command_registry", namespace=NAMESPACE
                    )
                    command_found = True
                    logger.debug(f"Extension {self.name} connected to command registry")
                except ValueError:
                    pass

            if template_found and command_found:
                logger.info(f"Extension {self.name} connected to all registries")
                return

            await asyncio.sleep(REGISTRY_POLL_INTERVAL)
            elapsed += REGISTRY_POLL_INTERVAL

        # Timeout reached
        missing = []
        if not template_found:
            missing.append("template_registry")
        if not command_found:
            missing.append("command_registry")

        raise TimeoutError(
            f"Extension {self.name} timed out waiting for registries: {', '.join(missing)}"
        )

    async def disconnect(self) -> None:
        """Disconnect from the Ray cluster."""
        if self._loaded:
            await self.unload()

        self._template_registry = None
        self._command_registry = None
        self._connected = False
        logger.info(f"Extension {self.name} disconnected")

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def load(self) -> None:
        """Load the extension, calling on_load()."""
        if not self._connected:
            raise RuntimeError(f"Extension {self.name} must be connected first")

        if self._loaded:
            logger.warning(f"Extension {self.name} already loaded")
            return

        await self.on_load()
        self._loaded = True
        logger.info(f"Extension {self.name} loaded")

    async def unload(self) -> None:
        """Unload the extension, calling on_unload()."""
        if not self._loaded:
            return

        await self.on_unload()
        self._loaded = False
        logger.info(f"Extension {self.name} unloaded")

    @abstractmethod
    async def on_load(self) -> None:
        """
        Called when the extension is loaded.

        Override this to register your content:
            await self.register_rooms([...])
            await self.register_command(...)
        """
        pass

    async def on_unload(self) -> None:
        """
        Called when the extension is unloaded.

        Override this to clean up if needed.
        """
        pass

    # =========================================================================
    # Template Registration
    # =========================================================================

    async def register_rooms(self, templates: List[Any]) -> int:
        """
        Register room templates.

        Args:
            templates: List of RoomTemplate instances

        Returns:
            Number of templates registered
        """
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        count = await self._template_registry.register_rooms_batch.remote(templates)
        logger.info(f"Extension {self.name} registered {count} room templates")
        return count

    async def register_room(self, template: Any) -> None:
        """Register a single room template."""
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        await self._template_registry.register_room.remote(template)
        logger.debug(f"Extension {self.name} registered room: {template.template_id}")

    async def register_mobs(self, templates: List[Any]) -> int:
        """
        Register mob templates.

        Args:
            templates: List of MobTemplate instances

        Returns:
            Number of templates registered
        """
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        count = await self._template_registry.register_mobs_batch.remote(templates)
        logger.info(f"Extension {self.name} registered {count} mob templates")
        return count

    async def register_mob(self, template: Any) -> None:
        """Register a single mob template."""
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        await self._template_registry.register_mob.remote(template)
        logger.debug(f"Extension {self.name} registered mob: {template.template_id}")

    async def register_items(self, templates: List[Any]) -> int:
        """
        Register item templates.

        Args:
            templates: List of ItemTemplate instances

        Returns:
            Number of templates registered
        """
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        count = await self._template_registry.register_items_batch.remote(templates)
        logger.info(f"Extension {self.name} registered {count} item templates")
        return count

    async def register_item(self, template: Any) -> None:
        """Register a single item template."""
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        await self._template_registry.register_item.remote(template)
        logger.debug(f"Extension {self.name} registered item: {template.template_id}")

    async def register_portals(self, templates: List[Any]) -> int:
        """
        Register portal templates.

        Args:
            templates: List of PortalTemplate instances

        Returns:
            Number of templates registered
        """
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        count = await self._template_registry.register_portals_batch.remote(templates)
        logger.info(f"Extension {self.name} registered {count} portal templates")
        return count

    async def register_portal(self, template: Any) -> None:
        """Register a single portal template."""
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")

        await self._template_registry.register_portal.remote(template)
        logger.debug(f"Extension {self.name} registered portal: {template.template_id}")

    # =========================================================================
    # Command Registration
    # =========================================================================

    async def register_command(
        self,
        name: str,
        handler_module: str,
        handler_name: str,
        aliases: Optional[List[str]] = None,
        category: str = "information",
        min_position: str = "standing",
        help_text: str = "",
        usage: str = "",
        admin_only: bool = False,
        in_combat: bool = True,
        hidden: bool = False,
    ) -> None:
        """
        Register a command.

        Args:
            name: Command name (e.g., "look")
            handler_module: Module containing the handler (e.g., "myext.commands")
            handler_name: Function name in the module (e.g., "cmd_look")
            aliases: Alternative names for the command
            category: Command category for help organization
            min_position: Minimum position to use command
            help_text: Help description
            usage: Usage string
            admin_only: Restrict to admins
            in_combat: Can be used while in combat
            hidden: Hide from help listing
        """
        if self._command_registry is None:
            raise RuntimeError("Not connected to command registry")

        # Import the category enum dynamically to avoid circular imports
        # We use string values which the actor will handle
        from dataclasses import dataclass, field

        @dataclass
        class DistributedCommandDefinition:
            name: str
            handler_module: str
            handler_name: str
            aliases: List[str] = field(default_factory=list)
            category: str = "information"
            min_position: str = "standing"
            help_text: str = ""
            usage: str = ""
            admin_only: bool = False
            in_combat: bool = True
            hidden: bool = False

        definition = DistributedCommandDefinition(
            name=name,
            handler_module=handler_module,
            handler_name=handler_name,
            aliases=aliases or [],
            category=category,
            min_position=min_position,
            help_text=help_text,
            usage=usage or f"{name} [arguments]",
            admin_only=admin_only,
            in_combat=in_combat,
            hidden=hidden,
        )

        await self._command_registry.register.remote(definition)
        logger.debug(f"Extension {self.name} registered command: {name}")

    async def register_commands(self, definitions: List[Any]) -> int:
        """
        Register multiple commands at once.

        Args:
            definitions: List of DistributedCommandDefinition instances

        Returns:
            Number of commands registered
        """
        if self._command_registry is None:
            raise RuntimeError("Not connected to command registry")

        count = await self._command_registry.register_batch.remote(definitions)
        logger.info(f"Extension {self.name} registered {count} commands")
        return count

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_template_stats(self) -> Dict[str, int]:
        """Get statistics about registered templates."""
        if self._template_registry is None:
            raise RuntimeError("Not connected to template registry")
        return await self._template_registry.get_stats.remote()

    async def get_command_stats(self) -> Dict[str, int]:
        """Get statistics about registered commands."""
        if self._command_registry is None:
            raise RuntimeError("Not connected to command registry")
        return await self._command_registry.get_stats.remote()
